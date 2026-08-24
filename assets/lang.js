/* ═══════════════════════════════════════════════════════════
   Язык интерфейса: выбор, словарь, имена стран.

   Файл общий для всех страниц сайта. Раньше это жило в app.js, и страница
   пары не могла ничем из этого воспользоваться: app.js целиком завязан на
   главную — CONFLICTS, VIEWS, витрину. Поэтому пара была русской, чем бы ни
   пользовался читатель.

   Здесь только то, что нужно ЛЮБОЙ странице: какой язык выбран, как достать
   строку из словаря, как назвать страну и пару, как просклонять после числа
   и как разложить словарь по разметке. Ничего про конкретный экран.
   ═══════════════════════════════════════════════════════════ */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

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

/* Недостающий ключ подменяется английским, а не своим же именем: на экране
   «worldTitle» вместо заголовка выглядит как поломка сайта, а английская
   строка — просто как непереведённый кусок. Языков шестнадцать, и держать
   их все в ногу с каждой правкой текста нереально. */
const t = k => (I18N[LANG] && I18N[LANG][k]) || (I18N.en && I18N.en[k]) || k;

/* Локализованное поле: loc(o,'name') → name_ru | name_en, loc(o) → ru | en */
function loc(o, prefix) {
  const p = prefix ? prefix + '_' : '';
  return o[p + LANG] || o[p + 'en'] || o[p + 'ru'] || '';
}

/* Трёхбуквенные коды реестра -> двухбуквенные, которые понимает Intl.
   Таблица нужна ровно одна на все языки: названия стран знает браузер.
   Косово (XKX) — не код ISO 3166, но Intl его отдаёт, потому что он есть
   в CLDR как пользовательский; если однажды перестанет — сработает откат
   на русское имя из витрины. */
const A3_TO_A2 = {
  AFG: 'AF', ARM: 'AM', AZE: 'AZ', CHN: 'CN', COD: 'CD', DZA: 'DZ', EGY: 'EG',
  ERI: 'ER', ETH: 'ET', GRC: 'GR', GUY: 'GY', IND: 'IN', IRN: 'IR', ISR: 'IL',
  JPN: 'JP', KHM: 'KH', KOR: 'KR', LBN: 'LB', MAR: 'MA', PAK: 'PK', PHL: 'PH',
  PRK: 'KP', RUS: 'RU', RWA: 'RW', SRB: 'RS', THA: 'TH', TUR: 'TR', TWN: 'TW',
  UKR: 'UA', USA: 'US', VEN: 'VE', XKX: 'XK', YEM: 'YE',
};

let _dn = null, _dnLang = null;
function countryName(a3) {
  const a2 = A3_TO_A2[a3];
  if (!a2) return null;
  try {
    if (_dnLang !== LANG) {
      _dn = new Intl.DisplayNames([LANG], { type: 'region' });
      _dnLang = LANG;
    }
    const n = _dn.of(a2);
    return n && n !== a2 ? n : null;
  } catch (e) { return null; }
}

/* Имя пары на языке читателя. Откат на строку из витрины — если кода нет
   в таблице или браузер не знает страну. */
function pairName(c) {
  const a = countryName(c.sideA), b = countryName(c.sideB);
  return (a && b) ? `${a} — ${b}` : loc(c, 'short');
}

function regionName(c) {
  const m = (I18N[LANG] && I18N[LANG].regions) || (I18N.en && I18N.en.regions) || {};
  return m[c.regionKey] || c.region || '';
}

function disputedName(c) {
  const m = (I18N[LANG] && I18N[LANG].disputed) || (I18N.en && I18N.en.disputed) || {};
  return m[c.disputed_key || c.disputedKey] || c.disputed || '';
}

function tempoTitle(c) {
  const m = (I18N[LANG] && I18N[LANG].tempos) || (I18N.en && I18N.en.tempos) || {};
  return m[c.tempo || 'none'] || c.tempoName || '';
}

/* Название ступени берётся из словаря по НОМЕРУ, а не из данных.
   Витрина переведена на шестнадцать языков, а пайплайн присылает готовую
   русскую строку — немец и китаец видели бы кириллицу. Номер ступени
   язык не имеет. Русская строка из данных остаётся последним запасом:
   если словарь языка неполон, откат идёт на английский, потом на неё. */
function phaseTitle(c) {
  const list = (I18N[LANG] && I18N[LANG].phases) || (I18N.en && I18N.en.phases);
  return (Array.isArray(list) && list[c.phase]) || c.phaseName || '';
}

/* Склонение после числа: 1 пара, 2 пары, 5 пар. Для языков без падежей
   формы совпадают, и правило вырождается само. */
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  return b === 1 ? one : many;
}

/* Правовые документы существуют в двух редакциях: русской и английской.
   Через словарь их не пропустишь — это связный текст с таблицами, а не
   подписи. Поэтому ссылка ведёт в ту редакцию, на языке которой человек
   читает сайт; для языков без своей редакции — в английскую, а не в русскую,
   которую он точно не прочтёт. Старшей при расхождении остаётся русская, и
   это написано в самих документах. */
const docHref = name => (LANG === 'ru' ? `${name}.html` : `${name}.en.html`);

/* Разложить словарь по разметке. Заголовок страницы НЕ трогаем: на главной
   он один, на странице пары — имя пары, и знать об этом должна сама
   страница, а не общий файл. */
function applyLang() {
  const d = document.documentElement;
  d.lang = LANG.split('-')[0];
  d.dir = I18N[LANG]._dir;
  d.dataset.script = ['zh', 'ja', 'ko'].includes(LANG) ? 'cjk'
    : ['ar', 'fa'].includes(LANG) ? 'arabic' : 'latin';
  $$('[data-i18n]').forEach(n => { n.textContent = t(n.dataset.i18n); });
  $$('[data-doc]').forEach(a => { a.href = docHref(a.dataset.doc); });
}

/* Переключатель. Что перерисовывать после смены языка, знает страница —
   поэтому она и передаёт это сюда, а не общий файл догадывается. */
function buildLangPicker(onChange) {
  const sel = $('#lang');
  if (!sel) return;
  sel.innerHTML = LANG_ORDER.filter(c => I18N[c])
    .map(c => `<option value="${c}"${c === LANG ? ' selected' : ''}>${I18N[c]._name}</option>`).join('');
  sel.addEventListener('change', () => {
    LANG = sel.value;
    localStorage.setItem('px.lang', LANG);
    if (onChange) onChange();
  });
}

/* Дата на языке читателя. Раньше страница пары звала Intl с жёстким 'ru-RU'
   и печатала «19 августа» немцу. */
function fmtDay(s) {
  const d = new Date(String(s || '').replace(' ', 'T'));
  if (!s || isNaN(d)) return String(s || '—');
  return new Intl.DateTimeFormat(LANG, { day: 'numeric', month: 'long', year: 'numeric' }).format(d);
}

/* Строка из словаря-подсловаря по ключу: t2('sources', 'ucdp_ged').
   Откат тот же, что у t(): язык -> английский -> то, что дала витрина. */
function t2(group, key, fallback) {
  const m = (I18N[LANG] && I18N[LANG][group]) || (I18N.en && I18N.en[group]) || {};
  return m[key] || fallback || '';
}
