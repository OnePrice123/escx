"""Реестр диад: единственное место, где решается, ЧТО мы вообще наблюдаем."""
from __future__ import annotations
import json
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "config" / "dyads.json"


def load(path: str | Path = DEFAULT) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def install(con, dyads: list[dict]) -> None:
    con.executemany(
        "INSERT OR REPLACE INTO dyads(dyad_id,side_a,side_b,dyad_type,disputed,since,status)"
        " VALUES(?,?,?,?,?,?,?)",
        [(d["dyad_id"], d["side_a"], d["side_b"], d["dyad_type"],
          d.get("disputed"), d.get("since"), d.get("status", "active")) for d in dyads])
    con.commit()
