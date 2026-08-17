/* Синтетические числа — ТОЛЬКО для работы над вёрсткой.
   В продакшен не подключается: index.html грузит live.js, который берёт
   реальную витрину из data/index.json. Публиковать выдуманные числа под
   настоящими названиями стран нельзя — человек примет их за измерение. */
const CONFLICTS = {

  /* ─── Россия — Украина ─────────────────────────────── */
  'ru-ua': {
    id: 'ru-ua', kind: 'dyad', theatre: null,
    name_ru: 'Россия — Украина', name_uk: 'Росія — Україна', name_en: 'Russia — Ukraine',
    short_ru: 'Россия — Украина', short_uk: 'Росія — Україна', short_en: 'Russia — Ukraine',
    startDate: '2022-02-24',
    now: 23.4, weekAgo: 25.2, monthAgo: 21.9,
    escalationRisk: 41,
    updatedAt: '2026-08-04T09:40:00+03:00',
    sourcesLive: 38, eventsLast24h: 247,

    axes: [
      { id: 'diplomacy', value: 31, delta: -3.1 },
      { id: 'combat',    value: 18, delta: -0.4 },
      { id: 'human',     value: 34, delta: +2.6 },
      { id: 'economy',   value: 22, delta: -1.2 },
      { id: 'rhetoric',  value: 19, delta: -2.0 },
    ],

    /* Слова и дела на одной шкале 0..100. lagDays — оценённое запаздывание
       действий, на которое сдвигается сравнение (иначе разрыв мерил бы календарь). */
    divergence: {
      words: 27, deeds: 20, lagDays: 26,
      history: [
        6, 5, 7, 9, 8, 6, 4, 3, 5, 7, 9, 11,
        10, 8, 6, 5, 4, 6, 8, 9, 8, 7, 6, 7,
      ],
    },

    chokepoints: [
      { id: 'bosphorus', share: 10, unit: 'wheat', sensitivity: 34,
        name_ru: 'Черноморский коридор', name_uk: 'Чорноморський коридор', name_en: 'Black Sea corridor' },
      { id: 'gas-eu', share: 8, unit: 'gas', sensitivity: 21,
        name_ru: 'Трубопроводный экспорт газа в Европу', name_uk: 'Трубопровідний експорт газу до Європи', name_en: 'Pipeline gas exports to Europe' },
    ],

    factors: [
      { key: 'f1', date: '2026-08-03', axis: 'human',     impact: +1.4, sources: 11, confidence: 'high',   signal: 'news' },
      { key: 'f2', date: '2026-08-02', axis: 'combat',    impact: -0.9, sources: 24, confidence: 'high',   signal: 'news' },
      { key: 'f3', date: '2026-08-01', axis: 'diplomacy', impact: -1.6, sources:  7, confidence: 'medium', signal: 'news' },
      { key: 'f4', date: '2026-07-31', axis: 'economy',   impact: -0.7, sources: 15, confidence: 'high',   signal: 'tender' },
      { key: 'f5', date: '2026-07-30', axis: 'rhetoric',  impact: -0.5, sources:  9, confidence: 'medium', signal: 'news' },
      { key: 'f6', date: '2026-07-29', axis: 'diplomacy', impact: +0.5, sources:  4, confidence: 'low',    signal: 'flight' },
    ],

    seriesFrom: '2022-02', seriesStep: 'month', syntheticFrom: 42,
    series: [
      29.0, 37.8, 33.1, 28.4, 26.0, 33.6, 31.2, 26.7, 25.1, 24.4,
      23.0, 22.1, 24.6, 26.2, 25.0, 23.8, 22.4, 24.9, 21.3, 20.0,
      19.4, 20.8, 22.0, 21.2, 20.5, 23.7, 26.4, 24.9, 23.1, 27.8,
      25.6, 24.0, 22.9, 23.8, 25.2, 24.1, 23.0, 22.2, 24.5, 26.1,
      25.4, 23.9, 22.6, 21.8, 23.3, 24.8, 26.6, 25.9, 24.2, 22.8,
      21.9, 23.5, 25.2, 23.4,
    ],
    milestones: [
      { key: 'm1', i: 1 }, { key: 'm2', i: 5 }, { key: 'm3', i: 17 },
      { key: 'm4', i: 23 }, { key: 'm5', i: 28 },
    ],
  },

  /* ─── США — Иран ───────────────────────────────────── */
  'us-ir': {
    id: 'us-ir', kind: 'dyad', theatre: 'iran',
    name_ru: 'США — Иран', name_uk: 'США — Іран', name_en: 'United States — Iran',
    short_ru: 'США — Иран', short_uk: 'США — Іран', short_en: 'US — Iran',
    startDate: '2018-05-08',        // выход США из СВПД — начало текущей фазы
    now: 31.7, weekAgo: 30.4, monthAgo: 29.8,
    escalationRisk: 52,
    updatedAt: '2026-08-04T09:40:00+03:00',
    sourcesLive: 31, eventsLast24h: 118,

    axes: [
      { id: 'diplomacy', value: 46, delta: +2.4 },
      { id: 'combat',    value: 22, delta: -1.1 },
      { id: 'human',     value: 33, delta:  0.0 },
      { id: 'economy',   value: 26, delta: +1.8 },
      { id: 'rhetoric',  value: 30, delta: -0.6 },
    ],

    divergence: {
      words: 23, deeds: 40, lagDays: 31,
      history: [
        -4, -6, -5, -3, -2, -4, -7, -9, -8, -6, -5, -7,
        -9, -11, -10, -8, -9, -12, -14, -13, -15, -16, -14, -17,
      ],
    },

    chokepoints: [
      { id: 'hormuz', share: 20, unit: 'oil', sensitivity: 61,
        name_ru: 'Ормузский пролив', name_uk: 'Ормузька протока', name_en: 'Strait of Hormuz' },
      { id: 'hormuz-lng', share: 20, unit: 'lng', sensitivity: 47,
        name_ru: 'Ормузский пролив — СПГ', name_uk: 'Ормузька протока — СПГ', name_en: 'Strait of Hormuz — LNG' },
    ],

    factors: [
      { date: '2026-08-03', axis: 'diplomacy', impact: +1.9, sources: 14, confidence: 'high', signal: 'flight',
        ru: 'Возобновлён непрямой переговорный канал при посредничестве третьей страны',
        uk: 'Відновлено непрямий переговорний канал за посередництва третьої країни',
        en: 'Indirect negotiating channel resumed under third-country mediation' },
      { date: '2026-08-02', axis: 'economy', impact: +0.8, sources: 9, confidence: 'medium', signal: 'tender',
        ru: 'Выданы отдельные лицензии на гуманитарные и медицинские поставки',
        uk: 'Видано окремі ліцензії на гуманітарні та медичні постачання',
        en: 'Individual licences issued for humanitarian and medical supplies' },
      { date: '2026-07-31', axis: 'combat', impact: -1.2, sources: 21, confidence: 'high', signal: 'market',
        ru: 'Инцидент с судоходством в Ормузском проливе',
        uk: 'Інцидент із судноплавством у Ормузькій протоці',
        en: 'Shipping incident in the Strait of Hormuz' },
      { date: '2026-07-29', axis: 'rhetoric', impact: -0.6, sources: 12, confidence: 'medium', signal: 'news',
        ru: 'Ужесточение формулировок в заявлениях по ядерной программе',
        uk: 'Жорсткіші формулювання в заявах щодо ядерної програми',
        en: 'Harder wording in statements on the nuclear programme' },
    ],

    seriesFrom: '2015-07', seriesStep: 'quarter', syntheticFrom: 40,
    series: [
      62, 60,
      58, 57, 56, 55,
      52, 50, 48, 46,
      44, 30, 26, 24,
      22, 20, 18, 16,
      10, 14, 16, 18,
      24, 30, 32, 30,
      34, 36, 30, 26,
      24, 28, 32, 30,
      28, 22, 20, 18,
      20, 24, 26, 28,
      30, 32, 31.7,
    ],
    milestones: [
      { i: 0,  ru: 'Подписание СВПД', uk: 'Підписання СВПД', en: 'JCPOA signed' },
      { i: 11, ru: 'Выход США из СВПД', uk: 'Вихід США із СВПД', en: 'US withdrawal from the JCPOA' },
      { i: 18, ru: 'Гибель Касема Сулеймани', uk: 'Загибель Касема Сулеймані', en: 'Killing of Qasem Soleimani' },
      { i: 23, ru: 'Венские переговоры о восстановлении сделки', uk: 'Віденські переговори про відновлення угоди', en: 'Vienna talks on restoring the deal' },
    ],
  },

  /* ─── Израиль — Иран ───────────────────────────────── */
  'il-ir': {
    id: 'il-ir', kind: 'dyad', theatre: 'iran',
    name_ru: 'Израиль — Иран', name_uk: 'Ізраїль — Іран', name_en: 'Israel — Iran',
    short_ru: 'Израиль — Иран', short_uk: 'Ізраїль — Іран', short_en: 'Israel — Iran',
    startDate: '2024-04-13',        // первый прямой обмен ударами
    now: 16.3, weekAgo: 19.1, monthAgo: 21.0,
    escalationRisk: 71,
    updatedAt: '2026-08-04T09:40:00+03:00',
    sourcesLive: 27, eventsLast24h: 164,

    axes: [
      { id: 'diplomacy', value:  9, delta: -0.8 },
      { id: 'combat',    value: 14, delta: -3.4 },
      { id: 'human',     value: 26, delta: -0.5 },
      { id: 'economy',   value: 24, delta: -0.9 },
      { id: 'rhetoric',  value: 12, delta: -2.7 },
    ],

    divergence: {
      words: 9, deeds: 14, lagDays: 9,
      history: [
        -2, -3, -4, -6, -5, -3, -2, -4, -6, -7, -5, -4,
        -3, -5, -6, -4, -3, -5, -7, -6, -4, -5, -6, -5,
      ],
    },

    chokepoints: [
      { id: 'bab', share: 12, unit: 'trade', sensitivity: 55,
        name_ru: 'Баб-эль-Мандеб и Красное море', name_uk: 'Баб-ель-Мандеб і Червоне море', name_en: 'Bab el-Mandeb and the Red Sea' },
    ],

    factors: [
      { date: '2026-08-03', axis: 'combat', impact: -2.4, sources: 29, confidence: 'high', signal: 'news',
        ru: 'Обмен ударами по военным объектам за пределами линии соприкосновения',
        uk: 'Обмін ударами по військових об’єктах поза лінією зіткнення',
        en: 'Exchange of strikes on military sites beyond the line of contact' },
      { date: '2026-08-02', axis: 'rhetoric', impact: -1.1, sources: 18, confidence: 'high', signal: 'news',
        ru: 'Публичные заявления о готовности к дальнейшим ударам с обеих сторон',
        uk: 'Публічні заяви про готовність до подальших ударів з обох боків',
        en: 'Public statements on readiness for further strikes from both sides' },
      { date: '2026-08-01', axis: 'diplomacy', impact: -0.7, sources: 6, confidence: 'low', signal: 'flight',
        ru: 'Посреднические усилия третьей стороны отклонены',
        uk: 'Посередницькі зусилля третьої сторони відхилено',
        en: 'Third-party mediation effort declined' },
      { date: '2026-07-30', axis: 'human', impact: +0.4, sources: 8, confidence: 'medium', signal: 'market',
        ru: 'Открыт коридор для эвакуации гражданских из приграничного района',
        uk: 'Відкрито коридор для евакуації цивільних із прикордонного району',
        en: 'Corridor opened for civilian evacuation from a border area' },
    ],

    seriesFrom: '2015-07', seriesStep: 'quarter', syntheticFrom: 40,
    series: [
      34, 33,
      32, 32, 31, 30,
      30, 29, 28, 28,
      27, 26, 24, 23,
      22, 22, 21, 20,
      18, 19, 20, 20,
      21, 22, 22, 21,
      20, 20, 19, 19,
      18, 18, 17, 12,
      14, 10, 16, 11,
      12, 14, 15, 16,
      17, 18, 16.3,
    ],
    milestones: [
      { i: 33, ru: 'Резкий рост региональной напряжённости', uk: 'Різке зростання регіональної напруженості', en: 'Sharp rise in regional tension' },
      { i: 35, ru: 'Первый прямой обмен ударами, апрель 2024', uk: 'Перший прямий обмін ударами, квітень 2024', en: 'First direct exchange of strikes, April 2024' },
      { i: 37, ru: 'Второй прямой обмен ударами, октябрь 2024', uk: 'Другий прямий обмін ударами, жовтень 2024', en: 'Second direct exchange of strikes, October 2024' },
    ],
  },

  /* ─── Китай — Тайвань ──────────────────────────────
     Конфликт ниже порога войны: индекс держится в «пате», считать нечего
     в терминах боевых действий — и именно поэтому ценен риск, а не индекс.
     startDate нет: счётчик дней войны здесь был бы враньём. */
  'cn-tw': {
    id: 'cn-tw', kind: 'dyad', theatre: null,
    name_ru: 'Китай — Тайвань', name_uk: 'Китай — Тайвань', name_en: 'China — Taiwan',
    short_ru: 'Китай — Тайвань', short_uk: 'Китай — Тайвань', short_en: 'China — Taiwan',
    now: 44.1, weekAgo: 44.8, monthAgo: 45.2,
    escalationRisk: 38,
    updatedAt: '2026-08-04T09:40:00+03:00',
    sourcesLive: 24, eventsLast24h: 73,

    axes: [
      { id: 'diplomacy', value: 48, delta: -1.4 },
      { id: 'combat',    value: 40, delta: -0.9 },
      { id: 'human',     value: 55, delta:  0.0 },
      { id: 'economy',   value: 42, delta: -0.5 },
      { id: 'rhetoric',  value: 36, delta: -2.2 },
    ],

    divergence: {
      words: 33, deeds: 47, lagDays: 44,
      history: [
        -8, -9, -10, -8, -7, -9, -11, -12, -10, -9, -11, -13,
        -12, -10, -11, -13, -14, -12, -11, -13, -15, -14, -13, -14,
      ],
    },

    chokepoints: [
      { id: 'taiwan-strait', share: 20, unit: 'trade', sensitivity: 58,
        name_ru: 'Тайваньский пролив', name_uk: 'Тайванська протока', name_en: 'Taiwan Strait' },
      { id: 'advanced-chips', share: 90, unit: 'chips', sensitivity: 72,
        unitLabel_ru: 'передовая логика', unitLabel_uk: 'передова логіка', unitLabel_en: 'advanced logic',
        name_ru: 'Производство передовых микросхем', name_uk: 'Виробництво передових мікросхем', name_en: 'Advanced chip fabrication' },
    ],

    factors: [
      { date: '2026-08-03', axis: 'combat', impact: -0.8, sources: 19, confidence: 'high', signal: 'news',
        ru: 'Рост числа пересечений срединной линии пролива за отчётные сутки',
        uk: 'Зростання кількості перетинів серединної лінії протоки за звітну добу',
        en: 'More median-line crossings recorded over the reporting day' },
      { date: '2026-08-02', axis: 'economy', impact: +0.6, sources: 11, confidence: 'high', signal: 'market',
        ru: 'Ставки страхования грузов на маршруте через пролив без изменений',
        uk: 'Ставки страхування вантажів на маршруті через протоку без змін',
        en: 'Cargo insurance rates on the strait route unchanged' },
      { date: '2026-07-31', axis: 'rhetoric', impact: -1.3, sources: 22, confidence: 'high', signal: 'news',
        ru: 'Ужесточение формулировок в официальных заявлениях по статусу острова',
        uk: 'Жорсткіші формулювання в офіційних заявах щодо статусу острова',
        en: 'Harder wording in official statements on the island’s status' },
      { date: '2026-07-28', axis: 'diplomacy', impact: +0.5, sources: 7, confidence: 'medium', signal: 'tender',
        ru: 'Опубликованы контракты на расширение портовой инфраструктуры в регионе',
        uk: 'Опубліковано контракти на розширення портової інфраструктури в регіоні',
        en: 'Contracts published for expanding regional port infrastructure' },
    ],

    seriesFrom: '2015-07', seriesStep: 'quarter', syntheticFrom: 40,
    series: [
      58, 57,
      56, 55, 54, 53,
      52, 52, 51, 51,
      50, 50, 49, 49,
      48, 48, 47, 46,
      45, 44, 44, 43,
      43, 42, 42, 41,
      42, 41, 36, 38,
      39, 40, 41, 40,
      41, 42, 41, 42,
      43, 43, 44, 44,
      44, 45, 44.1,
    ],
    milestones: [
      { i: 2,  ru: 'Смена администрации на Тайване, январь 2016', uk: 'Зміна адміністрації на Тайвані, січень 2016', en: 'Change of administration in Taiwan, January 2016' },
      { i: 28, ru: 'Визит спикера Палаты представителей США и последовавшие учения, август 2022', uk: 'Візит спікерки Палати представників США і подальші навчання, серпень 2022', en: 'Visit by the US House Speaker and the exercises that followed, August 2022' },
      { i: 34, ru: 'Выборы на Тайване, январь 2024', uk: 'Вибори на Тайвані, січень 2024', en: 'Elections in Taiwan, January 2024' },
    ],
  },
};

