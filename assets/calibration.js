/* ═══════════════════════════════════════════════════════════
   Стенд калибровки: завершившиеся конфликты

   ЧТО ЗДЕСЬ РЕАЛЬНО:
     даты, названия соглашений, тип исхода, сорвавшиеся договорённости.
     Это ground truth — проверяемый набор для обратного прогона.

   ЧТО ЗДЕСЬ МОДЕЛЬНОЕ:
     сами кривые индекса. Реальный прогон по историческим источникам
     ещё не выполнялся. Процедура описана в docs/06-kalibrovka.md.

   Формат: 36 помесячных значений, последнее = месяц разрешения конфликта.
   marks: { i, type } — 'failed' сорвавшаяся договорённость внутри окна.
   Порог сигнала — 50 (переход из «пата» в «деэскалацию»).
   ═══════════════════════════════════════════════════════════ */

const CAL_THRESHOLD = 50;

const CALIBRATION = [
  {
    id: 'bosnia',
    name_ru: 'Босния и Герцеговина', name_uk: 'Боснія і Герцеговина', name_en: 'Bosnia and Herzegovina',
    years: '1992—1995', outcome: 'negotiated',
    accord_ru: 'Дейтонские соглашения · 14.12.1995',
    accord_uk: 'Дейтонські угоди · 14.12.1995',
    accord_en: 'Dayton Accords · 14 Dec 1995',
    from: '1993-01',
    series: [
      22,20,19,18,21,20,18,17,19,21,23,25,
      28,32,34,31,29,27,30,28,26,24,22,20,
      18,16,15,14,16,18,15,14,38,52,66,74,
    ],
    marks: [],
  },
  {
    id: 'nireland',
    name_ru: 'Северная Ирландия', name_uk: 'Північна Ірландія', name_en: 'Northern Ireland',
    years: '1968—1998', outcome: 'negotiated',
    accord_ru: 'Белфастское соглашение · 10.04.1998',
    accord_uk: 'Белфастська угода · 10.04.1998',
    accord_en: 'Belfast Agreement · 10 Apr 1998',
    from: '1995-05',
    series: [
      66,64,63,62,60,61,60,58,
      55,52,38,36,35,34,36,33,35,37,38,40,
      42,44,46,48,50,52,54,58,62,64,66,68,
      72,74,76,80,
    ],
    marks: [{ i: 10, type: 'failed', ru: 'Срыв перемирия, февраль 1996', uk: 'Зрив перемир’я, лютий 1996', en: 'Ceasefire collapse, Feb 1996' }],
  },
  {
    id: 'elsalvador',
    name_ru: 'Сальвадор', name_uk: 'Сальвадор', name_en: 'El Salvador',
    years: '1979—1992', outcome: 'negotiated',
    accord_ru: 'Чапультепекские соглашения · 16.01.1992',
    accord_uk: 'Чапультепекські угоди · 16.01.1992',
    accord_en: 'Chapultepec Peace Accords · 16 Jan 1992',
    from: '1989-02',
    series: [
      22,24,23,25,26,28,27,29,30,32,28,
      30,32,34,36,35,37,38,40,42,44,43,45,
      46,48,50,52,54,53,55,58,60,62,66,70,
    ],
    marks: [],
  },
  {
    id: 'guatemala',
    name_ru: 'Гватемала', name_uk: 'Гватемала', name_en: 'Guatemala',
    years: '1960—1996', outcome: 'negotiated',
    accord_ru: 'Соглашение о прочном мире · 29.12.1996',
    accord_uk: 'Угода про міцний мир · 29.12.1996',
    accord_en: 'Accord for a Firm and Lasting Peace · 29 Dec 1996',
    from: '1994-01',
    series: [
      30,32,34,36,35,37,38,40,39,41,42,40,
      42,44,43,45,46,48,47,49,50,52,54,53,
      55,58,60,62,64,66,68,70,72,74,76,80,
    ],
    marks: [],
  },
  {
    id: 'mozambique',
    name_ru: 'Мозамбик', name_uk: 'Мозамбік', name_en: 'Mozambique',
    years: '1977—1992', outcome: 'negotiated',
    accord_ru: 'Римское общее соглашение · 04.10.1992',
    accord_uk: 'Римська загальна угода · 04.10.1992',
    accord_en: 'Rome General Peace Accords · 4 Oct 1992',
    from: '1989-11',
    series: [
      24,26,
      28,30,32,34,33,35,36,38,37,39,40,42,
      41,43,44,46,45,47,46,48,47,49,48,50,
      52,54,56,58,60,64,68,72,76,82,
    ],
    marks: [],
  },
  {
    id: 'angola',
    name_ru: 'Ангола', name_uk: 'Ангола', name_en: 'Angola',
    years: '1975—2002', outcome: 'military',
    accord_ru: 'Луэнский меморандум · 04.04.2002',
    accord_uk: 'Луенський меморандум · 04.04.2002',
    accord_en: 'Luena Memorandum · 4 Apr 2002',
    note_ru: 'Ранее сорвались Бисесские соглашения (1991) и Лусакский протокол (1994) — вне окна',
    note_uk: 'Раніше зірвалися Бісесські угоди (1991) і Лусакський протокол (1994) — поза вікном',
    note_en: 'The Bicesse Accords (1991) and Lusaka Protocol (1994) both collapsed — outside the window',
    from: '1999-05',
    series: [
      14,13,13,15,16,16,17,17,
      18,19,19,20,21,22,22,23,24,24,25,26,
      27,28,28,29,30,30,31,32,32,33,34,36,
      40,62,74,84,
    ],
    marks: [],
  },
  {
    id: 'sierraleone',
    name_ru: 'Сьерра-Леоне', name_uk: 'Сьєрра-Леоне', name_en: 'Sierra Leone',
    years: '1991—2002', outcome: 'negotiated',
    accord_ru: 'Объявление об окончании войны · 18.01.2002',
    accord_uk: 'Оголошення про завершення війни · 18.01.2002',
    accord_en: 'Declaration of the end of the war · 18 Jan 2002',
    from: '1999-02',
    series: [
      20,22,26,34,48,58,60,56,52,48,44,
      34,26,22,20,24,28,32,36,40,44,48,50,
      54,56,58,60,62,64,66,68,70,72,74,80,
    ],
    marks: [{ i: 5, type: 'failed', ru: 'Ломейское соглашение сорвалось, 1999', uk: 'Ломейська угода зірвалася, 1999', en: 'Lomé Accord collapsed, 1999' }],
  },
  {
    id: 'liberia',
    name_ru: 'Либерия', name_uk: 'Ліберія', name_en: 'Liberia',
    years: '1999—2003', outcome: 'negotiated',
    accord_ru: 'Аккрское соглашение · 18.08.2003',
    accord_uk: 'Аккрська угода · 18.08.2003',
    accord_en: 'Accra Peace Agreement · 18 Aug 2003',
    from: '2000-09',
    series: [
      22,21,20,20,
      19,18,18,17,17,18,18,19,19,20,20,21,
      20,19,18,17,16,16,17,18,19,20,22,24,
      26,28,32,38,44,50,62,78,
    ],
    marks: [],
  },
  {
    id: 'nepal',
    name_ru: 'Непал', name_uk: 'Непал', name_en: 'Nepal',
    years: '1996—2006', outcome: 'negotiated',
    accord_ru: 'Всеобъемлющее мирное соглашение · 21.11.2006',
    accord_uk: 'Всеосяжна мирна угода · 21.11.2006',
    accord_en: 'Comprehensive Peace Accord · 21 Nov 2006',
    from: '2003-12',
    series: [
      34,
      30,28,26,24,22,20,22,24,26,24,22,20,
      18,16,15,14,16,18,20,22,26,30,36,42,
      46,52,56,60,64,68,70,72,74,76,84,
    ],
    marks: [],
  },
  {
    id: 'aceh',
    name_ru: 'Ачех, Индонезия', name_uk: 'Ачех, Індонезія', name_en: 'Aceh, Indonesia',
    years: '1976—2005', outcome: 'negotiated',
    accord_ru: 'Хельсинкский меморандум · 15.08.2005',
    accord_uk: 'Гельсінський меморандум · 15.08.2005',
    accord_en: 'Helsinki Memorandum · 15 Aug 2005',
    note_ru: 'Перелом связан с внешним шоком — цунами 26.12.2004',
    note_uk: 'Перелом пов’язаний із зовнішнім шоком — цунамі 26.12.2004',
    note_en: 'The turn followed an external shock — the tsunami of 26 Dec 2004',
    from: '2002-09',
    series: [
      30,34,40,52,
      54,44,30,22,18,16,15,14,14,15,15,16,
      16,17,17,18,18,19,19,20,20,21,22,40,
      48,56,60,64,68,72,76,82,
    ],
    marks: [{ i: 3, type: 'failed', ru: 'Соглашение о прекращении огня сорвалось, 2003', uk: 'Угода про припинення вогню зірвалася, 2003', en: 'Cessation of hostilities agreement collapsed, 2003' }],
  },
  {
    id: 'srilanka',
    name_ru: 'Шри-Ланка', name_uk: 'Шрі-Ланка', name_en: 'Sri Lanka',
    years: '1983—2009', outcome: 'military',
    accord_ru: 'Окончание боевых действий · 18.05.2009',
    accord_uk: 'Завершення бойових дій · 18.05.2009',
    accord_en: 'End of hostilities · 18 May 2009',
    note_ru: 'Перемирие 2002 года при посредничестве Норвегии сорвалось — вне окна',
    note_uk: 'Перемир’я 2002 року за посередництва Норвегії зірвалося — поза вікном',
    note_en: 'The Norwegian-brokered 2002 ceasefire collapsed — outside the window',
    from: '2006-06',
    series: [
      24,20,18,16,15,14,14,
      13,13,12,12,12,11,11,11,10,10,10,10,
      10,9,9,9,8,8,8,7,7,7,6,6,
      6,5,5,6,10,
    ],
    marks: [],
  },
  {
    id: 'karabakh',
    name_ru: 'Нагорный Карабах', name_uk: 'Нагірний Карабах', name_en: 'Nagorno-Karabakh',
    years: '2020', outcome: 'ceasefire',
    accord_ru: 'Трёхстороннее заявление · 10.11.2020',
    accord_uk: 'Тристороння заява · 10.11.2020',
    accord_en: 'Trilateral statement · 10 Nov 2020',
    from: '2017-12',
    series: [
      36,
      36,37,38,38,39,40,40,39,38,38,37,36,
      36,35,35,34,34,33,33,32,32,31,31,30,
      30,29,28,26,24,22,20,18,12,10,58,
    ],
    marks: [],
  },
  {
    id: 'tigray',
    name_ru: 'Эфиопия — Тыграй', name_uk: 'Ефіопія — Тиграй', name_en: 'Ethiopia — Tigray',
    years: '2020—2022', outcome: 'negotiated',
    accord_ru: 'Преторийское соглашение · 02.11.2022',
    accord_uk: 'Преторійська угода · 02.11.2022',
    accord_en: 'Pretoria Agreement · 2 Nov 2022',
    from: '2019-12',
    series: [
      40,
      38,36,34,32,30,28,26,24,20,16,12,10,
      10,11,12,14,16,18,14,12,10,10,11,12,
      14,16,20,24,22,18,14,12,20,46,68,
    ],
    marks: [],
  },
  {
    id: 'colombia',
    name_ru: 'Колумбия — FARC', name_uk: 'Колумбія — FARC', name_en: 'Colombia — FARC',
    years: '1964—2016', outcome: 'negotiated',
    accord_ru: 'Итоговое соглашение · 24.11.2016',
    accord_uk: 'Підсумкова угода · 24.11.2016',
    accord_en: 'Final Peace Agreement · 24 Nov 2016',
    from: '2013-12',
    series: [
      44,
      45,46,46,47,48,48,49,50,50,51,52,52,
      53,50,48,46,48,52,56,60,62,64,66,68,
      70,72,74,76,78,80,82,84,86,58,88,
    ],
    marks: [{ i: 34, type: 'failed', ru: 'Первая редакция отклонена на референдуме, 02.10.2016', uk: 'Першу редакцію відхилено на референдумі, 02.10.2016', en: 'First version rejected by referendum, 2 Oct 2016' }],
  },
  {
    id: 'iraniraq',
    name_ru: 'Иран — Ирак', name_uk: 'Іран — Ірак', name_en: 'Iran — Iraq',
    years: '1980—1988', outcome: 'ceasefire',
    accord_ru: 'Прекращение огня по резолюции 598 · 20.08.1988',
    accord_uk: 'Припинення вогню за резолюцією 598 · 20.08.1988',
    accord_en: 'Ceasefire under UNSC Resolution 598 · 20 Aug 1988',
    from: '1985-09',
    series: [
      16,15,14,14,
      13,12,12,11,11,12,12,13,13,12,12,11,
      11,12,13,14,15,16,18,20,22,24,26,28,
      30,32,28,24,26,34,52,74,
    ],
    marks: [],
  },
  {
    id: 'eritrea',
    name_ru: 'Эритрея — Эфиопия', name_uk: 'Еритрея — Ефіопія', name_en: 'Eritrea — Ethiopia',
    years: '1998—2000', outcome: 'negotiated',
    accord_ru: 'Алжирское соглашение · 12.12.2000',
    accord_uk: 'Алжирська угода · 12.12.2000',
    accord_en: 'Algiers Agreement · 12 Dec 2000',
    from: '1998-01',
    series: [
      44,30,22,20,24,28,30,32,34,36,34,32,
      30,26,20,18,22,26,30,32,34,32,30,28,
      26,22,16,14,18,24,40,52,58,62,66,80,
    ],
    marks: [],
  },
];

/* Опережение сигнала: за сколько месяцев до разрешения индекс перешёл порог
   и уже не опускался ниже. null — сигнала не было. */
function leadMonths(c) {
  const s = c.series, last = s.length - 1;
  let i = last;
  while (i >= 0 && s[i] >= CAL_THRESHOLD) i--;
  const cross = i + 1;
  return cross > last ? null : last - cross;
}
