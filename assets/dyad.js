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
   ═══════════════════════════════════════════════════════════ */

const $ = s => document.querySelector(s);
const { heatColor, heatWash } = window.ESCX || {};

const show = id => ['loading', 'failed', 'body'].forEach(x => {
  const n = document.getElementById(x);
  if (n) n.hidden = x !== id;
});

const esc = s => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/* Склонение после числа: 1 блок, 2 блока, 5 блоков. Пишется руками, потому
   что Intl.PluralRules даёт категорию, а формы всё равно перечислять здесь. */
const plural = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  return b === 1 ? one : many;
};

const fmtDate = s => {
  const d = new Date(String(s || '').replace(' ', 'T'));
  if (!s || isNaN(d)) return String(s || '—');
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(d);
};

/* Названия источников словами. Строка «gdelt_export» читателю ничего не
   говорит, а «GDELT» с расшифровкой — говорит. */
const SOURCE_RU = {
  gdelt_export: 'GDELT', ucdp_ged: 'UCDP GED', ofac_sdn: 'OFAC SDN',
  adsb: 'ADS-B', unvotes: 'ГА ООН',
};

/* Корни кодов CAMEO словами — только те, что реально встречаются в выборке.
   Полная таблица на двести кодов на странице не нужна: она заменила бы
   объяснение перечислением. */
const CAMEO_RU = {
  '01': 'публичное заявление', '02': 'обращение', '03': 'намерение к диалогу',
  '04': 'консультации', '05': 'дипломатический шаг', '06': 'сотрудничество',
  '07': 'помощь', '08': 'уступка', '09': 'расследование', '10': 'требование',
  '11': 'осуждение', '12': 'отказ', '13': 'угроза', '14': 'протест',
  '15': 'демонстрация силы', '16': 'разрыв отношений', '17': 'принуждение',
  '18': 'нападение', '19': 'бой', '20': 'применение ОМП',
};

function cameoName(type, code) {
  const root = String(type || '').replace('cameo:', '').slice(0, 2);
  const ru = CAMEO_RU[root];
  const num = code || root;
  return ru ? `${ru} (${num})` : (num || '—');
}

/* ------------------------------------------------------------------ шапка */

const STATUS_RU = { dormant: 'завершён', resolved: 'разрешён' };

/**
 * Шапка завершённого конфликта.
 *
 * Накала и ступени у него нет — и это не пропуск витрины: расчёт по спящим
 * парам не ведётся вовсе. Показать здесь прочерк на месте числа значило бы
 * намекнуть, что число должно быть и потерялось. Поэтому вместо накала —
 * период и объём собранного, а вместо ступени — статус.
 */
function paintArchived(d) {
  document.title = `${d.name || d.dyad_id} — brink.watch`;
  $('#dRegion').textContent = [d.region, 'завершённый конфликт'].filter(Boolean).join(' · ');
  $('#dName').textContent = d.name || d.dyad_id;
  $('#dDisputed').textContent = d.disputed ? `Предмет спора: ${d.disputed}.` : '';

  const years = d.events_from && d.events_to
    ? `${String(d.events_from).slice(0, 4)}—${String(d.events_to).slice(0, 4)}` : '—';
  const src = Object.entries(d.sources || {})
    .map(([k, n]) => `${SOURCE_RU[k] || k} ${n}`).join(', ');

  $('.dhead__nums').innerHTML = `
    <div class="dnum"><span class="dnum__v">${esc(STATUS_RU[d.status] || d.status || '—')}</span><span class="dnum__k">статус</span></div>
    <div class="dnum"><span class="dnum__v num">${esc(years)}</span><span class="dnum__k">события за</span></div>
    <div class="dnum"><span class="dnum__v num">${d.events_total != null ? d.events_total : '—'}</span><span class="dnum__k">записей источников</span></div>
    ${d.since ? `<div class="dnum"><span class="dnum__v num">${d.since}</span><span class="dnum__k">начало спора</span></div>` : ''}`;

  $('#dBasis').textContent =
    'Накал и ступень по этой паре не считаются: расчёт ведётся только по действующим конфликтам. '
    + 'Из реестра она не удалена намеренно — её история нужна как база сравнения для действующих пар. '
    + (src ? `Собрано: ${src}.` : '');
}

function paintHead(d) {
  if (d.status && d.status !== 'active') return paintArchived(d);

  document.title = `${d.name || d.dyad_id} — brink.watch`;
  $('#dRegion').textContent = d.region || '';
  $('#dName').textContent = d.name || d.dyad_id;
  $('#dDisputed').textContent = d.disputed ? `Предмет спора: ${d.disputed}.` : '';

  const h = d.h_abs;
  const el = $('#dHeat');
  el.textContent = Number.isFinite(h) ? h : '—';
  if (Number.isFinite(h) && heatColor) el.style.color = heatColor(h);

  $('#dPhase').textContent = d.phase_name || (d.phase != null ? d.phase : '—');
  $('#dTempo').textContent = d.tempo_name || '—';
  $('#dCov').textContent = d.data_coverage != null ? d.data_coverage + '%' : '—';

  // Накал — отклонение от нормы этой пары, а не расстояние до войны. Это
  // единственное место, где число можно объяснить рядом с ним самим.
  const parts = [];
  parts.push('Накал 50 означает «норма для этой пары», а не «половина пути к войне»: это отклонение от её собственной медианы.');
  if (d.phase_basis === 'media')
    parts.push('Ступень выведена из медиапотока (коды CAMEO в GDELT), а не из документов: реестров санкций и дипломатических нот в пайплайне пока нет.');
  if (d.phase_basis === 'ucdp')
    parts.push('Ступень стоит на боевых смертях UCDP по порогам 25 и 1000 в год — они взяты из UCDP/PRIO, а не придуманы нами.');
  $('#dBasis').textContent = parts.join(' ');
}

