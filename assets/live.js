/* ═══════════════════════════════════════════════════════════
   brink.watch — витрина в реестр интерфейса.

   Единственный источник чисел на странице: data/index.json, который
   пайплайн пересчитывает и коммитит раз в сутки. HTML при этом не меняется —
   поэтому стрелка едет сама, без пересборки и деплоя сайта.

   Ровно один принцип, из которого следует всё остальное:
   ЧЕГО НЕТ В ВИТРИНЕ — ТОГО НЕТ НА СТРАНИЦЕ. Раздел, которому нечем питаться,
   скрывается целиком. Заполнить его правдоподобными числами под настоящими
   названиями стран — это выдать оформление за измерение.
   ═══════════════════════════════════════════════════════════ */

/* Витрина считает НАКАЛ (0 холодно .. 100 горячо). Прототип рисовал стрелку
   по «индексу мира» с обратным направлением; направление развёрнуто в ZONES,
   в scale.js — здесь число не преобразуется вообще. */

const LIVE_URL = 'data/index.json';

function isoToId(dyadId) {
  return String(dyadId || '').toLowerCase();
}

/* Витрина пишет время как «2026-08-17 03:42 UTC». Такую строку Date не
   разбирает: получается Invalid Date, а Intl молча печатает «1 января 00:00».
   Приводим к ISO явно, а не надеемся на разбор произвольного формата. */
function toIso(stamp) {
  if (!stamp) return null;
  const m = String(stamp).match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::(\d{2}))?\s*(UTC|Z)?$/);
  if (!m) return stamp;
  return `${m[1]}T${m[2]}:${m[3] || '00'}Z`;
}

/* Ряд из витрины — ежедневный, 90 точек. Прототип рисовал помесячно от даты
   начала конфликта; подпись оси берётся из шага, поэтому его надо назвать
   честно, а не выдать дни за месяцы. */
function seriesOf(d) {
  const s = Array.isArray(d.series_90d) ? d.series_90d.slice() : [];
  return s.length ? s : null;
}

function startOfSeries(d, n) {
  const end = new Date((d.day || d.built_at || '').slice(0, 10) || Date.now());
  const from = new Date(end);
  from.setDate(from.getDate() - (n - 1));
  return from.toISOString().slice(0, 10);
}

function toConflict(d, builtAt) {
  const now = Number(d.h_abs);
  const series = seriesOf(d);
  const name = d.name || d.dyad_id;

  return {
    id: isoToId(d.dyad_id),
    kind: 'dyad',
    theatre: null,

    /* Названия приходят из витрины по-русски. Отдельных переводов у пайплайна
       нет, поэтому во всех языках показывается одно и то же имя — это честнее,
       чем машинно переведённое название стороны конфликта. */
    name_ru: name, name_en: name, name_uk: name,
    short_ru: name, short_en: name, short_uk: name,

    startDate: d.day,
    now,
    /* delta_7 и delta_30 — изменение НАКАЛА за период, поэтому «неделю назад»
       восстанавливается вычитанием, а не отдельным полем. */
    weekAgo:  now - Number(d.delta_7 || 0),
    monthAgo: now - Number(d.delta_30 || 0),
    // Время сборки лежит в корне витрины, а не в каждой диаде.
    updatedAt: toIso(d.built_at || builtAt),

    /* Поля витрины, которых у прототипа не было */
    phase: d.phase,
    phaseName: d.phase_name,
    phaseBasis: d.phase_basis,
    tempo: d.tempo,
    tempoName: d.tempo_name,
    region: d.region,
    disputed: d.disputed,
    coverage: d.data_coverage,
    weightShare: d.weight_share,

    seriesFrom: series ? startOfSeries(d, series.length) : null,
    seriesStep: 'day',
    series,

    /* Масштабы времени, как на биржевом графике. Часового нет и быть не может:
       индекс суточный — окна усреднения 7 и 30 дней, а события UCDP датированы
       днём. Часовой ряд пришлось бы интерполировать, то есть выдумать. */
    scales: d.series || null,
    /* Покрытие по тем же корзинам. На длинном графике состав блоков меняется
       (в 2025-м есть кинетика и нет медиапотока, в 2026-м наоборот), и не
       показать этого — значит молча склеить несравнимое. */
    scaleCoverage: d.coverage || null,

    /* Ниже — то, чего пайплайн не считает. Оставлены пустыми намеренно:
       painter'ы в app.js прячут свои разделы, увидев пустоту. */
    escalationRisk: null,
    sourcesLive: null,
    eventsLast24h: d.events_30d ?? null,
    axes: [],
    divergence: null,
    chokepoints: [],
    factors: [],
    milestones: [],
  };
}

