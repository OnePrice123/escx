"""Расчёт: сырые события -> индикаторы -> накал -> фаза.

Это недостающее звено между сбором и витриной. `pull-gdelt` и `backfill-ucdp`
кладут события в `raw_events`; сборщик сайта читает `heat_daily` и `dyads`.
Пока никто не считает то, что между ними, сайт честно показывает пустой реестр
— именно это и происходило до появления этого модуля.

Что здесь считается и чего НЕ считается:

  * блок «кинетика» — из UCDP (события, боевые смерти, охват географии);
  * блок «инфополе» — из GDELT (взвешенный Голдштейн и доля в мировом потоке);
  * блоки «военный», «дипломатический», «экономический» источников пока не имеют.

Веса блоков при этом НЕ пересчитываются на имеющиеся. Соблазн велик: разделить
0.35 и 0.15 так, чтобы в сумме была единица, и получить «полноценное» число.
Но это ровно то, против чего правило 6 методологии: отсутствие данных не есть
отсутствие риска. При двух блоках из пяти сумма весов равна 0.5, накал тянется
к 50, и рядом стоит coverage = 40 — читатель видит, что половина картины не
измерена. Так честнее, чем уверенное число из четверти источников.

Опорные величины (медиана и MAD) считаются один раз на прогон, а не скользящим
окном: скользящее требует пересчёта на каждый день каждой диады и на реальных
объёмах превращает минутный прогон в часовой. Из опорного окна исключены
последние 30 дней — иначе сегодняшний всплеск сам себя нормирует и исчезает.
"""
from __future__ import annotations
import statistics as st
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import sanctions
from .indicators import BLOCK_WEIGHTS, MAD_K, heat, robust_z, tempo, winsorize

METHOD_VERSION = "0.3.1"

WIN_KIN = 30          # окно кинетики, дней
WIN_INF = 7           # окно инфополя: медиа реагируют быстрее
SERIES_DAYS = 90      # длина ряда для спарклайна на витрине
WARMUP_DAYS = 365     # сколько истории нужно, чтобы z был осмысленным
REF_LAG = 30          # хвост, исключённый из опорного окна

# индикатор -> блок. Ключи попадают в indicator_daily как есть.
INDICATORS = {
    "kin_events":     "kinetic",
    "kin_fatalities": "kinetic",
    "kin_geo":        "kinetic",
    "inf_pressure":   "informational",
    "inf_share":      "informational",
    "inf_violence":   "informational",
    "eco_sanctions":  "economic",
}

# Корни CAMEO, означающие применение силы: 18 — нападение, 19 — бой,
# 20 — неконвенциональное массовое насилие. Кодбук GDELT, раздел QuadClass 4.
CAMEO_VIOLENCE = {"18", "19", "20"}

# Минимальный размер выборки для доли силовых событий.
#
# Поймано на живых данных: у пары Египет — Эфиопия за окно набралось ШЕСТЬ
# событий, пять из них с кодом 190. Доля 83 % вынесла спор о плотине на первое
# место по накалу — выше России и Украины, где событий в окне 1960. Пропорция,
# посчитанная по шести наблюдениям, не значит ничего: её доверительный интервал
# шире самой шкалы.
#
# 30 — не подобранное число, а порог, ниже которого доля перестаёт отличаться
# от шума на глаз. Ниже него индикатор отдаёт None: «не измерено» честнее
# уверенной цифры из шести строк GDELT, половина которых — ошибки кодирования.
VIOLENCE_MIN_EVENTS = 30
# Все пять блоков методологии. Отсутствующие остаются пустыми — и видны в coverage.
ALL_BLOCKS = list(BLOCK_WEIGHTS)

UCDP_SOURCES = ("ucdp_ged", "ucdp_candidate")

PHASES = {0: "Нормализация", 1: "Напряжённость", 2: "Кризис",
          3: "Вооружённые инциденты", 4: "Ограниченный конфликт",
          5: "Война", 6: "Расширенная война"}

# CAMEO-корни для фаз 1–2. Взяты из кодбука: 15 — демонстрация силы,
# 16 — разрыв отношений и санкции, 11–13 — осуждение, отказ, угроза.
CAMEO_CRISIS = {"15", "16"}
CAMEO_TENSION = {"11", "12", "13"}
MEDIA_MIN_EVENTS = 3      # порог против единичной ошибки кодирования GDELT


# --------------------------------------------------------------------------
# Вспомогательное
# --------------------------------------------------------------------------
def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except ValueError:
        return None


