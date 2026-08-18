/* Офлайн-тесты API. Сеть и Cloudflare не нужны:
 * D1 подменяется заглушкой на обычных объектах, crypto берётся из Node.
 * Проверяется то, что ломается тихо: подписи, одноразовость ссылок, границы тарифов,
 * и главное про пароли — что в базе не остаётся ничего, чем можно войти.
 */
import { hmacHex, sha256Hex, timingSafeEqual, randomToken,
         normalizeEmail, looksLikeEmail, readCookie, sessionCookie } from '../src/util.js';
import { verifyPaddle, verifyStripe, parsePaddleEvent } from '../src/billing.js';
import { hashPassword, verifyPassword, checkPasswordPolicy, burnTime,
         HASH_ITERS, MIN_PASSWORD } from '../src/password.js';
import { registerUser, signIn, changePassword, resetPassword, createLink, consumeLink,
         whoami, destroySession, getUser, markVerified, setNotify,
         FAIL_MAX, RESET_TTL_SEC, VERIFY_TTL_SEC } from '../src/auth.js';
import { planFor, limitsOf, applyLimits, PLANS } from '../src/entitlement.js';

let ok = 0, bad = 0;
const check = (name, cond, extra = '') => {
  if (cond) { ok++; console.log(`  [ok]   ${name}`); }
  else { bad++; console.log(`  [FAIL] ${name} ${extra ?? ''}`); }
};

/* --- крошечная заглушка D1: тот же интерфейс prepare().bind().first()/run() --- */
function fakeDB() {
  const t = { magic_links: [], sessions: [], subscriptions: [], webhook_log: [],
              users: [], login_fails: [] };
  return {
    _t: t,
    prepare(sql) {
      const s = sql.replace(/\s+/g, ' ').trim();
      let args = [];
      const api = {
        bind(...a) { args = a; return api; },
        async first() {
          if (s.startsWith('SELECT email, pass_hash, verified_at, notify FROM users'))
            return t.users.find(r => r.email === args[0]) || null;
          if (s.startsWith('SELECT verified_at FROM users'))
            return t.users.find(r => r.email === args[0]) || null;
          if (s.startsWith('SELECT fails, window_end FROM login_fails'))
            return t.login_fails.find(r => r.scope === args[0]) || null;
          if (s.startsWith('SELECT email, purpose, expires_at, used FROM magic_links'))
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
          if (s.startsWith('INSERT INTO users'))
            t.users.push({ email: args[0], pass_hash: args[1], verified_at: null, notify: 1 });

          else if (s.startsWith('UPDATE users SET pass_hash')) {
            const u = t.users.find(x => x.email === args[1]); if (u) u.pass_hash = args[0];
          } else if (s.startsWith('UPDATE users SET verified_at')) {
            const u = t.users.find(x => x.email === args[0]);
            if (u) u.verified_at = u.verified_at || '2026-08-18 00:00:00';
          } else if (s.startsWith('UPDATE users SET notify')) {
            const u = t.users.find(x => x.email === args[1]); if (u) u.notify = args[0];
          }

          else if (s.startsWith('INSERT INTO login_fails')) {
            // Повторяем смысл ON CONFLICT: окно живо — счётчик растёт,
            // окно истекло — начинается заново.
            const [scope, newEnd, now] = [args[0], args[1], args[2]];
            const r = t.login_fails.find(x => x.scope === scope);
            if (!r) t.login_fails.push({ scope, fails: 1, window_end: newEnd });
            else if (r.window_end > now) r.fails += 1;
            else { r.fails = 1; r.window_end = newEnd; }
          } else if (s.startsWith('DELETE FROM login_fails'))
            t.login_fails = t.login_fails.filter(x => x.scope !== args[0]);

          else if (s.startsWith('INSERT INTO magic_links'))
            // used в запросе задан литералом, а не параметром — отсюда ?? 0.
            t.magic_links.push({ token_hash: args[0], email: args[1], purpose: args[2],
                                 expires_at: args[3], used: args[4] ?? 0 });
          else if (s.startsWith('UPDATE magic_links SET used')) {
            const r = t.magic_links.find(x => x.token_hash === args[0]); if (r) r.used = 1;
          }

          else if (s.startsWith('INSERT INTO sessions'))
            t.sessions.push({ session_hash: args[0], email: args[1], expires_at: args[2] });
          else if (s.startsWith('DELETE FROM sessions WHERE session_hash'))
            t.sessions = t.sessions.filter(x => x.session_hash !== args[0]);
          else if (s.startsWith('DELETE FROM sessions WHERE email'))
            t.sessions = t.sessions.filter(x => x.email !== args[0]);

          return { success: true };
        },
      };
      return api;
    },
  };
}

