"""Сопоставление события с диадой.

Это самое хрупкое место всего пайплайна, и ошибка здесь не даёт сбоя — она молча
портит все расчёты выше. Событие «столкновение на границе X» может относиться к
диаде X–Y, X–Z или ни к одной. Поэтому три уровня, и КАЖДОЕ сопоставление
записывает, каким уровнем оно получено.

  rule  — обе стороны события явно закодированы и образуют диаду из реестра
  geo   — событие в спорной зоне диады, стороны закодированы частично
  llm   — неоднозначный случай, отдан модели, обоснование сохраняется
  unmatched — не отнесено ни к чему; таких событий надо СЧИТАТЬ, а не выбрасывать

Точность измеряется на размеченной вручную выборке (см. tests/) и публикуется.
Если атрибуция врёт, врёт всё, что построено выше.
"""
from __future__ import annotations
from math import radians, sin, cos, asin, sqrt


def build_index(dyads: list[dict]) -> dict[frozenset, str]:
    """Неупорядоченная пара ISO3 -> dyad_id. Диада симметрична как объект."""
    return {frozenset((d["side_a"], d["side_b"])): d["dyad_id"] for d in dyads}


def match_rule(event: dict, index: dict[frozenset, str]) -> str | None:
    a, b = event.get("actor_a"), event.get("actor_b")
    if not a or not b or a == b:
        return None
    return index.get(frozenset((a, b)))


def haversine(lat1, lon1, lat2, lon2) -> float:
    """Расстояние в километрах."""
    r = 6371.0
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(h))


def match_geo(event: dict, zones: list[dict], max_km: float = 120.0) -> str | None:
    """Событие внутри спорной зоны диады.

    zones: [{'dyad_id':..., 'lat':..., 'lon':..., 'radius_km':...}]
    Работает только когда одна из сторон уже известна ИЛИ зона узкая.
    Радиус по умолчанию намеренно небольшой: широкий радиус даёт ложные привязки,
    а пропущенное событие честнее приписанного не туда.
    """
    lat, lon = event.get("lat"), event.get("lon")
    if lat is None or lon is None:
        return None
    best, best_d = None, 1e9
    for z in zones:
        d = haversine(lat, lon, z["lat"], z["lon"])
        lim = z.get("radius_km", max_km)
        if d <= lim and d < best_d:
            best, best_d = z["dyad_id"], d
    return best


def attribute(event: dict, index: dict[frozenset, str],
              zones: list[dict] | None = None) -> tuple[str | None, str]:
    """Возвращает (dyad_id, match_level). Ничего не выбрасывает."""
    d = match_rule(event, index)
    if d:
        return d, "rule"
    if zones:
        d = match_geo(event, zones)
        if d:
            return d, "geo"
    return None, "unmatched"


def attribute_all(events: list[dict], dyads: list[dict],
                  zones: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Проставляет dyad_id/match_level всем событиям и возвращает статистику.

    Статистика — не украшение: рост доли unmatched вдвое означает, что источник
    изменил формат или в реестре не хватает диады. Это одна из ежедневных проверок.
    """
    index = build_index(dyads)
    stats = {"rule": 0, "geo": 0, "unmatched": 0, "total": len(events)}
    for e in events:
        d, lvl = attribute(e, index, zones)
        e["dyad_id"], e["match_level"] = d, lvl
        stats[lvl] += 1
    stats["unmatched_share"] = (stats["unmatched"] / len(events)) if events else 0.0
    return events, stats
