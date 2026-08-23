"""Тесты расчёта. Сети не требуют: события генерируются здесь же.

Проверяется не «работает ли код», а ровно те места, где ошибка не падает,
а тихо портит число: пороги фаз, гистерезис, знак Голдштейна, поведение при
отсутствии данных и то, что веса блоков НЕ перенормируются.
"""
import sys, pathlib, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from datetime import date, timedelta

from escx import compute as comp, db, dyads as dy, weights as wt

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  [ok]   {name}")
    else:    fail += 1; print(f"  [FAIL] {name} {extra}")


TODAY = date(2026, 8, 1)


def ev(day, *, source="ucdp_ged", fat=0, lat=None, lon=None,
       gold=None, mentions=None, root=None, prec=1, sid=None):
    return {"source": source, "occurred_at": day.isoformat(), "fatalities": fat,
            "lat": lat, "lon": lon, "goldstein": gold, "num_mentions": mentions,
            "date_prec": prec, "event_type": f"cameo:{root}" if root else None}


print("\n1. Корзины и окна")
evs = [ev(TODAY - timedelta(days=i), fat=2, lat=10.0, lon=20.0) for i in range(40)]
b = comp.bucket(evs)
COV = {"kinetic": (TODAY - timedelta(days=400), TODAY),
       "informational": (TODAY - timedelta(days=400), TODAY)}
v = comp.raw_values(b, TODAY, {}, COV)
check("окно кинетики ровно 30 дней", v["kin_events"] == 30, v["kin_events"])
check("погибшие суммируются по окну", v["kin_fatalities"] == 60, v["kin_fatalities"])
check("гео-ячейки схлопываются", v["kin_geo"] == 1, v["kin_geo"])

b2 = comp.bucket([ev(TODAY, fat=100, prec=4)])
check("событие с точностью до месяца в кинетику не идёт",
      comp.raw_values(b2, TODAY, {}, COV)["kin_fatalities"] == 0)

print("\n2. Инфополе")
b3 = comp.bucket([ev(TODAY, source="gdelt_export", gold=-8.0, mentions=10, root="19"),
                  ev(TODAY, source="gdelt_export", gold=+2.0, mentions=1, root="04")])
v3 = comp.raw_values(b3, TODAY, {TODAY: 1000.0}, COV)
check("знак перевёрнут: конфликт даёт положительное давление",
      v3["inf_pressure"] > 0, v3["inf_pressure"])
check("Голдштейн взвешен на упоминания, а не усреднён в лоб",
      abs(v3["inf_pressure"] - 7.0909) < 0.01, v3["inf_pressure"])
check("доля считается от мирового объёма", abs(v3["inf_share"] - 0.011) < 0.001,
      v3["inf_share"])
check("без мирового объёма доля не выдумывается",
      comp.raw_values(b3, TODAY, {}, COV)["inf_share"] is None)

# Прокси кинетики из CAMEO. Главное здесь — что он НЕ становится счётчиком
# медиавнимания: доля силовых событий не должна расти от того, что одно и то же
# событие процитировали больше раз.
big = ([ev(TODAY, source="gdelt_export", gold=-8.0, mentions=10, root="19")] * 20
       + [ev(TODAY, source="gdelt_export", gold=+2.0, mentions=1, root="04")] * 20)
vbig = comp.raw_values(comp.bucket(big), TODAY, {TODAY: 1e6}, COV)
check("доля силовых событий: двадцать из сорока",
      abs(vbig["inf_violence"] - 0.5) < 1e-9, vbig["inf_violence"])
check("на малой выборке доля не выдаётся за измерение",
      v3["inf_violence"] is None, v3["inf_violence"])
b3x = comp.bucket([ev(TODAY, source="gdelt_export", gold=-8.0, mentions=10000, root="19"),
                   ev(TODAY, source="gdelt_export", gold=+2.0, mentions=1, root="04")])
