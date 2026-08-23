"""Тесты без сети. Проверяют логику, которая ломается тише всего:
коды стран, сопоставление событий с диадами и робастную нормализацию.
"""
import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from escx import codes, match, indicators as ind, db, dyads as dy
from escx.sources import gdelt, ucdp
from datetime import date

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  [ok]   {name}")
    else:    fail += 1; print(f"  [FAIL] {name} {extra}")

print("\n1. Таблица кодов")
check("UCDP GW 750 -> IND", codes.from_gw(750) == "IND")
check("GDELT CAMEO 'RP' -> PHL (не ISO3!)", codes.from_cameo("RP") == "PHL")
check("CAMEO 'GER' -> DEU, а не 'GER'", codes.from_cameo("GER") == "DEU")
check("пустой код -> None", codes.from_cameo("") is None)
check("все записи полны", all(len(v) == 3 for v in codes.COUNTRY.values()))

print("\n2. Сопоставление с диадами")
D = dy.load()
idx = match.build_index(D)
check("порядок сторон не важен",
      match.match_rule({"actor_a":"PAK","actor_b":"IND"}, idx) == "IND-PAK")
check("актор сам с собой не диада",
      match.match_rule({"actor_a":"IND","actor_b":"IND"}, idx) is None)
check("пара не из реестра не сопоставляется",
      match.match_rule({"actor_a":"IND","actor_b":"JPN"}, idx) is None)

zones = [{"dyad_id":"IND-PAK","lat":34.0,"lon":74.5,"radius_km":150}]
check("гео-привязка внутри зоны",
      match.match_geo({"lat":34.2,"lon":74.7}, zones) == "IND-PAK")
check("гео-привязка вне зоны не срабатывает",
      match.match_geo({"lat":20.0,"lon":74.7}, zones) is None)

evs = [{"actor_a":"IND","actor_b":"PAK"}, {"actor_a":"IND","actor_b":"JPN"},
       {"actor_a":"CHN","actor_b":"TWN"}]
evs, st = match.attribute_all(evs, D)
check("статистика считает несопоставленные", st["unmatched"] == 1 and st["rule"] == 2, st)
check("несопоставленные не выбрасываются", len(evs) == 3)

print("\n3. Робастная нормализация")
hist = [1,1,2,1,2,1,1,2,1,1,2,1]
check("выброс даёт большой z", ind.robust_z(40, hist) > 5)
check("норма даёт z около нуля", abs(ind.robust_z(1, hist)) < 1.5)
check("короткая история -> 0", ind.robust_z(99, [1,2]) == 0.0)
w = ind.winsorize([1.0]*98 + [1000.0, -500.0])
check("винзоризация срезает хвост", max(w) < 1000 and min(w) > -500, (min(w), max(w)))
check("винзоризация не схлопывает короткий ряд", ind.winsorize([1,2,3,4]) == [1,2,3,4])

print("\n4. Кинетика и точность даты")
events = [
 {"occurred_at":"2026-08-01","fatalities":3,"lat":34.0,"lon":74.5,"date_prec":1},
 {"occurred_at":"2026-07-20","fatalities":5,"lat":34.4,"lon":74.9,"date_prec":1},
 {"occurred_at":"2026-07-15","fatalities":99,"lat":34.0,"lon":74.5,"date_prec":4},  # дата до года
 {"occurred_at":"2026-01-01","fatalities":7,"lat":34.0,"lon":74.5,"date_prec":1},   # вне окна
]
r = ind.rolling_counts(events, date(2026,8,4), 30)
check("события вне окна не попадают", r["events_30d"] == 2, r)
check("неточные даты отброшены", r["fatalities_30d"] == 8, r)
check("гео-ячейки считаются", r["geo_cells_30d"] == 2, r)

print("\n5. Голдштейн и нормировка на внимание")
g = ind.goldstein_weighted([{"goldstein":-8.0,"num_mentions":100},
                            {"goldstein":+2.0,"num_mentions":1}])
check("взвешивание на упоминания работает", g is not None and g < -7, g)
check("без упоминаний -> None", ind.goldstein_weighted([]) is None)
check("нормировка на объём", abs(ind.media_normalized(50, 1000) - 0.05) < 1e-9)

print("\n6. Накал и темп")
check("нулевые z -> H = 50", abs(ind.heat({k:0.0 for k in ind.BLOCK_WEIGHTS}) - 50) < 1e-6)
check("высокие z -> H > 85", ind.heat({k:3.0 for k in ind.BLOCK_WEIGHTS}) > 85,
      round(ind.heat({k:3.0 for k in ind.BLOCK_WEIGHTS}), 1))
