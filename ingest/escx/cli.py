"""Точка входа. Команды запускаются из cron или GitHub Actions.

  python -m escx.cli init
  python -m escx.cli backfill-ucdp --start 2015-01-01 --end 2024-12-31
  python -m escx.cli pull-gdelt --slices 8
  python -m escx.cli status
"""
from __future__ import annotations
import argparse, sys, uuid
from datetime import datetime, timedelta, timezone

from . import db, dyads as dy, match
from .sources import ucdp, gdelt


def cmd_init(args):
    con = db.connect(args.db)
    ds = dy.load()
    dy.install(con, ds)
    print(f"схема создана, диад в реестре: {len(ds)}")


def cmd_backfill_ucdp(args):
    con = db.connect(args.db)
    ds = dy.load()
    print(f"UCDP GED {ucdp.VERSION}: {args.start} .. {args.end}")
    rows = ucdp.fetch_ged(start=args.start, end=args.end)
    print(f"  получено событий: {len(rows)}")
    norm = ucdp.normalize(rows)
    norm, stats = match.attribute_all(norm, ds)
    n = db.upsert_events(con, norm)
    print(f"  записано новых: {n}")
    print(f"  сопоставление: rule={stats['rule']} geo={stats['geo']} "
          f"unmatched={stats['unmatched']} ({stats['unmatched_share']:.1%})")


def cmd_pull_gdelt(args):
    con = db.connect(args.db)
    ds = dy.load()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    now -= timedelta(minutes=now.minute % 15)
    total = 0
    for i in range(args.slices):
        stamp = (now - timedelta(minutes=15 * (i + 1))).strftime("%Y%m%d%H%M%S")
        blob = gdelt.get(gdelt.slice_url(stamp), use_cache=True)
        if not blob:
            print(f"  {stamp}: срез недоступен, пропуск")
            continue
        norm = gdelt.normalize(gdelt.parse_export(blob))
        norm, stats = match.attribute_all(norm, ds)
        keep = [e for e in norm if e["dyad_id"]]
        total += db.upsert_events(con, keep)
        print(f"  {stamp}: пар государств {len(norm)}, отнесено к диадам {len(keep)}")
    db.set_watermark(con, "gdelt_export", now.strftime("%Y%m%d%H%M%S"))
    print(f"записано новых событий: {total}")


def cmd_llm_eval(args):
    """Согласие разметки модели с ручной. Решает, пускать ли индикатор в индекс."""
    import json
    from .llm import agreement_report
    gold = json.loads(open(args.gold, encoding="utf-8").read())
    pred = json.loads(open(args.pred, encoding="utf-8").read())
    rep = agreement_report(gold, pred, reject_rate=args.reject_rate)
    print(f"размер выборки:              {rep['n']}")
    print(f"точное совпадение:           {rep['exact_match']:.1%}")
    print(f"расхождение не более ступени:{rep['within_one']:.1%}")
    print(f"взвешенная каппа (эскалация):{rep['weighted_kappa_escalation']:.3f} "
          f"(порог {0.65})")
    print(f"каппа по виду признака:      {rep['kappa_kind']:.3f} (порог {0.60})")
    print(f"доля брака схемы:            {rep['reject_rate']:.1%} (порог 5%)")
    print(f"нестабильность:              {rep['instability']:.1%} (порог 10%)")
    print()
    for f in rep["per_level"]:
        print(f"  ступень {f['label']}: P={f['precision']:.2f} R={f['recall']:.2f} "
              f"F1={f['f1']:.2f} n={f['support']}")
    print(f"\nВЕРДИКТ: {rep['verdict']}")
    return 0 if rep["admitted"] else 1


def cmd_status(args):
    con = db.connect(args.db)
    print("диад в реестре:",
          con.execute("SELECT COUNT(*) c FROM dyads").fetchone()["c"])
    for r in con.execute(
            "SELECT source, COUNT(*) n, MIN(occurred_at) a, MAX(occurred_at) b "
            "FROM raw_events GROUP BY source"):
        print(f"  {r['source']:<16} {r['n']:>8} событий  {r['a']} .. {r['b']}")
    for r in con.execute("SELECT * FROM watermarks"):
        print(f"  метка {r['source']}: {r['position']} ({r['updated_at']})")


def main(argv=None):
    p = argparse.ArgumentParser(prog="escx")
    p.add_argument("--db", default="escx.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    b = sub.add_parser("backfill-ucdp")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.set_defaults(fn=cmd_backfill_ucdp)

    g = sub.add_parser("pull-gdelt")
    g.add_argument("--slices", type=int, default=4)
    g.set_defaults(fn=cmd_pull_gdelt)

    e = sub.add_parser("llm-eval")
    e.add_argument("--gold", required=True, help="JSON с ручной разметкой")
    e.add_argument("--pred", required=True, help="JSON с разметкой модели")
    e.add_argument("--reject-rate", type=float, default=0.0)
    e.set_defaults(fn=cmd_llm_eval)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
