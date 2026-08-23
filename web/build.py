#!/usr/bin/env python3
"""Сборка статического сайта ESCX.

Идея архитектуры, которая делает хостинг бесплатным:
сайт не ходит в базу. Пайплайн раз в сутки считает всё в SQLite, этот скрипт
выгружает результат в несколько JSON-файлов, и получается папка со статикой —
её отдаёт любой бесплатный хостинг без сервера, без базы и без бэкенда.

    python3 web/build.py                 # site/ из ingest/escx.db
    python3 web/build.py --demo          # site/ с выдуманными числами — ТОЛЬКО для работы над дизайном
    python3 -m http.server -d site 8000  # посмотреть локально

ВАЖНО про --demo. Публиковать выдуманные числа под реальными названиями стран нельзя:
человек увидит «Россия — Украина: 91» и решит, что это измерение. Поэтому без базы
собирается не демо, а честное пустое состояние: реестр диад без единой цифры и прямая
подпись, что индекс ещё не рассчитан. Флаг --demo существует только для локальной
работы над вёрсткой и в деплой не попадает.

Зависимостей нет: только стандартная библиотека.
"""
from __future__ import annotations
import argparse, json, math, shutil, sqlite3, sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))
from escx import weights as wt          # noqa: E402  веса последствий для GEI

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DB   = ROOT / "ingest" / "escx.db"

# Список обязан совпадать с лестницей в compute.PHASES. Седьмая ступень —
# абсолютный предел шкалы: автоматически она не выставляется никогда, но
# без неё сборщик отдал бы phase_name = null, если фаза когда-нибудь придёт.
PHASES = ["Нормализация", "Напряжённость", "Кризис", "Вооружённые инциденты",
          "Ограниченный конфликт", "Война", "Расширенная война",
          "Применение оружия массового поражения"]
TEMPO  = {"spike": "Резкая эскалация", "up": "Нагрев", "flat": "Стабильно",
          "down": "Разрядка", "frozen": "Заморозка",
          # Пайплайн отдаёт None, когда сравнивать не с чем: между этим днём и
          # тем, с которым сравниваем, изменилось покрытие. Показываем прямо,
          # а не пустым местом — пустота читается как «ничего не происходит».
          None: "Не сравнить: менялся состав данных"}

# Человеческие имена блоков и индикаторов. Живут здесь, а не в пайплайне:
# это подписи витрины, и переписать их можно, не трогая расчёт.
BLOCK_RU = {"kinetic": "Кинетика", "military": "Военный", "diplomatic": "Дипломатия",
            "economic": "Экономика", "informational": "Инфополе"}
IND_RU = {
    "kin_events": "боевые эпизоды", "kin_fatalities": "боевые смерти",
    "kin_geo": "география боёв", "inf_pressure": "тон сообщений",
    "inf_share": "доля в новостном потоке", "inf_violence": "доля силовых событий",
    "eco_sanctions": "санкционные меры", "dip_distance": "расстояние позиций в ООН",
    "mil_air": "военная авиация в зоне",
}
# Откуда взялось число. Показывается рядом с индикатором: без этого «доля
# силовых событий 0.83» выглядит измерением, а не пересказом кодировки GDELT.
IND_SOURCE = {
    "kin_events": "UCDP GED", "kin_fatalities": "UCDP GED", "kin_geo": "UCDP GED",
    "inf_pressure": "GDELT", "inf_share": "GDELT", "inf_violence": "GDELT",
    "eco_sanctions": "OFAC SDN", "dip_distance": "голосования ГА ООН (Voeten)",
    "mil_air": "ADS-B (adsb.lol)",
}
EVENTS_SHOWN = 40      # больше на странице не читают, а вес файла растёт


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------
def _bucket(values: list[int], size: int) -> list[int]:
    """Среднее по корзинам размера size, считая от КОНЦА ряда.

    От конца, а не от начала: последняя корзина обязана заканчиваться сегодня,
    иначе на графике последняя точка окажется неполной неделей и будет
    выглядеть провалом там, где его нет.
    """
    if not values:
        return []
    out = []
    n = len(values)
    start = n % size
    if start:
        out.append(round(sum(values[:start]) / start))
    for i in range(start, n, size):
        chunk = values[i:i + size]
        out.append(round(sum(chunk) / len(chunk)))
    return out


DISPLAY_LOOKBACK = 14      # в каком окне ищем день с полным составом данных