check("H монотонна по z",
      ind.heat({k:1.0 for k in ind.BLOCK_WEIGHTS}) < ind.heat({k:2.0 for k in ind.BLOCK_WEIGHTS}))
check("отрицательные z -> H < 50", ind.heat({k:-2.0 for k in ind.BLOCK_WEIGHTS}) < 50)
check("сумма весов = 1", abs(sum(ind.BLOCK_WEIGHTS.values()) - 1.0) < 1e-9)
check("заморозка распознаётся", ind.tempo(40,40,41,3,800) == "frozen")
check("заморозка не ставится при низкой фазе", ind.tempo(40,40,41,1,800) == "flat")
check("резкий скачок важнее нагрева", ind.tempo(60,42,30,2,10) == "spike")
check("разрядка", ind.tempo(30,33,45,2,10) == "down")
check("покрытие данных", abs(ind.data_coverage({"a":1,"b":None,"c":3,"d":None}) - 50) < 1e-9)

print("\n7. Разбор GDELT export")
row = ["1234567","20260801","202608","2026","2026.5833",
       "IND","INDIA","IND","","","","","","","",
       "PAK","PAKISTAN","PAK","","","","","","","",
       "1","190","190","19","4",
       "-10.0","42","7","42","-6.5",
       "1","Kashmir","IN","","", "34.0","74.5","0",
       "1","Kashmir","PK","","", "34.1","74.6","0",
       "1","Kashmir","IN","","", "34.0","74.5","0",
       "20260801120000","http://example.org/a"]
parsed = [dict(zip(gdelt.EXPORT_COLS, row))]
n = gdelt.normalize(parsed)
check("нормализация даёт одну строку", len(n) == 1)
check("дата приведена к ISO", n[0]["occurred_at"] == "2026-08-01", n[0]["occurred_at"])
check("акторы переведены в ISO3", (n[0]["actor_a"], n[0]["actor_b"]) == ("IND","PAK"))
check("Голдштейн разобран", n[0]["goldstein"] == -10.0)
n2, s2 = match.attribute_all(n, D)
check("событие отнесено к IND-PAK правилом",
      n2[0]["dyad_id"] == "IND-PAK" and n2[0]["match_level"] == "rule")

row_self = list(row); row_self[17] = "IND"      # Actor2CountryCode = IND
check("внутригосударственное событие отсеяно",
      len(gdelt.normalize([dict(zip(gdelt.EXPORT_COLS, row_self))])) == 0)

print("\n8. Нормализация UCDP")
u = ucdp.normalize([{"id":88,"date_start":"2026-07-02 00:00:00.000",
                     "gwnoa":750,"gwnob":770,
                     "side_a_new_id":141,"side_b_new_id":300,"type_of_violence":1,
                     "best":4,"date_prec":1,"latitude":34.0,"longitude":74.5,
                     "country":"India","side_a":"Government of India"}])
check("id и дата разобраны", u[0]["source_id"] == "88" and u[0]["occurred_at"] == "2026-07-02")
check("GW-коды переведены", (u[0]["actor_a"], u[0]["actor_b"]) == ("IND","PAK"))
# side_a_new_id — идентификатор актора, а не код страны. Совпадение номеров
# с кодами Гледича–Уорда случайно и приписало бы событие чужому государству.
u2 = ucdp.normalize([{"id":89,"date_start":"2026-07-02","side_a_new_id":750,
                      "side_b_new_id":770,"type_of_violence":2,"best":1}])
check("идентификатор актора не принимается за код страны",
      (u2[0]["actor_a"], u2[0]["actor_b"]) == (None, None), (u2[0]["actor_a"], u2[0]["actor_b"]))

print("\n8a. Разбор готовой выгрузки UCDP")
row = {"id":"5","best":"12","date_prec":"1","latitude":"34,0".replace(",","."),
       "longitude":"74.5","gwnoa":"750","gwnob":"770","type_of_violence":"1",
       "deaths_a":"NA","side_a_new_id":""}
typed = ucdp._typed(row)
check("числа приведены из строк", typed["best"] == 12 and typed["id"] == 5)
check("координаты стали числами", typed["latitude"] == 34.0)
check("NA и пустые значения стали None",
      typed["deaths_a"] is None and typed["side_a_new_id"] is None)
check("строка выгрузки нормализуется как строка API",
      ucdp.normalize([typed])[0]["actor_a"] == "IND")
