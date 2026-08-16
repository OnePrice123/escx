/* Офлайн-тесты API. Сеть и Cloudflare не нужны:
 * D1 подменяется заглушкой на обычных объектах, crypto берётся из Node.
 * Проверяется то, что ломается тихо: подписи, одноразовость ссылок, границы тарифов.
 */
import { hmacHex, sha256Hex, timingSafeEqual, randomToken,
         normalizeEmail, looksLikeEmail, readCookie, sessionCookie } from '../src/util.js';
import { verifyPaddle, verifyStripe, parsePaddleEvent } from '../src/billing.js';
import { createMagicLink, consumeMagicLink, whoami, destroySession,
         MAGIC_TTL_SEC } from '../src/auth.js';
import { planFor, limitsOf, applyLimits, PLANS } from '../src/entitlement.js';

let ok = 0, bad = 0;
const check = (name, cond, extra = '') => {
  if (cond) { ok++; console.log(`  [ok]   ${name}`); }
  else { bad++; console.log(`  [FAIL] ${name} ${extra ?? ''}`); }
};

/* --- крошечная заглушка D1: тот же интерфейс prepare().bind().first()/run() --- */
function fakeDB() {
  const t = { magic_links: [], sessions: [], subscriptions: [], webhook_log: [] };
  return {
    _t: t,
    prepare(sql) {
      const s = sql.replace(/\s+/g, ' ').trim();
      let args = [];
      const api = {
        bind(...a) { args = a; return api; },
        async first() {
          if (s.startsWith('SELECT email, expires_at, used FROM magic_links'))
            return t.magic_links.find(r => r.token_hash === args[0]) || null;
          if (s.startsWith('SELECT email, expires_at FROM sessions'))
            return t.sessions.find(r => r.session_hash === args[0]) || null;
          if (s.startsWith('SELECT plan, status, active'))
            return t.subscriptions.filter(r => r.email === args[0])
                     .sort((a, b) => b.updated_at - a.updated_at)[0] || null;
          if (s.startsWith('SELECT 1 FROM webhook_log'))
            return t.webhook_log.find(r => r.event_id === args[0]) || null;
          return null;
        },
        async run() {
          if (s.startsWith('INSERT INTO magic_links'))
            t.magic_links.push({ token_hash: args[0], email: args[1],
                                 expires_at: args[2], used: args[3] });
          else if (s.startsWith('UPDATE magic_links SET used')) {
            const r = t.magic_links.find(x => x.token_hash === args[0]); if (r) r.used = 1;
          } else if (s.startsWith('INSERT INTO sessions'))
            t.sessions.push({ session_hash: args[0], email: args[1], expires_at: args[2] });
          else if (s.startsWith('DELETE FROM sessions'))
            t.sessions = t.sessions.filter(x => x.session_hash !== args[0]);
          return { success: true };
        },
      };
      return api;
    },
  };
}

const NOW = 1_780_000_000;

console.log('\n1. Криптоутилиты');
check('HMAC воспроизводим', await hmacHex('k', 'msg') === await hmacHex('k', 'msg'));
check('другой ключ — другой HMAC', await hmacHex('k1', 'm') !== await hmacHex('k2', 'm'));
check('сравнение равных строк', timingSafeEqual('abc', 'abc'));
check('сравнение разных строк', !timingSafeEqual('abc', 'abd'));
check('разная длина не совпадает', !timingSafeEqual('abc', 'abcd'));
check('нестроковые аргументы безопасны', !timingSafeEqual(null, 'abc'));
const toks = new Set(Array.from({ length: 500 }, () => randomToken(16)));
check('токены не повторяются', toks.size === 500);
check('токен достаточной длины', randomToken(32).length === 64);

console.log('\n2. Адреса');
check('регистр и пробелы нормализуются', normalizeEmail('  A@B.Ru ') === 'a@b.ru');
check('нормальный адрес принят', looksLikeEmail('user@example.com'));
check('без домена отклонён', !looksLikeEmail('user@localhost'));
check('без собаки отклонён', !looksLikeEmail('userexample.com'));
check('пустой отклонён', !looksLikeEmail(''));

console.log('\n3. Подпись вебхука Paddle');
const SECRET = 'pdl_ntfset_testsecret';
const body = JSON.stringify({ event_id: 'evt_1', event_type: 'subscription.created' });
const goodSig = `ts=${NOW};h1=${await hmacHex(SECRET, `${NOW}:${body}`)}`;
check('верная подпись принята', (await verifyPaddle(body, goodSig, SECRET, NOW)).ok);
check('чужой секрет отклонён', !(await verifyPaddle(body, goodSig, 'другой', NOW)).ok);
check('изменённое тело отклонено',
  !(await verifyPaddle(body + ' ', goodSig, SECRET, NOW)).ok);
check('старая метка времени отклонена (защита от повтора)',
  !(await verifyPaddle(body, goodSig, SECRET, NOW + 3600)).ok);
check('метка в пределах допуска принята',
  (await verifyPaddle(body, goodSig, SECRET, NOW + 3)).ok);
check('без заголовка отклонено', !(await verifyPaddle(body, null, SECRET, NOW)).ok);
check('мусор в заголовке отклонён', !(await verifyPaddle(body, 'ерунда', SECRET, NOW)).ok);
check('без секрета отклонено', !(await verifyPaddle(body, goodSig, '', NOW)).ok);

console.log('\n4. Подпись вебхука Stripe');
const sSig = `t=${NOW},v1=${await hmacHex(SECRET, `${NOW}.${body}`)}`;
check('верная подпись принята', (await verifyStripe(body, sSig, SECRET, NOW)).ok);
check('подделка отклонена', !(await verifyStripe(body, `t=${NOW},v1=deadbeef`, SECRET, NOW)).ok);