bigx = ([ev(TODAY, source="gdelt_export", gold=-8.0, mentions=10000, root="19")] * 20
        + [ev(TODAY, source="gdelt_export", gold=+2.0, mentions=1, root="04")] * 20)
check("цитируемость не раздувает долю насилия",
      comp.raw_values(comp.bucket(bigx), TODAY, {TODAY: 1e6}, COV)["inf_violence"]
      == vbig["inf_violence"])
b3y = comp.bucket([ev(TODAY, source="gdelt_export", gold=+2.0, mentions=5, root="04")] * 40)
check("ноль силовых событий — это 0.0, а не «нет данных»",
      comp.raw_values(b3y, TODAY, {TODAY: 1000.0}, COV)["inf_violence"] == 0.0)
b3z = comp.bucket([ev(TODAY, fat=1)])          # только UCDP, медиапотока нет
check("отсутствие медиапотока — None, а не ноль",
      comp.raw_values(b3z, TODAY, {TODAY: 1000.0}, COV)["inf_violence"] is None)
check("прокси живёт в инфоблоке, а не в кинетическом",
      comp.INDICATORS["inf_violence"] == "informational")

print("\n2a. Санкции: событие — это дельта, а не список")
from escx import sanctions as sanc
def sev(day, sign):
    return {"source": "ofac_sdn", "source_id": f"x{sign}{day}",
            "occurred_at": day.isoformat(), "dyad_id": "IRN-USA",
            "match_level": "rule", "fatalities": None, "lat": None, "lon": None,
            "goldstein": None, "num_mentions": None, "date_prec": None,
            "cameo_code": None,
            "event_type": "sanction_add" if sign > 0 else "sanction_lift"}
COV_E = {**COV, "economic": (TODAY, TODAY)}
bs = comp.bucket([sev(TODAY, +1)] * 5 + [sev(TODAY, -1)] * 2)
check("введения и снятия складываются со знаком",
      comp.raw_values(bs, TODAY, {}, COV_E)["eco_sanctions"] == 3.0,
      comp.raw_values(bs, TODAY, {}, COV_E)["eco_sanctions"])
check("ноль изменений — это 0.0, измеренная тишина",
      comp.raw_values(comp.bucket([]), TODAY, {}, COV_E)["eco_sanctions"] == 0.0)
check("вне периода источника — не ноль, а None",
      comp.raw_values(bs, TODAY, {}, COV)["eco_sanctions"] is None)
check("санкции живут в экономическом блоке",
      comp.INDICATORS["eco_sanctions"] == "economic")
# Главный инвариант: пара без привязки программ не получает нулей и не надувает
# покрытие. Проверяется на самой таблице привязок, а не на моке.
ch = sanc.dyads_with_channel()
check("канал есть не у всех пар", 0 < len(ch) < 21, len(ch))
check("пары без канала в таблице отсутствуют", "EGY-ETH" not in ch)

print("\n2b. Дипломатия: годовой замер со сроком годности")
COV_D = {**COV, "diplomatic": (date(1946, 1, 1), TODAY)}
empty = comp.bucket([])
check("свежий замер попадает в индикатор",
      comp.raw_values(empty, TODAY, {}, COV_D, (TODAY.year, 4.02))["dip_distance"] == 4.02)
check("замер позапрошлого года ещё годен",
      comp.raw_values(empty, TODAY, {}, COV_D, (TODAY.year - 2, 0.8))["dip_distance"] == 0.8)
# Китай — Тайвань: последний общий замер стоит 1971 годом, когда Тайвань
# потерял место в ООН. Показать его как сегодняшнюю дипломатию — соврать на полвека.
check("замер полувековой давности отбрасывается",
      comp.raw_values(empty, TODAY, {}, COV_D, (1971, 1.476))["dip_distance"] is None)
check("нет замера — нет значения",
      comp.raw_values(empty, TODAY, {}, COV_D, None)["dip_distance"] is None)
check("дипломатия — свой блок, а не довесок к инфополю",
      comp.INDICATORS["dip_distance"] == "diplomatic")

