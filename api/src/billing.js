/* Приём вебхуков платёжной системы.
 *
 * Главное правило: источник истины о том, оплачено ли, — платёжная система,
 * а не наша база. База — только кэш её решений. При любом сомнении переспрашиваем.
 */
import { hmacHex, timingSafeEqual, normalizeEmail } from './util.js';

/**
 * Проверка подписи вебхука Paddle Billing.
 *
 * Заголовок: Paddle-Signature: ts=<unix>;h1=<hex>
 * Подписывается строка `${ts}:${rawBody}` алгоритмом HMAC-SHA256
 * на секрете точки назначения (префикс pdl_ntfset_).
 *
 * Тело обязательно берётся СЫРЫМ. Если сначала распарсить JSON, а потом
 * сериализовать обратно, подпись не сойдётся: порядок ключей и пробелы изменятся.
 */
export async function verifyPaddle(rawBody, signatureHeader, secret, nowSec, toleranceSec = 5) {
  if (!signatureHeader || !secret) return { ok: false, reason: 'нет подписи или секрета' };

  let ts = null, h1 = null;
  for (const part of String(signatureHeader).split(';')) {
    const [k, v] = part.split('=');
    if (k === 'ts') ts = v;
    if (k === 'h1') h1 = v;
  }
  if (!ts || !h1) return { ok: false, reason: 'заголовок подписи не разобран' };

  const age = Math.abs(Number(nowSec) - Number(ts));
  if (!Number.isFinite(age) || age > toleranceSec) {
    return { ok: false, reason: `метка времени вне допуска (${age} с)` };
  }

  const expected = await hmacHex(secret, `${ts}:${rawBody}`);
  return timingSafeEqual(expected, h1)
    ? { ok: true }
    : { ok: false, reason: 'подпись не совпала' };
}

/** Проверка подписи Stripe: Stripe-Signature: t=<unix>,v1=<hex>, подпись над `${t}.${body}`. */
export async function verifyStripe(rawBody, signatureHeader, secret, nowSec, toleranceSec = 300) {
  if (!signatureHeader || !secret) return { ok: false, reason: 'нет подписи или секрета' };
  let t = null; const v1 = [];
  for (const part of String(signatureHeader).split(',')) {
    const [k, v] = part.split('=');
    if (k?.trim() === 't') t = v;
    if (k?.trim() === 'v1') v1.push(v);
  }
  if (!t || !v1.length) return { ok: false, reason: 'заголовок подписи не разобран' };
  if (Math.abs(Number(nowSec) - Number(t)) > toleranceSec) {
    return { ok: false, reason: 'метка времени вне допуска' };
  }
  const expected = await hmacHex(secret, `${t}.${rawBody}`);
  return v1.some(s => timingSafeEqual(expected, s))
    ? { ok: true }
    : { ok: false, reason: 'подпись не совпала' };
}

/** Какие события Paddle меняют состояние подписки. */
const ACTIVE = new Set(['active', 'trialing']);

/**
 * Событие Paddle -> плоская запись для базы.
 * Возвращает null для событий, которые нас не касаются: молча игнорируем,
 * а не падаем — платёжка присылает много типов, и список со временем растёт.
 */
export function parsePaddleEvent(evt) {
  const type = evt?.event_type;
  if (!type || !String(type).startsWith('subscription.')) return null;

  const d = evt.data || {};
  const email = normalizeEmail(d.custom_data?.email || d.customer?.email);
  if (!email) return null;

  const item = (d.items || [])[0] || {};
  return {
    email,
    provider: 'paddle',
    subscription_id: d.id || null,
    customer_id: d.customer_id || null,
    price_id: item.price?.id || null,
    plan: item.price?.name || d.custom_data?.plan || 'pro',
    status: d.status || 'unknown',
    active: ACTIVE.has(d.status) ? 1 : 0,
    current_period_end: d.current_billing_period?.ends_at || null,
    raw_event_id: evt.event_id || null,
  };
}