/* ─── Театры ────────────────────────────────────────── */

const THEATRES = {
  iran: {
    id: 'iran',
    name_ru: 'Иран и его противники', name_uk: 'Іран та його опоненти', name_en: 'Iran and its adversaries',
    short_ru: 'Иран — театр', short_uk: 'Іран — театр', short_en: 'Iran — theatre',
    dyads: ['us-ir', 'il-ir'],
    /* Связанность: доля событий в одной диаде, вызывающих отклик в другой
       в течение 72 часов. Считается из данных, не назначается. */
    coupling: 0.72,
    updatedAt: '2026-08-04T09:40:00+03:00',
    note_ru: 'Одна сторона общая, но каналы разные: у Вашингтона и Тегерана есть непрямой переговорный трек, у Иерусалима и Тегерана его нет. Усреднять эти две диады в одно число — значит стереть ровно ту разницу, ради которой индекс и нужен.',
    note_uk: 'Одна сторона спільна, але канали різні: у Вашингтона й Тегерана є непрямий переговорний трек, у Єрусалима й Тегерана його немає. Усереднювати ці дві діади в одне число — означає стерти саме ту різницю, заради якої індекс і потрібен.',
    note_en: 'One party is shared, but the channels are not: Washington and Tehran have an indirect negotiating track, Jerusalem and Tehran do not. Averaging these two dyads into one number erases exactly the difference the index exists to show.',
  },
};

