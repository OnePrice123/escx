"""Реестр диад: единственное место, где решается, ЧТО мы вообще наблюдаем."""
from __future__ import annotations
import json
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "config" / "dyads.json"


def load(path: str | Path = DEFAULT) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def install(con, dyads: list[dict]) -> None:
    """Заливает реестр в базу.

    INSERT OR REPLACE, а не INSERT OR IGNORE: реестр — управляемый файл, и правка
    в нём (переименование, перевод в dormant) обязана доезжать до базы. Но фазу
    и её основание REPLACE обнулил бы, поэтому они переносятся из старой строки:
    их считает compute, а не реестр.
    """
    prev = {r["dyad_id"]: (r["phase"], r["phase_basis"])
            for r in con.execute("SELECT dyad_id, phase, phase_basis FROM dyads")}
    con.executemany(
        "INSERT OR REPLACE INTO dyads"
        "(dyad_id,side_a,side_b,dyad_type,disputed,since,status,name,region,phase,phase_basis)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [(d["dyad_id"], d["side_a"], d["side_b"], d["dyad_type"],
          d.get("disputed"), d.get("since"), d.get("status", "active"),
          d.get("name"), d.get("region"),
          *prev.get(d["dyad_id"], (None, None))) for d in dyads])
    con.commit()