def _ref(values: list[float]) -> tuple[float, float]:
    """Опорные медиана и MAD. MAD=0 (ряд почти константа) -> берём pstdev."""
    v = winsorize([x for x in values if x is not None])
    if len(v) < 8:
        return (0.0, 0.0)
    med = st.median(v)
    mad = st.median([abs(x - med) for x in v])
    if mad == 0:
        sd = st.pstdev(v)
        return (med, sd / MAD_K if sd else 0.0)
    return (med, mad)


def _z(x: float, ref: tuple[float, float]) -> float:
    med, mad = ref
    return 0.0 if not mad else (x - med) / (MAD_K * mad)


# --------------------------------------------------------------------------
# Дневные срезы
# --------------------------------------------------------------------------
def bucket(events: list[dict]) -> dict[date, dict]:
    """Сырьё -> суточные корзины. Дальше всё считается только по ним.

    События с date_prec >= 3 (дата известна лишь до месяца или года) в кинетику
    не идут: положив их в 30-дневное окно, мы размажем один бой по всему месяцу.
    В медиапоток они не попадают по построению — у GDELT дата всегда суточная.
    """
    out: dict[date, dict] = defaultdict(
        lambda: {"kin_n": 0, "kin_fat": 0, "cells": set(),
                 "g_num": 0.0, "g_den": 0.0, "mentions": 0.0,
                 "med_n": 0, "med_viol": 0, "sanc": 0,
                 "cameo": defaultdict(int)})
    for e in events:
        d = _d(e["occurred_at"])
        if not d:
            continue
        b = out[d]
        if e["source"] == "ofac_sdn":
            # Введение меры и снятие — одно событие с разным знаком. Складываем,
            # а не считаем по отдельности: неделя, где ввели десять мер и сняли
            # десять, по смыслу ближе к нулю, чем к двадцати.
            b["sanc"] += 1 if e["event_type"] == "sanction_add" else -1
        elif e["source"] in UCDP_SOURCES:
            if (e["date_prec"] or 1) >= 3:
                continue
            b["kin_n"] += 1
            b["kin_fat"] += e["fatalities"] or 0
            if e["lat"] is not None and e["lon"] is not None:
                b["cells"].add((round(e["lat"] * 2) / 2, round(e["lon"] * 2) / 2))
        else:
            m = e["num_mentions"] or 1
            if e["goldstein"] is not None:
                b["g_num"] += e["goldstein"] * m
                b["g_den"] += m
            b["mentions"] += m
            root = (e["event_type"] or "").replace("cameo:", "")[:2]
            if root:
                b["cameo"][root] += 1
            # Доля насилия считается по СОБЫТИЯМ, а не по упоминаниям: одна
            # перестрелка, которую процитировали двести раз, не есть двести
            # перестрелок. Упоминания уже учтены в inf_share, где они и уместны.
            b["med_n"] += 1
            if root in CAMEO_VIOLENCE:
                b["med_viol"] += 1
    return out