print("\n2c. Потолок шкалы: 100 зарезервировано за применением ОМП")
from escx.indicators import heat as H, Z_CAP, HEAT_MAX
# До правки Россия — Украина стояла ровно на 100 при фазе 5 из 7: дальше
# ухудшаться было некуда, и любое развитие событий не отражалось в числе.
check("накал не достигает 100 ни при каком z", H({"kinetic": 10 ** 6}) <= HEAT_MAX)
check("верх шкалы оставлен под абсолютный предел", HEAT_MAX < 100)
# Робастный z в 174 означает вырожденную опору, а не конец света.
check("вырожденная опора не упирает шкалу в потолок",
      abs(H({"kinetic": 174}) - H({"kinetic": Z_CAP})) < 1e-9)
check("обычные значения не тронуты", abs(H({"kinetic": 2}) - 60.8) < 0.1)
check("ступень ОМП есть в лестнице",
      comp.PHASES[7] == "Применение оружия массового поражения")
# Автоматически она не выставляется: источника, подтверждающего применение
# ядерного оружия, в пайплайне нет и быть не может.
check("автоматически седьмая фаза не выставляется",
      comp.phase_rule(10 ** 9, 10 ** 9, {"15": 10 ** 6})[0] <= 6)

print("\n2d. Калибровка: метрика опережения")
from escx import calibrate as CAL
S=CAL.load_set()
check("набор конфликтов не пуст и не крошечный", 15 <= len(S) <= 40, len(S))
check("у каждого есть дата развязки и тип исхода",
      all(x.get("resolved") and x.get("outcome") for x in S))
check("у каждого есть идентификатор конфликта UCDP",
      all(x.get("conflict_id") for x in S))
# Ошибка первая: «просто выше порога» даёт 36 месяцев конфликту, который
# все три года шёл на высокой интенсивности. Сигнала там не было — был фон.
check("фон выше порога сигналом не считается",
      CAL.lead_months([80.0] * 10)[0] is None)
# Ошибка вторая: «переход без возврата ниже» не проходит НИ ОДИН конфликт,
# потому что развязка означает прекращение боёв и падение накала.
check("падение накала после развязки не отменяет сигнал",
      CAL.lead_months([50, 50, 80, 80, 40])[0] == 2,
      CAL.lead_months([50, 50, 80, 80, 40]))
check("переход считается от первого пересечения снизу вверх",
      CAL.lead_months([50, 70, 50, 70])[0] == 2)
check("недостигнутый порог — не сигнал",
      CAL.lead_months([50, 55, 60])[0] is None)
check("окно кончается месяцем развязки",
      CAL.window_months("2009-05-18")[-1] == "2009-05")
check("длина окна равна заявленной",
      len(CAL.window_months("2009-05-18")) == CAL.WINDOW_M + 1)

check("переходы считаются все, а не только первый",
      CAL.crossings([50, 70, 50, 70, 50, 70]) == [1, 3, 5])
check("месяцы разворачиваются без пропусков",
      CAL.all_months({"1999-11": 1, "2000-02": 1}) ==
      ["1999-11", "1999-12", "2000-01", "2000-02"])
check("горизонт контроля задан явно", CAL.HORIZON_M > 0)

print("\n2e. Военная авиация: наблюдение против тишины")
COV_M = {**COV, "military": (TODAY - timedelta(days=9), TODAY)}
air = {TODAY - timedelta(days=k): 2.0 for k in range(3)}
check("среднее по окну, а не сумма",
      comp.raw_values(comp.bucket([]), TODAY, {}, COV_M, None, air)["mil_air"] == 2.0)
# Главное здесь: ноль бортов и ОТСУТСТВИЕ наблюдения — разные вещи. Именно
# там, где вещать перестают, обычно и происходит интересное.
check("зона без наблюдения даёт None, а не ноль",
      comp.raw_values(comp.bucket([]), TODAY, {}, COV_M, None, None)["mil_air"] is None)
