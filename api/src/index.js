/* ESCX API — Cloudflare Worker.
 *
 * Отвечает только за деньги и доступ. Публичная витрина остаётся статикой
 * на Pages и сюда не заходит: значит бесплатный лимит Worker тратится
 * только на тех, кто платит или собирается.
 *
 * Маршруты:
 *   POST /api/login          — прислать ссылку для входа
 *   GET  /api/verify?token=  — обменять ссылку на сессию
 *   POST /api/logout
 *   GET  /api/me             — кто я и что оплачено
 *   GET  /api/data           — витрина с учётом тарифа
 *   POST /api/webhook        — вебхук платёжной системы
 */
import { json, readCookie, sessionCookie, normalizeEmail, looksLikeEmail } from './util.js';
import { createMagicLink, consumeMagicLink, whoami, destroySession, SESSION_TTL_SEC } from './auth.js';
import { verifyPaddle, verifyStripe, parsePaddleEvent } from './billing.js';
import { planFor, applyLimits } from './entitlement.js';

const CORS = {
  'access-control-allow-methods': 'GET,POST,OPTIONS',
  'access-control-allow-headers': 'content-type',
  'access-control-allow-credentials': 'true',
};

function cors(env, req) {
  // Разрешаем только собственный сайт. Звёздочка вместе с credentials
  // всё равно не работает, а перечислять чужие домены незачем.
  const origin = req.headers.get('origin');
  return origin && origin === env.SITE_URL
    ? { ...CORS, 'access-control-allow-origin': origin, vary: 'Origin' }
    : {};
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const now = Math.floor(Date.now() / 1000);
    const h = cors(env, req);

    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: h });

    try {
      switch (`${req.method} ${url.pathname}`) {
        case 'POST /api/login':   return await login(req, env, now, h);
        case 'GET /api/verify':   return await verify(url, env, now);
        case 'POST /api/logout':  return await logout(req, env, h);
        case 'GET /api/me':       return await me(req, env, now, h);
        case 'GET /api/data':     return await data(req, env, now, h);
        case 'POST /api/webhook': return await webhook(req, env, now);
        default: return json({ error: 'не найдено' }, 404, h);
      }
    } catch (e) {
      // Наружу — без подробностей: текст ошибки может содержать внутренние детали.
      console.error('api error', e?.stack || e);
      return json({ error: 'внутренняя ошибка' }, 500, h);
    }
  },
};

/* ------------------------------------------------------------------ вход */
async function login(req, env, now, h) {
  const { email } = await req.json().catch(() => ({}));
  const e = normalizeEmail(email);

  // Отвечаем одинаково и на существующий адрес, и на несуществующий:
  // иначе форма входа превращается в способ проверять, кто у нас зарегистрирован.
  if (!looksLikeEmail(e)) return json({ ok: true }, 200, h);

  const token = await createMagicLink(env.DB, e, now);
  const link = `${env.SITE_URL}/api/verify?token=${token}`;
  await sendMail(env, e, 'Вход в ESCX', `Ссылка действует 15 минут:\n\n${link}`);
  return json({ ok: true }, 200, h);
}

async function verify(url, env, now) {
  const r = await consumeMagicLink(env.DB, url.searchParams.get('token'), now);
  if (!r.ok) return json({ error: r.reason }, 400);
  return new Response(null, {
    status: 302,
    headers: {
      location: `${env.SITE_URL}/app`,
      'set-cookie': sessionCookie(r.session, SESSION_TTL_SEC),
    },
  });
}

async function logout(req, env, h) {
  await destroySession(env.DB, readCookie(req, 'escx_session'));
  return json({ ok: true }, 200, { ...h, 'set-cookie': sessionCookie('', 0) });
}

/* ------------------------------------------------------------- состояние */
async function me(req, env, now, h) {
  const email = await whoami(env.DB, readCookie(req, 'escx_session'), now);
  const p = await planFor(env.DB, email, now);
  return json({ email, ...p }, 200, h);
}

async function data(req, env, now, h) {
  const email = await whoami(env.DB, readCookie(req, 'escx_session'), now);
  const { plan } = await planFor(env.DB, email, now);

  // Полная витрина лежит рядом со статикой. Worker её только фильтрует —
  // так закрытая часть не попадает в бесплатную выдачу даже теоретически.
  const res = await fetch(`${env.SITE_URL}/data/index.json`, { cf: { cacheTtl: 300 } });
  if (!res.ok) return json({ error: 'данные недоступны' }, 503, h);

  return json(applyLimits(await res.json(), plan, now), 200, {
    ...h, 'cache-control': 'private, max-age=60',
  });
}

/* --------------------------------------------------------------- вебхуки */
async function webhook(req, env, now) {
  const raw = await req.text();   // именно сырое тело: пересборка ломает подпись
  const provider = env.PROVIDER === 'stripe' ? 'stripe' : 'paddle';

  const check = provider === 'stripe'
    ? await verifyStripe(raw, req.headers.get('stripe-signature'), env.STRIPE_WEBHOOK_SECRET, now)
    : await verifyPaddle(raw, req.headers.get('paddle-signature'), env.PADDLE_WEBHOOK_SECRET, now);

  if (!check.ok) {
    console.warn('вебхук отклонён:', check.reason);
    return json({ error: 'подпись не принята' }, 401);
  }

  const evt = JSON.parse(raw);
  const eventId = evt.event_id || evt.id;

  // Защита от повторной обработки: платёжка перепосылает событие при сбое сети.
  const seen = await env.DB.prepare('SELECT 1 FROM webhook_log WHERE event_id = ?')
    .bind(eventId).first();
  if (seen) return json({ ok: true, duplicate: true });

  await env.DB.prepare(
    'INSERT INTO webhook_log (event_id, provider, event_type, payload) VALUES (?, ?, ?, ?)'
  ).bind(eventId, provider, evt.event_type || evt.type, raw.slice(0, 40000)).run();

  const sub = provider === 'paddle' ? parsePaddleEvent(evt) : null;
  if (sub) {
    await env.DB.prepare(
      `INSERT INTO subscriptions
         (email, provider, subscription_id, customer_id, price_id, plan,
          status, active, current_period_end, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
       ON CONFLICT(provider, subscription_id) DO UPDATE SET
         email=excluded.email, plan=excluded.plan, status=excluded.status,
         active=excluded.active, current_period_end=excluded.current_period_end,
         updated_at=excluded.updated_at`
    ).bind(sub.email, sub.provider, sub.subscription_id, sub.customer_id, sub.price_id,
           sub.plan, sub.status, sub.active, sub.current_period_end).run();
  }

  return json({ ok: true });
}

/* ----------------------------------------------------------------- почта */
async function sendMail(env, to, subject, text) {
  if (!env.RESEND_API_KEY) {           // локальная разработка — просто в лог
    console.log('[письмо не отправлено, нет ключа]', to, subject, text);
    return;
  }
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({ from: env.MAIL_FROM, to, subject, text }),
  });
  if (!r.ok) console.error('почта не ушла:', r.status, await r.text());
}