def display_day(con) -> str | None:
    """Последний день, у которого состав данных полный. Один на всю витрину.

    Раньше бралось просто MAX(day) — то есть сегодня. Но сегодня всегда самый
    бедный день из возможных: GDELT за текущие сутки ещё дособирается, и
    покрытие у него ниже вчерашнего. Витрина показывала самый неполный срез и
    называла его текущим состоянием мира.

    Берём последний день, у которого среднее покрытие дотягивает до лучшего за
    две недели. Если сегодняшний день полон — возьмётся он, задержки не будет;
    если недособран — отступим на день-два назад и честно подпишем дату.

    День ОДИН на все пары, а не свой у каждой: сопоставимость между парами —
    главное свойство продукта, а сравнивать вторник у одной пары со средой у
    другой значит её потерять.
    """
    rows = con.execute(
        "SELECT day, AVG(data_coverage) c FROM heat_daily "
        "WHERE day >= date((SELECT MAX(day) FROM heat_daily), ?) "
        "GROUP BY day ORDER BY day", (f"-{DISPLAY_LOOKBACK} day",)).fetchall()
    if not rows:
        return None
    best = max(r["c"] or 0 for r in rows)
    # Допуск на округление: полпункта покрытия — это не смена состава блоков.
    full = [r["day"] for r in rows if (r["c"] or 0) >= best - 0.5]
    return full[-1] if full else rows[-1]["day"]


def archive(con) -> list[dict]:
    """Завершённые конфликты: пары со статусом не active.

    Инвариант 6a требует переводить закончившийся конфликт в dormant, а не
    удалять: история нужна для базовых ставок. База это исполняет, а витрина
    до сих пор — нет: from_db берёт только active, и пара исчезала с сайта
    целиком вместе со своей историей.

    Накала и ступени у таких пар НЕТ, и это не упущение витрины: compute
    считает только активные, так что в heat_daily по ним ноль строк.
    Досчитывать задним числом нельзя без последствий — общая опора для
    масштаба «всё время» берётся по всем парам сразу, и появление новой
    истории сдвинуло бы числа у действующих пар. Поэтому здесь только то,
    что есть: реестровая запись и события источников.
    """
    out = []
    try:
        rows = con.execute(
            "SELECT dyad_id, name, region, side_a, side_b, dyad_type, disputed, "
            "       since, status FROM dyads WHERE status <> 'active' "
            "ORDER BY name").fetchall()
    except sqlite3.Error:
        return out

    for r in rows:
        d = dict(r)
        d["name"] = d.get("name") or f'{d["side_a"]} — {d["side_b"]}'
        try:
            s = con.execute(
                "SELECT COUNT(*) n, MIN(occurred_at) a, MAX(occurred_at) b "
                "FROM raw_events WHERE dyad_id=?", (d["dyad_id"],)).fetchone()
            d["events_total"] = s["n"] or 0
            d["events_from"] = str(s["a"])[:10] if s["a"] else None
            d["events_to"] = str(s["b"])[:10] if s["b"] else None
            d["sources"] = {x["source"]: x["n"] for x in con.execute(
                "SELECT source, COUNT(*) n FROM raw_events WHERE dyad_id=? "
                "GROUP BY source ORDER BY n DESC", (d["dyad_id"],))}
        except sqlite3.Error:
            d["events_total"] = 0
        out.append(d)
    return out


def _events_only(con, dyad_id: str, out: dict) -> dict:
    """Только исходные события. Для пар, по которым расчёта не было."""
    try:
        evs = []
        for r in con.execute(
                "SELECT occurred_at, source, event_type, cameo_code, fatalities, payload "
                "FROM raw_events WHERE dyad_id=? ORDER BY occurred_at DESC LIMIT ?",
                (dyad_id, EVENTS_SHOWN)):
            url = None
            try:
                url = (json.loads(r["payload"] or "{}") or {}).get("url")
            except (ValueError, TypeError):
                pass
            evs.append({"day": str(r["occurred_at"])[:10], "source": r["source"],
                        "type": r["event_type"], "cameo": r["cameo_code"],
                        "fatalities": r["fatalities"], "url": url})
        out["events"] = evs
    except sqlite3.Error:
        out["events"] = []
    return out


DIV_HISTORY_DAYS = 30      # столько столбиков рисует график разрыва
DIV_LAG_MAX = 21           # докуда искать запаздывание дел за словами


