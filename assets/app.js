/* ═══════════════════════════════════════════
   BRINK.WATCH — сборка интерфейса
   ═══════════════════════════════════════════ */

const SVGNS = 'http://www.w3.org/2000/svg';
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* Выбор языка при первом заходе.
   Берём Accept-Language браузера — сигнал, которым управляет сам пользователь.
   IP-геолокацию не используем сознательно: см. docs/03-stek.md.
   Явный выбор пользователя всегда старше всего остального. */
function negotiateLang() {
  const saved = localStorage.getItem('px.lang');
  if (saved && I18N[saved]) return saved;

  const available = LANG_ORDER.filter(c => I18N[c]);
  for (const want of (navigator.languages || [navigator.language || ''])) {
    const base = want.toLowerCase().split('-')[0];
    const hit = available.find(c => c === base);
    if (hit) return hit;
  }
  return 'en';   // x-default: нейтральный запасной вариант, а не язык автора
}

let LANG = negotiateLang();

/* Реестр наполняется асинхронно (live.js), поэтому выбрать вид на этапе
   загрузки скрипта нечем: VIEWS ещё пуст. Раньше здесь стоял VIEWS[0] —
   с реальной витриной это давало undefined и падение на первом же painter'е. */
let VIEW = null;

function initView() {
  const saved = localStorage.getItem('px.view');
  VIEW = VIEWS.find(v => v.type + ':' + v.id === saved) || VIEWS[0] || null;
}

const isTheatre = () => !!VIEW && VIEW.type === 'theatre';
const cur = () => (isTheatre() ? THEATRES[VIEW.id] : CONFLICTS[VIEW.id]);

/* Цвета диад внутри театра: первая — чернила, вторая — латунь */
const dyadColor = k => cssVar(k === 0 ? '--ink' : '--brass');

/* ── утилиты ───────────────────────────── */

/* Недостающий ключ подменяется английским, а не своим же именем: на экране
   «worldTitle» вместо заголовка выглядит как поломка сайта, а английская
   строка — просто как непереведённый кусок. Языков шестнадцать, и держать
   их все в ногу с каждой правкой текста нереально. */
const t = k => (I18N[LANG] && I18N[LANG][k]) || (I18N.en && I18N.en[k]) || k;
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/* Локализованное поле: loc(o,'name') → name_ru | name_en, loc(o) → ru | en */
function loc(o, prefix) {
  const p = prefix ? prefix + '_' : '';
  return o[p + LANG] || o[p + 'en'] || o[p + 'ru'] || '';
}
const textOf = o => (o.key ? t(o.key) : loc(o));

function zoneOf(v) {
  for (let i = 0; i < ZONES.length; i++) if (v < ZONES[i].to || i === ZONES.length - 1) return { ...ZONES[i], i };
  return { ...ZONES[0], i: 0 };
}
/* Цвет — из температурной шкалы (--t0..--t4), одной на всю страницу: дуга,
   график, метры и строки списка обязаны говорить одним цветом, иначе на
   макете оказывается два прибора с разной разметкой. Подписи зон при этом
   остаются своими: слов шесть, цветов пять, и связывать их незачем.
   Старая палитра --z1..--z6 осталась для полюсов «мир / война» в тексте. */
const zoneColor = v => heatColor(v);

function el(tag, attrs = {}, parent) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}

