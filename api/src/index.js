/* ESCX API — Cloudflare Worker.
 *
 * Отвечает только за деньги и доступ. Публичная витрина остаётся статикой
 * на Pages и сюда не заходит: значит бесплатный лимит Worker тратится
 * только на тех, кто платит или собирается.
 *
 * Маршруты:
 *   POST /api/register          — завести аккаунт: адрес и пароль
 *   POST /api/signin            — войти
 *   POST /api/logout
 *   GET  /api/me                — кто я и что оплачено
 *   POST /api/password/forgot   — прислать ссылку на смену пароля
 *   POST /api/password/reset    — задать пароль по ссылке
 *   POST /api/password/change   — сменить пароль, зная текущий
 *   POST /api/notify            — согласие на уведомления
 *   GET  /api/verify?token=     — подтвердить адрес по ссылке из письма
 *   POST /api/verify/resend     — выслать письмо подтверждения заново
 *   GET  /api/data              — витрина с учётом тарифа
 *   POST /api/webhook           — вебхук платёжной системы
 */
import { json, readCookie, sessionCookie, normalizeEmail, looksLikeEmail } from './util.js';
import { registerUser, signIn, changePassword, resetPassword, createLink, consumeLink,
         markVerified, setNotify, getUser, whoami, destroySession,
         SESSION_TTL_SEC, RESET_TTL_SEC, VERIFY_TTL_SEC } from './auth.js';
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

/** Перец для паролей. Отсутствие — не ошибка, но заметная слабость. */
function pepper(env) {
  if (!env.AUTH_PEPPER) {
    console.warn('AUTH_PEPPER не задан: пароли хэшируются без перца, ' +
                 'утечка базы даст перебор офлайн. wrangler secret put AUTH_PEPPER');
    return '';
  }
  return env.AUTH_PEPPER;
}

/** Адрес источника. Нужен только как ключ счётчика попыток. */
const clientIp = req => req.headers.get('cf-connecting-ip') || '';

/**
 * Требовать ли подтверждённый адрес.
 *
 * Один флаг закрывает две разные двери: вход в кабинет и платные возможности.
 * Разводить их на две настройки смысла нет — обе упираются в один вопрос,
 * доказано ли, что адрес принадлежит этому человеку.
 *
 * ВНИМАНИЕ. С флагом "1" рабочая отправка писем становится обязательной: без
 * неё никто не сможет ни зарегистрироваться, ни войти. Настройка почты —
 * docs/08-mail.md.
 */
const mustVerify = env => env.REQUIRE_VERIFIED_EMAIL === '1';

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const now = Math.floor(Date.now() / 1000);
    const h = cors(env, req);

    if (req.method === 'OPTIONS') return new Response(null, { status: 204, headers: h });

    try {
      switch (`${req.method} ${url.pathname}`) {
        case 'POST /api/register':        return await register(req, env, now, h);
        case 'POST /api/signin':          return await signin(req, env, now, h);
        case 'POST /api/logout':          return await logout(req, env, h);
        case 'GET /api/me':               return await me(req, env, now, h);
        case 'POST /api/password/forgot': return await forgot(req, env, now, h);
        case 'POST /api/password/reset':  return await resetPass(req, env, now, h);
        case 'POST /api/password/change': return await changePass(req, env, now, h);
        case 'POST /api/notify':          return await notify(req, env, now, h);
        case 'GET /api/verify':           return await verify(url, env, now);
        case 'POST /api/verify/resend':   return await resendVerify(req, env, now, h);
        case 'GET /api/data':             return await data(req, env, now, h);
        case 'POST /api/webhook':         return await webhook(req, env, now);
        default: return json({ error: 'не найдено' }, 404, h);
      }
    } catch (e) {
      // Наружу — без подробностей: текст ошибки может содержать внутренние детали.
      console.error('api error', e?.stack || e);
      return json({ error: 'внутренняя ошибка' }, 500, h);
    }
  },
};