const NOW = 1_780_000_000;
const PEPPER = 'перец-из-секретов-worker';
const PW = 'СтарыйКонь-77';
const PW2 = 'НовыйКонь-88';

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

console.log('\n6. Хэширование паролей');
const h1 = await hashPassword(PW, PEPPER);
const h2 = await hashPassword(PW, PEPPER);
check('хэш не содержит пароля', !h1.includes(PW));
check('одинаковые пароли дают разные хэши (соль работает)', h1 !== h2);
check('в хэше записаны параметры', h1.startsWith(`pbkdf2$sha256$${HASH_ITERS}$p1$`));
check('верный пароль принят', (await verifyPassword(h1, PW, PEPPER)).ok);
check('неверный пароль отклонён', !(await verifyPassword(h1, PW2, PEPPER)).ok);
check('пустой пароль отклонён', !(await verifyPassword(h1, '', PEPPER)).ok);

// Перец — единственное, что защищает базу при утечке: без него хэш
// перебирается офлайн, поэтому проверяем, что он реально участвует.
check('без перца тот же пароль не подходит', !(await verifyPassword(h1, PW, '')).ok);
check('чужой перец не подходит', !(await verifyPassword(h1, PW, 'другой перец')).ok);

const hNoPepper = await hashPassword(PW, '');
check('хэш без перца помечен p0', hNoPepper.includes('$p0$'));
const vNoPepper = await verifyPassword(hNoPepper, PW, PEPPER);
check('старый хэш проверяется по записанным в нём параметрам, а не по текущим',
  vNoPepper.ok);
check('появление перца требует перехэширования', vNoPepper.needsRehash);

const hWeak = await hashPassword(PW, PEPPER, 1000);
const vWeak = await verifyPassword(hWeak, PW, PEPPER);
check('хэш с меньшим числом итераций ещё проверяется', vWeak.ok);
check('устаревшие итерации требуют перехэширования', vWeak.needsRehash);
check('свежий хэш перехэширования не требует',
  !(await verifyPassword(h1, PW, PEPPER)).needsRehash);

check('испорченная строка хэша не роняет', !(await verifyPassword('мусор', PW, PEPPER)).ok);
check('пустая строка хэша не роняет', !(await verifyPassword('', PW, PEPPER)).ok);
check('хэш с чужим алгоритмом отклонён',
  !(await verifyPassword('bcrypt$sha256$1$p0$aa$bb', PW, PEPPER)).ok);
check('число итераций выше предела платформы отвергается',
  await hashPassword(PW, PEPPER, 200_000).then(() => false, () => true));
check('заглушка постоянного времени не роняет',
  await burnTime(PEPPER).then(() => true, () => false));

console.log('\n7. Политика пароля');
check('короткий отклонён', !!checkPasswordPolicy('a'.repeat(MIN_PASSWORD - 1)));
check('достаточной длины принят', checkPasswordPolicy('корова-на-льду') === null);
check('распространённый отклонён', !!checkPasswordPolicy('password123'));
check('из двух символов отклонён', !!checkPasswordPolicy('abababababab'));
check('слишком длинный отклонён', !!checkPasswordPolicy('a'.repeat(500)));
check('пустой отклонён', !!checkPasswordPolicy(''));
check('null не роняет', !!checkPasswordPolicy(null));

console.log('\n8. Регистрация и вход');
let db = fakeDB();
const reg = await registerUser(db, { email: ' User@Example.com ', password: PW, pepper: PEPPER }, NOW);
check('регистрация прошла', reg.ok, reg.reason);
check('адрес нормализован при регистрации', db._t.users[0].email === 'user@example.com');
check('пароль в базе не в открытом виде', !JSON.stringify(db._t.users).includes(PW));
check('регистрация сразу даёт сессию',
  await whoami(db, reg.session, NOW + 10) === 'user@example.com');

const dup = await registerUser(db, { email: 'user@example.com', password: PW2, pepper: PEPPER }, NOW);
check('повторная регистрация отклонена', !dup.ok && dup.code === 'taken');
check('слабый пароль не регистрируется',
  (await registerUser(db, { email: 'w@e.com', password: '123', pepper: PEPPER }, NOW)).code === 'password');
