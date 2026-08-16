/* Мелкие утилиты. Ничего специфичного для Cloudflare — поэтому тестируются офлайн. */

/** HMAC-SHA256 в hex. */
export async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/** SHA-256 в hex. Токены храним в базе только в виде хэша. */
export async function sha256Hex(s) {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Сравнение за постоянное время.
 * Обычное === выходит на первом несовпавшем байте, и по времени ответа можно
 * побайтно подобрать подпись. Здесь время не зависит от того, где расхождение.
 */
export function timingSafeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** Криптостойкий токен. */
export function randomToken(bytes = 32) {
  const b = new Uint8Array(bytes);
  crypto.getRandomValues(b);
  return [...b].map(x => x.toString(16).padStart(2, '0')).join('');
}

export function normalizeEmail(e) {
  return String(e || '').trim().toLowerCase();
}

/** Проверка вида адреса. Намеренно нестрогая: серьёзная проверка — доставка письма. */
export function looksLikeEmail(e) {
  return /^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$/.test(normalizeEmail(e));
}

export function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', ...headers },
  });
}

/** Разбор Cookie без зависимостей. */
export function readCookie(req, name) {
  const raw = req.headers.get('cookie') || '';
  for (const part of raw.split(';')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    if (part.slice(0, i).trim() === name) return decodeURIComponent(part.slice(i + 1).trim());
  }
  return null;
}

/**
 * Cookie сессии. HttpOnly — недоступна из JS, значит XSS не украдёт.
 * SameSite=Lax — не уходит на сторонние запросы, значит CSRF не сработает.
 */
export function sessionCookie(value, maxAgeSec) {
  const parts = [
    `escx_session=${encodeURIComponent(value)}`,
    'Path=/', 'HttpOnly', 'Secure', 'SameSite=Lax',
    `Max-Age=${maxAgeSec}`,
  ];
  return parts.join('; ');
}
