/* Вход по ссылке из письма. Паролей нет вообще.
 *
 * Почему так: пароль, которого мы не храним, невозможно украсть у нас.
 * Для инструмента с подпиской это не компромисс, а норма — человек всё равно
 * заходит раз в неделю, и «письмо со ссылкой» ему привычнее, чем ещё один пароль.
 */
import { randomToken, sha256Hex, normalizeEmail, looksLikeEmail } from './util.js';

export const MAGIC_TTL_SEC = 15 * 60;          // ссылка живёт 15 минут
export const SESSION_TTL_SEC = 30 * 24 * 3600; // сессия — 30 дней

/**
 * Создаёт одноразовую ссылку входа.
 * В базу кладём только SHA-256 от токена: утечка дампа не даёт войти.
 */
export async function createMagicLink(db, email, nowSec) {
  const e = normalizeEmail(email);
  if (!looksLikeEmail(e)) throw new Error('некорректный адрес');
  const token = randomToken(32);
  await db.prepare(
    'INSERT INTO magic_links (token_hash, email, expires_at, used) VALUES (?, ?, ?, 0)'
  ).bind(await sha256Hex(token), e, nowSec + MAGIC_TTL_SEC).run();
  return token;
}

/** Разменивает токен на сессию. Токен одноразовый. */
export async function consumeMagicLink(db, token, nowSec) {
  const hash = await sha256Hex(String(token || ''));
  const row = await db.prepare(
    'SELECT email, expires_at, used FROM magic_links WHERE token_hash = ?'
  ).bind(hash).first();

  if (!row) return { ok: false, reason: 'ссылка не найдена' };
  if (row.used) return { ok: false, reason: 'ссылка уже использована' };
  if (row.expires_at < nowSec) return { ok: false, reason: 'срок ссылки истёк' };

  await db.prepare('UPDATE magic_links SET used = 1 WHERE token_hash = ?').bind(hash).run();

  const sid = randomToken(32);
  await db.prepare(
    'INSERT INTO sessions (session_hash, email, expires_at) VALUES (?, ?, ?)'
  ).bind(await sha256Hex(sid), row.email, nowSec + SESSION_TTL_SEC).run();

  return { ok: true, email: row.email, session: sid };
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
