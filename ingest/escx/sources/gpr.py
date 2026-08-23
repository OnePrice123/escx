"""GPR — индекс геополитического риска Caldara & Iacoviello.

ЗАЧЕМ ЭТОТ ИСТОЧНИК. Не ради нового слагаемого в индексе, а ради проверки
существующего. Инфополе у нас целиком стоит на GDELT: один проект, одна
автоматическая кодировка, одна точка доверия. По собственной сверке GDELT
ошибается примерно в трети случаев, и это ещё до вопроса о том, что будет,
если источник однажды изменит поведение.

GPR — независимый конвейер, меряющий примерно то же самое: долю газетных
статей о геополитической напряжённости, считается академической группой по
архивам газет, методология опубликована и отрецензирована. Другие входные
данные, другие авторы, другие способы ошибиться. Если наш инфопоток дёрнулся,
а GPR нет — это аномалия источника, а не событие в мире.

ПОЧЕМУ .dta, А НЕ .xls. У автора четыре формата, и три из них не годятся:

  * data_gpr_export.xls — свежий, но это старый бинарный BIFF8 внутри OLE.
    Стандартная библиотека его не читает, а зависимостей в проекте нет;
  * копия на policyuncertainty.com в нормальном .xlsx обрывается 2017 годом;
  * архивные gpr_web_*.xlsx в репозитории автора — 2021 годом.

Единственный формат, который одновременно свежий и разбираемый без библиотек, —
Stata .dta версии 118: XML-обёртка с бинарными секциями, формат документирован
и стабилен. Отсюда небольшой разборщик ниже.

ЧТО В ФАЙЛЕ. Помесячно с 1900 года: глобальный GPR и 44 страны, уже кодами
ISO3 — GPRC_RUS, GPRC_UKR, GPRC_TWN. Из наших двадцати пар обе стороны
покрыты у пяти, одна сторона ещё у десяти, ни одной — у пяти. Это ограничение
источника: он считался для крупных экономик, а не для конфликтных пар.

ЛИЦЕНЗИЯ. В самом файле сказано: данные можно использовать свободно при
указании авторов, статьи и сайта. Атрибуция обязательна и не формальность.
"""
from __future__ import annotations

import struct
from datetime import date
from typing import Iterator

from ..http import get

DTA_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.dta"

# Числовые типы Stata: код -> (размер в байтах, формат struct).
_NUM = {65526: (8, "<d"), 65527: (4, "<f"),
        65528: (4, "<i"), 65529: (2, "<h"), 65530: (1, "<b")}

# Пропуск в Stata кодируется не NaN, а числом у верхней границы типа.
# Для float это 1.70141e38 — если не отсечь, оно уедет в базу как значение
# и превратится в чудовищный выброс, который переживёт любую винзоризацию.
_MISSING_FROM = 8.0e37

# Начало отсчёта месячных дат Stata: 0 — январь 1960 года.
_EPOCH_Y = 1960


def _tag(blob: bytes, name: str) -> bytes:
    """Содержимое <name>...</name>. Формат 118 обрамляет секции тегами."""
    o, c = f"<{name}>".encode(), f"</{name}>".encode()
    a = blob.index(o) + len(o)
    return blob[a:blob.index(c, a)]


def read_dta(blob: bytes) -> tuple[list[str], list[dict[str, float]]]:
    """Имена переменных и строки наблюдений. Только числовые столбцы.

    Строковые столбцы пропускаются намеренно: в этом файле их нет, а поддержка
    strL потянула бы за собой половину спецификации формата ради ничего.
    """
    if _tag(blob, "release") != b"118":
        raise ValueError(f"ожидался Stata 118, пришёл {_tag(blob, 'release')!r}")

    k = struct.unpack("<H", _tag(blob, "K"))[0]
    n = struct.unpack("<Q", _tag(blob, "N"))[0]
    types = struct.unpack(f"<{k}H", _tag(blob, "variable_types"))

    raw = _tag(blob, "varnames")
    step = len(raw) // k                      # 129 байт на имя в версии 118
    names = [raw[i * step:(i + 1) * step].split(b"\x00")[0].decode("utf-8", "replace")
             for i in range(k)]

    if any(t not in _NUM for t in types):
        raise ValueError("в файле есть строковые столбцы — разборщик их не умеет")

    width = sum(_NUM[t][0] for t in types)
    start = blob.index(b"<data>") + len(b"<data>")

    rows: list[dict[str, float]] = []
    for i in range(n):
        p = start + i * width
        row: dict[str, float] = {}
        for nm, t in zip(names, types):
            size, fmt = _NUM[t]
            v = struct.unpack(fmt, blob[p:p + size])[0]
            p += size
            row[nm] = None if abs(v) >= _MISSING_FROM else float(v)
        rows.append(row)
    return names, rows


def month_to_ym(m: float | None) -> str | None:
    """Месячная дата Stata -> «ГГГГ-ММ». 0 — январь 1960-го."""
    if m is None:
        return None
    mi = int(m)
    y, mm = divmod(mi, 12)
    return f"{_EPOCH_Y + y:04d}-{mm + 1:02d}"


def iter_series(blob: bytes, since: date | None = None) -> Iterator[tuple[str, str, float]]:
    """Ряды для записи: («global» либо «c:ISO3», «ГГГГ-ММ», значение).

    Страновые переменные названы GPRC_ISO3 — коды совпадают с нашими сторонами
    диад, поэтому сопоставлять ничего не нужно.
    """
    names, rows = read_dta(blob)
    cty = [n for n in names if n.startswith("GPRC_") and len(n) == len("GPRC_XXX")]
    cut = f"{since.year:04d}-{since.month:02d}" if since else None

    for row in rows:
        ym = month_to_ym(row.get("month"))
        if not ym or (cut and ym < cut):
            continue
        if row.get("GPR") is not None:
            yield "global", ym, row["GPR"]
        for c in cty:
            v = row.get(c)
            if v is not None:
                yield f"c:{c[5:]}", ym, v


def fetch() -> bytes:
    """Файл целиком. Меньше мегабайта, качается раз в сутки."""
    return get(DTA_URL, use_cache=False, timeout=120)