function applyIndex(doc) {
  const dyads = Array.isArray(doc.dyads) ? doc.dyads : [];

  /* Пустой реестр — штатное состояние до первого прогона, а не ошибка.
     Показать его прямо важнее, чем показать пустую шкалу без объяснения.

     Режим demo (build.py --demo) рисуется наравне с db, но под плашкой:
     без него локальная работа над вёрсткой невозможна вообще, а тихо
     приравнять выдуманные числа к посчитанным нельзя. Плашку ставит boot(). */
  const usable = doc.source === 'db' || doc.source === 'demo';
  const computed = dyads.filter(d => usable && d.h_abs != null);

  Object.keys(CONFLICTS).forEach(k => delete CONFLICTS[k]);
  VIEWS.splice(0, VIEWS.length);

  computed
    .slice()
    .sort((a, b) => Number(b.h_abs) - Number(a.h_abs))   // горячие сверху
    .forEach(d => {
      const c = toConflict(d, doc.built_at);
      CONFLICTS[c.id] = c;
      VIEWS.push({ type: 'conflict', id: c.id });
    });

  /* Глобальные оси считаются на весь мир, а не по диаде: показываем их один
     раз, отдельным блоком, и не выдаём за разложение конкретной пары. */
  LIVE.globalAxes = Array.isArray((doc.global || {}).axes) ? doc.global.axes : [];
  LIVE.gei = (doc.global || {}).gei ?? null;
  LIVE.geiDelta30 = (doc.global || {}).delta_30 ?? null;
  LIVE.builtAt = doc.built_at || null;
  LIVE.source = doc.source || 'registry';
  LIVE.registryTotal = doc.registry_total ?? dyads.length;
  LIVE.methodVersion = doc.method_version || null;

  HAS.axes = LIVE.globalAxes.length > 0;
  HAS.ledger = false;
  HAS.divergence = false;
  HAS.matrix = false;
  HAS.chokepoints = false;
  HAS.calibration = false;
  HAS.live = false;
  HAS.milestones = false;

  return computed.length;
}

const LIVE = {
  source: 'registry', builtAt: null, gei: null, geiDelta30: null,
  globalAxes: [], registryTotal: 0, methodVersion: null, ready: false,
};

/* Показать состояние «данных ещё нет» вместо шкалы. Именно этот текст висел
   на домене, когда витрину затирала пересборка — он должен появляться только
   когда пайплайн действительно ещё не считал. */
function showEmptyState(reason) {
  document.documentElement.dataset.state = 'empty';
  const band = document.querySelector('.demoband');
  if (band) {
    band.hidden = false;
    const label = band.querySelector('[data-i18n]');
    if (label) { label.removeAttribute('data-i18n'); label.textContent = reason; }
  }
}

function boot() {
  return fetch(LIVE_URL, { cache: 'no-store' })
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(doc => {
      const n = applyIndex(doc);
      LIVE.ready = n > 0;
      if (!LIVE.ready) {
        showEmptyState('Данные ещё не собраны — индекс не рассчитан');
        return;
      }
      document.documentElement.dataset.state = LIVE.source === 'demo' ? 'demo' : 'live';

      // Плашка относилась к выдуманным числам прототипа. При настоящих числах
      // ей здесь не место; в режиме demo она, наоборот, обязана быть видна.
      const band = document.querySelector('.demoband');
      if (band) {
        band.hidden = LIVE.source !== 'demo';
        const label = band.querySelector('span:last-child');
        if (label && LIVE.source === 'demo') {
          label.removeAttribute('data-i18n');
          label.textContent = 'Демонстрационные числа — не для публикации';
        }
      }
      renderAll();
      bootCalib();      // отдельный файл, свой темп обновления
    })
    .catch(err => {
      // Молчаливый провал загрузки — это застывшая шкала со вчерашним числом
      // и никакого признака, что что-то сломалось. Пусть лучше будет видно.
      console.error('витрина не загрузилась:', err);
      showEmptyState('Витрина не загрузилась — показывать нечего');
    });
}

boot();
