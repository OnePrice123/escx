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
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

from .indicators import MAD_K, Z_CAP, heat

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

    Возвращается (опережение, пояснение). None означает отсутствие перехода,
    и пояснение говорит, какого именно: фон уже был выше порога или порог
    не достигался вовсе. Схлопывать эти случаи в одно «сигнала нет» нельзя —
    они означают разное.
    """
    if not series:
        return None, "нет данных"
    if series[0] >= threshold:
        return None, "фон выше порога — перехода не было"
    for i in range(1, len(series)):
        if series[i - 1] < threshold <= series[i]:
            back = "" if all(v >= threshold for v in series[i:]) else ", с возвратом"
            return len(series) - 1 - i, "переход" + back
    return None, "порог не достигнут"


def run(con, path: Path | None = None) -> dict:
    rows = []
    for c in load_set(path):
        months = window_months(c["resolved"])
        fat = monthly_fatalities(con, c["conflict_id"])
        if not any(fat.get(m) for m in months):
            rows.append({**c, "note": "нет событий в окне", "lead": None})
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
