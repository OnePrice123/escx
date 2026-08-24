/* ═══════════════════════════════════════════════════════════
   Страница одной пары: раскрытие числа до исходного события.

   Зачем отдельная страница, если вид конфликта есть на главной. На главной
   показан ИТОГ: накал, ступень, график. Здесь — ОСНОВАНИЯ: какие индикаторы
   сложились в это число, какие блоки не измерены вовсе, когда и по какому
   правилу менялась ступень и какие сырые события за этим стоят.

   Разделение не косметическое. Сорок событий и разбор по девяти индикаторам
   на каждую из двадцати пар — это в разы больше данных, чем сама витрина, и
   тянуть их на главную ради читателя, который до них не дойдёт, незачем.
   Поэтому страница грузит ровно один файл — свой.

   Главное, что она обязана показывать честно, — ЧЕГО МЫ НЕ ЗНАЕМ. Блок без
   данных выводится как неизмеренный, а не как ноль, и вес его при этом не
   перераспределяется по остальным.

   Язык. Раньше страница была русской целиком: имена блоков, коды CAMEO,
   ступени и подписи приходили из пайплайна готовой русской фразой, а общий
   механизм словаря жил в app.js, который сюда не подключить — он завязан на
   главную. Теперь язык вынесен в assets/lang.js, а витрина отдаёт КЛЮЧИ
   (block, ключ индикатора, rule, cameo:NN, номер ступени) — словами их
   называет эта страница.
   ═══════════════════════════════════════════════════════════ */

const { heatColor, heatWash } = window.ESCX || {};

const show = id => ['loading', 'failed', 'body'].forEach(x => {
  const n = document.getElementById(x);
  if (n) n.hidden = x !== id;
});

const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Загруженные данные пары. Держим их, чтобы перерисовать страницу при смене
// языка, а не идти в сеть за тем же самым файлом второй раз.
let DATA = null;
// Причина неудачи хранится КЛЮЧОМ, а не готовой фразой: иначе смена языка
// на экране ошибки либо оставит старый язык, либо подменит «нет связи» на
// «нет такой пары» — общей разметкой data-i18n их не различить.
let FAIL = null;

/* Название источника словами. Строка «gdelt_export» читателю ничего не
   говорит, а «GDELT» — говорит. */
const sourceName = k => t2('sources', k, k);

/* Корень кода CAMEO словами. Полная таблица на двести кодов на странице не
   нужна: она заменила бы объяснение перечислением, — поэтому в словаре только
   двадцать корней, а номер показывается рядом в любом случае. */
function cameoName(type, code) {
  const root = String(type || '').replace('cameo:', '').slice(0, 2);
  const word = t2('cameo', root);
  const num = code || root;
  return word ? `${word} (${num})` : (num || '—');
}

/* Имя пары собирается из кодов сторон, как и в ленте на главной. Строка из
   витрины остаётся запасом — если кода нет в таблице. */
function nameOf(d) {
  const a = countryName(d.side_a), b = countryName(d.side_b);
  return (a && b) ? `${a} — ${b}` : (d.name || d.dyad_id);
}

/* Ступень по НОМЕРУ, а не по русской строке из витрины. */
function phaseWord(n, fallback) {
  const list = (I18N[LANG] && I18N[LANG].phases) || (I18N.en && I18N.en.phases);
  return (Array.isArray(list) && list[n]) || fallback || (n != null ? n : '—');
}

/* Подстановка в шаблон словаря: fill('dyadDispute', {x: 'Кашмир'}).
   Числа и имена в готовую фразу не склеиваются конкатенацией — порядок слов
   в шестнадцати языках разный, и место подстановки решает сам перевод. */
const fill = (k, vars) => {
  let s = t(k);
  for (const [name, v] of Object.entries(vars || {})) s = s.replace('{' + name + '}', v);
  return s;
};

/* ------------------------------------------------------------------ шапка */

/**
 * Шапка завершённого конфликта.
 *
 * Накала и ступени у него нет — и это не пропуск витрины: расчёт по спящим
 * парам не ведётся вовсе. Показать здесь прочерк на месте числа значило бы
 * намекнуть, что число должно быть и потерялось. Поэтому вместо накала —
 * период и объём собранного, а вместо ступени — статус.
 */