function fmt(n, digits = 1) {
  return new Intl.NumberFormat(I18N[LANG]._locale, {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(n);
}
const fmtInt = n => new Intl.NumberFormat(I18N[LANG]._locale).format(n);

/* целая часть — крупно, десятая — мельче: так число читается как показание прибора */
function putValue(v, intSel, fracSel) {
  const s = fmt(v);
  const m = s.match(/^(-?\d+)([.,]\d+)$/);
  const i = $(intSel), f = $(fracSel);
  if (i) i.textContent = m ? m[1] : s;
  if (f) f.textContent = m ? m[2] : '';
}

const showValue = v => putValue(v, '#valueInt', '#valueFrac');

/* Досчёт числа. Мгновенный скачок в мелком тексте читается как ошибка
   загрузки, а не как показание, поэтому число всегда доезжает. */
function countUp(target, intSel, fracSel) {
  if (REDUCED) { putValue(target, intSel, fracSel); return; }
  const dur = 900, t0 = performance.now();
  const ease = p => 1 - Math.pow(1 - p, 3);
  (function step(now) {
    const p = Math.min(1, (now - t0) / dur);
    putValue(target * ease(p), intSel, fracSel);
    if (p < 1) requestAnimationFrame(step); else putValue(target, intSel, fracSel);
  })(t0);
}

function signed(n, digits = 1) {
  const s = n > 0 ? '+' : n < 0 ? '−' : '±';
  return s + fmt(Math.abs(n), digits);
}

/* ── дуга ───────────────────────────────
   Латунный циферблат со стрелкой и рисками заменён дугой, которая
   разгорается к угольку: это тот же объект, что и знак в шапке, и держать
   на одной странице два разных прибора незачем. Геометрия и градиенты —
   в assets/arc.js (ESCX.lightArc), здесь только подключение к данным. */
const { lightArc, sparkWash, heatWash, heatColor, setTint, toggleNoColor } = ESCX;

function drawGauge() {
  const host = $('#dial');
  if (!host) return;

  const c = cur();
  if (!c) { host.innerHTML = ''; return; }

  const v = isTheatre() ? theatreRollup(c).index : c.now;
  const ghost = isTheatre() ? theatreRollup(c).weekAgo : c.weekAgo;

  host.innerHTML = lightArc(v, {
    id: 'dial',
    labels: [t('z6').toUpperCase(), t('z1').toUpperCase()],
  });

  // Положение неделю назад — тонкая засечка на дуге. У прототипа для этого
  // была вторая стрелка; у дуги стрелок нет, а сравнение «где было» терять
  // нельзя: без него одно число ничего не говорит о направлении.
  addGhostTick(host.querySelector('svg'), ghost, v);
}

/* Засечка «неделю назад». Геометрия повторяет lightArc: те же радиус,
   развёртка и центр, иначе метка сползёт с дуги при смене размеров. */
function addGhostTick(svg, ghost, now) {
  if (!svg || !Number.isFinite(ghost) || Math.abs(ghost - now) < 0.05) return;

  const r = 150, sw = 13, sweep = 228, pad = 40;
  const cx = r + sw + pad, cy = r + sw + 8;
  const a = (Math.max(0, Math.min(100, ghost)) / 100) * sweep - sweep / 2;
  const rad = (a - 90) * Math.PI / 180;
  const inner = r - sw / 2 - 3, outer = r + sw / 2 + 3;

  const line = document.createElementNS(SVGNS, 'line');
  line.setAttribute('x1', (cx + inner * Math.cos(rad)).toFixed(1));
  line.setAttribute('y1', (cy + inner * Math.sin(rad)).toFixed(1));
  line.setAttribute('x2', (cx + outer * Math.cos(rad)).toFixed(1));
  line.setAttribute('y2', (cy + outer * Math.sin(rad)).toFixed(1));
  line.setAttribute('stroke', cssVar('--ink-3'));
  line.setAttribute('stroke-width', '1.4');
  line.setAttribute('stroke-linecap', 'round');
  line.setAttribute('opacity', '.75');
  svg.appendChild(line);
}

/* Дуга рисуется сразу на конечном значении, а разгорается средствами CSS:
   перерисовывать строку SVG по кадрам ради «выезда стрелки» — это стоимость
   без смысла, дуга и так читается как процесс. Число досчитывается: оно
   мелкое, и мгновенный скачок в нём выглядит как ошибка загрузки. */
function drawNeedles() {
  const c = cur();
  if (!c) return;

  const headline = isTheatre() ? theatreRollup(c).index : c.now;

  if (REDUCED) { showValue(headline); return; }

  const dur = 900, t0 = performance.now();
  const ease = p => 1 - Math.pow(1 - p, 3);
  (function step(now) {
    const p = Math.min(1, (now - t0) / dur);
    showValue(headline * ease(p));
    if (p < 1) requestAnimationFrame(step); else showValue(headline);
  })(t0);
}

/* ── показания ─────────────────────────── */

function paintReadout() {
  const c = cur();
  const roll = isTheatre() ? theatreRollup(c) : null;
  const v = roll ? roll.index : c.now;
  const weekAgo = roll ? roll.weekAgo : c.weekAgo;
  const monthAgo = roll ? roll.monthAgo : c.monthAgo;

  $('#conflictName').textContent = loc(c, 'name');

  const zoneEl = $('#zoneNow');
  zoneEl.textContent = t(zoneOf(v).key);
  zoneEl.style.setProperty('--zoneColor', zoneColor(v));

  [['#dWeek', v - weekAgo, 'weekDelta'], ['#dMonth', v - monthAgo, 'monthDelta']].forEach(([sel, d, key]) => {
    const n = $(sel);
    n.dataset.dir = d > 0 ? 'up' : d < 0 ? 'down' : 'flat';
    n.innerHTML = `<i>${signed(d)}</i><small>${t(key)}</small>`;
  });

  // подстрочник: у диады — счётчик дней, у театра — какая диада задаёт число
  const sub = $('#conflictSub');
  const upd = new Intl.DateTimeFormat(I18N[LANG]._locale, {
    day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit',
  }).format(new Date(c.updatedAt));

  if (roll) {
    sub.innerHTML = `<span class="tag">${t('theatreTag')}</span>
      <span class="sep">·</span>${c.dyads.length} × ${t('dyadTag')}
      <span class="sep">·</span>${t('updated')} ${upd}`;
  } else {
    // Прототип считал здесь дни от начала боевых действий. Витрина такой даты
    // не хранит, а брать вместо неё дату расчёта — значит показывать «День 0»
    // у войны, идущей четвёртый год. Вместо счётчика — то, что посчитано:
    // фаза, темп и покрытие данных.
    const bit = (v, cls) => (v ? `<span class="sep">·</span><span${cls ? ` class="${cls}"` : ''}>${v}</span>` : '');
    sub.innerHTML = `<span class="tag">${t('dyadTag')}</span>`
      + bit(c.phaseName)
      + bit(c.tempoName)
      + bit(c.region)
      + (Number.isFinite(c.coverage) ? bit(`${t('coverage')} ${c.coverage}%`) : '')
      + `<span class="sep">·</span>${t('updated')} ${upd}`;
  }

  $('#readNote').textContent = roll ? `${t('theatreReadNote')} — ${loc(roll.hottest, 'short')}` : '';
  $('#readNote').hidden = !roll;

  paintRisk(c, roll);
  paintDialLegend(roll);

  $('#liveSources').textContent = fmtInt(roll ? roll.sourcesLive : c.sourcesLive);
  $('#liveEvents').textContent  = fmtInt(roll ? roll.eventsLast24h : c.eventsLast24h);
}

function paintRisk(c, roll) {
  const box = $('#riskBox');
  box.innerHTML = '';

  const bar = (val, label, color) => `
    <div class="risk__line">
      <p class="risk__val num"><span>${fmtInt(val)}</span><span class="risk__unit">%</span></p>
      <p class="risk__lab">${label}</p>
      <div class="risk__bar"><i style="width:${val}%;background:${color}"></i></div>
    </div>`;

  if (roll) {
    box.innerHTML = `
      <p class="eyebrow">${t('riskTitle')}</p>
      ${bar(roll.riskAny, t('riskAny'), cssVar('--z3'))}
      ${bar(roll.riskBoth, t('riskBoth'), cssVar('--z1'))}
      <div class="coupling">
        <p class="coupling__top"><span>${t('couplingTitle')}</span><b class="num">${fmt(c.coupling, 2)}</b></p>
        <div class="risk__bar"><i style="width:${c.coupling * 100}%;background:${cssVar('--verdigris')}"></i></div>
        <p class="risk__sub">${t('couplingSub')}</p>
      </div>`;
  } else {
    const r = c.escalationRisk;
    const rc = r < 33 ? cssVar('--z5') : r < 66 ? cssVar('--z3') : cssVar('--z1');
    box.innerHTML = `
      <p class="eyebrow">${t('riskTitle')}</p>
      ${bar(r, r < 33 ? t('riskLow') : r < 66 ? t('riskMid') : t('riskHigh'), rc)}
      <p class="risk__sub">${t('riskSub')}</p>`;
  }
}

function paintDialLegend(roll) {
  const leg = $('#dialLegend');
  if (!roll) { leg.hidden = true; leg.innerHTML = ''; return; }
  leg.hidden = false;
  leg.innerHTML = roll.dyads.map((d, k) => `
    <span class="dyadkey">
      <i style="background:${dyadColor(k)}"></i>
      ${loc(d, 'short')} <b class="num">${fmt(d.now)}</b>
    </span>`).join('');
}

/* ── лента факторов ────────────────────── */

const CONF_COLOR = { high: '--z5', medium: '--z3', low: '--ink-3' };
const CONF_KEY   = { high: 'confHigh', medium: 'confMedium', low: 'confLow' };

function currentFactors() {
  const c = cur();
  if (!isTheatre()) return c.factors.map(f => ({ ...f, from: null }));
  return c.dyads
    .flatMap((id, k) => CONFLICTS[id].factors.map(f => ({ ...f, from: CONFLICTS[id], fromIdx: k })))
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}

function paintLedger() {
  const list = $('#ledgerRows');
  list.innerHTML = '';
  currentFactors().forEach(f => {
    const li = document.createElement('li');
    li.className = 'row';
    li.style.setProperty('--impactColor', cssVar(f.impact >= 0 ? '--z5' : '--z2'));
    li.style.setProperty('--chipColor', cssVar('--ink-2'));
    li.innerHTML = `
      <span class="row__date">${new Intl.DateTimeFormat(I18N[LANG]._locale, { day: '2-digit', month: 'short' }).format(new Date(f.date))}</span>
      <div class="row__body">
        <p class="row__text">${textOf(f)}</p>
        <p class="row__meta">
          ${f.from ? `<span class="chip chip--dyad" style="--chipColor:${dyadColor(f.fromIdx)}">${loc(f.from, 'short')}</span>` : ''}
          <span class="chip">${t(f.axis)}</span>
          <span class="srcs">${f.sources} ${t('ledgerSources')}</span>
          <span class="conf" style="--confColor:${cssVar(CONF_COLOR[f.confidence])}">${t(CONF_KEY[f.confidence])}</span>
        </p>
      </div>
      <span class="row__impact">${signed(f.impact)}</span>`;
    list.appendChild(li);
  });
}

/* ── оси ───────────────────────────────── */

/* Оси приходят из витрины ГЛОБАЛЬНЫМИ — они считаются на весь мир, а не по
   диаде. Прототип рисовал по пять осей на каждый конфликт; таких чисел
   пайплайн не производит, и разложить одну пару по осям нечем. Поэтому здесь
   один общий блок с подписью, к чему он относится, а не пятёрка на диаду. */
function paintAxes() {
  const list = $('#axesList');
  list.innerHTML = '';

  (LIVE.globalAxes || []).forEach(a => {
    const li = document.createElement('li');
    li.className = 'meter';
    li.innerHTML = `
      <div class="meter__top">
        <span class="meter__name">${a.name}</span>
      </div>
      <div class="meter__row" style="--barColor:${zoneColor(a.value)}">
        <div class="meter__track"><i class="meter__fill" style="width:${a.value}%"></i></div>
        <span class="meter__val">${fmtInt(a.value)}</span>
      </div>
      ${a.note ? `<p class="meter__desc">${a.note}</p>` : ''}`;
    list.appendChild(li);
  });
}

/* ── откуда сигнал ─────────────────────── */

const SIG_KEY = { news: 'sigNews', flight: 'sigFlight', market: 'sigMarket', tender: 'sigTender' };
const SIG_COLOR = { news: '--ink-2', flight: '--verdigris', market: '--brass', tender: '--z2' };

function paintSignalMix() {
  const fs = currentFactors();
  const counts = SIGNAL_TYPES.map(s => [s, fs.filter(f => (f.signal || 'news') === s).length])
    .filter(([, n]) => n > 0);
  const total = counts.reduce((a, [, n]) => a + n, 0) || 1;

  $('#srcMixBar').innerHTML = counts.map(([s, n]) =>
    `<i style="width:${(n / total) * 100}%;background:${cssVar(SIG_COLOR[s])}" title="${t(SIG_KEY[s])}"></i>`).join('');

  $('#srcMixKeys').innerHTML = counts.map(([s, n]) =>
    `<li><i style="background:${cssVar(SIG_COLOR[s])}"></i>${t(SIG_KEY[s])} <b class="num">${n}</b></li>`).join('');
}

/* ── слова и дела ──────────────────────── */

function paintDivergence() {
  const c = cur();
  const roll = isTheatre() ? theatreRollup(c) : null;
  const d = roll ? roll.divergence : c.divergence;
  const owner = roll ? roll.divergenceOwner : null;
  const gap = d.words - d.deeds;

  const state = gap <= -DIVERGENCE_BAND ? 'deeds' : gap >= DIVERGENCE_BAND ? 'words' : 'aligned';
  const label = { deeds: 'divDeedsSofter', words: 'divWordsSofter', aligned: 'divAligned' }[state];
  const why   = { deeds: 'divDeedsSofterWhy', words: 'divWordsSofterWhy', aligned: 'divAlignedWhy' }[state];
  const color = { deeds: cssVar('--z5'), words: cssVar('--z1'), aligned: cssVar('--ink-3') }[state];

  $('#divVerdict').innerHTML = `
    <p class="verdict__gap num" style="color:${color}">${signed(gap, 0)}</p>
    <p class="verdict__label" style="color:${color}">${t(label)}</p>
    <p class="verdict__why">${t(why)}</p>
    ${owner ? `<p class="verdict__owner">${loc(owner, 'short')}</p>` : ''}`;

  const scale = (val, name, tone) => `
    <div class="dscale">
      <div class="dscale__top">
        <span class="dscale__name">${name}</span>
        <span class="dscale__val num">${fmtInt(val)}</span>
      </div>
      <div class="dscale__track"><i style="width:${val}%;background:${tone}"></i></div>
    </div>`;

  $('#divScales').innerHTML =
    scale(d.words, t('divWords'), cssVar('--rust')) +
    scale(d.deeds, t('divDeeds'), cssVar('--verdigris'));

  // единицу времени форматирует Intl — отдельный ключ перевода не нужен
  const days = new Intl.NumberFormat(I18N[LANG]._locale, {
    style: 'unit', unit: 'day', unitDisplay: 'long',
  }).format(d.lagDays);
  $('#divLag').textContent = `${t('divLag')} — ${days}`;
  drawDivSpark(d.history);
}

function drawDivSpark(hist) {
  const svg = $('#divSpark');
  [...svg.querySelectorAll(':not(title)')].forEach(n => n.remove());

  const W = 520, H = 130, P = { l: 30, r: 8, t: 12, b: 18 };
  const pw = W - P.l - P.r, ph = H - P.t - P.b;
  const lim = Math.max(DIVERGENCE_BAND + 4, ...hist.map(Math.abs));
  const X = i => P.l + pw * i / (hist.length - 1);
  const Y = v => P.t + ph / 2 - (ph / 2) * (v / lim);

  // полоса, внутри которой расхождение считается шумом
  el('rect', {
    x: P.l, y: Y(DIVERGENCE_BAND), width: pw, height: Y(-DIVERGENCE_BAND) - Y(DIVERGENCE_BAND),
    fill: cssVar('--ink-3'), opacity: .07,
  }, svg);
  el('line', { x1: P.l, y1: Y(0), x2: P.l + pw, y2: Y(0), stroke: cssVar('--hair'), 'stroke-width': 1 }, svg);

  [['+', DIVERGENCE_BAND], ['−', -DIVERGENCE_BAND]].forEach(([sign, v]) => {
    const n = el('text', {
      x: P.l - 7, y: Y(v) + 3.5, 'text-anchor': 'end', fill: cssVar('--ink-3'),
      'font-family': 'Consolas, ui-monospace, monospace', 'font-size': 10,
    }, svg);
    n.textContent = sign + DIVERGENCE_BAND;
  });

  hist.forEach((v, i) => {
    const x = X(i), w = Math.max(3, pw / hist.length - 3);
    const top = v >= 0 ? Y(v) : Y(0);
    el('rect', {
      x: x - w / 2, y: top, width: w, height: Math.abs(Y(v) - Y(0)) || 1, rx: 1,
      fill: Math.abs(v) < DIVERGENCE_BAND ? cssVar('--ink-3') : v > 0 ? cssVar('--z1') : cssVar('--z5'),
      opacity: i === hist.length - 1 ? 1 : .55,
    }, svg);
  });
}

/* ── матрица связанности ───────────────── */

function paintMatrix() {
  const ids = COUPLING.order;
  const head = `<tr><td></td>${ids.map(id =>
    `<th scope="col">${loc(CONFLICTS[id], 'short')}</th>`).join('')}</tr>`;

  const rows = ids.map(a => `
    <tr>
      <th scope="row">${loc(CONFLICTS[a], 'short')}</th>
      ${ids.map(b => {
        const v = COUPLING.m[a][b];
        if (a === b) return `<td class="mat__self">—</td>`;
        return `<td class="mat__cell num"
          style="--heat:${v}; background:color-mix(in oklab, var(--verdigris) ${Math.round(v * 78)}%, transparent);
                 color:${v > .5 ? 'var(--paper-raised)' : 'var(--ink)'}">${fmt(v, 2)}</td>`;
      }).join('')}
    </tr>`).join('');

  $('#matTable').innerHTML = head + rows;
}

/* ── круги на воде ─────────────────────── */

const UNIT_KEY = { oil: 'uOil', gas: 'uGas', lng: 'uLng', wheat: 'uWheat', trade: 'uTrade' };

function paintChokepoints() {
  const c = cur();
  const list = isTheatre() ? theatreRollup(c).chokepoints : (c.chokepoints || []);
  $('#chokeList').innerHTML = list.map(p => `
    <li class="choke__item">
      <div class="choke__head">
        <h4 class="choke__name">${loc(p, 'name')}</h4>
        <span class="chip">${loc(p, 'unitLabel') || t(UNIT_KEY[p.unit] || p.unit)}</span>
      </div>
      <div class="choke__nums">
        <div>
          <p class="choke__val num">${fmtInt(p.share)}<span class="choke__pc">%</span></p>
          <p class="choke__lab">${t('chokeShare')}</p>
        </div>
        <div>
          <p class="choke__val num" style="color:var(--brass)">${fmtInt(p.sensitivity)}</p>
          <p class="choke__lab">${t('chokeSens')}</p>
        </div>
      </div>
      <div class="choke__bar"><i style="width:${p.share}%"></i></div>
    </li>`).join('');
}

/* ── график истории ────────────────────── */

const CW = 1120, CH = 340;
const PAD = { l: 46, r: 18, t: 18, b: 36 };
const PW = CW - PAD.l - PAD.r, PH = CH - PAD.t - PAD.b;

function pointDate(conf, i) {
  const [y, m, d] = conf.seriesFrom.split('-').map(Number);
  // Витрина отдаёт ежедневный ряд за 90 дней; у прототипа шаг был месячный.
  // Считать дни месяцами — это подписать ось датами, которых в данных нет.
  if (conf.seriesStep === 'day') return new Date(y, m - 1, (d || 1) + i);
  const add = conf.seriesStep === 'quarter' ? i * 3 : i;
  return new Date(y, m - 1 + add, 1);
}

function chartSeries() {
  const c = cur();
  return isTheatre() ? c.dyads.map(id => CONFLICTS[id]) : [c];
}

function drawChart() {
  const grid = $('#cGrid'), band = $('#cBand'), area = $('#cArea'),
        line = $('#cLine'), marks = $('#cMarks'), axis = $('#cAxis');
  [grid, band, area, line, marks, axis].forEach(g => (g.innerHTML = ''));

  const list = chartSeries();
  const ref = list[0];
  const n = Math.max(...list.map(c => c.series.length));
  const peak = Math.max(...list.flatMap(c => c.series));
  const yMax = Math.max(45, Math.ceil((peak + 5) / 10) * 10);

  const X = i => PAD.l + (PW * i) / (n - 1);
  const Y = v => PAD.t + PH - (PH * v) / yMax;

  for (let v = 0; v <= yMax; v += 10) {
    el('line', { x1: PAD.l, y1: Y(v), x2: PAD.l + PW, y2: Y(v), stroke: cssVar('--hair-soft'), 'stroke-width': 1 }, grid);
    const lbl = el('text', {
      x: PAD.l - 10, y: Y(v) + 4, 'text-anchor': 'end', fill: cssVar('--ink-3'),
      'font-family': 'Consolas, ui-monospace, monospace', 'font-size': 11,
    }, grid);
    lbl.textContent = v;
  }

  // границы зон — привязка графика к циферблату
  [15, 35].forEach(v => {
    el('line', { x1: PAD.l, y1: Y(v), x2: PAD.l + PW, y2: Y(v), stroke: zoneColor(v - 1), 'stroke-width': 1, 'stroke-dasharray': '2 5', opacity: .8 }, grid);
    const lbl = el('text', {
      x: PAD.l + PW, y: Y(v) - 6, 'text-anchor': 'end', fill: zoneColor(v - 1),
      'font-family': 'Segoe UI, sans-serif', 'font-size': 9.5, 'font-weight': 600,
      'letter-spacing': 1.2, opacity: .9,
    }, grid);
    lbl.textContent = t(zoneOf(v - 1).key).toUpperCase();
  });

  // область без верифицированных данных
  const defs = el('defs', {}, band);
  const pat = el('pattern', { id: 'hatch', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
  el('line', { x1: 0, y1: 0, x2: 0, y2: 6, stroke: cssVar('--ink-3'), 'stroke-width': 1 }, pat);

  // Штриховка отмечала синтетический хвост ряда в прототипе. У витрины
  // синтетической части нет вовсе, поэтому без syntheticFrom полосы просто нет
  // (раньше X(undefined) давал NaN и SVG ругался на каждой перерисовке).
  if (Number.isFinite(ref.syntheticFrom)) {
    const bx = X(ref.syntheticFrom);
    el('rect', { x: bx, y: PAD.t, width: PAD.l + PW - bx, height: PH, fill: 'url(#hatch)', opacity: .32 }, band);
    el('line', { x1: bx, y1: PAD.t, x2: bx, y2: PAD.t + PH, stroke: cssVar('--ink-3'), 'stroke-width': 1, 'stroke-dasharray': '4 3' }, band);
    const bl = el('text', {
      x: PAD.l + PW - 6, y: PAD.t + 13, 'text-anchor': 'end', fill: cssVar('--ink-3'),
      'font-family': 'Segoe UI, sans-serif', 'font-size': 10.5,
    }, band);
    bl.textContent = t('syntheticBand');
  }

  // Акварель вместо чертежа: работает мягкая заливка, линия почти невидима.
  // Заливка окрашена по текущему накалу, а не латунью: график и дуга должны
  // говорить одним цветом, иначе на странице два разных прибора.
  const tail = list[0].series[list[0].series.length - 1];
  const washCol = heatColor(tail);

  const grad = el('linearGradient', { id: 'areaFill', x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
  el('stop', { offset: '0%',   'stop-color': washCol, 'stop-opacity': .34 }, grad);
  el('stop', { offset: '100%', 'stop-color': washCol, 'stop-opacity': 0 }, grad);

  list.forEach((c, k) => {
    const pts = c.series.map((v, i) => `${X(i).toFixed(2)},${Y(v).toFixed(2)}`);
    if (list.length === 1) {
      el('path', {
        d: `M ${PAD.l},${PAD.t + PH} L ${pts.join(' L ')} L ${X(c.series.length - 1)},${PAD.t + PH} Z`,
        fill: 'url(#areaFill)',
      }, area);
    }
    el('path', {
      d: `M ${pts.join(' L ')}`, fill: 'none',
      stroke: list.length === 1 ? washCol : dyadColor(k),
      'stroke-width': 1.4, 'stroke-opacity': list.length === 1 ? .6 : 1,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round',
      'stroke-dasharray': k === 1 ? '5 3' : 'none',
    }, line);
  });

  // Уголёк на конце ряда — та же метка, что на дуге и в знаке.
  if (list.length === 1) {
    const c0 = list[0], last = c0.series.length - 1;
    el('circle', {
      cx: X(last), cy: Y(c0.series[last]), r: 4, fill: washCol,
    }, line);
  }

  // события-якоря
  let badge = 0;
  list.forEach((c, k) => {
    c.milestones.forEach(m => {
      const x = X(m.i), y = Y(c.series[m.i]);
      badge++;
      el('line', { x1: x, y1: y, x2: x, y2: PAD.t + 26, stroke: cssVar('--brass-soft'), 'stroke-width': 1 }, marks);
      el('circle', { cx: x, cy: y, r: 3.6, fill: cssVar('--paper-raised'), stroke: dyadColor(list.length === 1 ? 0 : k), 'stroke-width': 1.8 }, marks);
      el('circle', { cx: x, cy: PAD.t + 20, r: 8.5, fill: cssVar('--brass'), opacity: .95 }, marks);
      const lbl = el('text', {
        x, y: PAD.t + 23.5, 'text-anchor': 'middle', fill: cssVar('--paper-raised'),
        'font-family': 'Consolas, ui-monospace, monospace', 'font-size': 10, 'font-weight': 700,
      }, marks);
      lbl.textContent = badge;
    });
  });

  // ось X: годовые отметки, прореженные под ширину
  const years = [];
  for (let i = 0; i < n; i++) {
    const d = pointDate(ref, i);
    if (i === 0 || d.getMonth() === 0) years.push([i, d.getFullYear()]);
  }
  const stepY = Math.ceil(years.length / 8);
  years.filter((_, i) => i % stepY === 0).forEach(([i, year]) => {
    const x = X(i);
    el('line', { x1: x, y1: PAD.t + PH, x2: x, y2: PAD.t + PH + 6, stroke: cssVar('--hair'), 'stroke-width': 1 }, axis);
    const lbl = el('text', {
      x, y: PAD.t + PH + 22, 'text-anchor': 'middle', fill: cssVar('--ink-3'),
      'font-family': 'Consolas, ui-monospace, monospace', 'font-size': 11,
    }, axis);
    lbl.textContent = year;
  });

  // легенда под графиком
  const leg = $('#milestoneList');
  leg.innerHTML = '';
  let num = 0;
  list.forEach(c => {
    c.milestones.forEach(m => {
      num++;
      const when = new Intl.DateTimeFormat(I18N[LANG]._locale, { month: 'short', year: 'numeric' }).format(pointDate(c, m.i));
      const li = document.createElement('li');
      li.innerHTML = `<b>${num} · ${when}</b><span>${textOf(m)}</span>`;
      leg.appendChild(li);
    });
  });
}

/* ── стенд калибровки ──────────────────── */

const SPARK_W = 260, SPARK_H = 62, SPARK_PAD = 4;

function drawSpark(c) {
  const s = c.series, n = s.length;
  const x = i => SPARK_PAD + (SPARK_W - SPARK_PAD * 2) * i / (n - 1);
  const y = v => SPARK_PAD + (SPARK_H - SPARK_PAD * 2) * (1 - v / 100);

  const svg = el('svg', {
    viewBox: `0 0 ${SPARK_W} ${SPARK_H}`, class: 'spark', dir: 'ltr',
    role: 'img', 'aria-label': loc(c, 'name'),
  });

  el('line', { x1: 0, y1: y(CAL_THRESHOLD), x2: SPARK_W, y2: y(CAL_THRESHOLD), stroke: cssVar('--hair'), 'stroke-width': 1, 'stroke-dasharray': '2 3' }, svg);

  const pts = s.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' L ');
  el('path', { d: `M ${SPARK_PAD},${SPARK_H - SPARK_PAD} L ${pts} L ${x(n - 1)},${SPARK_H - SPARK_PAD} Z`, fill: cssVar('--brass'), opacity: .12 }, svg);
  el('path', { d: `M ${pts}`, fill: 'none', stroke: cssVar('--ink'), 'stroke-width': 1.4, 'stroke-linejoin': 'round' }, svg);

  (c.marks || []).forEach(m => {
    el('line', { x1: x(m.i), y1: 0, x2: x(m.i), y2: SPARK_H, stroke: cssVar('--rust'), 'stroke-width': 1, 'stroke-dasharray': '2 2', opacity: .85 }, svg);
    el('circle', { cx: x(m.i), cy: y(s[m.i]), r: 2.6, fill: cssVar('--rust') }, svg);
  });

  const lead = leadMonths(c);
  if (lead !== null) {
    const ci = n - 1 - lead;
    el('circle', { cx: x(ci), cy: y(s[ci]), r: 3.2, fill: cssVar('--paper-raised'), stroke: cssVar('--z5'), 'stroke-width': 1.8 }, svg);
  }

  el('line', { x1: x(n - 1), y1: 0, x2: x(n - 1), y2: SPARK_H, stroke: cssVar('--verdigris'), 'stroke-width': 1.4 }, svg);
  el('circle', { cx: x(n - 1), cy: y(s[n - 1]), r: 3, fill: cssVar('--verdigris') }, svg);
  return svg;
}

const OUT_KEY = { negotiated: 'calOutNegotiated', ceasefire: 'calOutCeasefire', military: 'calOutMilitary' };

function paintCalibration() {
  const board = $('#calBoard');
  board.innerHTML = '';

  CALIBRATION.forEach(c => {
    const lead = leadMonths(c);
    const card = document.createElement('article');
    card.className = 'calcard';
    card.innerHTML = `
      <div class="calcard__head">
        <h4 class="calcard__name">${loc(c, 'name')}</h4>
        <span class="calcard__years num">${c.years}</span>
      </div>`;
    card.appendChild(drawSpark(c));

    const foot = document.createElement('div');
    foot.className = 'calcard__foot';
    foot.innerHTML = `
      <p class="calcard__accord">${loc(c, 'accord')}</p>
      <p class="calcard__row">
        <span class="chip chip--${c.outcome}">${t(OUT_KEY[c.outcome])}</span>
        <span class="calcard__lead${lead === null ? ' is-none' : ''}">${
          lead === null ? t('calLeadNone') : `${t('calLead')} <b class="num">${lead}</b> ${t('calMonths')}`}</span>
      </p>
      ${loc(c, 'note') ? `<p class="calcard__note">${loc(c, 'note')}</p>` : ''}`;
    card.appendChild(foot);
    board.appendChild(card);
  });

  const leads = CALIBRATION.map(leadMonths);
  const withSignal = leads.filter(v => v !== null).sort((a, b) => a - b);
  const median = withSignal.length
    ? (withSignal.length % 2
        ? withSignal[(withSignal.length - 1) / 2]
        : (withSignal[withSignal.length / 2 - 1] + withSignal[withSignal.length / 2]) / 2)
    : 0;

  $('#calStats').innerHTML = [
    [fmtInt(CALIBRATION.length), t('calStatSet')],
    [fmtInt(CALIBRATION.filter(c => c.outcome === 'negotiated').length), t('calStatAccord')],
    [fmtInt(CALIBRATION.reduce((n, c) => n + (c.marks || []).length, 0)), t('calStatFailed')],
    [`${fmt(median, median % 1 ? 1 : 0)} ${t('calMonths')}`, t('calStatMedian')],
    [fmtInt(leads.filter(v => v === null).length), t('calStatNoSignal')],
  ].map(([v, l]) => `<div><dt class="num">${v}</dt><dd>${l}</dd></div>`).join('');
}

/* ── шаги метода ───────────────────────── */

function paintSteps() {
  const box = $('#steps');
  box.innerHTML = '';
  for (let i = 1; i <= 6; i++) {
    const li = document.createElement('li');
    li.className = 'step';
    li.innerHTML = `<h4>${t('s' + i + 't')}</h4><p>${t('s' + i + 'd')}</p>`;
    box.appendChild(li);
  }
}

/* ── мир целиком ────────────────────────
   Глобальный индекс — взвешенное по последствиям среднее накала, у него нет
   ни фазы, ни диады. Поэтому у него своя дуга и свой блок: подмешивать его
   к показанию одной пары значило бы складывать разные величины. */

function paintWorld() {
  const host = $('#worldDial');
  if (!host) return;

  const v = Number.isFinite(LIVE.gei) ? LIVE.gei : null;
  const sec = $('#world');
  if (v === null) { if (sec) sec.hidden = true; return; }
  if (sec) sec.hidden = false;

  host.innerHTML = lightArc(v, {
    id: 'world',
    labels: [t('z6').toUpperCase(), t('z1').toUpperCase()],
  });

  const zone = $('#worldZone');
  zone.textContent = t(zoneOf(v).key);
  zone.style.setProperty('--zoneColor', zoneColor(v));

  const d = LIVE.geiDelta30;
  const el30 = $('#worldDelta');
  if (Number.isFinite(d)) {
    el30.dataset.dir = d > 0 ? 'up' : d < 0 ? 'down' : 'flat';
    el30.innerHTML = `<i>${signed(d)}</i><small>${t('monthDelta')}</small>`;
  } else {
    el30.innerHTML = '';
  }

  countUp(v, '#worldInt', '#worldFrac');

  $('#worldAxes').innerHTML = (LIVE.globalAxes || []).map(a => `
    <li class="meter">
      <div class="meter__top"><span class="meter__name">${a.name}</span></div>
      <div class="meter__row" style="--barColor:${zoneColor(a.value)}">
        <div class="meter__track"><i class="meter__fill" style="width:${a.value}%"></i></div>
        <span class="meter__val">${fmtInt(a.value)}</span>
      </div>
      ${a.note ? `<p class="meter__desc">${a.note}</p>` : ''}
    </li>`).join('');
}

/* ── топ конфликтов ─────────────────────
   Сортировка по накалу, а не по фазе: фаза меняется раз в год, и список,
   отсортированный по ней, был бы неподвижен. Фаза при этом подписана
   в каждой строке — без неё накал 50 у войны и у спора о границе выглядят
   одинаково. */

const TOP_SHOWN = 8;
let topExpanded = false;

function conflictsByHeat() {
  return Object.values(CONFLICTS)
    .filter(c => Number.isFinite(c.now))
    .sort((a, b) => b.now - a.now);
}

function paintTop() {
  const list = conflictsByHeat();
  const box = $('#topList');
  if (!box) return;

  const shown = topExpanded ? list : list.slice(0, TOP_SHOWN);

  box.innerHTML = shown.map(c => {
    const stale = Number.isFinite(c.coverage) && c.coverage < 40;
    const week = Number.isFinite(c.weekAgo) ? c.now - c.weekAgo : 0;
    return `
      <li class="toprow${stale ? ' is-thin' : ''}" style="--wash:${heatWash(c.now)}"
          data-id="${c.id}" tabindex="0" role="button">
        <div class="toprow__name">
          <span class="toprow__title">${loc(c, 'short')}</span>
          <span class="toprow__meta">${c.phaseName || ''}${c.region ? ' · ' + c.region : ''}</span>
        </div>
        <div class="toprow__spark">${sparkWash(c.series || [], { id: 'tl-' + c.id, color: zoneColor(c.now), h: 26 })}</div>
        <div class="toprow__num num" style="color:${zoneColor(c.now)}">${fmt(c.now, 0)}</div>
        <div class="toprow__d" data-dir="${week > 0 ? 'up' : week < 0 ? 'down' : 'flat'}">
          <i>${signed(week)}</i><small>${c.tempoName || ''}</small>
        </div>
      </li>`;
  }).join('');

  $$('.toprow', box).forEach(row => {
    const go = () => {
      VIEW = { type: 'conflict', id: row.dataset.id };
      localStorage.setItem('px.view', 'conflict:' + row.dataset.id);
      renderAll();
      $('#main').querySelector('.hero').scrollIntoView({ behavior: REDUCED ? 'auto' : 'smooth', block: 'start' });
    };
    row.addEventListener('click', go);
    row.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });

  const more = $('#topMore');
  if (list.length > TOP_SHOWN) {
    more.hidden = false;
    more.textContent = topExpanded
      ? t('topLess')
      : `${t('topMore')} — ${list.length - TOP_SHOWN}`;
  } else {
    more.hidden = true;
  }
}

/* Кто сдвинулся сильнее всего за месяц. Отдельно от списка: список отвечает
   «где горячо», а этот блок — «где меняется», и это разные вопросы. */
function paintMovers() {
  const box = $('#movers');
  if (!box) return;

  const withDelta = Object.values(CONFLICTS)
    .filter(c => Number.isFinite(c.now) && Number.isFinite(c.monthAgo))
    .map(c => ({ c, d: c.now - c.monthAgo }))
    .filter(x => Math.abs(x.d) >= 1);

  if (!withDelta.length) { box.hidden = true; return; }
  box.hidden = false;

  const up = withDelta.slice().sort((a, b) => b.d - a.d)[0];
  const down = withDelta.slice().sort((a, b) => a.d - b.d)[0];

  const card = (x, key) => !x || x.d === 0 ? '' : `
    <div class="mover" data-dir="${x.d > 0 ? 'up' : 'down'}">
      <p class="mover__label">${t(key)}</p>
      <p class="mover__name">${loc(x.c, 'short')}</p>
      <p class="mover__d num">${signed(x.d)}</p>
    </div>`;

  // Один и тот же конфликт не может быть одновременно самым горячим и самым
  // остывшим: если направление всего одно, показываем одну карточку.
  box.innerHTML = card(up && up.d > 0 ? up : null, 'moverUp')
                + card(down && down.d < 0 ? down : null, 'moverDown');
}

/* ── переключатель конфликтов ──────────── */

function buildViewPicker() {
  const box = $('#views');
  box.innerHTML = VIEWS.map(v => {
    const o = v.type === 'theatre' ? THEATRES[v.id] : CONFLICTS[v.id];
    const on = v.type === VIEW.type && v.id === VIEW.id;
    // Кнопка не раскрашивается, а теплеет по накалу: заливка фона вместо
    // цветной метки. Цветная метка утверждала бы «плохо / хорошо», которого
    // в накале нет, — а тепло читается как величина, и это честнее.
    const heat = o && Number.isFinite(o.now) ? o.now : null;
    const stale = o && Number.isFinite(o.coverage) && o.coverage < 40;
    // Заливку НЕ гасим по покрытию: сейчас под порогом все диады, и лента
    // выцвела бы целиком — приглушение перестало бы что-либо различать.
    // Низкое покрытие показываем пунктирной рамкой, она работает и без цвета.
    const wash = heat === null ? '' : `style="--wash:${heatWash(heat)}"`;
    return `<button type="button" class="viewbtn${on ? ' is-on' : ''}${v.nested ? ' is-nested' : ''}${stale ? ' is-thin' : ''}"
      data-type="${v.type}" data-id="${v.id}" ${wash}
      ${stale ? `title="покрытие данных ${o.coverage}%"` : ''}>${loc(o, 'short')}</button>`;
  }).join('');

  $$('.viewbtn', box).forEach(b => b.addEventListener('click', () => {
    VIEW = { type: b.dataset.type, id: b.dataset.id };
    localStorage.setItem('px.view', VIEW.type + ':' + VIEW.id);
    renderAll();
  }));
}

/* ── язык и тема ───────────────────────── */

function applyLang() {
  const d = document.documentElement;
  d.lang = LANG.split('-')[0];
  d.dir = I18N[LANG]._dir;
  d.dataset.script = ['zh', 'ja', 'ko'].includes(LANG) ? 'cjk'
    : ['ar', 'fa'].includes(LANG) ? 'arabic' : 'latin';
  $$('[data-i18n]').forEach(n => { n.textContent = t(n.dataset.i18n); });
  document.title = 'brink.watch — ' + t('brandTag');
}

function buildLangPicker() {
  const sel = $('#lang');
  sel.innerHTML = LANG_ORDER.filter(c => I18N[c])
    .map(c => `<option value="${c}"${c === LANG ? ' selected' : ''}>${I18N[c]._name}</option>`).join('');
  sel.addEventListener('change', () => {
    LANG = sel.value;
    localStorage.setItem('px.lang', LANG);
    renderAll();
  });
}

/* Раздел, которому нечем питаться, скрывается целиком, а не рисуется пустым.
   Пустая рамка с заголовком выглядит как поломка; отсутствующий раздел —
   как честно отсутствующий раздел. */
function section(sel, has, paint) {
  const node = $(sel);
  if (node) node.hidden = !has;
  if (has && paint) paint();
}

function renderAll() {
  if (!VIEW) initView();
  applyLang();
  buildViewPicker();

  paintWorld();
  paintTop();
  paintMovers();

  drawGauge();
  paintReadout();
  paintSteps();
  drawChart();
  drawNeedles();

  section('.ledger',      HAS.ledger,      paintLedger);
  section('.srcmix',      HAS.ledger,      paintSignalMix);
  // Оси переехали к мировой шкале: они считаются на весь мир, и в разделе
  // про одну пару читались как её разложение, которым не являются.
  section('.axes',        false,           paintAxes);
  section('#divergence',  HAS.divergence,  paintDivergence);
  section('#matrix',      HAS.matrix,      paintMatrix);
  section('#ripples',     HAS.chokepoints, paintChokepoints);
  section('#calibration', HAS.calibration, paintCalibration);
  section('.sidecard',    HAS.live);

  // Леджер и оси делят одну сетку: если ушёл один, второй занимает всю ширину.
  const split = $('.split');
  if (split) {
    split.hidden = !(HAS.ledger || HAS.axes);
    split.classList.toggle('split--single', HAS.ledger !== HAS.axes);
  }

  // Пункт меню, ведущий на скрытый раздел, — это ссылка в никуда.
  $$('.topnav a[href^="#"]').forEach(a => {
    const target = $(a.getAttribute('href'));
    a.hidden = !target || target.hidden;
  });
}

$('#topMore').addEventListener('click', () => {
  topExpanded = !topExpanded;
  paintTop();
});

/* Подтон бумаги. Хранится отдельно от темы: это разные оси — тема меняет
   свет, подтон меняет сорт бумаги, и сбрасывать одно при смене другого
   было бы сюрпризом. */
$$('.tint[data-tint]').forEach(b => b.addEventListener('click', () => {
  $$('.tint[data-tint]').forEach(x => x.classList.remove('is-on'));
  b.classList.add('is-on');
  setTint(b.dataset.tint);
  localStorage.setItem('px.tint', b.dataset.tint);
  renderAll();   // цвета в SVG заданы атрибутами — перерисовываем целиком
}));

$('#nocolor').addEventListener('click', function () {
  const off = toggleNoColor();
  this.classList.toggle('is-on', off);
  localStorage.setItem('px.nocolor', off ? '1' : '');
});

(function initTint() {
  const saved = localStorage.getItem('px.tint') || 'sand';
  setTint(saved);
  $$('.tint[data-tint]').forEach(x => x.classList.toggle('is-on', x.dataset.tint === saved));
  if (localStorage.getItem('px.nocolor')) {
    document.body.classList.add('escx-nocolor');
    $('#nocolor').classList.add('is-on');
  }
})();

$('#theme').addEventListener('click', () => {
  const mode = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
  const next = mode === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('px.theme', next);
  renderAll();   // цвета в SVG заданы атрибутами — перерисовываем целиком
});

/* стартовая тема: сохранённая → системная */
(function initTheme() {
  const saved = localStorage.getItem('px.theme');
  const sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.dataset.theme = saved || (sysDark ? 'dark' : 'light');
})();

/* Первый renderAll вызывает live.js — после того, как витрина загружена.
   Рисовать до неё нечего: реестр пуст, и стрелка встала бы на ноль. */
buildLangPicker();
