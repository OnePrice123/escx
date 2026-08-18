/* Вход по адресу почты и паролю. Сессии. Восстановление пароля.
 *
 * Раньше пароля не было: вход шёл по одноразовой ссылке из письма. Решение
 * отменено — оно требовало работающей отправки писем, а её пока нет, и
 * кабинет из-за этого стоял целиком. Теперь письмо нужно только чтобы вернуть
 * забытый пароль, и до первой такой просьбы кабинет работает без почты вовсе.
 *
 * Адрес — единственный идентификатор человека и здесь, и в платёжке, и в
 * будущей рассылке уведомлений. Поэтому он нормализуется в одном месте
 * (normalizeEmail) и нигде больше не приводится к нижнему регистру руками.
 */
import { randomToken, sha256Hex, normalizeEmail, looksLikeEmail } from './util.js';
import { hashPassword, verifyPassword, checkPasswordPolicy, burnTime } from './password.js';

export const SESSION_TTL_SEC = 30 * 24 * 3600;  // сессия — 30 дней

/* Срок ссылки зависит от того, зачем она.
 *
 * Смена пароля — час: ссылку просят прямо сейчас, сидя у почты, и чем меньше
 * она живёт, тем меньше толку от неё тому, кто получил доступ к ящику позже.
 *
 * Подтверждение адреса — сутки: письмо приходит не по просьбе, а само, и
 * человек вполне может открыть его вечером. Часовая ссылка здесь означала бы
 * поток обращений «ссылка не работает» на тот же support@. */
export const RESET_TTL_SEC = 60 * 60;
export const VERIFY_TTL_SEC = 24 * 3600;
const ttlFor = purpose => (purpose === 'verify' ? VERIFY_TTL_SEC : RESET_TTL_SEC);

/* Пять промахов за пятнадцать минут. Число выбрано так, чтобы человек,
 * перепутавший раскладку и регистр, до предела не добрался, а перебор по
 * словарю стал бессмысленным. */
export const FAIL_MAX = 5;
export const FAIL_WINDOW_SEC = 15 * 60;

/* ------------------------------------------------------- частота попыток */

/**
 * Не пора ли перестать отвечать этому источнику.
 * Проверяется до сверки пароля: считать PBKDF2 для того, кто уже исчерпал
 * попытки, — значит подарить ему наше процессорное время.
 */
export async function tooManyFails(db, scopes, nowSec) {
  for (const scope of scopes) {
    const row = await db.prepare(
      'SELECT fails, window_end FROM login_fails WHERE scope = ?'
    ).bind(scope).first();
    if (row && row.window_end > nowSec && row.fails >= FAIL_MAX) return true;
  }
  return false;
}

/** Отметить промах. Окно, если истекло, начинается заново с единицы. */
export async function noteFail(db, scopes, nowSec) {
  for (const scope of scopes) {
    await db.prepare(
      `INSERT INTO login_fails (scope, fails, window_end) VALUES (?, 1, ?)
         ON CONFLICT(scope) DO UPDATE SET
           fails = CASE WHEN login_fails.window_end > ?
                        THEN login_fails.fails + 1 ELSE 1 END,
           window_end = CASE WHEN login_fails.window_end > ?
                             THEN login_fails.window_end ELSE ? END`
    ).bind(scope, nowSec + FAIL_WINDOW_SEC, nowSec, nowSec, nowSec + FAIL_WINDOW_SEC).run();
  }
}

/** Удачный вход стирает счётчик: иначе он копится у нормального человека. */
export async function clearFails(db, scopes) {
  for (const scope of scopes) {
    await db.prepare('DELETE FROM login_fails WHERE scope = ?').bind(scope).run();
  }
}

/* ------------------------------------------------------------ сессии */

export async function createSession(db, email, nowSec) {
  const sid = randomToken(32);
  await db.prepare(
    'INSERT INTO sessions (session_hash, email, expires_at) VALUES (?, ?, ?)'
  ).bind(await sha256Hex(sid), email, nowSec + SESSION_TTL_SEC).run();
  return sid;
}

/** Кто пришёл. null, если сессии нет или она протухла. */
export async function whoami(db, sessionId, nowSec) {
  if (!sessionId) return null;
  const row = await db.prepare(
    'SELECT email, expires_at FROM sessions WHERE session_hash = ?'
  ).bind(await sha256Hex(sessionId)).first();
  if (!row || row.expires_at < nowSec) return null;
  return row.email;
}

export async function destroySession(db, sessionId) {
  if (!sessionId) return;
  await db.prepare('DELETE FROM sessions WHERE session_hash = ?')
    .bind(await sha256Hex(sessionId)).run();
}

