"""Расчёт индикаторов и робастная нормализация.

Здесь реализована формула из раздела 4 методологии: медиана и MAD вместо среднего
и стандартного отклонения. Причина: у конфликтных рядов тяжёлые хвосты, одно
крупное событие сдвигает среднее так, что все последующие значения выглядят
нормальными. Медиана этого не делает.
"""
from __future__ import annotations
import math, statistics as st
from collections import defaultdict
from datetime import date, timedelta

MAD_K = 1.4826            # приводит MAD к масштабу стандартного отклонения

# Предел z-оценки. Робастный z в 174 не означает конец света — он означает, что
# опорная величина выродилась: при короткой истории MAD уходит в 0.00004, и любое
# ненулевое значение делится почти на ноль. Именно так Россия — Украина оказалась
# ровно на 100 при фазе 5 из 7. Обрезка ловит вырождение и не даёт одной паре
# с бедной историей упереть шкалу в потолок.
Z_CAP = 8.0

# Потолок ОТНОСИТЕЛЬНОГО накала. Верхние пять пунктов шкалы зарезервированы за
# абсолютным пределом — применением ядерного оружия (фаза 7). Смысл резерва в
# запасе хода: пара, у которой уже идёт война, обязана иметь куда расти, иначе
# ухудшение конфликта не отражается в числе вовсе. До правки Россия — Украина
# стояла на 100 и не могла сдвинуться ни при каком развитии событий.
HEAT_MAX = 95.0
WINSOR = (0.01, 0.99)


def winsorize(xs: list[float], lo: float = WINSOR[0], hi: float = WINSOR[1]) -> list[float]:
    """Обрезка хвостов по перцентилям.

    Индексы считаются от n-1 и зажимаются в границы — наивная формула
    int(n*lo)-1 при коротком ряде даёт -1 и обрезает всё до максимума.
    Такая ошибка не падает, а молча превращает ряд в константу.
    """
    if not xs:
        return []
    s = sorted(xs)
    n = len(s)
    ia = min(max(round(lo * (n - 1)), 0), n - 1)
    ib = min(max(round(hi * (n - 1)), 0), n - 1)
    a, b = s[ia], s[ib]
    if a > b:
        a, b = b, a
    return [min(max(x, a), b) for x in xs]


def robust_z(x: float, history: list[float]) -> float:
    """z-оценка по медиане и MAD. При вырожденной истории возвращает 0."""
    h = winsorize([v for v in history if v is not None])
    if len(h) < 8:
        return 0.0
    med = st.median(h)
    mad = st.median([abs(v - med) for v in h])
    if mad == 0:
        sd = st.pstdev(h)
        z = 0.0 if sd == 0 else (x - med) / sd
    else:
        z = (x - med) / (MAD_K * mad)
    return max(-Z_CAP, min(Z_CAP, z))


def rolling_counts(events: list[dict], day: date, window: int = 30) -> dict:
    """Кинетика за окно: число событий, погибшие, охват географии.

    Отбрасываются события с date_prec >= 3 (дата известна лишь до месяца/года):
    класть их в 30-дневное окно нельзя, они размажут сигнал по всему периоду.
    """
    lo = day - timedelta(days=window)
    n = fat = 0
    cells = set()
    for e in events:
        if (e.get("date_prec") or 1) >= 3:
            continue
        d = e.get("occurred_at")
        if not d:
            continue
        try:
            ed = date.fromisoformat(d[:10])
        except ValueError:
            continue
        if lo < ed <= day:
            n += 1
            fat += e.get("fatalities") or 0
            if e.get("lat") is not None and e.get("lon") is not None:
                cells.add((round(e["lat"] * 2) / 2, round(e["lon"] * 2) / 2))
    return {"events_30d": n, "fatalities_30d": fat, "geo_cells_30d": len(cells)}


def goldstein_weighted(events: list[dict]) -> float | None:
    """Средний Голдштейн, взвешенный на число упоминаний.

    Взвешивание обязательно: без него одно упоминание в блоге весит столько же,
    сколько сюжет, разошедшийся по тысяче изданий. Это прямое следствие того,
    что Голдштейн — атрибут типа события, а не измеренная интенсивность.
    """
    num = den = 0.0
    for e in events:
        g, m = e.get("goldstein"), e.get("num_mentions") or 1
        if g is not None:
            num += g * m
            den += m
    return (num / den) if den else None


def media_normalized(mentions_dyad: float, mentions_global: float) -> float | None:
    """Доля покрытия диады в мировом потоке — правило 5 методологии.

    Абсолютный объём упоминаний измеряет внимание прессы, а не риск. Нормировка
    на общий объём убирает эффект «крупные сюжеты всегда ярче».
    """
    if not mentions_global:
        return None
    return mentions_dyad / mentions_global


BLOCK_WEIGHTS = {
    "kinetic": 0.35, "military": 0.20, "diplomatic": 0.15,
    "economic": 0.15, "informational": 0.15,
}


def heat(block_z: dict[str, float], scale: float = 1.6) -> float:
    """H = 100 * sigmoid(Σ w·z / scale). Раздел 4.1 методологии.

    scale — параметр калибровки, а не константа. При 1.6 шкала ложится так:
    z=0 -> 50, z=1 -> 65, z=2 -> 78, z=3 -> 87, z=4 -> 92. Начальное значение
    подобрано, чтобы одновременное отклонение всех пяти блоков на 3 MAD давало
    ~87, а не упиралось в потолок. Уточняется вместе с весами блоков в v0.2.
    """
    s = sum(BLOCK_WEIGHTS[k] * max(-Z_CAP, min(Z_CAP, v))
            for k, v in block_z.items() if k in BLOCK_WEIGHTS)
    return min(HEAT_MAX, 100.0 / (1.0 + math.exp(-s / scale)))


def data_coverage(indicators: dict[str, object]) -> float:
    """Доля индикаторов со свежими данными. Правило 6: нет данных ≠ нет риска."""
    if not indicators:
        return 0.0
    fresh = sum(1 for v in indicators.values() if v is not None)
    return 100.0 * fresh / len(indicators)


def tempo(h_now: float, h_7: float, h_30: float,
          phase: int, days_since_kinetic: int | None) -> str:
    """Классификация темпа по правилам раздела 3 методологии."""
    d7, d30 = h_now - h_7, h_now - h_30
    if phase >= 3 and abs(d30) <= 5 and (days_since_kinetic or 0) > 365:
        return "frozen"
    if d7 > 15:
        return "spike"
    if d30 > 8:
        return "up"
    if d30 < -8:
        return "down"
    return "flat"