check("payload сериализован", json.loads(u[0]["payload"])["country"] == "India")

print("\n8b. Чтение zip-выгрузки без сети")
import io as _io, zipfile as _zip, csv as _csv
_buf = _io.StringIO()
_w = _csv.DictWriter(_buf, fieldnames=["id","date_start","gwnoa","gwnob","best",
                                       "date_prec","latitude","longitude",
                                       "type_of_violence","deaths_a"])
_w.writeheader()
_w.writerow({"id":"1","date_start":"2025-03-01","gwnoa":"750","gwnob":"770","best":"7",
             "date_prec":"1","latitude":"34.1","longitude":"74.2",
             "type_of_violence":"1","deaths_a":"NA"})
_z = _io.BytesIO()
with _zip.ZipFile(_z, "w") as _zf:
    _zf.writestr("GEDEvent_v26_1.csv", _buf.getvalue())
_blob = _z.getvalue()
_real_get = ucdp.get
ucdp.get = lambda url, **kw: _blob if "ged261" in url else b""
ucdp._resolved = None
_v = ucdp.resolve_bulk_version()
_rows = list(ucdp.iter_bulk_ged(_v))
check("версия выгрузки определяется по факту скачивания", _v == "26.1", _v)
check("zip разобран", len(_rows) == 1 and _rows[0]["best"] == 7)
check("выгрузка и API дают одинаковую форму строки",
      ucdp.normalize(_rows)[0]["actor_a"] == "IND")
ucdp._resolved = None
ucdp.get = lambda url, **kw: b""
check("нет ни одной доступной версии -> None, а не исключение",
      ucdp.resolve_bulk_version() is None)
ucdp.get = _real_get
ucdp._resolved = None


print("\n9. Хранилище: идемпотентность и append-only")
import tempfile, os, sqlite3
tmp = tempfile.mktemp(suffix=".db")
con = db.connect(tmp); dy.install(con, D)
rows = [{"source":"t","source_id":"1","occurred_at":"2026-08-01","dyad_id":"IND-PAK",
         "match_level":"rule","fatalities":2}]
a = db.upsert_events(con, rows)
b = db.upsert_events(con, rows)          # тот же прогон второй раз
check("повторный прогон не дублирует", a == 1 and b == 0, f"{a}/{b}")
try:
    con.execute("UPDATE raw_events SET fatalities=99"); con.commit()
    check("UPDATE запрещён триггером", False, "прошёл, а не должен")
except sqlite3.IntegrityError as e:
    check("UPDATE запрещён триггером", "только для вставки" in str(e))
try:
    con.execute("DELETE FROM raw_events"); con.commit()
    check("DELETE запрещён триггером", False, "прошёл, а не должен")
except sqlite3.IntegrityError:
    check("DELETE запрещён триггером", True)
db.set_watermark(con, "gdelt_export", "20260804031500")
check("метка сохраняется", db.get_watermark(con, "gdelt_export") == "20260804031500")
con.close(); os.unlink(tmp)

print("\nGPR: разбор Stata .dta без библиотек")
import struct as _st
from escx.sources import gpr as G

def _dta(names, types, rows):
    """Минимальный файл Stata 118 — ровно то, что читает наш разборщик."""
    k, n = len(names), len(rows)
    head = (b"<stata_dta><header><release>118</release><byteorder>LSF</byteorder>"
            + b"<K>" + _st.pack("<H", k) + b"</K>"
            + b"<N>" + _st.pack("<Q", n) + b"</N></header>")
    body = (b"<variable_types>" + _st.pack(f"<{k}H", *types) + b"</variable_types>"
            + b"<varnames>" + b"".join(x.encode().ljust(129, b"\x00") for x in names)
            + b"</varnames><data>")
    for r in rows:
        for v, t in zip(r, types):
            body += _st.pack(G._NUM[t][1], v)
    return head + body + b"</data></stata_dta>"

_F = 65527   # float
_blob = _dta(["month", "GPR", "GPRC_RUS", "GPRC_UKR"], [_F] * 4,
             [(672.0, 100.5, 1.5, 2.5), (673.0, 110.0, 1.0e38, 3.0)])