/**
 * Выкинуть все сессии адреса.
 * Обязательно при смене и сбросе пароля: смысл смены пароля в том, чтобы
 * выгнать того, кто вошёл раньше. Если оставить его сессию живой, смена
 * пароля ничего не меняет, а человек считает, что защитился.
 */
export async function destroyAllSessions(db, email) {
  await db.prepare('DELETE FROM sessions WHERE email = ?')
    .bind(normalizeEmail(email)).run();
}

/* ------------------------------------------------------- пользователи */

export async function getUser(db, email) {
  return await db.prepare(
    'SELECT email, pass_hash, verified_at, notify FROM users WHERE email = ?'
  ).bind(normalizeEmail(email)).first();
}

/**
 * Регистрация.
 *
 * Здесь мы СОЗНАТЕЛЬНО отвечаем «адрес уже занят» вместо обезличенного «ок».
 * Прежнее правило «ответ одинаков для существующего и несуществующего адреса»
 * относится ко ВХОДУ и остаётся в силе. Для регистрации его выполнить нельзя
 * не соврав: показать «готово» тому, у кого аккаунт не создан, значит отправить
 * человека ждать письма, которого не будет. Утечка здесь ровно одна — можно
 * узнать, зарегистрирован ли адрес; частота попыток ограничена тем же
 * счётчиком, а платящих у нас единицы.
 *
 * requireVerified меняет исход: аккаунт заводится, но сессия НЕ выдаётся —
 * пока человек не откроет ссылку из письма, войти он не сможет. Отсюда
 * pending в ответе: регистрация прошла, но кабинет ещё закрыт.
 */
export async function registerUser(db, { email, password, pepper = '', requireVerified = false }, nowSec) {
  const e = normalizeEmail(email);
  if (!looksLikeEmail(e)) return { ok: false, code: 'email', reason: 'некорректный адрес' };

  const bad = checkPasswordPolicy(password);
  if (bad) return { ok: false, code: 'password', reason: bad };

  // Пароль, равный собственному адресу, формально проходит политику по длине.
  if (String(password).trim().toLowerCase() === e)
    return { ok: false, code: 'password', reason: 'пароль не должен совпадать с адресом' };

  if (await getUser(db, e))
    return { ok: false, code: 'taken', reason: 'адрес уже зарегистрирован' };

  await db.prepare(
    `INSERT INTO users (email, pass_hash, created_at, updated_at)
     VALUES (?, ?, datetime('now'), datetime('now'))`
  ).bind(e, await hashPassword(password, pepper)).run();

  if (requireVerified) return { ok: true, email: e, pending: true, session: null };
  return { ok: true, email: e, pending: false, session: await createSession(db, e, nowSec) };
}

/**
 * Вход.
 *
 * Причина отказа наружу одна на все случаи — «адрес или пароль не подходят».
 * Разделять «нет такого адреса» и «пароль неверный» удобно человеку и ещё
 * удобнее тому, кто собирает список наших подписчиков.
 */
export async function signIn(db, { email, password, pepper = '', ip = '', requireVerified = false }, nowSec) {
  const e = normalizeEmail(email);
  const scopes = ip ? [`email:${e}`, `ip:${ip}`] : [`email:${e}`];

  if (await tooManyFails(db, scopes, nowSec))
    return { ok: false, code: 'throttled', reason: 'слишком много попыток, попробуйте через 15 минут' };

  const user = await getUser(db, e);

  // Ни адреса, ни пароля — но время потратить обязаны: мгновенный отказ
  // отличается от отказа после PBKDF2 и выдаёт, что адрес не зарегистрирован.
  if (!user || !user.pass_hash) {
    await burnTime(pepper);
    await noteFail(db, scopes, nowSec);
    return { ok: false, code: 'bad', reason: 'адрес или пароль не подходят' };
  }

  const { ok, needsRehash } = await verifyPassword(user.pass_hash, password, pepper);
  if (!ok) {
    await noteFail(db, scopes, nowSec);
    return { ok: false, code: 'bad', reason: 'адрес или пароль не подходят' };
  }

  // Параметры хэширования устарели (подняли итерации или завели перец) —
  // пережимаем сейчас, пока пароль у нас в руках в открытом виде.
  if (needsRehash) await setPassword(db, e, password, pepper);

  // Счётчик стираем ДО проверки подтверждения: пароль назван верно, значит
  // это хозяин аккаунта, и держать его под подозрением в переборе не за что.
  await clearFails(db, scopes);

  // Адрес не подтверждён — вход закрыт, но причина названа прямо и адрес
  // возвращается: интерфейсу нужно предложить выслать письмо заново, а тайны
  // здесь уже нет — пароль человек знает, то есть аккаунт его.
  if (requireVerified && !user.verified_at)
    return { ok: false, code: 'unverified', email: e,
             reason: 'адрес не подтверждён — откройте ссылку из письма' };

  return { ok: true, email: e, session: await createSession(db, e, nowSec) };
}

