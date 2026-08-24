"""Обратный прогон: проверка индекса на конфликтах с известным исходом.

Единственный способ отличить улучшение метода от самообмана. Пока индекс не
проверен на конфликтах, которые уже закончились, любые рассуждения о его
точности непроверяемы.

ЧТО ИМЕННО ПРОВЕРЯЕТСЯ. Только кинетический блок. У него история с 1989 года
(UCDP GED), и этого хватает. Инфополе, дипломатию и экономику задним числом
проверить нечем: GDELT в базе за последние месяцы, голосования ООН годовые,
санкционные списки состояния на сегодня. Заявлять калибровку всего индекса,
проверив четверть, было бы ровно тем подлогом, против которого весь проект.

ПРО МЕТРИКУ ОПЕРЕЖЕНИЯ — самое важное здесь.

Наивная метрика «первый месяц, когда индекс выше порога» даёт бессмысленные
ответы: у конфликта, который все три года шёл на высокой интенсивности, она
покажет «сигнал за 36 месяцев», хотя никакого сигнала не было — был фон.
Проверено на живых данных: так вели себя Сьерра-Леоне и Сальвадор.

Поэтому сигналом считается ПЕРЕХОД: индекс обязан сначала побывать НИЖЕ
порога, потом подняться выше и не вернуться. Ряд, начинающийся выше порога,
перехода не содержит, и честный ответ по нему — «фон выше порога», а не число.
"""
from __future__ import annotations
import json
import math
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

from .indicators import MAD_K, Z_CAP, heat, winsorize

CONFIG = Path(__file__).resolve().parent.parent / "config" / "calibration.json"

WINDOW_M = 36          # окно наблюдения до развязки, месяцев
REF_TAIL_M = 6         # хвост, исключённый из опоры: иначе всплеск сам себя нормирует
THRESHOLD = 65.0       # порог сигнала по шкале накала


def load_set(path: Path | None = None) -> list[dict]:
    p = path or CONFIG
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("conflicts", [])


def monthly_fatalities(con, conflict_id: str) -> dict[str, int]:
    """Боевые смерти по месяцам для одного конфликта UCDP."""
    out: dict[str, int] = defaultdict(int)
    for r in con.execute("SELECT occurred_at, fatalities, payload FROM raw_events "
                         "WHERE source='ucdp_ged'"):
        p = json.loads(r["payload"] or "{}")
        if p.get("conflict_new_id") != conflict_id:
            continue
        out[r["occurred_at"][:7]] += r["fatalities"] or 0
    return dict(out)


def window_months(resolved: str, months: int = WINDOW_M) -> list[str]:
    d = date.fromisoformat(resolved)
    out = []
    for k in range(months, -1, -1):
        y, m = d.year, d.month - k
        while m <= 0:
            m += 12
            y -= 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def heat_series(fat_by_month: dict[str, int], months: list[str]) -> list[float]:
    """Накал по месяцам окна. Опора — те же медиана и MAD, что в проде."""
    vals = [fat_by_month.get(m, 0) for m in months]
    ref = vals[:-REF_TAIL_M] or vals
    med = st.median(ref)
    mad = st.median([abs(v - med) for v in ref])
    if mad == 0:
        sd = st.pstdev(ref)
        mad = sd / MAD_K if sd else 0.0
    out = []
    for v in vals:
        z = 0.0 if not mad else max(-Z_CAP, min(Z_CAP, (v - med) / (MAD_K * mad)))
        out.append(heat({"kinetic": z}))
    return out


def lead_months(series: list[float], threshold: float = THRESHOLD) -> tuple[int | None, str]:
    """За сколько месяцев до развязки индекс ВПЕРВЫЕ перешёл порог снизу вверх.

    Две ошибки, которые здесь легко сделать, и обе были сделаны и исправлены
    на живых данных.

    Первая: считать сигналом просто «индекс выше порога». Тогда конфликт,
    все три года шедший на высокой интенсивности, получает «опережение
    36 месяцев», хотя никакого сигнала не было — был фон. Поэтому требуется
    именно ПЕРЕХОД: ряд обязан сначала побывать ниже порога.

    Вторая: требовать «перехода без возврата ниже». Для живого индекса это
    разумно, для обратного прогона — невыполнимо: развязка и означает, что
    бои прекратились, поэтому к месяцу соглашения накал закономерно падает.
    По этому условию не проходил ни один конфликт с пиком 85.

    Возвращается (опережение, КЛЮЧ пояснения). None означает отсутствие
    перехода, и ключ говорит, какого именно: фон уже был выше порога или
    порог не достигался вовсе. Схлопывать эти случаи в одно «сигнала нет»
    нельзя — они означают разное. Ключ, а не готовая фраза: словами его
    называет витрина, и на каждом из шестнадцати языков по-своему.
    """
    if not series:
        return None, "noData"
    if series[0] >= threshold:
        return None, "background"
    for i in range(1, len(series)):
        if series[i - 1] < threshold <= series[i]:
            back = all(v >= threshold for v in series[i:])
            return len(series) - 1 - i, "crossed" if back else "crossedBack"
    return None, "notReached"


