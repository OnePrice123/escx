# ESCX — Escalation Index

Индекс эскалации конфликтов между государствами: фаза, накал, темп и вероятность
перехода на следующую ступень — из открытых данных, по опубликованной методологии,
с раскрытием каждого числа до исходного события.

---

## Быстрый старт

```bash
# 1. тесты сборщика данных — сеть не нужна
python3 ingest/tests/test_offline.py
python3 ingest/tests/test_llm_offline.py

# 2. посмотреть дизайн-язык и прототипы — просто открыть в браузере
open design/styleguide.html     # витрина дизайна, три оттенка
open design/demo.html           # минимальный пример: tokens.css + escx-ui.js
open web/prototype.html         # кликабельный прототип
open web/schema.html            # вся система на одной странице

# 3. собрать первые данные
cd ingest
python3 -m escx.cli init
python3 -m escx.cli backfill-ucdp --start 2024-01-01 --end 2024-12-31
python3 -m escx.cli status
```

Зависимостей нет — только стандартная библиотека Python 3.11+.

---

## Что где лежит

| Папка | Содержимое |
|---|---|
| `docs/` | Пять документов. Читать по порядку номеров |
| `design/` | `tokens.css` и `escx-ui.js` — дизайн-язык в коде. `styleguide.html` — витрина |
| `web/` | Прототипы интерфейса |
| `ingest/` | Сборщик данных: UCDP, GDELT, санкции, GPR + LLM-извлечение |
| `.github/` | Ежечасный и ежедневный прогоны, тесты на push |

### Документы

1. **Методология** — фазы, накал, темп, вероятности, глобальный индекс, восемь правил
   против «пальца в небо»
2. **Бизнес-план** — рынок, конкуренты, тарифы, юнит-экономика, риски, план на 24 недели
3. **Техплан** — архитектура, модель данных, пайплайн, дизайн-система, роадмап
4. **Сбор данных** — источники, инструменты, лимиты, пять ловушек
5. **ИИ в контуре** — где помогает, где вредит, правило допуска индикатора

---

## Дизайн-язык «Тепло»

Структуру держат не линии, а свет. Данные не раскрашиваются — поверхность теплеет.

```html
<html data-tint="sand">          <!-- sand | ash | clay -->
<link rel="stylesheet" href="design/tokens.css">
```

```html
<script src="design/escx-ui.js"></script>
```
```js
gaugeEl.innerHTML = ESCX.lightArc(64, { id: 'global' });
rowEl.style.setProperty('--heat', ESCX.heatWash(79));
sparkEl.innerHTML  = ESCX.sparkWash(series);
```

Обычный `<script>`, а не ES-модуль — намеренно: модули не работают по `file://`
из-за CORS, а страницы здесь должны открываться двойным кликом, без сервера и сборки.
Проверить: откройте `design/demo.html`.

---

## Состояние

Проектирование завершено, реализация не начата. Веб-приложения ещё нет — есть прототипы
и рабочий сборщик данных. Ближайшая задача: перевести `web/prototype.html` на дизайн-язык
из `design/`.

Контекст для Claude Code — в `CLAUDE.md`.

---

## Источники и лицензии

Проект использует открытые данные: [UCDP](https://ucdp.uu.se/),
[GDELT](https://www.gdeltproject.org/), [GPR Index](https://www.matteoiacoviello.com/gpr.htm)
(CC BY), [SIPRI](https://www.sipri.org/), публичные санкционные реестры,
[голосования ГА ООН](https://digitallibrary.un.org/collection/Voting%20Data).
Бенчмарк прогнозов — [VIEWS](https://viewsforecasting.org/) (Uppsala/PRIO).

[ACLED](https://acleddata.com/contentusage) **не используется**: их условия запрещают
проекты этого типа. См. `CLAUDE.md`, инвариант 4.
