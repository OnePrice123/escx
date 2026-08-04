"""GDELT — поток мировых новостей, разобранный на события.

Что даёт: каждые 15 минут — новый файл с событиями, извлечёнными из мировых СМИ
на 65 языках, с кодами CAMEO, шкалой Голдштейна и тоном. Это блок 3 (дипломатия)
и блок 5 (информационное поле). Полностью бесплатно и открыто.

Два способа доступа, и выбирать надо осознанно:

1. ФАЙЛОВЫЙ ПОТОК (реализован здесь) — http://data.gdeltproject.org/gdeltv2/
   lastupdate.txt отдаёт три ссылки на последний срез, masterfilelist.txt — на все.
   Имена: YYYYMMDDHHMMSS.export.CSV.zip / .mentions.CSV.zip / .gkg.csv.zip
   Обновление в :00, :15, :30, :45. Плюс: бесплатно и без лимитов.
   Минус: чтобы собрать историю за год, надо скачать ~35 тысяч файлов.

2. BIGQUERY — gdelt-bq.gdeltv2.events_partitioned (~63 ГБ), gkg_partitioned (~3.6 ТБ)
   Для исторического бэкфилла способ единственно разумный. Бесплатный лимит
   Google — 1 ТБ обработанных данных в месяц; таблица gkg его сжигает одним
   неаккуратным запросом. Поэтому: только партиционированные таблицы, только с
   фильтром по дате, и ОБЯЗАТЕЛЬНО dry_run перед каждым запросом (см. bq_estimate).

ЛОВУШКИ:
  * GLOBALEVENTID не уникален во времени: одно и то же событие переизлагается и
    попадает в несколько срезов. Дедупликация по ключу обязательна.
  * Goldstein — это атрибут ТИПА события по справочнику CAMEO, а не измеренная
    интенсивность. Усреднять его «в лоб» нельзя: нужно взвешивать на NumMentions
    и нормировать на общий объём покрытия, иначе индекс станет трекером
    медиавнимания. Об этом же — правило 5 в методологии.
  * Actor1CountryCode — код CAMEO, НЕ ISO3. См. escx/codes.py.
"""
from __future__ import annotations
import csv, io, json, zipfile
from ..http import get
from ..codes import from_cameo

ROOT = "http://data.gdeltproject.org/gdeltv2"

# Колонки CSV export не имеют заголовка. Порядок задан кодбуком GDELT 2.0.
EXPORT_COLS = [
 "GLOBALEVENTID","SQLDATE","MonthYear","Year","FractionDate",
 "Actor1Code","Actor1Name","Actor1CountryCode","Actor1KnownGroupCode",
 "Actor1EthnicCode","Actor1Religion1Code","Actor1Religion2Code",
 "Actor1Type1Code","Actor1Type2Code","Actor1Type3Code",
 "Actor2Code","Actor2Name","Actor2CountryCode","Actor2KnownGroupCode",
 "Actor2EthnicCode","Actor2Religion1Code","Actor2Religion2Code",
 "Actor2Type1Code","Actor2Type2Code","Actor2Type3Code",
 "IsRootEvent","EventCode","EventBaseCode","EventRootCode","QuadClass",
 "GoldsteinScale","NumMentions","NumSources","NumArticles","AvgTone",
 "Actor1Geo_Type","Actor1Geo_FullName","Actor1Geo_CountryCode","Actor1Geo_ADM1Code",
 "Actor1Geo_ADM2Code","Actor1Geo_Lat","Actor1Geo_Long","Actor1Geo_FeatureID",
 "Actor2Geo_Type","Actor2Geo_FullName","Actor2Geo_CountryCode","Actor2Geo_ADM1Code",
 "Actor2Geo_ADM2Code","Actor2Geo_Lat","Actor2Geo_Long","Actor2Geo_FeatureID",
 "ActionGeo_Type","ActionGeo_FullName","ActionGeo_CountryCode","ActionGeo_ADM1Code",
 "ActionGeo_ADM2Code","ActionGeo_Lat","ActionGeo_Long","ActionGeo_FeatureID",
 "DATEADDED","SOURCEURL"]