def raw_values(buckets: dict[date, dict], day: date,
               global_mentions: dict[date, float],
               covered: dict[str, tuple[date, date] | None] | None = None
               ) -> dict[str, float | None]:
    """Значения индикаторов на день. None = данных нет, а не ноль.

    Различие между «ноль событий» и «источник не отработал» — не придирка.
    UCDP покрывает весь мир: ноль боевых смертей у диады означает измеренную
    тишину, и это ценный сигнал. А вот день, до которого бэкфилл не дошёл, тоже
    даёт ноль — и выглядит точно такой же тишиной. Поэтому дни вне периода,
    покрытого источником, отдают None: пусть индикатор пропадёт и покрытие
    просядет, чем спокойное число, за которым ничего нет.

    covered — {'kinetic': (первый день, последний), 'informational': ...}.
    """
    kin_n = kin_fat = 0
    sanc = 0
    cells: set = set()
    for i in range(WIN_KIN):
        b = buckets.get(day - timedelta(days=i))
        if b:
            kin_n += b["kin_n"]
            kin_fat += b["kin_fat"]
            cells |= b["cells"]
            sanc += b["sanc"]

    g_num = g_den = mentions = 0.0
    med_n = med_viol = 0
    glob = 0.0
    for i in range(WIN_INF):
        d = day - timedelta(days=i)
        b = buckets.get(d)
        if b:
            g_num += b["g_num"]
            g_den += b["g_den"]
            mentions += b["mentions"]
            med_n += b["med_n"]
            med_viol += b["med_viol"]
        glob += global_mentions.get(d, 0.0)

    # Голдштейн: −10 (нападение) .. +10 (уступка). Переворачиваем знак, чтобы
    # у всех индикаторов «больше» значило «хуже» — иначе знак веса блока
    # придётся помнить в двух местах и однажды перепутать.
    pressure = -(g_num / g_den) if g_den else None
    share = (mentions / glob) if glob else None

    # Доля силовых событий в медиапотоке пары. Это ПРОКСИ кинетики, а не её
    # замена: UCDP считает подтверждённые боевые смерти, GDELT — сообщения.
    # Поэтому индикатор живёт в блоке «инфополе» рядом с тоном и объёмом, а не
    # в кинетическом: сложить их в один блок значило бы выдать медиапоток за
    # измерение и удвоить один и тот же сигнал.
    #
    # Ноль событий вообще и ноль СИЛОВЫХ событий — разные вещи: первое None
    # (не измерено), второе 0.0 (измеренная тишина).
    violence = (med_viol / med_n) if med_n >= VIOLENCE_MIN_EVENTS else None

    out = {
        "kin_events": float(kin_n),
        "kin_fatalities": float(kin_fat),
        "kin_geo": float(len(cells)),
        "inf_pressure": pressure,
        "inf_share": share,
        "inf_violence": violence,
        # Чистое изменение числа мер за 30 дней. Ноль здесь ЗНАЧИМ: он говорит
        # «список смотрели, ничего не менялось», и это измеренная тишина, а не
        # отсутствие данных. Отсутствие данных задаётся ниже, через covered.
        "eco_sanctions": float(sanc),
    }
    for key, block in INDICATORS.items():
        span = (covered or {}).get(block)
        if span is None or not (span[0] <= day <= span[1]):
            out[key] = None
    return out


# --------------------------------------------------------------------------
# Фаза
# --------------------------------------------------------------------------
def phase_rule(fat_365: int, force_365: int, cameo_30: dict[str, int]) -> tuple[int, str]:
    """Фаза по правилам раздела 2 методологии. Возвращает (фаза, основание).

    Пороги 25 и 1000 — UCDP/PRIO, не наши. Фазы 3–5 стоят на измеренных боевых
    смертях, и это самое твёрдое, что здесь есть.

    Фазы 1–2 в методологии определяются через санкции, отзыв послов, мобилизацию.
    Реестров санкций и дипломатических нот в пайплайне пока нет, поэтому они
    выводятся из кодов CAMEO и помечаются основанием 'media': это индикатор
    медиапотока, а не документ. Ниже порога в три события — фаза 0, потому что
    единственная строка GDELT слишком часто оказывается ошибкой кодирования.
    """
    if fat_365 >= 1000:
        return 5, "ucdp"
    if fat_365 >= 25:
        return 4, "ucdp"
    if force_365 > 0:
        return 3, "ucdp"
    crisis = sum(n for r, n in cameo_30.items() if r in CAMEO_CRISIS)
    if crisis >= MEDIA_MIN_EVENTS:
        return 2, "media"
    tension = sum(n for r, n in cameo_30.items() if r in CAMEO_TENSION)
    if tension >= MEDIA_MIN_EVENTS:
        return 1, "media"
    return 0, "media"


def apply_hysteresis(series: list[tuple[date, int, str]],
                     cooldown: int = 90) -> list[tuple[date, int, str]]:
    """Защита от дребезга (раздел 2.1): вверх сразу, вниз — через 90 дней.

    Асимметрия намеренная и повторяет реальность: эскалация происходит за день,
    деэскалация признаётся месяцами. Без неё фаза мигала бы на каждом затишье,
    а журнал фаз превратился бы в шум.
    """
    out = []
    cur, basis, since_lower = None, "", None
    for day, want, wb in series:
        if cur is None or want > cur:
            cur, basis, since_lower = want, wb, None
        elif want < cur:
            if since_lower is None:
                since_lower = day
            if (day - since_lower).days >= cooldown:
                cur, basis, since_lower = want, wb, None
        else:
            since_lower = None
        out.append((day, cur, basis))
    return out