check('пароль, равный адресу, не регистрируется',
  (await registerUser(db, { email: 'sameaddr@e.com', password: 'sameaddr@e.com', pepper: PEPPER }, NOW))
    .code === 'password');
check('кривой адрес не регистрируется',
  (await registerUser(db, { email: 'без-собаки', password: PW, pepper: PEPPER }, NOW)).code === 'email');
check('неудачная регистрация не создала пользователя', db._t.users.length === 1);

const in1 = await signIn(db, { email: 'USER@example.com ', password: PW, pepper: PEPPER }, NOW);
check('вход с верным паролем', in1.ok);
check('вход даёт рабочую сессию',
  await whoami(db, in1.session, NOW + 10) === 'user@example.com');

const inBadPw = await signIn(db, { email: 'user@example.com', password: 'не тот пароль' , pepper: PEPPER }, NOW);
const inNoUser = await signIn(db, { email: 'нет@такого.com', password: PW, pepper: PEPPER }, NOW);
check('неверный пароль отклонён', !inBadPw.ok);
check('несуществующий адрес отклонён', !inNoUser.ok);
check('причина отказа одна и та же — форма входа не выдаёт, кто зарегистрирован',
  inBadPw.reason === inNoUser.reason, `${inBadPw.reason} / ${inNoUser.reason}`);

// Перехэширование на входе: иначе заведённый позже секрет так и не начнёт
// защищать записи, сделанные до него.
db._t.users[0].pass_hash = await hashPassword(PW, '');
const inStale = await signIn(db, { email: 'user@example.com', password: PW, pepper: PEPPER }, NOW);
check('вход по устаревшему хэшу проходит', inStale.ok);
check('устаревший хэш пережат на входе', db._t.users[0].pass_hash.includes('$p1$'));

console.log('\n9. Ограничение частоты попыток');
db = fakeDB();
await registerUser(db, { email: 'u@e.com', password: PW, pepper: PEPPER }, NOW);
for (let i = 0; i < FAIL_MAX; i++)
  await signIn(db, { email: 'u@e.com', password: 'мимо', pepper: PEPPER, ip: '1.2.3.4' }, NOW);
const blocked = await signIn(db, { email: 'u@e.com', password: PW, pepper: PEPPER, ip: '1.2.3.4' }, NOW);
check('после предела попыток отказ даже с верным паролем', !blocked.ok && blocked.code === 'throttled');
check('окно не вечное — по его истечении вход снова открыт',
  (await signIn(db, { email: 'u@e.com', password: PW, pepper: PEPPER, ip: '1.2.3.4' },
                NOW + 16 * 60)).ok);
check('удачный вход обнулил счётчик', db._t.login_fails.length === 0);

// Перебор одного пароля по многим адресам счётчик по адресу не поймает —
// поэтому считаем и по источнику запроса.
db = fakeDB();
for (let i = 0; i < FAIL_MAX; i++)
  await signIn(db, { email: `нет${i}@e.com`, password: 'мимо', pepper: PEPPER, ip: '9.9.9.9' }, NOW);
check('счётчик по источнику ловит перебор по разным адресам',
  (await signIn(db, { email: 'ещё@e.com', password: 'мимо', pepper: PEPPER, ip: '9.9.9.9' }, NOW))
    .code === 'throttled');

console.log('\n10. Смена пароля');
db = fakeDB();
const acc = await registerUser(db, { email: 'c@e.com', password: PW, pepper: PEPPER }, NOW);
check('смена с неверным текущим паролем отклонена',
  !(await changePassword(db, { email: 'c@e.com', oldPassword: 'мимо', newPassword: PW2, pepper: PEPPER }, NOW)).ok);
check('слабый новый пароль отклонён',
  (await changePassword(db, { email: 'c@e.com', oldPassword: PW, newPassword: '1234', pepper: PEPPER }, NOW))
    .code === 'password');
const chg = await changePassword(db, { email: 'c@e.com', oldPassword: PW, newPassword: PW2, pepper: PEPPER }, NOW);
check('смена пароля прошла', chg.ok, chg.reason);
check('старая сессия убита — иначе смена пароля никого не выгоняет',
  await whoami(db, acc.session, NOW + 10) === null);
