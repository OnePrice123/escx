"""Хранилище. SQLite из стандартной библиотеки.

Почему SQLite, а не Postgres/DuckDB на старте: 60 диад × 365 дней × ~40 индикаторов —
это порядка миллиона строк в год. SQLite держит такое без напряжения, ставится нулём
команд и работает на любой машине. Схема написана так, что переносится в Postgres
заменой трёх типов.

Инвариант из техплана: raw_events, phase_log и forecasts — только INSERT.
Здесь он не на честном слове, а триггерами: UPDATE и DELETE физически запрещены.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS dyads (
  dyad_id     TEXT PRIMARY KEY,
  side_a      TEXT NOT NULL,
  side_b      TEXT NOT NULL,
  dyad_type   TEXT NOT NULL,
  disputed    TEXT,
  since       INTEGER,
  status      TEXT NOT NULL DEFAULT 'active',
  -- Название и регион нужны витрине. Держим их в базе, а не только в JSON:
  -- сборщик сайта читает базу и не должен знать про файлы реестра.
  name        TEXT,
  region      TEXT,
  phase       INTEGER,           -- текущая фаза; пересчитывается compute
  phase_basis TEXT               -- 'ucdp' | 'media' | NULL — на чём основана
);

-- Сырьё. Естественный ключ (source, source_id) даёт идемпотентность:
-- повторный прогон того же файла ничего не дублирует.
CREATE TABLE IF NOT EXISTS raw_events (
  source        TEXT NOT NULL,
  source_id     TEXT NOT NULL,
  occurred_at   TEXT NOT NULL,
  ingested_at   TEXT NOT NULL DEFAULT (datetime('now')),
  dyad_id       TEXT,
  match_level   TEXT,          -- rule | geo | llm | unmatched
  actor_a       TEXT,
  actor_b       TEXT,
  event_type    TEXT,
  fatalities    INTEGER,
  cameo_code    TEXT,
  goldstein     REAL,
  num_mentions  INTEGER,
  date_prec     INTEGER,       -- точность даты у UCDP: 1 = день, 5 = год
  lat           REAL,
  lon           REAL,
  payload       TEXT,
  PRIMARY KEY (source, source_id)
);
CREATE INDEX IF NOT EXISTS ix_raw_dyad_date ON raw_events(dyad_id, occurred_at);

CREATE TABLE IF NOT EXISTS series (          -- внешние готовые ряды (GPR, SIPRI…)
  source     TEXT NOT NULL,
  series_key TEXT NOT NULL,
  as_of      TEXT NOT NULL,
  value      REAL,
  PRIMARY KEY (source, series_key, as_of)
);

CREATE TABLE IF NOT EXISTS indicator_daily (
  dyad_id       TEXT NOT NULL,
  day           TEXT NOT NULL,
  indicator_key TEXT NOT NULL,
  raw_value     REAL,
  z_score       REAL,
  fresh         INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (dyad_id, day, indicator_key)
);

CREATE TABLE IF NOT EXISTS heat_daily (
  dyad_id        TEXT NOT NULL,
  day            TEXT NOT NULL,
  h_abs          REAL, h_rel REAL,
  delta_7        REAL, delta_30 REAL,
  tempo          TEXT,
  data_coverage  REAL,
  events_30d     REAL,          -- сколько событий стоит за числом; NULL = источник не покрывал период
  method_version TEXT NOT NULL,
  run_id         TEXT NOT NULL,
  PRIMARY KEY (dyad_id, day, method_version)
);

CREATE TABLE IF NOT EXISTS phase_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  dyad_id     TEXT NOT NULL,
  changed_at  TEXT NOT NULL,
  phase_from  INTEGER, phase_to INTEGER NOT NULL,
  rule        TEXT NOT NULL,
  evidence    TEXT,
  reviewer    TEXT,
  method_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS forecasts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  dyad_id    TEXT, question_key TEXT,
  issued_at  TEXT NOT NULL,
  horizon_m  INTEGER NOT NULL,
  p          REAL NOT NULL, ci_low REAL, ci_high REAL,
  base_rate  REAL,
  model_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  resolved_at TEXT, outcome INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
  run_id   TEXT PRIMARY KEY,
  started  TEXT NOT NULL,
  finished TEXT,
  status   TEXT,
  note     TEXT
);

-- Метка последнего успешно обработанного среза по каждому источнику.
-- Без неё каждый прогон тянет всё заново; с ней — только новое.
-- Текущий состав санкционного списка по диадам.
-- Изменяемая таблица, и это осознанно: raw_events остаётся append-only, туда
-- пишутся СОБЫТИЯ (мера введена / мера снята), а здесь лежит состояние, по
-- которому эти события вычисляются. Без него снятие меры отличить не от чего:
-- запись просто исчезает из выгрузки OFAC, никакого признака не оставляя.
CREATE TABLE IF NOT EXISTS sanctions_state (
  dyad_id    TEXT NOT NULL,
  ent_num    TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen  TEXT NOT NULL,
  PRIMARY KEY (dyad_id, ent_num)
);

CREATE TABLE IF NOT EXISTS watermarks (
  source     TEXT PRIMARY KEY,
  position   TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Append-only не на дисциплине разработчика, а на уровне БД.
GUARDS = """
CREATE TRIGGER IF NOT EXISTS raw_events_no_update BEFORE UPDATE ON raw_events
BEGIN SELECT RAISE(ABORT, 'raw_events только для вставки'); END;
CREATE TRIGGER IF NOT EXISTS raw_events_no_delete BEFORE DELETE ON raw_events
BEGIN SELECT RAISE(ABORT, 'raw_events только для вставки'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_no_update BEFORE UPDATE OF p, issued_at, horizon_m ON forecasts
BEGIN SELECT RAISE(ABORT, 'опубликованный прогноз не переписывается'); END;
CREATE TRIGGER IF NOT EXISTS forecasts_no_delete BEFORE DELETE ON forecasts
BEGIN SELECT RAISE(ABORT, 'опубликованный прогноз не удаляется'); END;
CREATE TRIGGER IF NOT EXISTS phase_log_no_delete BEFORE DELETE ON phase_log
BEGIN SELECT RAISE(ABORT, 'журнал фаз только для вставки'); END;
"""


# Колонки, добавленные после первых прогонов. У кого база уже создана, ALTER
# доводит её до текущей схемы: CREATE TABLE IF NOT EXISTS существующую не трогает.
MIGRATIONS = [
    ("dyads", "name",        "TEXT"),
    ("dyads", "region",      "TEXT"),
    ("dyads", "phase",       "INTEGER"),
    ("dyads", "phase_basis", "TEXT"),
    ("heat_daily", "events_30d", "REAL"),
    ("heat_daily", "h_words",    "REAL"),
    ("heat_daily", "h_deeds",    "REAL"),
]


def connect(path: str | Path = "escx.db") -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.executescript(GUARDS)
    for table, col, decl in MIGRATIONS:
        cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    con.commit()
    return con


def upsert_events(con: sqlite3.Connection, rows: list[dict]) -> int:
    """Вставка сырья. Дубликаты игнорируются — прогон идемпотентен."""
    if not rows:
        return 0
    cols = ["source","source_id","occurred_at","dyad_id","match_level","actor_a",
            "actor_b","event_type","fatalities","cameo_code","goldstein",
            "num_mentions","date_prec","lat","lon","payload"]
    sql = (f"INSERT OR IGNORE INTO raw_events ({','.join(cols)}) "
           f"VALUES ({','.join('?' * len(cols))})")
    before = con.total_changes
    con.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    con.commit()
    return con.total_changes - before


def add_series(con, source: str, key: str, as_of: str, value: float) -> None:
    """Накопительная запись внешнего ряда.

    Именно накопительная, а не перезапись: за сутки приходит до 96 срезов GDELT,
    и каждый добавляет свой объём к дневному итогу. REPLACE оставил бы только
    последний срез, а знаменатель нормировки стал бы в сто раз меньше числителя.
    Повторная загрузка того же среза защищена меткой watermark, а не этой строкой.
    """
    con.execute(
        "INSERT INTO series(source,series_key,as_of,value) VALUES(?,?,?,?) "
        "ON CONFLICT(source,series_key,as_of) DO UPDATE SET value=value+excluded.value",
        (source, key, as_of, value))
    con.commit()


def sanctions_state(con, dyad_id: str) -> set[str]:
    """Записи, числившиеся активными по итогам прошлого прогона."""
    return {r["ent_num"] for r in con.execute(
        "SELECT ent_num FROM sanctions_state WHERE dyad_id=?", (dyad_id,))}


def set_sanctions_state(con, dyad_id: str, ent_nums: set[str], day: str) -> None:
    """Заменяет состояние диады на текущее. Вызывать ПОСЛЕ вычисления дельты."""
    con.execute("DELETE FROM sanctions_state WHERE dyad_id=?", (dyad_id,))
    con.executemany(
        "INSERT INTO sanctions_state(dyad_id,ent_num,first_seen,last_seen) "
        "VALUES(?,?,?,?)", [(dyad_id, e, day, day) for e in sorted(ent_nums)])
    con.commit()


def set_series(con, source: str, key: str, as_of: str, value: float) -> None:
    """Перезапись значения ряда, в отличие от накопительной add_series.

    Нужна для источников, которые отдают ИТОГ за период, а не приращение:
    расстояние позиций в ООН за 2025 год — это одно число, и повторный прогон
    обязан его заменить, а не удвоить.
    """
    con.execute(
        "INSERT INTO series(source,series_key,as_of,value) VALUES(?,?,?,?) "
        "ON CONFLICT(source,series_key,as_of) DO UPDATE SET value=excluded.value",
        (source, key, as_of, value))
    con.commit()


def get_watermark(con, source: str, default: str = "") -> str:
    r = con.execute("SELECT position FROM watermarks WHERE source=?", (source,)).fetchone()
    return r["position"] if r else default


def set_watermark(con, source: str, position: str) -> None:
    con.execute("INSERT INTO watermarks(source,position,updated_at) VALUES(?,?,datetime('now')) "
                "ON CONFLICT(source) DO UPDATE SET position=excluded.position, "
                "updated_at=excluded.updated_at", (source, position))
    con.commit()
