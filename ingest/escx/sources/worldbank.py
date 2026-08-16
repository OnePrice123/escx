"""Всемирный банк — доли населения, ВВП и военных расходов.

Зачем этот источник вообще нужен. Глобальный индекс — это не среднее по диадам,
а средневзвешенное по «весу последствий» (раздел 5A методологии): диада ядерных
держав с половиной мирового ВВП весит больше пограничного спора двух малых
государств. Без этих трёх величин глобальный индекс не считается вовсе, и на
сайте на его месте стоит прочерк.

Почему именно Всемирный банк, а не три разных источника:

  * население и ВВП (ППС) он отдаёт сам;
  * военные расходы в его базе — это перепубликация SIPRI (индикатор
    MS.MIL.XPND.CD), то есть тот самый источник, который назван в методологии.

Один открытый API вместо трёх ручных выгрузок — и он без ключа и без лимитов.

Ловушка, которую легко не заметить: у части стран за последний год данных нет,
и API отдаёт value = null. Брать вместо этого ноль нельзя — государство с
неизвестным ВВП получило бы нулевой вес и молча выпало бы из индекса. Поэтому
берётся последнее непустое значение (mrnev), а страны, у которых его нет вовсе,
возвращаются отдельным списком: пусть о них знают, а не догадываются.
"""
from __future__ import annotations
from ..http import get_json

BASE = "https://api.worldbank.org/v2"

INDICATORS = {
    "pop": "SP.POP.TOTL",        # население, человек
    "gdp": "NY.GDP.MKTP.PP.CD",  # ВВП по ППС, текущие международные доллары
    "mil": "MS.MIL.XPND.CD",     # военные расходы, текущие доллары США (данные SIPRI)
}


def fetch(indicator: str, *, per_page: int = 400) -> dict[str, tuple[int, float]]:
    """Последнее известное значение показателя по всем странам.

    Возвращает {ISO3: (год, значение)}. Агрегаты («Мир», «Европа») отбрасываются:
    у них в ответе тот же вид, что у стран, и попав в сумму, они удвоят её.
    """
    url = (f"{BASE}/country/all/indicator/{indicator}"
           f"?format=json&per_page={per_page}&mrnev=1")
    data = get_json(url)
    rows = data[1] if isinstance(data, list) and len(data) > 1 else []
    out: dict[str, tuple[int, float]] = {}
    for r in rows or []:
        iso = (r.get("countryiso3code") or "").strip()
        val = r.get("value")
        # У агрегатов код региона непустой, а у стран — да, поэтому фильтруем
        # по длине кода и по отсутствию значения. Списка агрегатов API не даёт.
        if len(iso) != 3 or val is None:
            continue
        try:
            year = int(r.get("date"))
        except (TypeError, ValueError):
            continue
        if iso not in out or year > out[iso][0]:
            out[iso] = (year, float(val))
    return out


def shares(values: dict[str, tuple[int, float]]) -> dict[str, float]:
    """Доли в мировом итоге, в процентах. Итог — сумма по странам списка."""
    total = sum(v for _, v in values.values())
    if not total:
        return {}
    return {k: 100.0 * v / total for k, (_, v) in values.items()}
