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
          "down": "Разрядка", "frozen": "Заморозка"}


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------
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
        rows = con.execute("""
            SELECT d.dyad_id, d.name, d.region, d.side_a, d.side_b, d.dyad_type,
                   d.disputed, d.phase, d.phase_basis,
                   h.day, h.h_abs, h.h_rel, h.delta_7, h.delta_30, h.tempo,
                   h.data_coverage, h.events_30d, h.method_version
            FROM dyads d
            JOIN heat_daily h ON h.dyad_id = d.dyad_id
            WHERE h.day = (SELECT MAX(day) FROM heat_daily WHERE dyad_id = d.dyad_id)
              AND d.status = 'active'
        """).fetchall()
        if not rows:
            return None

        series: dict[str, list[int]] = {}
        for r in con.execute("SELECT dyad_id, day, h_abs FROM heat_daily "
                             "ORDER BY dyad_id, day"):
            series.setdefault(r["dyad_id"], []).append(round(r["h_abs"] or 0))

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
        d["series_90d"] = series.get(d["dyad_id"], [])[-90:]
        d["events_30d"] = None if d.get("events_30d") is None else int(d["events_30d"])
        d["weight"] = wt.consequence(d["side_a"], d["side_b"], shares)
        dyads.append(d)

    total_w = sum(d["weight"] for d in dyads if d["weight"])
    for d in dyads:
        d["weight_share"] = round(100 * d["weight"] / total_w, 1) if (total_w and d["weight"]) else None
        d.pop("weight", None)
    dyads.sort(key=lambda x: (-(x["h_abs"] or 0), x["name"]))

    return {"dyads": dyads, "source": "db",
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

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {**data, "built_at": stamp, "method_version": "0.3.1"}
    (SITE / "data" / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # по диаде — отдельный файл: страница тянет только то, что показывает
    for d in data["dyads"]:
        (SITE / "data" / f"{d['dyad_id']}.json").write_text(
            json.dumps({**d, "built_at": stamp}, ensure_ascii=False), encoding="utf-8")

    tpl = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    (SITE / "index.html").write_text(tpl, encoding="utf-8")

    # витрина дизайна и схема проекта едут вместе с сайтом
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
        "User-agent: *\nAllow: /\n", encoding="utf-8")

    n = sum(1 for _ in SITE.rglob("*") if _.is_file())
    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file())
    return {"files": n, "bytes": size, "dyads": len(data["dyads"]), "source": data["source"]}


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
