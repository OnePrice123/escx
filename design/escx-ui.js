/* ============================================================================
   ESCX · дизайн-язык «Тепло» — примитивы отрисовки
   Ванильный ES-модуль, зависимостей нет. Работает и как <script type="module">,
   и через import в сборщике.

     import { lightArc, sparkWash, heatColor, heatWash } from './escx-ui.js';
     el.innerHTML = lightArc(64, { id: 'global' });

   Все функции возвращают строку SVG/CSS, ничего не монтируют сами и не трогают
   DOM — так их одинаково просто использовать из React, Vue и из голого JS.
   ============================================================================ */

const cssVar = name =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/** Цвет по накалу 0–100. Пять ступеней шкалы из tokens.css. */
export function heatColor(v){
  const i = v < 20 ? 0 : v < 40 ? 1 : v < 60 ? 2 : v < 80 ? 3 : 4;
  return cssVar('--t' + i);
}

/**
 * Значение для CSS-переменной --heat у .heatrow.
 * Сила заливки растёт с накалом: строка не раскрашивается, а теплеет.
 * stale=true (покрытие данных ниже порога) гасит подсветку полностью.
 */
export function heatWash(v, { stale = false } = {}){
  if (stale) return 'transparent';
  const strength = Math.round(6 + (Math.max(0, Math.min(100, v)) / 100) * 20);
  return `color-mix(in srgb, ${heatColor(v)} ${strength}%, transparent)`;
}