def divergence_of(pairs: list[tuple[float, float]]) -> dict | None:
    """Слова, дела, история разрывов и оценка запаздывания.

    pairs — упорядоченные по дате (слова, дела); дни, где измерена не вся
    сторона, в список не попадают вовсе.

    Запаздывание ищется перебором сдвига: на сколько дней надо подвинуть слова
    вперёд, чтобы они лучше всего совпали с делами. Это грубая оценка, и она
    честно названа оценкой в подписи на витрине — но именно она отвечает на
    вопрос, ради которого раздел затевался: риторика опережает действия или
    догоняет их.
    """
    if len(pairs) < DIV_HISTORY_DAYS:
        return None
    words = [w for w, _ in pairs]
    deeds = [d for _, d in pairs]

    def corr(a: list[float], b: list[float]) -> float:
        n = len(a)
        if n < 30:
            return 0.0
        ma, mb = sum(a) / n, sum(b) / n
        sa = sum((x - ma) ** 2 for x in a) ** 0.5
        sb = sum((x - mb) ** 2 for x in b) ** 0.5
        if not sa or not sb:
            return 0.0
        return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)

    best_lag, best = 0, corr(words, deeds)
    for lag in range(1, DIV_LAG_MAX + 1):
        if len(words) - lag < 30:
            break
        c = corr(words[:-lag], deeds[lag:])
        if c > best:
            best_lag, best = lag, c

    hist = [round(w - d) for w, d in pairs[-DIV_HISTORY_DAYS:]]
    return {"words": round(words[-1], 1), "deeds": round(deeds[-1], 1),
            "history": hist, "lagDays": best_lag}


def dyad_detail(con, dyad_id: str, day: str) -> dict:
    """Раскрытие пары до исходных фактов: фазы, индикаторы, события.

    Ради этого проект и затевался: «каждое число раскрывается до исходного
    события». До сих пор витрина показывала итог и не показывала, из чего он
    сложился, — то есть просила верить на слово ровно так же, как источники,
    которым мы верить не предлагаем.

    Ни один запрос здесь не имеет права уронить сборку: пустая деталь — это
    страница без раздела, а упавшая сборка — это сайт без данных.
    """
    sys.path.insert(0, str(ROOT / "ingest"))
    from escx.compute import INDICATORS
    from escx.indicators import BLOCK_WEIGHTS

    out: dict = {}

    # История фаз. Берётся из phase_log, куда пишется только INSERT: каждая
    # запись — это то, что система утверждала в тот день, а не то, что она
    # думает об этом сейчас.
    try:
        out["phase_history"] = [
            {"at": str(r["changed_at"])[:10], "from": r["phase_from"], "to": r["phase_to"],
             "from_name": PHASES[r["phase_from"]] if isinstance(r["phase_from"], int)
                          and 0 <= r["phase_from"] < len(PHASES) else None,
             "to_name": PHASES[r["phase_to"]] if isinstance(r["phase_to"], int)
                        and 0 <= r["phase_to"] < len(PHASES) else None,
             "rule": r["rule"]}
            for r in con.execute(
                "SELECT changed_at, phase_from, phase_to, rule FROM phase_log "
                "WHERE dyad_id=? ORDER BY changed_at DESC LIMIT 40", (dyad_id,))]
    except sqlite3.Error:
        out["phase_history"] = []

    # Разбор накала. Блок без единого свежего индикатора помечается
    # неизмеренным, а не нулевым: ноль означал бы «проверили, там пусто».
    #
    # У завершённой пары дня расчёта нет вовсе, и разбор пропускается целиком:
    # пять пустых блоков читались бы как «измерено 0 из 5», то есть как
    # неудачное измерение, тогда как измерения не было.
    if not day:
        out["blocks"] = []
        return _events_only(con, dyad_id, out)
    try:
        have = {r["indicator_key"]: r for r in con.execute(
            "SELECT indicator_key, raw_value, z_score, fresh FROM indicator_daily "
            "WHERE dyad_id=? AND day=?", (dyad_id, day))}
        blocks: dict[str, dict] = {}
        for key, block in INDICATORS.items():
            b = blocks.setdefault(block, {
                "block": block, "name": BLOCK_RU.get(block, block),
                "weight": BLOCK_WEIGHTS.get(block), "indicators": [], "measured": False})
            r = have.get(key)
            fresh = bool(r["fresh"]) if r is not None else False
            b["indicators"].append({
                "key": key, "name": IND_RU.get(key, key), "source": IND_SOURCE.get(key),
                "raw": None if r is None or r["raw_value"] is None else round(r["raw_value"], 3),
                "z": None if r is None or r["z_score"] is None else round(r["z_score"], 2),
                "fresh": fresh})
            b["measured"] = b["measured"] or fresh
        out["blocks"] = sorted(blocks.values(), key=lambda b: -(b["weight"] or 0))
    except sqlite3.Error:
        out["blocks"] = []

    # Исходные события. Ссылка на статью — то самое место, где читатель может
    # проверить нас, а не поверить.
    return _events_only(con, dyad_id, out)