def last_update() -> dict[str, str]:
    """Ссылки на последний 15-минутный срез: export / mentions / gkg."""
    txt = get(f"{ROOT}/lastupdate.txt", use_cache=False).decode("utf-8", "replace")
    urls = {}
    for line in txt.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3:
            u = parts[2]
            kind = ("gkg" if ".gkg." in u else
                    "mentions" if ".mentions." in u else "export")
            urls[kind] = u
    return urls


def slice_url(stamp: str, kind: str = "export") -> str:
    """stamp — 'YYYYMMDDHHMMSS', минуты только 00/15/30/45."""
    ext = "gkg.csv.zip" if kind == "gkg" else f"{kind}.CSV.zip"
    return f"{ROOT}/{stamp}.{ext}"


def parse_export(blob: bytes) -> list[dict]:
    """Разбирает zip со срезом export в список словарей."""
    if not blob:
        return []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = z.namelist()[0]
        raw = z.read(name).decode("utf-8", "replace")
    rows = []
    for rec in csv.reader(io.StringIO(raw), delimiter="\t"):
        if len(rec) < len(EXPORT_COLS):
            continue
        rows.append(dict(zip(EXPORT_COLS, rec)))
    return rows


def normalize(rows: list[dict]) -> list[dict]:
    """GDELT export -> строки raw_events. Оставляем только межгосударственные пары."""
    out = []
    for r in rows:
        a = from_cameo(r.get("Actor1CountryCode"))
        b = from_cameo(r.get("Actor2CountryCode"))
        if not a or not b or a == b:
            continue                      # не пара государств — не наш объект
        d = r.get("SQLDATE", "")
        out.append({
            "source": "gdelt_export",
            "source_id": r["GLOBALEVENTID"],
            "occurred_at": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else None,
            "actor_a": a, "actor_b": b,
            "event_type": f"cameo:{r.get('EventRootCode')}",
            "cameo_code": r.get("EventCode"),
            "goldstein": _f(r.get("GoldsteinScale")),
            "num_mentions": _i(r.get("NumMentions")),
            "lat": _f(r.get("ActionGeo_Lat")), "lon": _f(r.get("ActionGeo_Long")),
            "payload": json.dumps({
                "quad": r.get("QuadClass"), "tone": _f(r.get("AvgTone")),
                "sources": _i(r.get("NumSources")), "url": r.get("SOURCEURL"),
            }, ensure_ascii=False),
        })
    return out


def bq_estimate(sql: str) -> str:
    """Шаблон обязательной проверки объёма ПЕРЕД запросом в BigQuery.

    Возвращает команду; выполнять её надо там, где установлен gcloud SDK.
    Правило простое: не запускать ни одного запроса, не увидев его цену.
    """
    return ("bq query --use_legacy_sql=false --dry_run "
            f"--format=prettyjson '{sql.strip()}'")


BQ_EXAMPLE = """
-- Дипломатический баланс по паре государств, помесячно.
-- Партиционированная таблица + фильтр по дате = запрос читает мегабайты, а не гигабайты.
SELECT
  FORMAT_DATE('%Y-%m', PARSE_DATE('%Y%m%d', CAST(SQLDATE AS STRING))) AS ym,
  COUNTIF(QuadClass IN (3,4))                       AS conflictual,
  COUNTIF(QuadClass IN (1,2))                       AS cooperative,
  SAFE_DIVIDE(SUM(GoldsteinScale * NumMentions), SUM(NumMentions)) AS goldstein_w,
  SUM(NumMentions)                                  AS mentions
FROM `gdelt-bq.gdeltv2.events_partitioned`
WHERE _PARTITIONTIME BETWEEN TIMESTAMP('2024-01-01') AND TIMESTAMP('2026-08-01')
  AND ((Actor1CountryCode='IND' AND Actor2CountryCode='PAK')
    OR (Actor1CountryCode='PAK' AND Actor2CountryCode='IND'))
GROUP BY ym ORDER BY ym
"""


def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def _i(v):
    try: return int(v)
    except (TypeError, ValueError): return None