function paintArchived(d) {
  const name = nameOf(d);
  document.title = `${name} — brink.watch`;
  $('#dRegion').textContent =
    [t2('regions', d.region_key, d.region), t('dyadArchivedTag')].filter(Boolean).join(' · ');
  $('#dName').textContent = name;
  const dispute = t2('disputed', d.disputed_key, d.disputed);
  $('#dDisputed').textContent = dispute ? fill('dyadDispute', { x: dispute }) : '';

  const years = d.events_from && d.events_to
    ? `${String(d.events_from).slice(0, 4)}—${String(d.events_to).slice(0, 4)}` : '—';
  const src = Object.entries(d.sources || {})
    .map(([k, n]) => `${sourceName(k)} ${n}`).join(', ');

  $('.dhead__nums').innerHTML = `
    <div class="dnum"><span class="dnum__v">${esc(t2('statuses', d.status, d.status) || '—')}</span><span class="dnum__k">${esc(t('kStatus'))}</span></div>
    <div class="dnum"><span class="dnum__v num">${esc(years)}</span><span class="dnum__k">${esc(t('kEventsSpan'))}</span></div>
    <div class="dnum"><span class="dnum__v num">${d.events_total != null ? d.events_total : '—'}</span><span class="dnum__k">${esc(t('kRecords'))}</span></div>
    ${d.since ? `<div class="dnum"><span class="dnum__v num">${d.since}</span><span class="dnum__k">${esc(t('kSince'))}</span></div>` : ''}`;

  $('#dBasis').textContent = t('dyadArchivedBasis')
    + (src ? ' ' + fill('dyadCollected', { x: src }) : '');
}

function paintHead(d) {
  if (d.status && d.status !== 'active') return paintArchived(d);

  const name = nameOf(d);
  document.title = `${name} — brink.watch`;
  $('#dRegion').textContent = t2('regions', d.region_key, d.region);
  $('#dName').textContent = name;
  const dispute = t2('disputed', d.disputed_key, d.disputed);
  $('#dDisputed').textContent = dispute ? fill('dyadDispute', { x: dispute }) : '';

  const h = d.h_abs;
  const el = $('#dHeat');
  el.textContent = Number.isFinite(h) ? h : '—';
  if (Number.isFinite(h) && heatColor) el.style.color = heatColor(h);

  $('#dPhase').textContent = phaseWord(d.phase, d.phase_name);
  $('#dTempo').textContent = t2('tempos', d.tempo || 'none', d.tempo_name) || '—';
  $('#dCov').textContent = d.data_coverage != null ? d.data_coverage + '%' : '—';

  // Накал — отклонение от нормы этой пары, а не расстояние до войны. Это
  // единственное место, где число можно объяснить рядом с ним самим.
  const parts = [t('dyadBasisHeat')];
  if (d.phase_basis === 'media') parts.push(t('dyadBasisMedia'));
  if (d.phase_basis === 'ucdp') parts.push(t('dyadBasisUcdp'));
  $('#dBasis').textContent = parts.join(' ');
}

/* ------------------------------------------------- разбор накала по блокам */

function paintBlocks(d) {
  const blocks = d.blocks || [];
  if (!blocks.length) { $('#blocks').closest('.dsec').hidden = true; return; }

  const measured = blocks.filter(b => b.measured);
  const wSum = measured.reduce((s, b) => s + (b.weight || 0), 0);
  $('#blocksLede').textContent =
    fill('dyadBlocksLede', { n: measured.length, total: blocks.length, w: wSum.toFixed(2) })
    + (wSum < 0.99 ? t('dyadBlocksPull') : '.');

  $('#blocks').innerHTML = blocks.map(b => {
    const inds = (b.indicators || []).map(i => `
      <div class="ind${i.fresh ? '' : ' ind--none'}">
        <span class="ind__name">${esc(t2('indicators', i.key, i.name))}</span>
        <span class="ind__src">${esc(t2('indSources', i.key, i.source || ''))}</span>
        <span class="ind__z num">${i.fresh && i.z != null ? (i.z > 0 ? '+' : '') + i.z : '—'}</span>
        <span class="ind__raw num">${i.fresh && i.raw != null ? i.raw : esc(t('dyadNoData'))}</span>
      </div>`).join('');
    return `
      <section class="blk${b.measured ? '' : ' blk--none'}">
        <header class="blk__head">
          <span class="blk__name">${esc(t2('blocks', b.block, b.name))}</span>
          <span class="blk__w num">${esc(t('dyadWeight'))} ${b.weight != null ? b.weight.toFixed(2) : '—'}</span>
          <span class="blk__state">${esc(t(b.measured ? 'dyadMeasured' : 'dyadNotMeasured'))}</span>
        </header>
        <div class="blk__inds">${inds}</div>
      </section>`;
  }).join('');
}