def from_db(path: Path) -> dict | None:
    """Читает витрину. Возвращает None, если базы или расчётов ещё нет.

    None здесь — не ошибка, а штатное состояние до первого прогона: сборка
    переключается на честный пустой реестр. Поэтому все запросы обёрнуты, и ни
    один из них не имеет права уронить сборку сайта.
    """
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        show_day = display_day(con)
        if not show_day:
            return None
        rows = con.execute("""
            SELECT d.dyad_id, d.name, d.region, d.side_a, d.side_b, d.dyad_type,
                   d.disputed, d.phase, d.phase_basis,
                   h.day, h.h_abs, h.h_rel, h.delta_7, h.delta_30, h.tempo,
                   h.data_coverage, h.events_30d, h.method_version
            FROM dyads d
            JOIN heat_daily h ON h.dyad_id = d.dyad_id
            WHERE h.day = ? AND d.status = 'active'
        """, (show_day,)).fetchall()
        if not rows:
            return None

        # Глубокая история считается один раз на прогон, до цикла по диадам.
        deep: dict[str, tuple[list[str], list[float]]] = {}
        try:
            sys.path.insert(0, str(ROOT / "ingest"))
            from escx import calibrate as _cal
            _ref = _cal.deep_reference(con)      # одна опора на все пары
            for r0 in con.execute("SELECT dyad_id FROM dyads WHERE status='active'"):
                h = _cal.dyad_deep_history(con, r0["dyad_id"], _ref)
                if h[1]:
                    deep[r0["dyad_id"]] = h
        except Exception as e:                            # noqa: BLE001
            print(f"  глубокая история не собралась: {e}", file=sys.stderr)

        series: dict[str, list[int]] = {}
        coverage: dict[str, list[int]] = {}
        div_pairs: dict[str, list[tuple[float, float]]] = {}
        for r in con.execute("SELECT dyad_id, day, h_abs, data_coverage, h_words, h_deeds "
                             "FROM heat_daily ORDER BY dyad_id, day"):
            series.setdefault(r["dyad_id"], []).append(round(r["h_abs"] or 0))
            coverage.setdefault(r["dyad_id"], []).append(round(r["data_coverage"] or 0))
            if r["h_words"] is not None and r["h_deeds"] is not None:
                div_pairs.setdefault(r["dyad_id"], []).append((r["h_words"], r["h_deeds"]))

        # Доли для весов последствий: последний известный срез по каждой стране.
        shares: dict[str, dict[str, float]] = {"pop": {}, "gdp": {}, "mil": {}}
        for r in con.execute(
                "SELECT series_key, value, as_of FROM series "
                "WHERE source='worldbank' ORDER BY as_of"):
            k = r["series_key"]                     # share_pop:RUS
            if not k.startswith("share_") or ":" not in k:
                continue
            kind, iso = k[6:].split(":", 1)
            if kind in shares:
                shares[kind][iso] = r["value"]

        # Раскрытие пары. Собирается здесь, пока соединение открыто, но в
        # index.json НЕ кладётся: сорок событий и разбор по индикаторам на
        # двадцать пар утяжелили бы главную страницу впятеро ради данных,
        # которые нужны только тому, кто открыл конкретную пару.
        details = {r["dyad_id"]: dyad_detail(con, r["dyad_id"], r["day"]) for r in rows}

        # Завершённые конфликты. В ленту они не выводятся — инвариант 6a
        # требует показывать там только active, — но со страницы пары
        # доступны: их события и есть та история, ради которой пару не удаляют.
        arch = archive(con)
        for a in arch:
            details[a["dyad_id"]] = dyad_detail(con, a["dyad_id"], "")
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()

    dyads = []
    for r in rows:
        d = dict(r)
        ph = d.get("phase")
        d["phase_name"] = PHASES[ph] if isinstance(ph, int) and 0 <= ph < len(PHASES) else None
        d["tempo_name"] = TEMPO.get(d.get("tempo"))
        d["name"] = d.get("name") or f'{d["side_a"]} — {d["side_b"]}'
        for k in ("h_abs", "h_rel", "delta_7", "delta_30", "data_coverage"):
            d[k] = None if d.get(k) is None else round(d[k])
        full = series.get(d["dyad_id"], [])
        cov = coverage.get(d["dyad_id"], [])
        d["series_90d"] = full[-90:]                      # прежнее поле, не ломаем
        # Масштабы времени, как на биржевом графике. Часового нет и быть не
        # может: индекс суточный — окна усреднения 7 и 30 дней, а события UCDP
        # датированы днём. Часовой ряд был бы интерполяцией, то есть выдумкой.
        d["series"] = {
            "day":   full[-90:],
            "week":  _bucket(full, 7)[-104:],             # два года по неделям
            "month": _bucket(full, 30)[-36:],             # три года по месяцам
        }
        # Покрытие по тем же корзинам: длинный график склеивает периоды с
        # разным составом блоков, и не показать этого — значит соврать.
        d["coverage"] = {
            "day":   cov[-90:],
            "week":  _bucket(cov, 7)[-104:],
            "month": _bucket(cov, 30)[-36:],
        }

        # Вся глубина UCDP, помесячно и только по кинетике. Нужна, чтобы было
        # видно, КАК конфликт к этому шёл: у России с Украиной первое боевое
        # событие датировано мартом 2014-го, а до него — пусто, и это тоже
        # факт, который график обязан показывать.
        dm, dh = deep.get(d["dyad_id"], ([], []))
        if dh:
            d["series"]["all"] = [round(x) for x in dh]
            d["series_all_from"] = dm[0]
            d["coverage"]["all"] = [20] * len(dh)         # только кинетика

        d["divergence"] = divergence_of(div_pairs.get(d["dyad_id"], []))
        d["events_30d"] = None if d.get("events_30d") is None else int(d["events_30d"])
        d["weight"] = wt.consequence(d["side_a"], d["side_b"], shares)
        dyads.append(d)

    total_w = sum(d["weight"] for d in dyads if d["weight"])
    for d in dyads:
        d["weight_share"] = round(100 * d["weight"] / total_w, 1) if (total_w and d["weight"]) else None
        d.pop("weight", None)
    # ПОРЯДОК: сначала ступень, потом накал.
    #
    # Раньше сортировали по одному накалу, и это давало нелепицу, которую видно
    # с первого взгляда: 19 августа Россия с Украиной (фаза 5, «Война») стояли
    # ниже Ирана с США (фаза 2, «Кризис»), потому что по доле в мировом
    # новостном потоке Иран в тот день был крупнее — 0.16 против 0.15.
    #
    # Накал и не должен был отвечать на вопрос «где хуже»: он меряет отклонение
    # от нормы, а не тяжесть. На вопрос «где хуже» отвечает ступень, и в
    # методологии она стоит первой из четырёх сущностей карточки. Список обязан
    # читаться так же: война выше кризиса всегда, накал упорядочивает внутри
    # ступени.
    #
    # Особенно это важно, пока кинетика отстаёт от календаря: без неё накал
    # вообще не отличает войну от новостного цикла, а ступень — отличает,
    # потому что держится гистерезисом на последних подтверждённых данных.
    dyads.sort(key=lambda x: (-(x["phase"] if x["phase"] is not None else -1),
                              -(x["h_abs"] or 0), x["name"]))

    return {"dyads": dyads, "source": "db", "details": details, "archive": arch,
            # День, к которому относятся числа. Отдаётся отдельно от built_at:
            # время сборки и дата данных — разные вещи, и путать их значит
            # выдавать вчерашний срез за сегодняшний.
            "data_day": show_day,
            "global": global_index(dyads, shares),
            "registry_total": len(dyads)}