check('выдана новая сессия', await whoami(db, chg.session, NOW + 10) === 'c@e.com');
check('старый пароль больше не подходит',
  !(await signIn(db, { email: 'c@e.com', password: PW, pepper: PEPPER }, NOW)).ok);
check('новый пароль подходит',
  (await signIn(db, { email: 'c@e.com', password: PW2, pepper: PEPPER }, NOW)).ok);

console.log('\n11. Восстановление пароля по ссылке');
db = fakeDB();
const lost = await registerUser(db, { email: 'l@e.com', password: PW, pepper: PEPPER }, NOW);
const tok = await createLink(db, ' L@e.com ', 'reset', NOW);
check('в базу попал только хэш токена',
  db._t.magic_links[0].token_hash !== tok && db._t.magic_links[0].token_hash.length === 64);
check('ссылка для подтверждения не годится для сброса',
  !(await consumeLink(db, await createLink(db, 'l@e.com', 'verify', NOW), 'reset', NOW)).ok);

const weakReset = await resetPassword(db, { token: tok, newPassword: '123', pepper: PEPPER }, NOW);
check('слабый пароль при сбросе отклонён', weakReset.code === 'password');
check('отклонённый по паролю сброс не сжёг ссылку', db._t.magic_links[0].used === 0);

const res = await resetPassword(db, { token: tok, newPassword: PW2, pepper: PEPPER }, NOW + 60);
check('сброс прошёл', res.ok, res.reason);
check('сброс убил старые сессии', await whoami(db, lost.session, NOW + 61) === null);
check('сброс подтвердил адрес — письмо ведь дошло', !!db._t.users[0].verified_at);
check('новый пароль работает',
  (await signIn(db, { email: 'l@e.com', password: PW2, pepper: PEPPER }, NOW + 61)).ok);
check('повторное использование ссылки отклонено',
  !(await resetPassword(db, { token: tok, newPassword: PW, pepper: PEPPER }, NOW + 62)).ok);

const tokOld = await createLink(db, 'l@e.com', 'reset', NOW);
check('просроченная ссылка отклонена',
  !(await consumeLink(db, tokOld, 'reset', NOW + RESET_TTL_SEC + 1)).ok);
check('выдуманный токен отклонён', !(await consumeLink(db, 'нет-такого', 'reset', NOW)).ok);

// Ссылка подтверждения живёт дольше ссылки на смену пароля: её не просят,
// она приходит сама, и человек открывает письмо когда угодно.
const tokV = await createLink(db, 'l@e.com', 'verify', NOW);
check('ссылка подтверждения живёт дольше часа',
  (await consumeLink(db, tokV, 'verify', NOW + RESET_TTL_SEC + 60)).ok);
check('но не дольше суток',
  !(await consumeLink(db, await createLink(db, 'l@e.com', 'verify', NOW), 'verify',
                      NOW + VERIFY_TTL_SEC + 1)).ok);

console.log('\n11a. Обязательное подтверждение адреса');
db = fakeDB();
const pend = await registerUser(
  db, { email: 'v@e.com', password: PW, pepper: PEPPER, requireVerified: true }, NOW);
check('регистрация проходит', pend.ok);
check('но сессии не даёт — адрес не подтверждён', pend.session === null && pend.pending === true);
check('аккаунт при этом создан', db._t.users.length === 1);

const notYet = await signIn(
  db, { email: 'v@e.com', password: PW, pepper: PEPPER, requireVerified: true }, NOW);
check('вход с верным паролем закрыт до подтверждения',
  !notYet.ok && notYet.code === 'unverified');
check('но адрес возвращается — интерфейсу нужно предложить выслать письмо',
  notYet.email === 'v@e.com');
// Пароль назван верно — значит это хозяин аккаунта, и копить ему промахи
// не за что: иначе он упрётся в лимит, просто нажимая «войти» до подтверждения.
check('верный пароль не оставил счётчик попыток взведённым', db._t.login_fails.length === 0);
check('неверный пароль до подтверждения — обычный отказ, без намёка на аккаунт',
  (await signIn(db, { email: 'v@e.com', password: 'мимо', pepper: PEPPER, requireVerified: true }, NOW))
    .code === 'bad');
check('а вот промах счётчик взводит', db._t.login_fails.length === 1);

await markVerified(db, 'v@e.com');
const nowYes = await signIn(
  db, { email: 'v@e.com', password: PW, pepper: PEPPER, requireVerified: true }, NOW);