check("измеренный ноль остаётся нулём",
      comp.raw_values(comp.bucket([]), TODAY, {}, COV_M, None,
                      {TODAY: 0.0})["mil_air"] == 0.0)
check("авиация — военный блок", comp.INDICATORS["mil_air"] == "military")
# Неделя, а не восемь часов: над базой понедельник утром и воскресенье ночью —
# разное небо, и без полного цикла отклонение считалось бы от времени суток.
check("норма зоны требует недели наблюдений", comp.AIR_MIN_HOURS >= 24 * 7)

print("\n3. Пороги фаз — числа UCDP, не наши")
check("1000 смертей -> война", comp.phase_rule(1000, 50, {})[0] == 5)
check("999 смертей -> ограниченный конфликт", comp.phase_rule(999, 50, {})[0] == 4)
check("25 смертей -> ограниченный конфликт", comp.phase_rule(25, 5, {})[0] == 4)
check("24 смерти -> вооружённые инциденты", comp.phase_rule(24, 5, {})[0] == 3)
check("применение силы без жертв -> фаза 3", comp.phase_rule(0, 1, {})[0] == 3)
check("фазы 3-5 всегда основаны на UCDP", comp.phase_rule(30, 3, {})[1] == "ucdp")
check("санкции и демонстрация силы -> кризис",
      comp.phase_rule(0, 0, {"16": 4})[0] == 2)
check("кризис по медиа помечен как медийный",
      comp.phase_rule(0, 0, {"16": 4})[1] == "media")
check("угрозы -> напряжённость", comp.phase_rule(0, 0, {"13": 3})[0] == 1)
check("одна строка GDELT фазу не поднимает", comp.phase_rule(0, 0, {"16": 1})[0] == 0)

print("\n4. Гистерезис: вверх сразу, вниз через 90 дней")
d0 = date(2026, 1, 1)
seq = ([(d0 + timedelta(days=i), 1, "media") for i in range(10)]
       + [(d0 + timedelta(days=10), 4, "ucdp")]
       + [(d0 + timedelta(days=11 + i), 1, "media") for i in range(120)])
res = dict((d, p) for d, p, _ in comp.apply_hysteresis(seq))
check("повышение мгновенное", res[d0 + timedelta(days=10)] == 4)
check("через 60 дней фаза ещё держится", res[d0 + timedelta(days=70)] == 4)
check("через 90 дней тишины фаза падает", res[d0 + timedelta(days=101)] == 1)

print("\n5. Веса последствий")
sh = {"pop": {"IND": 17.8, "PAK": 3.0, "GRC": 0.13, "TUR": 1.06},
      "gdp": {"IND": 7.9, "PAK": 0.4, "GRC": 0.3, "TUR": 1.9},
      "mil": {"IND": 3.4, "PAK": 0.4, "GRC": 0.3, "TUR": 0.7}}
c_ip = wt.consequence("IND", "PAK", sh)
c_gt = wt.consequence("GRC", "TUR", sh)
check("две ядерные стороны дают множитель 3.6",
      wt.nuclear_mult("IND", "PAK") == 3.6)
check("диада ядерных держав весит больше неядерной", c_ip > c_gt, (c_ip, c_gt))
check("сжатие 0.62 не даёт весу расти линейно", c_ip / c_gt < 20, c_ip / c_gt)
check("страна без данных -> веса нет, а не ноль",
      wt.consequence("IND", "CHN", sh) is None)
check("союзная связность у члена НАТО выше",
      wt.alliance_density("GRC", "TUR") > wt.alliance_density("IND", "PAK"))

print("\n6. Полный прогон на синтетической базе")
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
con = db.connect(tmp)
dy.install(con, dy.load())
rows = []
for i in range(400):
    d = TODAY - timedelta(days=i)
    # ровный фон плюс всплеск в последнюю неделю — так видно, что z работает
    n = 8 if i < 7 else 1
    for j in range(n):
        rows.append({"source": "ucdp_ged", "source_id": f"{i}-{j}",
                     "occurred_at": d.isoformat(), "dyad_id": "IND-PAK",
                     "match_level": "rule", "fatalities": 3,
                     "lat": 34.0 + j * 0.6, "lon": 74.0, "date_prec": 1})