/* Успешный вход и регистрация отвечают одинаково: кука с сессией. */
const withSession = (body, session, h) =>
  json(body, 200, { ...h, 'set-cookie': sessionCookie(session, SESSION_TTL_SEC) });

/* ------------------------------------------------------------ аккаунт */

async function register(req, env, now, h) {
  const { email, password } = await req.json().catch(() => ({}));
  const r = await registerUser(
    env.DB, { email, password, pepper: pepper(env), requireVerified: mustVerify(env) }, now);
  if (!r.ok) return json({ error: r.reason, code: r.code }, r.code === 'taken' ? 409 : 400, h);

  await sendVerify(env, r.email, now);

  // Подтверждение обязательно — сессию не выдаём. Пустить человека в кабинет
  // и следующим экраном сказать «а теперь подтвердите» значит сделать
  // требование необязательным на вид и обязательным на деле.
  if (r.pending) return json({ ok: true, email: r.email, pending: true }, 200, h);
  return withSession({ ok: true, email: r.email }, r.session, h);
}

async function signin(req, env, now, h) {
  const { email, password } = await req.json().catch(() => ({}));
  const r = await signIn(env.DB, { email, password, pepper: pepper(env),
                                   ip: clientIp(req), requireVerified: mustVerify(env) }, now);
  if (r.ok) return withSession({ ok: true, email: r.email }, r.session, h);

  const status = r.code === 'throttled' ? 429 : r.code === 'unverified' ? 403 : 401;
  return json({ error: r.reason, code: r.code }, status, h);
}

/**
 * Выслать письмо подтверждения заново.
 *
 * Спрашиваем пароль, а не только адрес. Ручка «пришлите письмо на этот адрес»
 * без пароля — это готовый способ засыпать чужой ящик нашими письмами, а
 * заодно испортить репутацию домена, с которого уходят письма всем остальным.
 * Проверка идёт тем же signIn: значит те же счётчики попыток и та же
 * неразличимость «неверный пароль» и «нет такого адреса».
 */
async function resendVerify(req, env, now, h) {
  const { email, password } = await req.json().catch(() => ({}));
  const r = await signIn(env.DB, { email, password, pepper: pepper(env),
                                   ip: clientIp(req), requireVerified: true }, now);

  if (r.code === 'throttled') return json({ error: r.reason, code: r.code }, 429, h);
  if (!r.ok && r.code !== 'unverified') return json({ error: r.reason, code: r.code }, 401, h);

  // Уже подтверждён — письма не шлём, но и отказом это не является:
  // человеку надо просто войти. Сессию, которую завёл signIn, здесь гасим:
  // куки мы не ставим, и жить ей в базе тридцать дней незачем.
  if (r.ok) {
    await destroySession(env.DB, r.session);
    return json({ ok: true, verified: true }, 200, h);
  }

  await sendVerify(env, r.email, now);
  return json({ ok: true, verified: false }, 200, h);
}

async function logout(req, env, h) {
  await destroySession(env.DB, readCookie(req, 'escx_session'));
  return json({ ok: true }, 200, { ...h, 'set-cookie': sessionCookie('', 0) });
}

/* ------------------------------------------------------------ пароль */

/**
 * Забытый пароль.
 * Ответ одинаков всегда — это тот самый случай, ради которого правило и
 * существует: здесь, в отличие от регистрации, обезличенный ответ ничего
 * не ломает. Кому надо, письмо придёт.
 */
async function forgot(req, env, now, h) {
  const { email } = await req.json().catch(() => ({}));
  const e = normalizeEmail(email);

  if (looksLikeEmail(e) && await getUser(env.DB, e)) {
    const token = await createLink(env.DB, e, 'reset', now);
    const link = `${env.SITE_URL}/account.html?reset=${token}`;
    await sendMail(env, e, 'Смена пароля в brink.watch',
      `Чтобы задать новый пароль, откройте ссылку. Она действует ${RESET_TTL_SEC / 60} минут ` +
      `и срабатывает один раз:\n\n${link}\n\n` +
      `Если пароль вы не забывали — письмо можно не читать, старый продолжает работать.`);
  }
  return json({ ok: true }, 200, h);
}

