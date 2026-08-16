"""UCDP — Uppsala Conflict Data Program.

Что даёт: georeferenced event dataset (GED) с 1989 года — отдельные события
организованного насилия с датой, координатами, сторонами и числом погибших.
Это единственный источник в наборе, где число боевых смертей — измеренная величина,
а не оценка. На нём стоит вся кинетика (блок 1) и пороги фаз 3/4/5.

ДВА СПОСОБА ДОСТУПА, и по умолчанию используется второй.

1. API (https://ucdpapi.pcr.uu.se/api/) — с 2026 года ТРЕБУЕТ ТОКЕН. Запрос без
   заголовка `x-ucdp-access-token` отдаёт 401. Токен выдают по письму, заявку
   рассматривают 3–5 рабочих дней. Если токен есть, положите его в переменную
   окружения UCDP_TOKEN, и API снова заработает.

2. ГОТОВЫЕ ФАЙЛЫ (https://ucdp.uu.se/downloads/) — открыты, без токена и без
   регистрации, лицензия CC BY 4.0. Это и есть путь по умолчанию.

   Файлы даже удобнее API для нашей задачи: вся история — один zip вместо
   четырёхсот страничных запросов, и никакого расхода лимита в 5000 запросов
   в сутки. API остаётся полезен только для точечных дозагрузок.

ЛОВУШКА, о которой нужно знать заранее:
  GED выходит РАЗ В ГОД (версия 26.1 = данные по 2025 включительно).
  Для текущего года есть UCDP Candidate — предварительные ежемесячные данные,
  которые ПОТОМ ПЕРЕСМАТРИВАЮТСЯ задним числом. Смешивать их с финальными нельзя:
  модель, обученная на пересмотренных данных, будет знать будущее.
  Поэтому источник помечается в source ('ucdp_ged' против 'ucdp_candidate'),
  а обучающая выборка строится только на финальных версиях.
"""
from __future__ import annotations
import csv, io, json, os, zipfile
from typing import Iterator

from ..http import get, get_json
from ..codes import from_gw

BASE = "https://ucdpapi.pcr.uu.se/api"
VERSION = "26.1"

# Готовые выгрузки. Номер в имени файла — версия без точки: 26.1 -> ged261.
BULK_GED = "https://ucdp.uu.se/downloads/ged/ged{v}-csv.zip"
BULK_CANDIDATE = "https://ucdp.uu.se/downloads/candidateged/GEDEvent_v{y}_0_{m}.csv"

# Версии GED, которые пробуем по очереди, если основная не отвечает.
# Зачем это нужно: датасет выходит раз в год, номер версии меняется, а
# несуществующая версия отдаёт 404. Наш HTTP-слой на 404 не падает намеренно
# (у файловых потоков отсутствие файла — норма), поэтому устаревший номер даёт
# ноль событий и выглядит как «в мире было тихо». Тишина, вызванная опечаткой
# в номере версии, — худший вид ошибки: она не падает и не спорит.
VERSION_CANDIDATES = ["26.1", "25.1", "24.1", "23.1", "27.1"]

_resolved: str | None = None


def api_headers() -> dict[str, str]:
    """Заголовки для API. Пусто, если токена нет — тогда API вернёт 401."""
    tok = os.environ.get("UCDP_TOKEN", "").strip()
    return {"x-ucdp-access-token": tok} if tok else {}


def resolve_bulk_version(preferred: str = VERSION) -> str | None:
    """Первая версия готовой выгрузки, которая реально скачивается.

    Проверяется не по номеру, а по факту: запрашиваем файл и смотрим, пришёл ли
    он. Номер версии меняется раз в год, и захардкоженный однажды тихо
    перестанет существовать — а 404 у нас не исключение, а пустой ответ.
    """
    global _resolved
    if _resolved:
        return _resolved
    order = [preferred] + [v for v in VERSION_CANDIDATES if v != preferred]
    for v in order:
        url = BULK_GED.format(v=v.replace(".", ""))
        if get(url, use_cache=True, timeout=600, retries=2):
            _resolved = v
            return v
    return None


def iter_bulk_ged(version: str | None = None) -> Iterator[dict]:
    """Строки полного GED из zip-выгрузки. Генератор, а не список.

    Генератор здесь не стилистика: в GED около 400 тысяч событий, и материализация
    их в список словарей съедает под гигабайт. Вызывающий читает партиями и пишет
    в базу партиями, так что в памяти всегда лежит одна партия.

    CSV отдаёт всё строками. Приводим к числам ровно те поля, которые дальше
    считаются: иначе `best` окажется строкой, и суммирование смертей молча
    превратится в склейку цифр.
    """
    v = version or resolve_bulk_version()
    if not v:
        return
    blob = get(BULK_GED.format(v=v.replace(".", "")), use_cache=True,
               timeout=600, retries=2)
    if not blob:
        return
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            return
        with z.open(names[0]) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8-sig", newline="")
            for row in csv.DictReader(text):
                yield _typed(row)


def iter_candidate(year: int, month: int) -> Iterator[dict]:
    """Предварительные события за текущий год. Помечаются отдельным источником.

    Кандидатские данные пересматриваются задним числом, поэтому в базе они
    лежат под source='ucdp_candidate' и никогда не смешиваются с финальными.
    """
    blob = get(BULK_CANDIDATE.format(y=year, m=month), use_cache=True, timeout=300)
    if not blob:
        return
    text = io.StringIO(blob.decode("utf-8-sig", errors="replace"))
    for row in csv.DictReader(text):
        yield _typed(row)


def latest_candidate(year: int) -> int | None:
    """Номер последнего доступного месячного файла кандидатов. None — нет ни одного."""
    for m in range(12, 0, -1):
        if get(BULK_CANDIDATE.format(y=year, m=m), use_cache=True, timeout=300, retries=1):
            return m
    return None


_INT = ("id", "type_of_violence", "best", "high", "low", "date_prec",
        "gwnoa", "gwnob", "side_a_new_id", "side_b_new_id", "where_prec",
        "deaths_a", "deaths_b", "deaths_civilians", "deaths_unknown")
_FLOAT = ("latitude", "longitude")


def _typed(row: dict) -> dict:
    out = dict(row)
    for k in _INT:
        v = out.get(k)
        if v in (None, "", "NA"):
            out[k] = None
        else:
            try:
                out[k] = int(float(v))
            except (TypeError, ValueError):
                out[k] = None
    for k in _FLOAT:
        v = out.get(k)
        try:
            out[k] = float(v) if v not in (None, "", "NA") else None
        except (TypeError, ValueError):
            out[k] = None
    return out


def resolve_version(preferred: str = VERSION) -> str | None:
    """То же для API. Требует токен: без него любой запрос вернёт 401."""
    global _resolved
    if _resolved:
        return _resolved
    if not api_headers():
        return None
    order = [preferred] + [v for v in VERSION_CANDIDATES if v != preferred]
    for v in order:
        data = get_json(f"{BASE}/gedevents/{v}?pagesize=1&page=0", headers=api_headers())
        if data.get("Result"):
            _resolved = v
            return v
    return None


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
        data = get_json(url, headers=api_headers())
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
            # ТОЛЬКО gwnoa/gwnob. side_a_new_id — идентификатор актора в
            # справочнике UCDP, а не код Гледича–Уорда. Раньше он стоял первым,
            # и там, где номера случайно совпадали, событие приписывалось не той
            # стране: ошибка, которая не падает и не видна в логе.
            "actor_a": from_gw(r.get("gwnoa")),
            "actor_b": from_gw(r.get("gwnob")),
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
