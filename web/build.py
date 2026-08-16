#!/usr/bin/env python3
"""Сборка статического сайта ESCX.

Идея архитектуры, которая делает хостинг бесплатным:
сайт не ходит в базу. Пайплайн раз в сутки считает всё в SQLite, этот скрипт
выгружает результат в несколько JSON-файлов, и получается папка со статикой —
её отдаёт любой бесплатный хостинг без сервера, без базы и без бэкенда.

    python3 web/build.py                 # соберёт site/ из ingest/escx.db
    python3 web/build.py --demo          # соберёт на демо-данных (базы может не быть)
    python3 -m http.server -d site 8000  # посмотреть локально

Зависимостей нет: только стандартная библиотека.
"""
from __future__ import annotations
import argparse, json, math, shutil, sqlite3, sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DB   = ROOT / "ingest" / "escx.db"

PHASES = ["Нормализация", "Напряжённость", "Кризис", "Вооружённые инциденты",
          "Ограниченный конфликт", "Война", "Расширенная война"]
TEMPO  = {"spike": "Резкая эскалация", "up": "Нагрев", "flat": "Стабильно",
          "down": "Разрядка", "frozen": "Заморозка"}


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------
def from_db(path: Path) -> dict | None:
    """Читает витрину. Возвращает None, если базы или расчётов ещё нет."""
    if not path.exists():
        return None
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("""
            SELECT d.dyad_id, d.side_a, d.side_b, d.dyad_type, d.disputed,
                   h.day, h.h_abs, h.h_rel, h.delta_7, h.delta_30, h.tempo,
                   h.data_coverage, h.method_version
            FROM dyads d
            JOIN heat_daily h ON h.dyad_id = d.dyad_id
            WHERE h.day = (SELECT MAX(day) FROM heat_daily WHERE dyad_id = d.dyad_id)
              AND d.status = 'active'
        """).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    if not rows:
        return None
    return {"dyads": [dict(r) for r in rows], "source": "db"}


def demo() -> dict:
    """Демо-витрина. Нужна, чтобы сайт собирался и деплоился с первого дня,
    пока пайплайн ещё не наполнил базу. Все числа помечены как демонстрационные."""
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
    data = None if demo_mode else from_db(DB)
    if data is None:
        if not demo_mode:
            print("  база пуста или отсутствует — собираю на демо-данных", file=sys.stderr)
        data = demo()

    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    (SITE / "design").mkdir()

    # дизайн-система как есть
    for f in ("tokens.css", "escx-ui.js"):
        shutil.copy2(ROOT / "design" / f, SITE / "design" / f)

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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Сборка статического сайта ESCX")
    ap.add_argument("--demo", action="store_true", help="собрать на демо-данных")
    a = ap.parse_args()
    r = build(a.demo)
    print(f"site/ собран: {r['files']} файлов, {r['bytes']/1024:.0f} КБ, "
          f"диад {r['dyads']}, источник — {r['source']}")