/* --- геометрия дуги --- */
const polar = (cx, cy, r, deg) => {
  const a = (deg - 90) * Math.PI / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
};
const arcPath = (cx, cy, r, a0, a1) => {
  const [x0, y0] = polar(cx, cy, r, a0), [x1, y1] = polar(cx, cy, r, a1);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${(a1 - a0) > 180 ? 1 : 0} 1 ` +
         `${x1.toFixed(2)} ${y1.toFixed(2)}`;
};

/**
 * Дуга как свет, а не как прибор.
 * Ни обводки, ни делений, ни стрелки: полоса разгорается к текущему значению
 * и заканчивается угольком. Значение читается числом рядом — цвет никогда
 * не является единственным носителем смысла.
 *
 * @param {number} value 0–100
 * @param {object} o  { r, sw, sweep, id, labels }  labels = ['МИР','ВОЙНА'] или null
 */
export function lightArc(value, o = {}){
  const { r = 150, sw = 13, sweep = 228, id = 'a',
          labels = ['МИР', 'ВОЙНА'] } = o;
  const pad = labels ? 40 : 16;
  const cx = r + sw + pad, cy = r + sw + 8, w = cx * 2;
  const h = cy + r * Math.sin((sweep / 2 - 90) * Math.PI / 180) + sw / 2 + (labels ? 34 : 14);
  const v  = Math.max(0, Math.min(100, value));
  const a0 = -sweep / 2, a1 = sweep / 2, av = a0 + (v / 100) * sweep;
  const col = heatColor(v), cold = cssVar('--t0');
  const [ex, ey] = polar(cx, cy, r, av);

  const ends = labels ? `
    <text x="${(cx - r - sw / 2 - 4).toFixed(0)}" y="${(cy + r * 0.62).toFixed(0)}"
      font-size="10" letter-spacing="2.6" text-anchor="middle"
      style="fill:var(--ink-4);font-weight:600">${labels[0]}</text>
    <text x="${(cx + r + sw / 2 + 4).toFixed(0)}" y="${(cy + r * 0.62).toFixed(0)}"
      font-size="10" letter-spacing="2.6" text-anchor="middle"
      style="fill:var(--ink-4);font-weight:600">${labels[1]}</text>` : '';

  return `
  <svg viewBox="0 0 ${w} ${h.toFixed(0)}" role="img"
       aria-label="Значение ${Math.round(v)} из 100"
       style="display:block;width:100%;height:auto;overflow:visible">
    <defs>
      <linearGradient id="lg-${id}" gradientUnits="userSpaceOnUse" x1="${cx - r}" y1="0" x2="${ex}" y2="0">
        <stop offset="0"   stop-color="${cold}" stop-opacity=".22"/>
        <stop offset=".45" stop-color="${col}"  stop-opacity=".62"/>
        <stop offset="1"   stop-color="${col}"  stop-opacity="1"/>
      </linearGradient>
      <radialGradient id="hl-${id}">
        <stop offset="0" stop-color="${col}" stop-opacity=".55"/>
        <stop offset="1" stop-color="${col}" stop-opacity="0"/>
      </radialGradient>
      <filter id="bl-${id}" x="-40%" y="-40%" width="180%" height="180%">
        <feGaussianBlur stdDeviation="9"/>
      </filter>
    </defs>
    <path d="${arcPath(cx, cy, r, a0, a1)}" fill="none" stroke-width="${sw}" stroke-linecap="round"
      style="stroke:color-mix(in srgb, var(--ink) 5%, transparent)"/>
    <path d="${arcPath(cx, cy, r, a0, av)}" fill="none" stroke="url(#lg-${id})"
      stroke-width="${sw + 10}" stroke-linecap="round" filter="url(#bl-${id})" opacity=".5"/>
    <path d="${arcPath(cx, cy, r, a0, av)}" fill="none" stroke="url(#lg-${id})"
      stroke-width="${sw}" stroke-linecap="round"/>
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="${sw * 1.9}" fill="url(#hl-${id})"/>
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="${(sw / 2 + 1).toFixed(1)}" fill="${col}"/>
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="${(sw / 2 - 3.2).toFixed(1)}"
      fill="var(--paper)" opacity=".92"/>
    ${ends}
  </svg>`;
}

/**
 * Спарклайн как акварель: линия почти невидима, работает мягкая заливка.
 * fluid=true растягивает по ширине контейнера (preserveAspectRatio="none").
 */
export function sparkWash(series, o = {}){
  const { w = 200, h = 30, color, id = 's', fluid = true } = o;
  if (!series || series.length < 2) return '';
  const col = color || heatColor(series[series.length - 1]);
  const mn = Math.min(...series), mx = Math.max(...series), r = (mx - mn) || 1;
  const X = i => (i / (series.length - 1)) * w;
  const Y = v => h - 3 - ((v - mn) / r) * (h - 7);
  const line = series.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1)).join(' ');
  const size = fluid
    ? `style="display:block;width:100%;height:${h}px" preserveAspectRatio="none"`
    : `width="${w}" height="${h}" style="display:block;overflow:visible"`;
  return `<svg viewBox="0 0 ${w} ${h}" ${size} aria-hidden="true">
    <defs><linearGradient id="w-${id}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity=".34"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/>
    </linearGradient></defs>
    <path d="${line} L ${w} ${h} L 0 ${h} Z" fill="url(#w-${id})"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="1.1" stroke-opacity=".45"
      stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

/**
 * Большой график накала с отсечками смен фазы.
 * marks: [{ at: индекс, label: 'Ограниченный конфликт' }]
 */
export function heatChart(series, o = {}){
  const { w = 1000, h = 210, marks = [], color, from = '12 месяцев назад', to = 'сегодня' } = o;
  const col = color || heatColor(series[series.length - 1]);
  const mn = Math.min(...series), mx = Math.max(...series), r = (mx - mn) || 1;
  const X = i => (i / (series.length - 1)) * w;
  const Y = v => h - 26 - ((v - mn) / r) * (h - 52);
  const line = series.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1)).join(' ');
  const mk = marks.map((m, i) => {
    const x = X(m.at);
    return `<line x1="${x.toFixed(0)}" y1="${i % 2 ? 34 : 14}" x2="${x.toFixed(0)}" y2="${h - 26}"
      style="stroke:color-mix(in srgb,var(--ink) 8%,transparent)" stroke-width="1"/>
      <text x="${(x + 8).toFixed(0)}" y="${i % 2 ? 38 : 18}" font-size="10.5"
      style="fill:var(--ink-3)">${m.label}</text>`;
  }).join('');
  return `<svg viewBox="0 0 ${w} ${h}" style="display:block;width:100%;height:auto">
    <defs><linearGradient id="hc-w" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity=".26"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    ${mk}
    <path d="${line} L ${w} ${h - 26} L 0 ${h - 26} Z" fill="url(#hc-w)"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="1.4" stroke-opacity=".6"
      stroke-linejoin="round"/>
    <circle cx="${X(series.length - 1).toFixed(1)}" cy="${Y(series[series.length - 1]).toFixed(1)}"
      r="4" fill="${col}"/>
    <text x="0" y="${h - 6}" font-size="10.5" style="fill:var(--ink-4)">${from}</text>
    <text x="${w}" y="${h - 6}" font-size="10.5" text-anchor="end"
      style="fill:var(--ink-4)">${to}</text>
  </svg>`;
}

/** Переключатель оттенка: sand | ash | clay. */
export function setTint(tint){
  document.documentElement.dataset.tint = tint;
}

/** Grayscale-тест. Правило продукта, а не отладочная утилита. */
export function toggleNoColor(){
  return document.body.classList.toggle('escx-nocolor');
}