db.upsert_events(con, rows)
r = comp.compute(con, days=30, today=TODAY)
check("прогон отработал", r.get("heat_rows", 0) > 0, r)

hot = con.execute("SELECT h_abs, h_rel, data_coverage, tempo FROM heat_daily "
                  "WHERE dyad_id='IND-PAK' ORDER BY day DESC LIMIT 1").fetchone()
old = con.execute("SELECT h_abs FROM heat_daily WHERE dyad_id='IND-PAK' "
                  "ORDER BY day ASC LIMIT 1").fetchone()
check("всплеск поднял накал", hot["h_abs"] > old["h_abs"], (hot["h_abs"], old["h_abs"]))
check("накал в границах шкалы", 0 <= hot["h_abs"] <= 100, hot["h_abs"])
check("покрытие считается от пяти блоков, а не от имеющихся",
      hot["data_coverage"] <= 40.0, hot["data_coverage"])
check("темп распознал нагрев", hot["tempo"] in ("up", "spike"), hot["tempo"])

ph = con.execute("SELECT phase, phase_basis FROM dyads WHERE dyad_id='IND-PAK'").fetchone()
check("фаза выставлена по смертям (1200 за год -> война)", ph["phase"] == 5, dict(ph))
check("основание фазы — UCDP", ph["phase_basis"] == "ucdp")
check("смена фазы попала в журнал",
      con.execute("SELECT COUNT(*) c FROM phase_log").fetchone()["c"] > 0)

quiet = con.execute("SELECT h_abs, data_coverage FROM heat_daily "
                    "WHERE dyad_id='GRC-TUR' ORDER BY day DESC LIMIT 1").fetchone()
check("диада без событий существует в витрине", quiet is not None)
if quiet:
    check("без данных накал ровно 50, а не ноль", abs(quiet["h_abs"] - 50) < 0.01,
          quiet["h_abs"])
    check("измеренная тишина считается данными (UCDP покрывает весь мир)",
          quiet["data_coverage"] == 20.0, quiet["data_coverage"])

print("\n6a. День вне периода источника — не тишина, а отсутствие данных")
far = comp.raw_values(comp.bucket([]), TODAY - timedelta(days=900), {}, COV)
check("до начала покрытия индикаторы пустые", far["kin_events"] is None, far)

check("повторный прогон не ломается и не дублирует",
      comp.compute(con, days=30, today=TODAY).get("heat_rows", 0) > 0)
check("строк накала столько же, сколько диад × дней",
      con.execute("SELECT COUNT(*) c FROM heat_daily").fetchone()["c"] == r["heat_rows"])

print("\n7. Реестр не теряет фазу при перезаливке")
dy.install(con, dy.load())
check("фаза пережила переустановку реестра",
      con.execute("SELECT phase FROM dyads WHERE dyad_id='IND-PAK'").fetchone()["phase"] == 5)
check("название доехало до базы",
      con.execute("SELECT name FROM dyads WHERE dyad_id='IND-PAK'").fetchone()["name"]
      == "Индия — Пакистан")

print("\nСлова и дела: индекс расхождения")
from escx.indicators import side_heat, WORDS_BLOCKS, DEEDS_BLOCKS, MIN_SIDE_SHARE
_all = {"kinetic": 2.0, "military": 0.0, "economic": 0.0,
        "diplomatic": 0.0, "informational": -1.0}
_w = side_heat(_all, WORDS_BLOCKS)
_d = side_heat(_all, DEEDS_BLOCKS)
check("слова и дела считаются по своим блокам", _w is not None and _d is not None)
check("дела жёстче слов при боях без огласки", _d > _w, f"{_d:.1f} против {_w:.1f}")
check("слова ниже нормы при отрицательном z", _w < 50, _w)

