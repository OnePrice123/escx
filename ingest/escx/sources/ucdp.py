"""UCDP — Uppsala Conflict Data Program.

Что даёт: georeferenced event dataset (GED) с 1989 года — отдельные события
организованного насилия с датой, координатами, сторонами и числом погибших.
Это единственный источник в наборе, где число боевых смертей — измеренная величина,
а не оценка. На нём стоит вся кинетика (блок 1) и пороги фаз 3/4/5.

Доступ: https://ucdpapi.pcr.uu.se/api/<resource>/<version>?<params>
Бесплатно, без ключа. Лимиты: 5000 запросов в сутки на IP, до 1000 строк на страницу.

ЛОВУШКА, о которой нужно знать заранее:
  GED выходит РАЗ В ГОД (версия 25.1 = данные по 2024 включительно).
  Для текущего года есть UCDP Candidate — предварительные ежемесячные данные,
  которые ПОТОМ ПЕРЕСМАТРИВАЮТСЯ задним числом. Смешивать их с финальными нельзя:
  модель, обученная на пересмотренных данных, будет знать будущее.
  Поэтому источник помечается в source ('ucdp_ged' против 'ucdp_candidate'),
  а обучающая выборка строится только на финальных версиях.
"""
from __future__ import annotations
import json
from ..http import get_json
from ..codes import from_gw

BASE = "https://ucdpapi.pcr.uu.se/api"
VERSION = "25.1"


def fetch_ged(*, start: str, end: str, version: str = VERSION,
              pagesize: int = 1000, max_pages: int = 200) -> list[dict]:
    """Тянет события GED за период. Пагинация обязательна — API её требует.

    start/end — 'YYYY-MM-DD'.
    """
    out, page = [], 0
    while page < max_pages:
        url = (f"{BASE}/gedevents/{version}"
               f"?pagesize={pagesize}&page={page}"
               f"&StartDate={start}&EndDate={end}")
        data = get_json(url)
        rows = data.get("Result") or []
        out.extend(rows)
        if not data.get("NextPageUrl") or not rows:
            break
        page += 1
    return out


def normalize(rows: list[dict], source: str = "ucdp_ged") -> list[dict]:
    """GED -> строки raw_events.

    Поле date_prec сохраняется намеренно: у части событий дата известна лишь с
    точностью до месяца или года (date_prec >= 3). Такие события нельзя класть
    в 30-дневные окна — они размажут кинетику. Фильтрация делается на этапе
    расчёта индикаторов, а не при загрузке: сырьё сохраняем как есть.
    """
    out = []
    for r in rows:
        out.append({
            "source": source,
            "source_id": str(r.get("id")),
            "occurred_at": (r.get("date_start") or "")[:10],
            "actor_a": from_gw(r.get("side_a_new_id") or r.get("gwnoa")),
            "actor_b": from_gw(r.get("side_b_new_id") or r.get("gwnob")),
            "event_type": {1: "state-based", 2: "non-state", 3: "one-sided"}.get(
                r.get("type_of_violence"), "unknown"),
            "fatalities": r.get("best"),
            "date_prec": r.get("date_prec"),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "payload": json.dumps({
                k: r.get(k) for k in
                ("conflict_new_id", "dyad_new_id", "side_a", "side_b",
                 "country", "region", "where_prec", "source_article",
                 "deaths_a", "deaths_b", "deaths_civilians")
            }, ensure_ascii=False),
        })
    return out
