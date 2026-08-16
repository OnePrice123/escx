/* Что человеку доступно.
 *
 * Одно место принятия решения на весь проект. Если проверка доступа
 * размазана по обработчикам, рано или поздно один из них забудут — и закрытые
 * данные утекут. Здесь она одна и покрыта тестами.
 */

export const PLANS = {
  free: { dyads: 20, delayHours: 24, history_days: 90, alerts: false, api: false },
  pro:  { dyads: Infinity, delayHours: 0, history_days: Infinity, alerts: true, api: false },
  team: { dyads: Infinity, delayHours: 0, history_days: Infinity, alerts: true, api: false },
  api:  { dyads: Infinity, delayHours: 0, history_days: Infinity, alerts: true, api: true },
};

/**
 * Текущий тариф по данным базы.
 * Гость и человек с истёкшей подпиской — оба получают free, а не отказ:
 * бесплатная часть доступна всем, это витрина продукта.
 */
export async function planFor(db, email, nowSec) {
  if (!email) return { plan: 'free', status: 'anonymous', until: null };

  const row = await db.prepare(
    `SELECT plan, status, active, current_period_end
       FROM subscriptions
      WHERE email = ?
      ORDER BY updated_at DESC
      LIMIT 1`
  ).bind(email).first();

  if (!row) return { plan: 'free', status: 'none', until: null };

  const until = row.current_period_end ? Date.parse(row.current_period_end) / 1000 : null;

  // Подписка считается действующей, если платёжка сказала «активна»
  // И оплаченный период ещё не кончился. Достаточно одному условию отвалиться.
  const live = row.active === 1 && (until === null || until > nowSec);
  const plan = live && PLANS[row.plan] ? row.plan : 'free';

  return { plan, status: row.status, until: row.current_period_end || null };
}

/** Ограничения тарифа. Неизвестный тариф трактуется как free — безопасная сторона. */
export function limitsOf(plan) {
  return PLANS[plan] || PLANS.free;
}

/**
 * Фильтрация витрины под тариф.
 * На free режем список и прячем свежие сутки: это и есть ценность подписки.
 */
export function applyLimits(payload, plan, nowSec) {
  const lim = limitsOf(plan);
  const out = { ...payload, plan };

  if (Array.isArray(payload.dyads)) {
    let dyads = [...payload.dyads].sort((a, b) => (b.delta_30 ?? 0) - (a.delta_30 ?? 0));
    if (Number.isFinite(lim.dyads)) {
      out.dyads_total = dyads.length;
      dyads = dyads.slice(0, lim.dyads);
    }
    if (Number.isFinite(lim.history_days)) {
      dyads = dyads.map(d => Array.isArray(d.series_90d)
        ? { ...d, series_90d: d.series_90d.slice(-lim.history_days) }
        : d);
    }
    out.dyads = dyads;
  }

  if (lim.delayHours > 0) {
    out.delayed_hours = lim.delayHours;
    out.notice = `Бесплатный доступ: ${lim.dyads} диад, задержка ${lim.delayHours} ч`;
  }
  return out;
}