/* ------------------------------------------------- разбор накала по блокам */

function paintBlocks(d) {
  const blocks = d.blocks || [];
  if (!blocks.length) { $('#blocks').closest('.dsec').hidden = true; return; }

  const measured = blocks.filter(b => b.measured);
  const wSum = measured.reduce((s, b) => s + (b.weight || 0), 0);
  const bw = plural(measured.length, 'блок', 'блока', 'блоков');
  $('#blocksLede').textContent =
    `Измерено ${measured.length} ${bw} из ${blocks.length}. Суммарный вес измеренного — `
    + `${wSum.toFixed(2)} из 1.00`
    + (wSum < 0.99 ? ', поэтому накал тянется к 50: часть картины не наблюдается.' : '.');

  $('#blocks').innerHTML = blocks.map(b => {
    const inds = (b.indicators || []).map(i => `
      <div class="ind${i.fresh ? '' : ' ind--none'}">
        <span class="ind__name">${esc(i.name)}</span>
        <span class="ind__src">${esc(i.source || '')}</span>
        <span class="ind__z num">${i.fresh && i.z != null ? (i.z > 0 ? '+' : '') + i.z : '—'}</span>
        <span class="ind__raw num">${i.fresh && i.raw != null ? i.raw : 'нет данных'}</span>
      </div>`).join('');
    return `
      <section class="blk${b.measured ? '' : ' blk--none'}">
        <header class="blk__head">
          <span class="blk__name">${esc(b.name)}</span>
          <span class="blk__w num">вес ${b.weight != null ? b.weight.toFixed(2) : '—'}</span>
          <span class="blk__state">${b.measured ? 'измерен' : 'не измерен'}</span>
        </header>
        <div class="blk__inds">${inds}</div>
      </section>`;
  }).join('');
}

/* --------------------------------------------------------- история ступеней */

function paintHistory(d) {
  const h = d.phase_history || [];
  if (!h.length) { $('#histSec').hidden = true; return; }
  $('#hist').innerHTML = h.map(x => `
    <li class="hist__it">
      <span class="hist__at num">${esc(fmtDate(x.at))}</span>
      <span class="hist__move">${x.from_name ? esc(x.from_name) + ' → ' : ''}${esc(x.to_name || x.to)}</span>
      <span class="hist__rule">${esc(x.rule || '')}</span>
    </li>`).join('');
}

/* ------------------------------------------------------- исходные события */

function paintEvents(d) {
  const ev = d.events || [];
  if (!ev.length) { $('#evSec').hidden = true; return; }

  const withUrl = ev.filter(e => e.url).length;
  $('#evLede').textContent =
    `Последние ${ev.length} записей источников по этой паре`
    + (withUrl ? `, из них ${withUrl} со ссылкой на публикацию.` : '.');

  $('#ev').innerHTML =
    `<thead><tr><th>Дата</th><th>Источник</th><th>Что записано</th><th>Погибшие</th><th></th></tr></thead>`
    + '<tbody>' + ev.map(e => `
      <tr>
        <td class="num">${esc(e.day)}</td>
        <td>${esc(SOURCE_RU[e.source] || e.source)}</td>
        <td>${esc(cameoName(e.type, e.cameo))}</td>
        <td class="num">${e.fatalities != null ? e.fatalities : ''}</td>
        <td>${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener nofollow">статья</a>` : ''}</td>
      </tr>`).join('') + '</tbody>';
}

/* --------------------------------------------------------------------- старт */

async function boot() {
  // Регистр приводится к реестровому: файлы названы RUS-UKR, а прийти сюда
  // могут и строчными — из старой ссылки, из истории браузера, из чужого
  // пересказа. Хостинг регистр различает, а читатель об этом знать не обязан.
  const raw = new URL(location.href).searchParams.get('id');
  const id = String(raw || '').toUpperCase();
  if (!id || !/^[A-Z]{3}-[A-Z]{3}$/.test(id)) {
    $('#failMsg').textContent = 'Пара не указана или указана неверно. Откройте её из списка на главной.';
    return show('failed');
  }
  try {
    const r = await fetch(`data/${encodeURIComponent(id)}.json`, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();

    paintHead(d);
    paintBlocks(d);
    paintHistory(d);
    paintEvents(d);
    $('#stamp').textContent = d.built_at ? `Данные собраны ${d.built_at}` : '';
    document.body.style.setProperty('--wash', heatWash ? heatWash(d.h_abs || 50) : '');
    show('body');
  } catch (e) {
    console.error('пара:', e);
    // Отличаем «нет такой пары» от «сеть отвалилась»: первое — про реестр,
    // второе — не вина читателя и не повод писать, что пары не существует.
    $('#failMsg').textContent = navigator.onLine === false
      ? 'Нет связи. Барометр статический и заработает, как только сеть вернётся.'
      : 'Такой пары нет в реестре или данные по ней ещё не собраны.';
    show('failed');
  }
}

boot();