# --------------------------------------------------------------------------
# Главный проход
# --------------------------------------------------------------------------
def compute(con, *, days: int = SERIES_DAYS, today: date | None = None) -> dict:
    """Пересчитывает indicator_daily, heat_daily, phase_log и фазу в dyads.

    days — сколько последних дней записать в витрину. История глубже нужна
    всё равно: без неё не из чего считать опорные величины.
    """
    run_id = uuid.uuid4().hex[:12]
    today = today or datetime.now(timezone.utc).date()
    con.execute("INSERT INTO runs(run_id,started,status) VALUES(?,?,?)",
                (run_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), "running"))

    dyads = [dict(r) for r in con.execute(
        "SELECT dyad_id, name, phase FROM dyads WHERE status='active' ORDER BY dyad_id")]
    if not dyads:
        return {"run_id": run_id, "dyads": 0, "days": 0, "note": "реестр пуст"}

    # Мировой объём упоминаний за сутки — знаменатель для доли покрытия.
    # Без него доля превращается в абсолютный объём, то есть в измеритель
    # внимания прессы. Пишется при сборе GDELT в таблицу series.
    global_mentions: dict[date, float] = {}
    for r in con.execute("SELECT as_of, value FROM series "
                         "WHERE source='gdelt' AND series_key='global_mentions'"):
        d = _d(r["as_of"])
        if d:
            global_mentions[d] = (global_mentions.get(d, 0.0) or 0.0) + (r["value"] or 0.0)

    # 1. Сырьё по диадам
    # Периоды, реально покрытые источниками. Считаются по всей базе, а не по
    # диаде: у тихой пары своих событий может не быть вовсе, но источник по ней
    # отработал — и это именно измеренная тишина.
    covered: dict[str, tuple[date, date] | None] = {}
    for block, srcs in (("kinetic", UCDP_SOURCES), ("informational", ("gdelt_export",)),
                        ("economic", ("ofac_sdn",))):
        marks = ",".join("?" * len(srcs))
        r = con.execute(f"SELECT MIN(occurred_at) a, MAX(occurred_at) b FROM raw_events "
                        f"WHERE source IN ({marks})", srcs).fetchone()
        a, b = _d(r["a"]), _d(r["b"])
        covered[block] = (a, b) if a and b else None

    sanc_channel = sanctions.dyads_with_channel()

    buckets: dict[str, dict[date, dict]] = {}
    first_day = today
    for d in dyads:
        rows = [dict(r) for r in con.execute(
            "SELECT source, occurred_at, fatalities, lat, lon, goldstein, "
            "       num_mentions, date_prec, event_type "
            "FROM raw_events WHERE dyad_id=? ORDER BY occurred_at", (d["dyad_id"],))]
        b = bucket(rows)
        buckets[d["dyad_id"]] = b
        if b:
            first_day = min(first_day, min(b))

    span_start = max(first_day, today - timedelta(days=WARMUP_DAYS + days))
    all_days = [span_start + timedelta(days=i)
                for i in range((today - span_start).days + 1)]
    if len(all_days) < 2:
        return {"run_id": run_id, "dyads": len(dyads), "days": 0, "note": "нет событий"}

    # 2. Сырые значения индикаторов по всем дням
    raw: dict[str, dict[date, dict]] = {}
    for d in dyads:
        b = buckets[d["dyad_id"]]
        # Покрытие экономического блока — ПОДИАДНОЕ, в отличие от остальных.
        # Санкционный источник меряет не все пары, а только те, для которых
        # есть привязка программ. У прочих блок обязан остаться неизмеренным:
        # ноль означал бы «мер не вводили», и покрытие выросло бы до 40 % у
        # всех двадцати при реальном сигнале у трёх. Это ровно тот самообман,
        # против которого покрытие и придумано.
        cov_d = dict(covered)
        if d["dyad_id"] not in sanc_channel:
            cov_d["economic"] = None
        raw[d["dyad_id"]] = {day: raw_values(b, day, global_mentions, cov_d)
                             for day in all_days}

    # 3. Опорные величины. Хвост в REF_LAG дней отрезан: иначе сегодняшний
    #    всплеск попадает в собственную норму и сам себя гасит.
    ref_days = [x for x in all_days if x <= today - timedelta(days=REF_LAG)] or all_days
    ref_abs: dict[str, tuple[float, float]] = {}      # по всему пулу диад
    ref_rel: dict[tuple[str, str], tuple[float, float]] = {}   # по истории диады
    for key in INDICATORS:
        pool = [raw[dd["dyad_id"]][day][key] for dd in dyads for day in ref_days]
        ref_abs[key] = _ref([v for v in pool if v is not None])
        for dd in dyads:
            own = [raw[dd["dyad_id"]][day][key] for day in ref_days]
            ref_rel[(dd["dyad_id"], key)] = _ref([v for v in own if v is not None])

    # 4. Накал, темп, фаза
    out_days = [x for x in all_days if x > today - timedelta(days=days)]
    ind_rows, heat_rows, phase_rows = [], [], []

    for d in dyads:
        did = d["dyad_id"]
        b = buckets[did]
        h_abs_by_day: dict[date, float] = {}
        h_rel_by_day: dict[date, float] = {}
        cov_by_day: dict[date, float] = {}

        for day in all_days:
            vals = raw[did][day]
            z_abs = defaultdict(list)
            z_rel = defaultdict(list)
            for key, block in INDICATORS.items():
                v = vals[key]
                if v is None:
                    continue
                z_abs[block].append(_z(v, ref_abs[key]))
                z_rel[block].append(_z(v, ref_rel[(did, key)]))
            block_abs = {k: sum(v) / len(v) for k, v in z_abs.items() if v}
            block_rel = {k: sum(v) / len(v) for k, v in z_rel.items() if v}
            h_abs_by_day[day] = heat(block_abs)
            h_rel_by_day[day] = heat(block_rel)
            # Покрытие считается по всем пяти блокам методологии, а не по тем,
            # что мы умеем: иначе оно всегда будет 100 и ничего не сообщит.
            cov_by_day[day] = 100.0 * len(block_abs) / len(ALL_BLOCKS)

        # фаза по дням + гистерезис
        want = []
        for day in all_days:
            fat = force = 0
            for i in range(365):
                bb = b.get(day - timedelta(days=i))
                if bb:
                    fat += bb["kin_fat"]
                    force += bb["kin_n"]
            cameo_30: dict[str, int] = defaultdict(int)
            for i in range(30):
                bb = b.get(day - timedelta(days=i))
                if bb:
                    for r, n in bb["cameo"].items():
                        cameo_30[r] += n
            want.append((day, *phase_rule(fat, force, cameo_30)))
        phased = dict((day, (ph, basis)) for day, ph, basis in apply_hysteresis(want))

        prev_phase = d["phase"]
        for day in out_days:
            ph, basis = phased[day]
            h = h_abs_by_day[day]
            h7 = h_abs_by_day.get(day - timedelta(days=7), h)
            h30 = h_abs_by_day.get(day - timedelta(days=30), h)
            last_kin = next((i for i in range(0, 730)
                             if (b.get(day - timedelta(days=i)) or {}).get("kin_n")), None)
            tp = tempo(h, h7, h30, ph, last_kin if last_kin is not None else 10 ** 4)

            heat_rows.append((did, day.isoformat(), round(h, 2),
                              round(h_rel_by_day[day], 2),
                              round(h - h7, 2), round(h - h30, 2),
                              tp, round(cov_by_day[day], 1),
                              raw[did][day]["kin_events"],
                              METHOD_VERSION, run_id))
            for key in INDICATORS:
                v = raw[did][day][key]
                ind_rows.append((did, day.isoformat(), key, v,
                                 None if v is None else round(_z(v, ref_rel[(did, key)]), 4),
                                 0 if v is None else 1))
            if prev_phase is None or ph != prev_phase:
                phase_rows.append((did, day.isoformat(), prev_phase, ph,
                                   f"rule:{basis}", METHOD_VERSION))
                prev_phase = ph

        con.execute("UPDATE dyads SET phase=?, phase_basis=? WHERE dyad_id=?",
                    (phased[out_days[-1]][0], phased[out_days[-1]][1], did))

    # 5. Запись. indicator_daily и heat_daily пересчитываемые — REPLACE.
    #    phase_log только INSERT, это защищено триггером базы.
    con.executemany(
        "INSERT OR REPLACE INTO indicator_daily"
        "(dyad_id,day,indicator_key,raw_value,z_score,fresh) VALUES(?,?,?,?,?,?)", ind_rows)
    con.executemany(
        "INSERT OR REPLACE INTO heat_daily"
        "(dyad_id,day,h_abs,h_rel,delta_7,delta_30,tempo,data_coverage,events_30d,"
        " method_version,run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)", heat_rows)
    con.executemany(
        "INSERT INTO phase_log(dyad_id,changed_at,phase_from,phase_to,rule,method_version)"
        " VALUES(?,?,?,?,?,?)", phase_rows)
    con.execute("UPDATE runs SET finished=?, status=? WHERE run_id=?",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok", run_id))
    con.commit()

    return {"run_id": run_id, "dyads": len(dyads), "days": len(out_days),
            "heat_rows": len(heat_rows), "phase_changes": len(phase_rows),
            "span": f"{all_days[0]} .. {all_days[-1]}"}