/* --------------------------------------------------------- история ступеней */

function paintHistory(d) {
  const h = d.phase_history || [];
  if (!h.length) { $('#histSec').hidden = true; return; }
  $('#hist').innerHTML = h.map(x => {
    const from = x.from != null ? phaseWord(x.from, x.from_name) + ' → ' : '';
    return `
    <li class="hist__it">
      <span class="hist__at num">${esc(fmtDay(x.at))}</span>
      <span class="hist__move">${esc(from)}${esc(phaseWord(x.to, x.to_name))}</span>
      <span class="hist__rule">${esc(t2('rules', x.rule, x.rule || ''))}</span>
    </li>`;
  }).join('');
}

/* ------------------------------------------------------- исходные события */

function paintEvents(d) {
  const ev = d.events || [];
  if (!ev.length) { $('#evSec').hidden = true; return; }

  const withUrl = ev.filter(e => e.url).length;
  $('#evLede').textContent = fill('dyadEvLede', { n: ev.length })
    + (withUrl ? fill('dyadEvLedeUrls', { n: withUrl }) : '.');

  $('#ev').innerHTML =
    `<thead><tr><th>${esc(t('colDate'))}</th><th>${esc(t('colSource'))}</th>`
    + `<th>${esc(t('colWhat'))}</th><th>${esc(t('colDead'))}</th><th></th></tr></thead>`
    + '<tbody>' + ev.map(e => `
      <tr>
        <td class="num">${esc(e.day)}</td>
        <td>${esc(sourceName(e.source))}</td>
        <td>${esc(cameoName(e.type, e.cameo))}</td>
        <td class="num">${e.fatalities != null ? e.fatalities : ''}</td>
        <td>${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener nofollow">${esc(t('colArticle'))}</a>` : ''}</td>
      </tr>`).join('') + '</tbody>';
}

/* --------------------------------------------------------------------- старт */

/* Полная перерисовка. Вызывается и при загрузке, и при смене языка: разделить
   «первый раз» и «перерисовать» значило бы держать два пути, которые обязаны
   давать одно и то же, — и один из них рано или поздно отстанет. */
function renderPage() {
  applyLang();
  if (FAIL) $('#failMsg').textContent = t(FAIL);
  if (!DATA) return;
  paintHead(DATA);
  paintBlocks(DATA);
  paintHistory(DATA);
  paintEvents(DATA);
  $('#stamp').textContent = DATA.built_at ? fill('dyadBuiltAt', { at: DATA.built_at }) : '';
}

async function boot() {
  buildLangPicker(renderPage);
  applyLang();      // экран загрузки и возможная ошибка тоже на языке читателя

  // Регистр приводится к реестровому: файлы названы RUS-UKR, а прийти сюда
  // могут и строчными — из старой ссылки, из истории браузера, из чужого
  // пересказа. Хостинг регистр различает, а читатель об этом знать не обязан.
  const raw = new URL(location.href).searchParams.get('id');
  const id = String(raw || '').toUpperCase();
  if (!id || !/^[A-Z]{3}-[A-Z]{3}$/.test(id)) {
    FAIL = 'dyadBadId';
    $('#failMsg').textContent = t(FAIL);
    return show('failed');
  }
  try {
    const r = await fetch(`data/${encodeURIComponent(id)}.json`, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    DATA = await r.json();

    renderPage();
    document.body.style.setProperty('--wash', heatWash ? heatWash(DATA.h_abs || 50) : '');
    show('body');
  } catch (e) {
    console.error('пара:', e);
    // Отличаем «нет такой пары» от «сеть отвалилась»: первое — про реестр,
    // второе — не вина читателя и не повод писать, что пары не существует.
    FAIL = navigator.onLine === false ? 'dyadOffline' : 'dyadNotFoundMsg';
    $('#failMsg').textContent = t(FAIL);
    show('failed');
  }
}

boot();