/* ─── Матрица связанности ───────────────────────────────
   ρ(A,B) — доля событий в A, вызвавших событие с |impact| > 1 в B
   в течение 72 часов. Скользящее окно 180 дней. Симметрична по построению:
   считается по объединению обоих направлений.
   Связи есть и между театрами — рынки энергоносителей и логистика
   переносят возмущение через полмира. Это и делает матрицу интересной. */
const COUPLING = {
  order: ['ru-ua', 'us-ir', 'il-ir', 'cn-tw'],
  m: {
    'ru-ua': { 'ru-ua': 1,    'us-ir': 0.21, 'il-ir': 0.14, 'cn-tw': 0.19 },
    'us-ir': { 'ru-ua': 0.21, 'us-ir': 1,    'il-ir': 0.72, 'cn-tw': 0.16 },
    'il-ir': { 'ru-ua': 0.14, 'us-ir': 0.72, 'il-ir': 1,    'cn-tw': 0.09 },
    'cn-tw': { 'ru-ua': 0.19, 'us-ir': 0.16, 'il-ir': 0.09, 'cn-tw': 1    },
  },
};

/* Порядок в переключателе. type: 'conflict' | 'theatre' */
const VIEWS = [
  { type: 'conflict', id: 'ru-ua' },
  { type: 'theatre',  id: 'iran' },
  { type: 'conflict', id: 'us-ir', nested: true },
  { type: 'conflict', id: 'il-ir', nested: true },
  { type: 'conflict', id: 'cn-tw' },
];

/* Шкала: границы зон */