def global_index(dyads: list[dict], shares: dict[str, dict[str, float]]) -> dict | None:
    """GEI = Σ(c·H)/Σc. None, если веса последствий ещё не загружены.

    Прочерк вместо числа — осознанное решение. Заменить недостающие веса
    единицами технически ничего не стоит, и получилось бы правдоподобное число,
    которое на самом деле было бы простым средним — ровно тем, что раздел 5A
    методологии отвергает как «успокаивающее число, не значащее ничего».
    """
    pairs = [(d, d.get("weight_share")) for d in dyads if d.get("weight_share")]
    if not pairs or not shares.get("gdp"):
        return None
    tw = sum(w for _, w in pairs)
    gei = round(sum(w * (d["h_abs"] or 0) for d, w in pairs) / tw)
    d30 = round(sum(w * (d.get("delta_30") or 0) for d, w in pairs) / tw)

    kinetic = [d for d in dyads if (d.get("phase") or 0) >= 3]
    nuclear = [d for d, w in pairs if wt.nuclear_mult(d["side_a"], d["side_b"]) > 1]
    top_mil = sorted(pairs, key=lambda p: -(shares["mil"].get(p[0]["side_a"], 0)
                                            + shares["mil"].get(p[0]["side_b"], 0)))[:8]

    def wavg(items):
        t = sum(w for _, w in items)
        return round(sum(w * (d["h_abs"] or 0) for d, w in items) / t) if t else None

    return {
        "gei": gei, "delta_30": d30,
        "axes": [
            {"key": "kinetic", "name": "Кинетическая интенсивность",
             "value": wavg([(d, w) for d, w in pairs if d in kinetic]),
             "note": f"диад в фазе 3 и выше: {len(kinetic)} из {len(dyads)}"},
            {"key": "powers", "name": "Вовлечённость крупных держав",
             "value": wavg(top_mil),
             "note": "восемь диад с наибольшей долей мировых военных расходов"},
            {"key": "strategic", "name": "Стратегический риск",
             "value": wavg([(d, w) for d, w in pairs if d in nuclear]),
             "note": f"диад с ядерной стороной: {len(nuclear)}"},
        ],
        "series_5y": [],
    }