HORIZON_M = 36         # за сколько месяцев после сигнала развязка ещё считается «той самой»


def all_months(fat: dict[str, int]) -> list[str]:
    """Все месяцы от первого события до последнего, без пропусков."""
    if not fat:
        return []
    lo, hi = min(fat), max(fat)
    y, m = int(lo[:4]), int(lo[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hi:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def crossings(series: list[float], threshold: float = THRESHOLD) -> list[int]:
    """Индексы всех переходов порога снизу вверх."""
    return [i for i in range(1, len(series))
            if series[i - 1] < threshold <= series[i]]


def control(con, path: Path | None = None) -> dict:
    """Ложные срабатывания: переходы порога, за которыми развязки НЕ последовало.

    Без этого счёта «сигнал у 16 из 19» не значит почти ничего. Метрика,
    которая срабатывает перед каждым урегулированием и заодно ещё двадцать раз
    посреди войны, бесполезна — а по одним только попаданиям это неотличимо.

    Контроль берётся из тех же конфликтов, но по ВСЕЙ их истории, а не по окну
    перед развязкой. Каждый переход порога проверяется на то, наступила ли
    известная развязка в течение HORIZON_M месяцев после него. Не наступила —
    ложная тревога.

    Ограничение, которое надо назвать: развязка известна только одна на
    конфликт, поэтому ранние переходы в длинных войнах почти неизбежно
    попадают в ложные. Это делает оценку ПЕССИМИСТИЧНОЙ, и лучше так, чем
    наоборот.
    """
    hits = false = 0
    per = []
    for c in load_set(path):
        fat = monthly_fatalities(con, c["conflict_id"])
        months = all_months(fat)
        if len(months) < 12:
            continue
        hs = heat_series(fat, months)
        res = c["resolved"][:7]
        h = f = 0
        for i in crossings(hs):
            # развязка попадает в горизонт после сигнала?
            y, m = int(months[i][:4]), int(months[i][5:7])
            m += HORIZON_M
            y += (m - 1) // 12
            m = (m - 1) % 12 + 1
            if months[i] <= res <= f"{y:04d}-{m:02d}":
                h += 1
            else:
                f += 1
        hits += h
        false += f
        per.append({"name": c["name"], "months": len(months),
                    "crossings": h + f, "hits": h, "false": f})
    total = hits + false
    return {"conflicts": per, "crossings": total, "hits": hits, "false": false,
            "precision": (hits / total) if total else None,
            "horizon_m": HORIZON_M}


def deep_scale(fatalities: float) -> float:
    """Логарифм боевых смертей за месяц.

    Потери распределены с тяжёлым хвостом: у одной и той же пары бывает ноль,
    двадцать и сто тысяч в месяц. В линейной шкале такой ряд сжимается в две
    ступени — «война» и «не война», — и всё между ними теряется. Проверено на
    России с Украиной: без логарифма весь Донбасс 2014-2021 годов, где счёт шёл
    на тысячи, читался ровно как спокойный 2010-й.

    log1p, а не log: месяцев с нулём большинство, и они обязаны остаться нулём,
    а не уйти в минус бесконечность.
    """
    return math.log1p(max(0.0, fatalities))


def deep_reference(con) -> tuple[float, float]:
    """Общая опора для глубоких графиков: медиана и MAD по ВСЕМ парам сразу.

    Считать опору по собственной истории пары здесь нельзя, и это выяснилось на
    живых данных. У России с Украиной двадцать пять лет нулей до 2014-го: их
    медиана равна нулю, MAD тоже, и в пересчёте война 2022 года с девяноста
    девятью тысячами погибших давала накал 50 — ровно столько же, сколько
    спокойный 2010-й. Своя история как мера работает на коротком окне, где она
    описывает «норму пары», и разваливается на длинном, где нормы просто нет.

    Общая опора делает глубокий график сравнимым и во времени, и между парами:
    сто тысяч погибших за месяц читаются как много при любом прошлом.
    """
    vals: list[float] = []
    for r in con.execute(
            "SELECT dyad_id, substr(occurred_at,1,7) m, SUM(fatalities) f "
            "FROM raw_events WHERE dyad_id IS NOT NULL AND source LIKE 'ucdp%' "
            "GROUP BY dyad_id, m"):
        vals.append(deep_scale(float(r["f"] or 0)))
    if len(vals) < 8:
        return (0.0, 0.0)
    v = winsorize(vals)
    med = st.median(v)
    mad = st.median([abs(x - med) for x in v])
    if mad == 0:
        sd = st.pstdev(v)
        mad = sd / MAD_K if sd else 0.0
    return (med, mad)


def dyad_deep_history(con, dyad_id: str,
                      ref: tuple[float, float] | None = None
                      ) -> tuple[list[str], list[float]]:
    """Помесячная история накала по паре за всю глубину UCDP.

    Отдельный путь, а не расширение суточного расчёта: посуточно на тридцать
    шесть лет это под четверть миллиона строк на двадцать пар, и считается
    минутами. Помесячно — четыреста точек на пару, доли секунды.

    Считается ТОЛЬКО кинетика: медиапоток начинается там, где начался сбор,
    голосования в ООН годовые, санкции — состояние на сегодня. Глубокий график
    показывает историю боевых действий, и подписывать его надо именно так.

    Для пары без событий UCDP возвращается пусто — у Китая с Тайванем боевых
    смертей в выгрузке нет вовсе, и рисовать им прямую на пятьдесят значило бы
    выдать отсутствие войны за измеренное спокойствие.
    """
    fat: dict[str, int] = {}
    for r in con.execute(
            "SELECT occurred_at, fatalities FROM raw_events "
            "WHERE dyad_id=? AND source LIKE 'ucdp%' AND occurred_at IS NOT NULL",
            (dyad_id,)):
        m = r["occurred_at"][:7]
        fat[m] = fat.get(m, 0) + (r["fatalities"] or 0)
    if not fat:
        return [], []

    # Ряд начинается НЕ с первого события пары, а с начала покрытия UCDP.
    # Разница принципиальная: у России с Украиной первое боевое событие
    # датировано мартом 2014-го, и если начать с него, график покажет войну
    # как данность. А UCDP покрывает весь мир с 1989 года, значит ноль событий
    # в 2010-м — это ИЗМЕРЕННОЕ спокойствие, а не отсутствие данных. Именно оно
    # и отвечает на вопрос «как к этому шло».
    first = con.execute(
        "SELECT MIN(occurred_at) a FROM raw_events WHERE source LIKE 'ucdp%'"
    ).fetchone()["a"]
    last = max(fat)
    if first:
        fat.setdefault(first[:7], 0)
    months = all_months(fat)
    if len(months) < 24:
        return [], []

    med, mad = ref if ref else deep_reference(con)
    out = []
    for m in months:
        v = deep_scale(fat.get(m, 0))
        z = 0.0 if not mad else max(-Z_CAP, min(Z_CAP, (v - med) / (MAD_K * mad)))
        out.append(heat({"kinetic": z}))
    return months, out


def run(con, path: Path | None = None) -> dict:
    rows = []
    for c in load_set(path):
        months = window_months(c["resolved"])
        fat = monthly_fatalities(con, c["conflict_id"])
        if not any(fat.get(m) for m in months):
            rows.append({**c, "why": "noEvents", "lead": None})
            continue
        hs = heat_series(fat, months)
        lead, why = lead_months(hs)
        rows.append({**c, "series": [round(x, 1) for x in hs],
                     "peak": round(max(hs), 1), "lead": lead, "why": why})

    leads = [r["lead"] for r in rows if r.get("lead") is not None]
    return {
        "threshold": THRESHOLD, "window_months": WINDOW_M,
        "block": "kinetic",
        "conflicts": rows,
        "n": len(rows),
        "with_signal": len(leads),
        "median_lead": st.median(leads) if leads else None,
    }