check('после подтверждения вход открыт', nowYes.ok);
check('и выдана рабочая сессия', await whoami(db, nowYes.session, NOW + 10) === 'v@e.com');

// Флаг выключен — старое поведение сохраняется целиком.
db = fakeDB();
const free1 = await registerUser(db, { email: 'f@e.com', password: PW, pepper: PEPPER }, NOW);
check('без флага регистрация сразу даёт сессию', !!free1.session && free1.pending === false);
check('без флага неподтверждённый адрес входит',
  (await signIn(db, { email: 'f@e.com', password: PW, pepper: PEPPER }, NOW)).ok);

console.log('\n12. Сессии и подписка на уведомления');
db = fakeDB();
const s = await registerUser(db, { email: 's@e.com', password: PW, pepper: PEPPER }, NOW);
check('сессия узнаётся', await whoami(db, s.session, NOW + 100) === 's@e.com');
check('чужая сессия не узнаётся', await whoami(db, randomToken(32), NOW) === null);
check('пустая сессия не узнаётся', await whoami(db, null, NOW) === null);
check('протухшая сессия не узнаётся', await whoami(db, s.session, NOW + 400 * 24 * 3600) === null);
await destroySession(db, s.session);
check('выход убивает сессию', await whoami(db, s.session, NOW + 100) === null);
check('новый аккаунт подписан на уведомления', (await getUser(db, 's@e.com')).notify === 1);
await setNotify(db, 's@e.com', false);
check('от уведомлений можно отписаться', (await getUser(db, 's@e.com')).notify === 0);
check('отписка не удалила аккаунт', db._t.users.length === 1);
await markVerified(db, 's@e.com');
check('подтверждение адреса записано', !!(await getUser(db, 's@e.com')).verified_at);

console.log('\n13. Тарифы и доступ');
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

// Флаг включается, когда заработает отправка писем.
db._t.users.push({ email: 'p@e.com', pass_hash: 'x', verified_at: null, notify: 1 });
check('с требованием подтверждения неподтверждённый адрес не получает pro',
  (await planFor(db, 'p@e.com', NOW, { requireVerified: true })).plan === 'free');
db._t.users[0].verified_at = '2026-08-18 00:00:00';
check('подтверждённый адрес получает pro',
  (await planFor(db, 'p@e.com', NOW, { requireVerified: true })).plan === 'pro');

console.log('\n14. Урезание витрины под тариф');
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

console.log('\n15. Cookie');
const req = new Request('https://x/', { headers: { cookie: 'a=1; escx_session=abc%20d; b=2' } });
check('cookie разобрана', readCookie(req, 'escx_session') === 'abc d');
check('отсутствующая cookie — null', readCookie(req, 'нет') === null);
const c = sessionCookie('v', 100);
check('cookie недоступна из JS', c.includes('HttpOnly'));
check('cookie только по HTTPS', c.includes('Secure'));
check('cookie защищена от CSRF', c.includes('SameSite=Lax'));

console.log('\n16. Маршруты Worker целиком');
/* Сами обработчики раньше не проверялись, и именно в них ломается самое
 * обидное: опечатка в имени поля, забытая кука, отсутствующая проверка входа.
 * Worker вызывается как настоящий — через свой fetch, с заглушкой D1. */
const worker = (await import('../src/index.js')).default;
const ENV = { DB: fakeDB(), SITE_URL: 'https://brink.watch', PROVIDER: 'paddle', AUTH_PEPPER: PEPPER };

/** Письмо без ключа Resend пишется в консоль — она бы утопила вывод тестов. */
async function quiet(fn) {
  const [log, warn] = [console.log, console.warn];
  console.log = console.warn = () => {};
  try { return await fn(); } finally { console.log = log; console.warn = warn; }
}
const hit = (method, path, body, cookie) => quiet(() => worker.fetch(new Request(
  `https://brink.watch${path}`,
  { method, headers: { 'content-type': 'application/json', ...(cookie ? { cookie } : {}) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) }), ENV, {}));
const cookieOf = res => (res.headers.get('set-cookie') || '').split(';')[0];

const rReg = await hit('POST', '/api/register', { email: 'w@e.com', password: PW });
check('POST /api/register отвечает 200', rReg.status === 200, rReg.status);
const sess = cookieOf(rReg);
check('регистрация выдаёт куку сессии', sess.startsWith('escx_session='));
check('кука закрыта от JS и CSRF',
  (rReg.headers.get('set-cookie') || '').includes('HttpOnly') &&
  (rReg.headers.get('set-cookie') || '').includes('SameSite=Lax'));