_names, _rows = G.read_dta(_blob)
check("имена переменных прочитаны", _names == ["month", "GPR", "GPRC_RUS", "GPRC_UKR"], _names)
check("наблюдения прочитаны", len(_rows) == 2)
check("значение разобрано", abs(_rows[0]["GPR"] - 100.5) < 0.01, _rows[0]["GPR"])
# Пропуск в Stata — не NaN, а число у верхней границы типа. Не отсечь его
# значит записать 1.7e38 как значение и получить выброс, переживающий любую
# винзоризацию.
check("пропуск Stata распознан как пропуск", _rows[1]["GPRC_RUS"] is None, _rows[1]["GPRC_RUS"])

check("месяц Stata: 0 — январь 1960", G.month_to_ym(0) == "1960-01", G.month_to_ym(0))
check("месяц Stata: 672 — январь 2016", G.month_to_ym(672) == "2016-01", G.month_to_ym(672))
check("месяц Stata: отрицательный — до 1960", G.month_to_ym(-12) == "1959-01", G.month_to_ym(-12))

_ser = list(G.iter_series(_blob))
check("глобальный ряд и страновые разделены",
      sorted({k for k, _, _ in _ser}) == ["c:RUS", "c:UKR", "global"], sorted({k for k, _, _ in _ser}))
check("пропуски в ряды не попали", all(v is not None for _, _, v in _ser))
check("страна берётся кодом ISO3 из имени переменной",
      ("c:UKR", "2016-02", 3.0) in _ser)
try:
    G.read_dta(_blob.replace(b"<release>118<", b"<release>117<"))
    check("чужая версия формата отвергается", False, "прошла")
except ValueError:
    check("чужая версия формата отвергается", True)

print("\nUCDP: адреса кандидатских файлов")
from escx.sources import ucdp as U
# Год в имени файла ДВУЗНАЧНЫЙ. Стоял четырёхзначный: адрес отдавал 404,
# HTTP-слой на 404 намеренно не падает, и pull-candidate возвращал ноль
# событий каждую ночь. Кинетика не измерялась ни у одной пары с января,
# и выглядело это как «в мире тихо» — ошибка, которая не падает и не спорит.
_urls = U.candidate_urls(2026, 6)
check("год в адресе двузначный", all("v26_" in u for u in _urls), _urls[0])
check("четырёхзначного года нет", not any("v2026" in u for u in _urls))
check("накопительный файл идёт первым",
      _urls[0].endswith("GEDEvent_v26_01_26_06.csv"), _urls[0])
check("месячный остаётся запасным",
      _urls[1].endswith("GEDEvent_v26_0_6.csv"), _urls[1])
check("месяц дополняется нулём в накопительном",
      U.candidate_urls(2026, 3)[0].endswith("v26_01_26_03.csv"))
check("смена века не ломает имя", U.candidate_urls(2100, 5)[0].count("v0_") == 0)

print("\nADS-B: наблюдаемость зоны")
from escx.sources import adsb as A
# Наблюдаемость мерится ВСЕМ трафиком, а не военным. Пока её считали по
# военной ленте, «военных нет» и «приёмников нет» были неотличимы, и зон
# под наблюдением выходило 1 из 14 вместо 9.
lat, lon, r = A.zone_center_radius([44.0, 27.0, 53.0, 41.0])   # RUS-UKR
check("центр зоны считается", abs(lat - 48.5) < 0.01 and abs(lon - 34.0) < 0.01)
check("радиус покрывает зону и влезает в потолок источника",
      0 < r <= A.MAX_RADIUS_NM, r)
_, _, r_big = A.zone_center_radius([0.0, 0.0, 60.0, 60.0])
check("огромная зона обрезается потолком", r_big == A.MAX_RADIUS_NM, r_big)
_, _, r_small = A.zone_center_radius([10.0, 10.0, 10.01, 10.01])
check("крошечная зона не даёт нулевой радиус", r_small >= 10, r_small)
check("борт внутри рамки распознан",
      A.in_box({"lat": 48.0, "lon": 34.0}, [44.0, 27.0, 53.0, 41.0]))
check("борт вне рамки не считается",
      not A.in_box({"lat": 10.0, "lon": 34.0}, [44.0, 27.0, 53.0, 41.0]))
_z = {"D": {"box": [44.0, 27.0, 53.0, 41.0]}}
_ac = [{"lat": 48.0, "lon": 34.0, "t": "R135"}, {"lat": 48.0, "lon": 34.0, "t": "H60"},
       {"lat": 10.0, "lon": 10.0, "t": "R135"}]
check("значимые типы отделяются от рутины", A.count_by_zone(_ac, _z)["D"] == (2, 1))

print(f"\n{'='*46}\nпройдено {ok}, провалено {fail}\n{'='*46}")
sys.exit(1 if fail else 0)
