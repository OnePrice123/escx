/* ═══════════════════════════════════════════════════════════
   Раздел обратного прогона.

   Здесь единственное место на сайте, где показывается, работает ли метод.
   Поэтому правило раздела жёстче общего: обе цифры стоят рядом ВСЕГДА.

   «16 из 19 поднимался перед развязкой» без второй цифры читается как
   «метод проверен и точен». Это неправда: тот же порог переходится 130 раз,
   и только 42 перехода заканчиваются урегулированием. Показывать первую
   цифру без второй — тот самый подлог, против которого весь проект.
   ═══════════════════════════════════════════════════════════ */

const CALIB_URL = 'data/calibration.json';
let CALIB = null;

const OUTCOME = {
  negotiated: 'соглашение',
  military:   'военная развязка',
  ceasefire:  'перемирие',
};

function calibSpark(series, w = 220, h = 44) {
  if (!series || series.length < 2) return '';
  const n = series.length;
  const X = i => (i / (n - 1)) * w;
  const Y = v => h - 2 - (v / 100) * (h - 6);
  const line = series.map((v, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1)).join(' ');
  const col = zoneColor(Math.max(...series));
  const thr = Y(CALIB ? CALIB.threshold : 65);
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"
    style="display:block;width:100%;height:${h}px" aria-hidden="true">
    <line x1="0" y1="${thr.toFixed(1)}" x2="${w}" y2="${thr.toFixed(1)}"
      stroke="${cssVar('--hair')}" stroke-width="1" stroke-dasharray="3 3"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="1.6"
      stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

function paintCalib() {
  const sec = $('#calibration');
  if (!sec) return;
  if (!CALIB) { sec.hidden = true; return; }
  sec.hidden = false;

  const c = CALIB.control || {};
  // Две цифры рядом и в одном размере: ни одна не крупнее другой.
  $('#calStats').innerHTML = `
    <div><dt class="num">${CALIB.with_signal} / ${CALIB.n}</dt>
      <dd>${t('calStatRose')}</dd></div>
    <div><dt class="num">${c.precision != null ? Math.round(c.precision * 100) + ' %' : '—'}</dt>
      <dd>${t('calStatPrecision')}</dd></div>
    <div><dt class="num">${CALIB.median_lead != null ? CALIB.median_lead + ' ' + t('calMonths') : '—'}</dt>
      <dd>${t('calStatMedian')}</dd></div>`;

  const rows = (CALIB.conflicts || []).slice()
    .sort((a, b) => (a.lead == null) - (b.lead == null) || (a.lead - b.lead));

  $('#calBoard').innerHTML = rows.map(r => {
    const lead = r.lead != null
      ? `<span class="calrow__lead">${r.lead} ${t('calMonths')}</span>`
      : `<span class="calrow__none">${r.why || r.note || ''}</span>`;
    return `
      <div class="calrow">
        <div class="calrow__meta">
          <span class="calrow__name">${r.name}</span>
          <span class="calrow__acc">${OUTCOME[r.outcome] || r.outcome} · ${r.accord || ''}</span>
        </div>
        <div class="calrow__spark">${calibSpark(r.series)}</div>
        <div class="calrow__right">${lead}</div>
      </div>`;
  }).join('');
}

function bootCalib() {
  return fetch(CALIB_URL, { cache: 'no-store' })
    .then(r => (r.ok ? r.json() : null))
    .then(d => {
      // Раздела нет, если прогон не собрался. Показывать пустую рамку с
      // заголовком «обратный прогон» — обещать проверку, которой не было.
      CALIB = (d && d.conflicts && d.conflicts.length) ? d : null;
      paintCalib();
    })
    .catch(() => { CALIB = null; paintCalib(); });
}