const rMe = await (await hit('GET', '/api/me', undefined, sess)).json();
check('GET /api/me узнаёт вошедшего', rMe.email === 'w@e.com', JSON.stringify(rMe));
check('новый аккаунт на бесплатном тарифе', rMe.plan === 'free');
check('новый аккаунт ещё не подтверждён', rMe.verified === false);
check('GET /api/me без куки не выдаёт адрес',
  (await (await hit('GET', '/api/me')).json()).email === null);

check('повторная регистрация — 409', (await hit('POST', '/api/register',
  { email: 'w@e.com', password: PW2 })).status === 409);
check('вход с неверным паролем — 401', (await hit('POST', '/api/signin',
  { email: 'w@e.com', password: 'мимо' })).status === 401);
check('вход с верным паролем — 200', (await hit('POST', '/api/signin',
  { email: 'w@e.com', password: PW })).status === 200);
check('забытый пароль отвечает 200 и на незнакомый адрес',
  (await hit('POST', '/api/password/forgot', { email: 'нет@такого.com' })).status === 200);

check('смена пароля без сессии — 401',
  (await hit('POST', '/api/password/change', { old_password: PW, password: PW2 })).status === 401);
check('уведомления без сессии — 401', (await hit('POST', '/api/notify', { on: true })).status === 401);
check('смена пароля с сессией проходит',
  (await hit('POST', '/api/password/change',
    { old_password: PW, password: PW2 }, sess)).status === 200);
check('после смены пароля старая сессия недействительна',
  (await (await hit('GET', '/api/me', undefined, sess)).json()).email === null);

check('пустое тело не роняет обработчик',
  (await hit('POST', '/api/signin', undefined)).status === 401);

/* Тот же Worker с включённым требованием подтверждения. Отдельная база:
 * иначе аккаунты из проверок выше сюда протекут. */
const ENV2 = { DB: fakeDB(), SITE_URL: 'https://brink.watch', PROVIDER: 'paddle',
               AUTH_PEPPER: PEPPER, REQUIRE_VERIFIED_EMAIL: '1' };
const hit2 = (method, path, body) => quiet(() => worker.fetch(new Request(
  `https://brink.watch${path}`,
  { method, headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) }), ENV2, {}));

const r2Reg = await hit2('POST', '/api/register', { email: 'v@e.com', password: PW });
check('с подтверждением регистрация отвечает 200', r2Reg.status === 200);
check('но куку не ставит', !r2Reg.headers.get('set-cookie'));
check('и честно говорит, что доступ ещё закрыт',
  (await r2Reg.json()).pending === true);
check('вход до подтверждения — 403, а не 401: пароль-то верный',
  (await hit2('POST', '/api/signin', { email: 'v@e.com', password: PW })).status === 403);

check('повторная отправка письма с чужим паролем — 401',
  (await hit2('POST', '/api/verify/resend', { email: 'v@e.com', password: 'мимо' })).status === 401);
const r2Send = await hit2('POST', '/api/verify/resend', { email: 'v@e.com', password: PW });
check('повторная отправка письма со своим паролем — 200', r2Send.status === 200);
check('и сообщает, что адрес ещё не подтверждён', (await r2Send.json()).verified === false);

// Проходим по ссылке из письма так же, как это сделал бы человек.
const link = ENV2.DB._t.magic_links.filter(l => l.purpose === 'verify' && !l.used).pop();
ENV2.DB._t.users[0].verified_at = '2026-08-18 00:00:00';   // как после GET /api/verify
check('письмо подтверждения вообще было отправлено', !!link);
check('после подтверждения вход проходит',
  (await hit2('POST', '/api/signin', { email: 'v@e.com', password: PW })).status === 200);
check('повторная отправка подтверждённому говорит, что письмо не нужно',
  (await (await hit2('POST', '/api/verify/resend', { email: 'v@e.com', password: PW })).json())
    .verified === true);
check('неизвестный маршрут — 404', (await hit('GET', '/api/чего-то')).status === 404);
check('OPTIONS отвечает 204', (await hit('OPTIONS', '/api/me')).status === 204);

console.log(`\n${'='.repeat(46)}\nпройдено ${ok}, провалено ${bad}\n${'='.repeat(46)}`);
process.exit(bad ? 1 : 0);