/** Смена пароля тем, кто уже вошёл. Старый пароль спрашивается обязательно. */
export async function changePassword(db, { email, oldPassword, newPassword, pepper = '' }, nowSec) {
  const e = normalizeEmail(email);
  const user = await getUser(db, e);
  if (!user || !user.pass_hash) return { ok: false, code: 'bad', reason: 'пароль не задан' };

  const { ok } = await verifyPassword(user.pass_hash, oldPassword, pepper);
  if (!ok) return { ok: false, code: 'bad', reason: 'текущий пароль не подходит' };

  const bad = checkPasswordPolicy(newPassword);
  if (bad) return { ok: false, code: 'password', reason: bad };

  await setPassword(db, e, newPassword, pepper);
  await destroyAllSessions(db, e);
  return { ok: true, email: e, session: await createSession(db, e, nowSec) };
}

/** Запись нового пароля. Точка, через которую проходят все изменения. */
export async function setPassword(db, email, password, pepper = '') {
  await db.prepare(
    `UPDATE users SET pass_hash = ?, updated_at = datetime('now') WHERE email = ?`
  ).bind(await hashPassword(password, pepper), normalizeEmail(email)).run();
}

/* ------------------------------------------- ссылки из письма (сброс) */

/**
 * Одноразовая ссылка. purpose разделяет назначения: токен, выданный для
 * подтверждения адреса, не должен годиться для смены пароля.
 */
export async function createLink(db, email, purpose, nowSec) {
  const e = normalizeEmail(email);
  if (!looksLikeEmail(e)) throw new Error('некорректный адрес');
  const token = randomToken(32);
  await db.prepare(
    'INSERT INTO magic_links (token_hash, email, purpose, expires_at, used) VALUES (?, ?, ?, ?, 0)'
  ).bind(await sha256Hex(token), e, purpose, nowSec + ttlFor(purpose)).run();
  return token;
}

/** Погасить токен. Одноразовость — свойство базы, а не вежливости клиента. */
export async function consumeLink(db, token, purpose, nowSec) {
  const hash = await sha256Hex(String(token || ''));
  const row = await db.prepare(
    'SELECT email, purpose, expires_at, used FROM magic_links WHERE token_hash = ?'
  ).bind(hash).first();

  if (!row) return { ok: false, reason: 'ссылка не найдена' };
  if (row.used) return { ok: false, reason: 'ссылка уже использована' };
  if (row.purpose !== purpose) return { ok: false, reason: 'ссылка не для этого действия' };
  if (row.expires_at < nowSec) return { ok: false, reason: 'срок ссылки истёк' };

  await db.prepare('UPDATE magic_links SET used = 1 WHERE token_hash = ?').bind(hash).run();
  return { ok: true, email: row.email };
}

/**
 * Сброс пароля по ссылке из письма.
 * Заодно подтверждает адрес: письмо дошло — значит адрес указан не чужой.
 */
export async function resetPassword(db, { token, newPassword, pepper = '' }, nowSec) {
  const bad = checkPasswordPolicy(newPassword);
  if (bad) return { ok: false, code: 'password', reason: bad };

  const r = await consumeLink(db, token, 'reset', nowSec);
  if (!r.ok) return { ok: false, code: 'link', reason: r.reason };

  await setPassword(db, r.email, newPassword, pepper);
  await markVerified(db, r.email);
  await destroyAllSessions(db, r.email);
  return { ok: true, email: r.email, session: await createSession(db, r.email, nowSec) };
}

export async function markVerified(db, email) {
  await db.prepare(
    `UPDATE users SET verified_at = COALESCE(verified_at, datetime('now')),
                      updated_at = datetime('now')
      WHERE email = ?`
  ).bind(normalizeEmail(email)).run();
}

/** Согласие на уведомления. Отписка не должна требовать удаления аккаунта. */
export async function setNotify(db, email, on) {
  await db.prepare(
    `UPDATE users SET notify = ?, updated_at = datetime('now') WHERE email = ?`
  ).bind(on ? 1 : 0, normalizeEmail(email)).run();
}