def registry_state() -> dict:
    """Честное пустое состояние: реестр диад без единого числа.

    Собирается, когда базы ещё нет. Показывает, ЧТО продукт наблюдает, и прямо
    говорит, что значения не рассчитаны. Это и честно, и информативно: посетитель
    видит охват, а не правдоподобную выдумку.
    """
    reg = json.loads((ROOT / "ingest" / "config" / "dyads.json").read_text(encoding="utf-8"))
    dyads = [{
        "dyad_id": d["dyad_id"],
        "name": d.get("name", d["dyad_id"]),
        "region": d.get("region", ""),
        "disputed": d.get("disputed", ""),
        "since": d.get("since"),
        "phase": None, "phase_name": None,
        "h_abs": None, "h_rel": None,
        "delta_7": None, "delta_30": None,
        "tempo": None, "tempo_name": None,
        "data_coverage": 0, "series_90d": [],
    } for d in reg if d.get("status") == "active"]
    dyads.sort(key=lambda x: x["name"])
    return {
        "dyads": dyads,
        "source": "registry",
        "global": None,
        "registry_total": len(reg),
        "dormant": [d.get("name", d["dyad_id"]) for d in reg if d.get("status") == "dormant"],
    }


def demo() -> dict:
    """Выдуманные числа для локальной работы над вёрсткой. В деплой не идут."""
    raw = [
        ("A-24", "Ограниченный конфликт", 4, 79, 97, 34, 26, "spike",  64, 2.9),
        ("A-03", "Ограниченный конфликт", 4, 83, 91, 30, 22, "spike",  76, 5.4),
        ("A-09", "Вооружённые инциденты", 3, 52, 74, 25, 18, "spike",  58, 4.6),
        ("A-05", "Напряжённость",         1, 34, 68, 10,  4, "up",     61, 0.6),
        ("A-01", "Кризис",                2, 71, 62,  6,  2, "flat",   92, 15.2),
        ("A-19", "Напряжённость",         1, 22, 55,  4,  1, "flat",   74, 0.4),
        ("A-06", "Вооружённые инциденты", 3, 38, 47,  1,  0, "frozen", 73, 0.5),
        ("A-17", "Ограниченный конфликт", 4, 74, 58,  0,  0, "flat",   38, 1.1),
        ("A-15", "Вооружённые инциденты", 3, 68, 41, -9, -4, "down",   71, 2.8),
        ("A-25", "Ограниченный конфликт", 4, 66, 38, -10, -6, "down",  54, 3.1),
    ]
    dyads = []
    for i, (sid, ph, L, h, hrel, d30, d7, tempo, cov, w) in enumerate(raw):
        dyads.append({
            "dyad_id": f"DEMO-{sid}", "name": f"Диада {sid}",
            "phase": L, "phase_name": ph,
            "h_abs": h, "h_rel": hrel, "delta_7": d7, "delta_30": d30,
            "tempo": tempo, "tempo_name": TEMPO[tempo],
            "data_coverage": cov, "weight_share": w,
            "series_90d": _walk(i * 97 + 11, 90, h, d30 / 30),
        })
    total_w = sum(d["weight_share"] for d in dyads) or 1
    gei = round(sum(d["weight_share"] * d["h_abs"] for d in dyads) / total_w)
    return {
        "dyads": dyads, "source": "demo",
        "global": {
            "gei": gei, "delta_30": 2,
            "axes": [
                {"key": "kinetic",   "name": "Кинетика",            "value": 61,
                 "note": "активные конфликты и их смертность"},
                {"key": "powers",    "name": "Крупные державы",      "value": 77,
                 "note": "доля мирового военного потенциала в фазе ≥ 2"},
                {"key": "strategic", "name": "Стратегический риск",  "value": 78,
                 "note": "ядерные диады, договоры, доктрина"},
            ],
            "series_5y": _walk(2026, 60, gei, 0.42),
        },
    }


def _walk(seed: int, n: int, end: float, drift: float) -> list[int]:
    """Детерминированное блуждание. Date.now() и random не используются
    намеренно: сборка должна быть воспроизводимой — иначе каждый деплой
    даёт новый диф и история коммитов превращается в шум."""
    s = seed & 0xFFFFFFFF
    def rnd():
        nonlocal s
        s = (s + 0x6D2B79F5) & 0xFFFFFFFF
        t = (s ^ (s >> 15)) * (1 | s) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (61 | t) & 0xFFFFFFFF)) ^ t & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    v, out = float(end), []
    for _ in range(n):
        out.append(v)
        v -= drift * (0.5 + rnd() * 0.9) + (rnd() - 0.5) * 2.2
        v = max(4.0, min(96.0, v))
    out.reverse()
    shift = end - out[-1]
    return [round(max(3, min(97, x + shift))) for x in out]