async function resetPass(req, env, now, h) {
  const { token, password } = await req.json().catch(() => ({}));
  const r = await resetPassword(env.DB, { token, newPassword: password, pepper: pepper(env) }, now);
  if (!r.ok) return json({ error: r.reason, code: r.code }, 400, h);
  return withSession({ ok: true, email: r.email }, r.session, h);
}

async function changePass(req, env, now, h) {
  const email = await whoami(env.DB, readCookie(req, 'escx_session'), now);
  if (!email) return json({ error: 'нужно войти' }, 401, h);

  const { old_password, password } = await req.json().catch(() => ({}));
  const r = await changePassword(
    env.DB, { email, oldPassword: old_password, newPassword: password, pepper: pepper(env) }, now);
  if (!r.ok) return json({ error: r.reason, code: r.code }, 400, h);

  // Старые сессии убиты, включая текущую, — выдаём новую, иначе человек
  // окажется выкинут из кабинета сразу после успешной смены пароля.
  return withSession({ ok: true, email: r.email }, r.session, h);
}

async function verify(url, env, now) {
  const r = await consumeLink(env.DB, url.searchParams.get('token'), 'verify', now);
  if (r.ok) await markVerified(env.DB, r.email);
  return new Response(null, {
    status: 302,
    headers: { location: `${env.SITE_URL}/account.html?verified=${r.ok ? 1 : 0}` },
  });
}

/* ------------------------------------------------------------- состояние */

async function notify(req, env, now, h) {
  const email = await whoami(env.DB, readCookie(req, 'escx_session'), now);
  if (!email) return json({ error: 'нужно войти' }, 401, h);
  const { on } = await req.json().catch(() => ({}));
  await setNotify(env.DB, email, !!on);
  return json({ ok: true, notify: !!on }, 200, h);
}

async function me(req, env, now, h) {
  const email = await whoami(env.DB, readCookie(req, 'escx_session'), now);
  const p = await planFor(env.DB, email, now, { requireVerified: env.REQUIRE_VERIFIED_EMAIL === '1' });
  const u = email ? await getUser(env.DB, email) : null;
  return json({
    email,
    verified: !!(u && u.verified_at),
    notify: u ? u.notify === 1 : false,
    ...p,
  }, 200, h);
}

async function data(req, env, now, h) {
  const email = await whoami(env.DB, readCookie(req, 'escx_session'), now);
  const { plan } = await planFor(env.DB, email, now,
    { requireVerified: env.REQUIRE_VERIFIED_EMAIL === '1' });

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

async function sendVerify(env, email, now) {
  const token = await createLink(env.DB, email, 'verify', now);
  await sendMail(env, email, 'Подтверждение адреса в brink.watch',
    `Вы завели кабинет на brink.watch. Чтобы войти, подтвердите адрес — ` +
    `откройте ссылку, она действует ${VERIFY_TTL_SEC / 3600} часа:\n\n` +
    `${env.SITE_URL}/api/verify?token=${token}\n\n` +
    `Если это были не вы, просто удалите письмо: без пароля в аккаунт не войти, ` +
    `а неподтверждённый аккаунт ничего не открывает.`);
}

async function sendMail(env, to, subject, text) {
  if (!env.RESEND_API_KEY) {           // локальная разработка — просто в лог
    console.log('[письмо не отправлено, нет ключа]', to, subject, text);
    return;
  }
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      from: env.MAIL_FROM, to, subject, text,
      // Ответ на служебное письмо должен попадать человеку, а не в никуда.
      ...(env.MAIL_REPLY_TO ? { reply_to: env.MAIL_REPLY_TO } : {}),
    }),
  });
  if (!r.ok) console.error('почта не ушла:', r.status, await r.text());
}