# Веса перенормируются внутри стороны: у инфополя вес 0.15, и без
# перенормировки риторика упиралась бы в 50 при любом накале.
_hot = side_heat({"informational": 3.0}, WORDS_BLOCKS)
check("риторика доходит до верха шкалы", _hot > 80, _hot)

# Сторона, измеренная меньше чем наполовину, не сторона. Поймано на живых
# данных: без этого порога Россия с Украиной получали ярлык «угрозы без дел»
# посреди войны — потому что кинетика ещё не опубликована, и «дела»
# схлопывались до одной дипломатии.
check("одна дипломатия из четырёх блоков делами не считается",
      side_heat({"diplomatic": 3.0}, DEEDS_BLOCKS) is None)
check("кинетика с дипломатией уже считаются",
      side_heat({"kinetic": 1.0, "diplomatic": 1.0}, DEEDS_BLOCKS) is not None)
check("пустая сторона даёт None", side_heat({}, DEEDS_BLOCKS) is None)
check("порог доли задан явно", 0 < MIN_SIDE_SHARE <= 1, MIN_SIDE_SHARE)


print("\nТемп: пороги и защита от смены покрытия")
from escx.indicators import tempo as _tempo, TEMPO_D30, TEMPO_D7, COV_TOLERANCE

# Пороги откалиброваны замером: ±8 и +15 из первой редакции срабатывали в 1.3%
# и 0% дней. «Резкая эскалация» была недостижима по построению.
check("порог месяца ниже прежних восьми", TEMPO_D30 < 8, TEMPO_D30)
check("порог недели ниже прежних пятнадцати", TEMPO_D7 < 15, TEMPO_D7)

_C = dict(cov_now=40.0, cov_7=40.0, cov_30=40.0)
check("нагрев распознан", _tempo(60, 58, 60 - TEMPO_D30 - 1, 2, None, **_C) == "up")
check("разрядка распознана", _tempo(50, 50, 50 + TEMPO_D30 + 1, 2, None, **_C) == "down")
check("плато остаётся плато", _tempo(50, 50, 50, 2, None, **_C) == "flat")
check("скачок распознан и перебивает спокойный месяц",
      _tempo(60, 60 - TEMPO_D7 - 1, 60, 2, None, **_C) == "spike")
check("заморозка требует фазы и года без боёв", _tempo(60, 60, 60, 4, 400, **_C) == "frozen")
check("заморозки нет при свежих боях", _tempo(60, 60, 60, 4, 10, **_C) == "flat")

# СМЕНА ПОКРЫТИЯ НЕ ЕСТЬ ИЗМЕНЕНИЕ КОНФЛИКТА. Поймано на живых данных: 1 июля
# 2026 кончились кандидатские данные UCDP, покрытие Украины упало с 60% до 40%,
# накал с 73.6 до 60.2 — и это прочиталось бы как «Разрядка» посреди войны.
_drop = _tempo(60.2, 60.2, 73.6, 5, 1, cov_now=40.0, cov_7=40.0, cov_30=60.0)
check("падение накала из-за потери источника не считается разрядкой", _drop is None, _drop)
check("при том же покрытии то же падение — разрядка",
      _tempo(60.2, 60.2, 73.6, 5, 1, cov_now=40.0, cov_7=40.0, cov_30=40.0) == "down")
check("скачок недели проходит, если недельное покрытие совпало",
      _tempo(60, 50, 60, 2, None, cov_now=40.0, cov_7=40.0, cov_30=60.0) == "spike")
check("допуск покрытия не съедает уход целого блока", COV_TOLERANCE < 20, COV_TOLERANCE)
check("без данных о покрытии темп считается как раньше", _tempo(60, 58, 50, 2, None) == "up")

print("\n" + "=" * 46)
print(f"пройдено {ok}, провалено {fail}")
print("=" * 46)
sys.exit(1 if fail else 0)