# --------------------------------------------------------------------------
# Сборка
# --------------------------------------------------------------------------
def build(demo_mode: bool = False) -> dict:
    if demo_mode:
        data = demo()
    else:
        data = from_db(DB)
        if data is None:
            print("  база пуста или отсутствует — собираю честное пустое состояние",
                  file=sys.stderr)
            data = registry_state()

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    (SITE / "design").mkdir()

    # дизайн-система как есть
    for f in ("tokens.css", "escx-ui.js"):
        shutil.copy2(ROOT / "design" / f, SITE / "design" / f)

    # Страница собрана из отдельных файлов, а не одним куском: словари шестнадцати
    # языков и отрисовка не помещаются в шаблон, который ещё и читать надо.
    # Копируется всё дерево, кроме демонстрационных чисел — их публиковать нельзя.
    assets_src = ROOT / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, SITE / "assets",
                        ignore=shutil.ignore_patterns("demo-data.js"))
    else:
        print("  нет assets/ — страница останется без стилей и отрисовки", file=sys.stderr)

    # Фирменные файлы кладём в корень, а не в подпапку: браузеры и мессенджеры
    # ходят за иконками по угаданным путям, и корень — единственный, который
    # угадывают все. Растровые иконки собираются brand/rasterize.py и лежат
    # в репозитории готовыми: на сборочной машине браузера нет.
    for f in ("favicon.svg", "icon-32.png", "icon-180.png", "icon-512.png",
              "og-cover.png", "logo.svg", "mark.svg"):
        p = ROOT / "brand" / f
        if p.exists():
            shutil.copy2(p, SITE / f)
        else:
            print(f"  нет brand/{f} — соберите: python3 brand/rasterize.py", file=sys.stderr)

    # Обратный прогон. Кладётся отдельным файлом, а не в index.json: он меняется
    # раз в месяцы, а витрина — каждую ночь, и таскать его в каждом ответе
    # незачем. Страница грузит его только когда доходит до раздела.
    try:
        sys.path.insert(0, str(ROOT / "ingest"))
        from escx import calibrate as cal, db as _db
        con = _db.connect(str(ROOT / "ingest" / "escx.db"))
        rep = cal.run(con)
        rep["control"] = cal.control(con)
        (SITE / "data" / "calibration.json").write_text(
            json.dumps(rep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"  калибровка: {rep['with_signal']} из {rep['n']}, "
              f"ложных {rep['control']['false']} из {rep['control']['crossings']}")
    except Exception as e:                       # noqa: BLE001
        # Обратный прогон — не повод ронять сборку сайта: без него раздел
        # просто не появится, а витрина с числами важнее.
        print(f"  калибровка не собралась: {e}", file=sys.stderr)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # Раскрытие пар едет только в файлы пар — в index.json его нет намеренно,
    # иначе главная страница потяжелела бы в разы ради данных, нужных лишь
    # тому, кто открыл конкретную пару.
    details = data.pop("details", {})
    payload = {**data, "built_at": stamp, "method_version": "0.3.1"}
    (SITE / "data" / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # по диаде — отдельный файл: страница тянет только то, что показывает.
    # Завершённые пары получают такой же файл: в ленте их нет, но страница
    # пары для них открывается — ради их истории пару и не удаляют.
    for d in list(data["dyads"]) + list(data.get("archive") or []):
        (SITE / "data" / f"{d['dyad_id']}.json").write_text(
            json.dumps({**d, **details.get(d["dyad_id"], {}), "built_at": stamp},
                       ensure_ascii=False), encoding="utf-8")

    tpl = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    (SITE / "index.html").write_text(tpl, encoding="utf-8")

    # витрина дизайна и схема проекта едут вместе с сайтом
    # Личный кабинет — отдельная страница: она не про данные, а про доступ,
    # и подмешивать её в главную незачем. Живёт рядом со статикой, потому что
    # вся работа идёт через Worker на /api.
    p_acc = ROOT / "account.html"
    if p_acc.exists():
        shutil.copy2(p_acc, SITE / "account.html")

    # Страница пары. Тоже отдельная, и по той же причине, что кабинет: она
    # грузит свой файл данных, вчетверо тяжелее витрины, и нужна тому, кто
    # захотел проверить конкретное число.
    p_dyad = ROOT / "dyad.html"
    if p_dyad.exists():
        shutil.copy2(p_dyad, SITE / "dyad.html")

    # Правовые документы. Обязаны попадать в сборку всегда, в том числе в
    # демо-режиме: ссылка из подвала на несуществующую страницу — худший вид
    # отсутствия политики конфиденциальности, чем её честное отсутствие.
    # Краткая справка для ИИ-ассистентов. Кладётся в корень рядом с robots.txt
    # по тому же соглашению: агент, которому разрешили читать сайт, должен
    # найти, что здесь есть и чем оно отличается, не разбирая вёрстку.
    p_llms = ROOT / "llms.txt"
    if p_llms.exists():
        shutil.copy2(p_llms, SITE / "llms.txt")

    for f in ("privacy.html", "terms.html"):
        p = ROOT / f
        if p.exists():
            shutil.copy2(p, SITE / f)
        else:
            print(f"  нет {f} — в подвале останется битая ссылка", file=sys.stderr)

    for src, dst in [("design/styleguide.html", "styleguide.html"),
                     ("design/demo.html",      "design-demo.html"),
                     ("web/schema.html",       "schema.html")]:
        p = ROOT / src
        if p.exists():
            shutil.copy2(p, SITE / dst)

    # .nojekyll обязателен: иначе GitHub Pages прогонит папку через Jekyll
    # и выбросит всё, что начинается с подчёркивания
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n"
        f"Sitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")

    write_sitemap(data)

    n = sum(1 for _ in SITE.rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    return {"files": n, "bytes": size, "dyads": len(data["dyads"]), "source": data["source"]}


SITE_URL = "https://brink.watch"

# Страницы, которых в карте быть не должно, и причины у каждой разные:
# кабинет закрыт от индексации своим noindex, витрина дизайна и схема — это
# рабочие материалы, а не содержание сайта.
SITEMAP_SKIP = {"account.html", "styleguide.html", "design-demo.html", "dyad.html"}


def write_sitemap(data: dict) -> int:
    """Карта сайта.

    До сих пор её не было вовсе: robots.txt писался, sitemap.xml — нет, и
    запрос по этому адресу отдавал главную страницу, потому что Cloudflare
    подставляет её вместо 404. То есть поисковик о карте не знал и не мог
    узнать, что у сайта есть страницы пар.

    Именно они здесь и главное: два десятка страниц с уникальным текстом,
    историей и событиями. Ссылки на них есть только с главной, а это самый
    медленный путь к индексации.

    Шаблон dyad.html в карту не идёт: сам по себе, без параметра, он пустой.
    В карту идут его конкретные адреса — по одному на пару, включая
    завершённые: их история и есть то, ради чего пары не удаляются.
    """
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls: list[tuple[str, str]] = [(SITE_URL + "/", "daily")]

    for f in sorted(SITE.glob("*.html")):
        if f.name in SITEMAP_SKIP or f.name == "index.html":
            continue
        urls.append((f"{SITE_URL}/{f.name}", "yearly"))

    for d in list(data.get("dyads") or []) + list(data.get("archive") or []):
        urls.append((f"{SITE_URL}/dyad.html?id={d['dyad_id']}", "daily"))

    body = "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{day}</lastmod>"
        f"<changefreq>{freq}</changefreq></url>"
        for u, freq in urls)
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n", encoding="utf-8")
    return len(urls)


def copy_to_root() -> int:
    """Разложить собранный сайт по корню репозитория.

    Зачем это нужно: проект на Cloudflare Pages настроен без команды сборки —
    он просто отдаёт корень репозитория как есть. Значит, собранные файлы
    обязаны в этом корне лежать, иначе push ничего не меняет.

    Правильнее было бы задать команду сборки и папку site, и тогда эта функция
    не нужна. Но пока настройки такие — держим оба варианта рабочими: site/
    для нормального деплоя, корень для текущего.
    """
    n = 0
    for src in SITE.rglob("*"):
        if src.is_dir():
            continue
        dst = ROOT / src.relative_to(SITE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Сборка статического сайта ESCX")
    ap.add_argument("--demo", action="store_true",
                    help="выдуманные числа для работы над вёрсткой; публиковать нельзя")
    ap.add_argument("--to-root", action="store_true",
                    help="дополнительно разложить собранный сайт по корню репозитория")
    a = ap.parse_args()
    r = build(a.demo)
    print(f"site/ собран: {r['files']} файлов, {r['bytes']/1024:.0f} КБ, "
          f"диад {r['dyads']}, источник — {r['source']}")
    if a.to_root:
        if a.demo:
            sys.exit("--to-root и --demo вместе запрещены: выдуманные числа "
                     "оказались бы в репозитории и уехали на публичный сайт")
        print(f"в корень репозитория скопировано файлов: {copy_to_root()}")