console.log('\n5. Разбор события подписки');
const evt = {
  event_id: 'evt_2', event_type: 'subscription.created',
  data: { id: 'sub_1', customer_id: 'ctm_1', status: 'active',
          custom_data: { email: 'A@Example.COM' },
          current_billing_period: { ends_at: '2026-09-16T00:00:00Z' },
          items: [{ price: { id: 'pri_1', name: 'pro' } }] },
};
const parsed = parsePaddleEvent(evt);
check('адрес нормализован', parsed.email === 'a@example.com');
check('активная подписка помечена', parsed.active === 1);
check('план извлечён', parsed.plan === 'pro');
check('отменённая не активна',
  parsePaddleEvent({ ...evt, data: { ...evt.data, status: 'canceled' } }).active === 0);
check('чужое событие игнорируется',
  parsePaddleEvent({ event_type: 'transaction.paid', data: {} }) === null);
check('событие без адреса игнорируется',
  parsePaddleEvent({ event_type: 'subscription.created', data: { id: 'x' } }) === null);

console.log('\n6. Вход по ссылке');
let db = fakeDB();
const tok = await createMagicLink(db, ' User@Example.com ', NOW);
check('в базу попал только хэш токена',
  db._t.magic_links[0].token_hash !== tok && db._t.magic_links[0].token_hash.length === 64);
const r1 = await consumeMagicLink(db, tok, NOW + 60);
check('ссылка обменена на сессию', r1.ok && r1.email === 'user@example.com');
const r2 = await consumeMagicLink(db, tok, NOW + 61);
check('повторное использование отклонено', !r2.ok, r2.reason);
const tok2 = await createMagicLink(db, 'b@example.com', NOW);
check('просроченная ссылка отклонена',
  !(await consumeMagicLink(db, tok2, NOW + MAGIC_TTL_SEC + 1)).ok);
check('выдуманный токен отклонён', !(await consumeMagicLink(db, 'нет-такого', NOW)).ok);
check('сессия узнаётся', await whoami(db, r1.session, NOW + 100) === 'user@example.com');
check('чужая сессия не узнаётся', await whoami(db, randomToken(32), NOW) === null);
check('пустая сессия не узнаётся', await whoami(db, null, NOW) === null);
check('протухшая сессия не узнаётся',
  await whoami(db, r1.session, NOW + 400 * 24 * 3600) === null);
await destroySession(db, r1.session);
check('выход убивает сессию', await whoami(db, r1.session, NOW + 100) === null);

console.log('\n7. Тарифы и доступ');
db = fakeDB();
check('гость получает free', (await planFor(db, null, NOW)).plan === 'free');
check('неизвестный адрес получает free', (await planFor(db, 'x@y.zz', NOW)).plan === 'free');
db._t.subscriptions.push({ email: 'p@e.com', plan: 'pro', status: 'active', active: 1,
  current_period_end: '2027-01-01T00:00:00Z', updated_at: 2 });
check('активная подписка даёт pro', (await planFor(db, 'p@e.com', NOW)).plan === 'pro');
db._t.subscriptions.push({ email: 'q@e.com', plan: 'pro', status: 'past_due', active: 0,
  current_period_end: '2027-01-01T00:00:00Z', updated_at: 2 });
check('неоплаченная подписка не даёт pro', (await planFor(db, 'q@e.com', NOW)).plan === 'free');
db._t.subscriptions.push({ email: 'r@e.com', plan: 'pro', status: 'active', active: 1,
  current_period_end: '2020-01-01T00:00:00Z', updated_at: 2 });
check('истёкший период не даёт pro, даже если статус активен',
  (await planFor(db, 'r@e.com', NOW)).plan === 'free');
check('неизвестный тариф трактуется как free', limitsOf('чтототакое') === PLANS.free);

console.log('\n8. Урезание витрины под тариф');
const payload = { dyads: Array.from({ length: 60 }, (_, i) => ({
  dyad_id: `D${i}`, delta_30: i, series_90d: Array.from({ length: 90 }, (_, k) => k) })) };
const free = applyLimits(payload, 'free', NOW);
const pro = applyLimits(payload, 'pro', NOW);
check('free урезан до 20 диад', free.dyads.length === 20, free.dyads.length);
check('free знает общее число', free.dyads_total === 60);
check('free получает самые изменившиеся', free.dyads[0].delta_30 === 59);
check('free предупреждён о задержке', free.delayed_hours === 24 && !!free.notice);
check('pro получает все диады', pro.dyads.length === 60);
check('pro без задержки', pro.delayed_hours === undefined);
check('исходные данные не испорчены', payload.dyads.length === 60);
check('тариф проставлен в ответе', free.plan === 'free' && pro.plan === 'pro');
check('пустая витрина не роняет', applyLimits({}, 'free', NOW).plan === 'free');

console.log('\n9. Cookie');
const req = new Request('https://x/', { headers: { cookie: 'a=1; escx_session=abc%20d; b=2' } });
check('cookie разобрана', readCookie(req, 'escx_session') === 'abc d');
check('отсутствующая cookie — null', readCookie(req, 'нет') === null);
const c = sessionCookie('v', 100);
check('cookie недоступна из JS', c.includes('HttpOnly'));
check('cookie только по HTTPS', c.includes('Secure'));
check('cookie защищена от CSRF', c.includes('SameSite=Lax'));

console.log(`\n${'='.repeat(46)}\nпройдено ${ok}, провалено ${bad}\n${'='.repeat(46)}`);
process.exit(bad ? 1 : 0);
