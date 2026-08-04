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
                     "side_a_new_id":750,"side_b_new_id":770,"type_of_violence":1,
                     "best":4,"date_prec":1,"latitude":34.0,"longitude":74.5,
                     "country":"India","side_a":"Government of India"}])
check("id и дата разобраны", u[0]["source_id"] == "88" and u[0]["occurred_at"] == "2026-07-02")
check("GW-коды переведены", (u[0]["actor_a"], u[0]["actor_b"]) == ("IND","PAK"))
check("payload сериализован", json.loads(u[0]["payload"])["country"] == "India")

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

print(f"\n{'='*46}\nпройдено {ok}, провалено {fail}\n{'='*46}")
sys.exit(1 if fail else 0)
