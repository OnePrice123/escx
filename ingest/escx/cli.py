"""Точка входа. Команды запускаются из cron или GitHub Actions.

  python -m escx.cli init
  python -m escx.cli load-ucdp                 # вся история из открытой выгрузки
  python -m escx.cli pull-candidate            # предварительные данные этого года
  python -m escx.cli backfill-ucdp --start 2015-01-01 --end 2024-12-31   # через API, нужен токен
  python -m escx.cli pull-gdelt --slices 8
  python -m escx.cli pull-weights
  python -m escx.cli compute
  python -m escx.cli status
"""
from __future__ import annotations
import argparse, json, sys, uuid
from datetime import date, datetime, timedelta, timezone

from . import compute as comp, db, dyads as dy, match
from .sources import ucdp, gdelt, worldbank, simple
from . import sanctions as sanc


def cmd_init(args):
    con = db.connect(args.db)
    ds = dy.load()
    dy.install(con, ds)
    print(f"схема создана, диад в реестре: {len(ds)}")


def cmd_backfill_ucdp(args):
    con = db.connect(args.db)
    ds = dy.load()
    # Версия датасета сверяется с API до загрузки. Иначе устаревший номер
    # молча отдаёт ноль событий, и прогон выглядит успешным при пустой базе.
    version = ucdp.resolve_version()
    if not version:
        sys.exit("API UCDP недоступно. С 2026 года оно требует токен: положите его "
                 "в переменную окружения UCDP_TOKEN (как получить — "
                 "https://ucdp.uu.se/apidocs/).\n"
                 "Токен нужен НЕ ВСЕГДА: те же данные лежат открытыми файлами. "
                 "Используйте `python -m escx.cli load-ucdp` — истории он берёт "
                 "оттуда и работает без токена.")
    if version != ucdp.VERSION:
        print(f"  ВНИМАНИЕ: версия {ucdp.VERSION} недоступна, работаю на {version}. "
              f"Обновите VERSION в escx/sources/ucdp.py")
    print(f"UCDP GED {version}: {args.start} .. {args.end}")
    rows = ucdp.fetch_ged(start=args.start, end=args.end, version=version)
    print(f"  получено событий: {len(rows)}")
    if not rows:
        print("  за период событий нет — это возможно для короткого промежутка, "
              "но подозрительно для целого года")
    norm = ucdp.normalize(rows)
    norm, stats = match.attribute_all(norm, ds)
    n = db.upsert_events(con, norm)
    print(f"  записано новых: {n}")
    print(f"  сопоставление: rule={stats['rule']} geo={stats['geo']} "
          f"unmatched={stats['unmatched']} ({stats['unmatched_share']:.1%})")


def _ingest_batches(con, ds, rows_iter, source: str, batch: int = 20000,
                    since: str = "", until: str = "") -> tuple[int, int]:
    """Общий конвейер для потоковой загрузки: партия -> нормализация -> база.

    Партиями, а не целиком: в полном GED около 400 тысяч событий, и список
    словарей такого размера занимает под гигабайт. Партия в двадцать тысяч
    держит память ровной и не мешает идемпотентности — ключ (source, source_id)
    всё равно отсекает повторы.
    """
    total = seen = 0
    buf: list[dict] = []

    def flush():
        nonlocal total
        if not buf:
            return
        norm = ucdp.normalize(buf, source=source)
        if since or until:
            norm = [e for e in norm if (not since or e["occurred_at"] >= since)
                    and (not until or e["occurred_at"] <= until)]
        norm, _ = match.attribute_all(norm, ds)
        total += db.upsert_events(con, norm)
        buf.clear()

    for row in rows_iter:
        buf.append(row)
        seen += 1
        if len(buf) >= batch:
            flush()
            print(f"  обработано {seen}, записано новых {total}", flush=True)
    flush()
    return seen, total


def cmd_load_ucdp(args):
    """Полная история из открытой выгрузки. Токен не нужен.

    С 2026 года API UCDP требует токен, а готовые файлы — нет. Для истории
    файлы и удобнее: один zip вместо четырёхсот страничных запросов.
    """
    con = db.connect(args.db)
    ds = dy.load()
    v = ucdp.resolve_bulk_version()
    if not v:
        sys.exit("выгрузка UCDP недоступна ни в одной известной версии "
                 f"({', '.join(ucdp.VERSION_CANDIDATES)}). "
                 "Проверьте https://ucdp.uu.se/downloads/ — вероятно, вышла новая "
                 "версия, её номер добавляется в escx/sources/ucdp.py")
    print(f"UCDP GED {v} (готовая выгрузка, ~50 МБ) — качаю")
    seen, total = _ingest_batches(con, ds, ucdp.iter_bulk_ged(v), "ucdp_ged",
                                  since=args.start or "", until=args.end or "")
    print(f"прочитано событий: {seen}, записано новых: {total}")
    if not seen:
        sys.exit("выгрузка пуста — это не бывает штатно, прогон остановлен")


def cmd_pull_candidate(args):
    """Предварительные данные за текущий год: месячные файлы, тоже без токена."""
    con = db.connect(args.db)
    ds = dy.load()
    year = args.year or datetime.now(timezone.utc).year
    month = args.month or ucdp.latest_candidate(year)
    if not month:
        print(f"за {year} год кандидатских файлов ещё нет — пропуск")
        return
    print(f"UCDP Candidate {year}-{month:02d}")
    seen, total = _ingest_batches(con, ds, ucdp.iter_candidate(year, month),
                                  "ucdp_candidate")
    print(f"прочитано событий: {seen}, записано новых: {total}")


def cmd_pull_sanctions(args):
    """Санкционные меры OFAC как события экономического блока.

    Индикатор — не список, а ДЕЛЬТА к прошлому прогону: сам по себе перечень из
    девятнадцати тысяч записей ничего не говорит о динамике, а введение меры
    является событием эскалации, снятие — деэскалации.

    Привязка записи к диаде идёт через программу (поле program в sdn.csv), и
    таблица привязок лежит в config/sanctions_programs.json отдельным файлом:
    это редакторское решение, а не выгрузка из источника. Страны в файле OFAC
    нет вовсе — программа единственная зацепка.

    Пара, для которой привязки нет, НЕ получает нулей: у неё экономический блок
    остаётся неизмеренным. Ноль означал бы «санкций не вводили», а правда в том,
    что этим источником её канал не меряется совсем.
    """
    con = db.connect(args.db)
    prog_map = sanc.load_program_map()
    if not prog_map:
        print("нет config/sanctions_programs.json — пропуск"); return

    blob = simple.get(simple.OFAC_SDN_CSV, use_cache=False)
    if not blob:
        print("выгрузка OFAC недоступна — пропуск"); return
    rows = simple.parse_ofac_sdn_rows(blob)
    if len(rows) < 1000:
        # Пустой или обрезанный файл выглядел бы как массовое снятие всех мер
        # разом и создал бы гигантский ложный сигнал деэскалации.
        print(f"в выгрузке всего {len(rows)} записей — это не похоже на правду, "
              f"прогон остановлен"); return
    print(f"OFAC SDN: записей {len(rows)}")

    today = datetime.now(timezone.utc).date().isoformat()
    events = []
    for dyad_id, progs in prog_map.items():
        curr = {r["ent_num"] for r in rows if progs & set(r["programs"])}
        prev = db.sanctions_state(con, dyad_id)
        first_run = not prev

        added, removed = curr - prev, prev - curr
        # Первый прогон — не событие: весь список разом не «вводился сегодня».
        # Иначе стартовый день дал бы всплеск на тысячи мер из ниоткуда.
        if first_run:
            print(f"  {dyad_id}: первый прогон, зафиксировано {len(curr)} мер "
                  f"(событиями не считаются)")
        else:
            for e in sorted(added):
                events.append(_sanction_event(dyad_id, e, today, +1))
            for e in sorted(removed):
                events.append(_sanction_event(dyad_id, e, today, -1))
            if added or removed:
                print(f"  {dyad_id}: введено {len(added)}, снято {len(removed)}")
            else:
                print(f"  {dyad_id}: без изменений ({len(curr)} мер)")
        db.set_sanctions_state(con, dyad_id, curr, today)

    n = db.upsert_events(con, events)
    print(f"записано событий: {n}")


def _sanction_event(dyad_id: str, ent_num: str, day: str, sign: int) -> dict:
    kind = "sanction_add" if sign > 0 else "sanction_lift"
    return {
        "source": "ofac_sdn",
        # Дата в ключе обязательна: одну и ту же запись могут снять и через год
        # вернуть, и без даты второе событие потерялось бы как дубликат.
        "source_id": f"{dyad_id}:{ent_num}:{kind}:{day}",
        "occurred_at": day,
        "dyad_id": dyad_id,
        "match_level": "rule",
        "event_type": kind,
        "payload": json.dumps({"ent_num": ent_num, "sign": sign}, ensure_ascii=False),
    }


def cmd_backfill_gdelt(args):
    """История GDELT из суточных файлов 1.0.

    Зачем отдельная команда, а не флаг у pull-gdelt: та ходит по срезам 2.0 и
    двигается ТОЛЬКО вперёд по метке watermark, потому что для живого потока это
    правильно. Бэкфилл идёт назад и по другим файлам — смешивать эти два обхода
    в одной функции значит гарантированно однажды сдвинуть метку не туда и
    потерять срезы навсегда.

    Почему это вообще нужно. История GDELT нигде, кроме базы, не хранится: файл
    базы лежит в кэше GitHub Actions и в репозиторий не коммитится. Потеря кэша
    до появления этой команды означала безвозвратную потерю всех данных за
    период, который UCDP ещё не покрыл, — то есть всего текущего года.
    """
    con = db.connect(args.db)
    ds = dy.load()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if start > end:
        print("начало позже конца"); return 1

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    print(f"бэкфилл GDELT: {len(days)} суток, {start} .. {end}")
    total = skipped = missing = 0

    for d in days:
        iso = d.isoformat()
        # Знаменатель нормировки в series накопительный: повторный проход по
        # тем же суткам удвоил бы его и тихо занизил инфополе вдвое. Поэтому
        # день, уже посчитанный, пропускается целиком — события идемпотентны
        # по ключу (source, source_id), а вот объём упоминаний нет.
        if db.get_watermark(con, f"gdelt_daily:{iso}"):
            skipped += 1
            continue

        blob = gdelt.get(gdelt.daily_url_v1(iso), use_cache=True)
        if not blob:
            print(f"  {iso}: файла нет, пропуск")
            missing += 1
            continue

        norm = gdelt.normalize(gdelt.parse_daily_v1(blob))
        norm, _ = match.attribute_all(norm, ds)
        keep = [e for e in norm if e["dyad_id"]]
        n = db.upsert_events(con, keep)
        total += n
        db.add_series(con, "gdelt", "global_mentions", iso,
                      sum(e.get("num_mentions") or 1 for e in norm))
        db.set_watermark(con, f"gdelt_daily:{iso}", "done")
        print(f"  {iso}: пар государств {len(norm)}, диад {len(keep)}, новых {n}")

    print(f"записано новых событий: {total}"
          + (f", пропущено уже загруженных суток: {skipped}" if skipped else "")
          + (f", файлов не нашлось: {missing}" if missing else ""))


def cmd_pull_gdelt(args):
    con = db.connect(args.db)
    ds = dy.load()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    now -= timedelta(minutes=now.minute % 15)
    # Метка последнего обработанного среза. Пропуск уже загруженных обязателен:
    # события защищены ключом (source, source_id) и повторов не дадут, а вот
    # суточный объём упоминаний накапливается — повторный срез удвоил бы
    # знаменатель нормировки и тихо занизил инфополе.
    seen = db.get_watermark(con, "gdelt_export")
    newest = seen
    total = skipped = 0
    for i in range(args.slices):
        stamp = (now - timedelta(minutes=15 * (i + 1))).strftime("%Y%m%d%H%M%S")
        if seen and stamp <= seen:
            skipped += 1
            continue
        blob = gdelt.get(gdelt.slice_url(stamp), use_cache=True)
        if not blob:
            print(f"  {stamp}: срез недоступен, пропуск")
            continue
        newest = max(newest, stamp)
        norm = gdelt.normalize(gdelt.parse_export(blob))
        norm, stats = match.attribute_all(norm, ds)
        keep = [e for e in norm if e["dyad_id"]]
        total += db.upsert_events(con, keep)

        # Общий объём упоминаний в срезе сохраняем ОТДЕЛЬНО от событий диад.
        # Это знаменатель нормировки инфополя (правило 5 методологии): без него
        # индикатор мерит внимание прессы, а не напряжённость. Считается по
        # всему срезу, включая пары, которые нас не касаются, — в этом весь смысл.
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
        db.add_series(con, "gdelt", "global_mentions", day,
                      sum(e.get("num_mentions") or 1 for e in norm))
        print(f"  {stamp}: пар государств {len(norm)}, отнесено к диадам {len(keep)}")
    # Метка двигается на реально обработанный срез, а не на «сейчас»: при сбое
    # сети «сейчас» перескочило бы через недокачанные срезы и потеряло их навсегда.
    if newest and newest != seen:
        db.set_watermark(con, "gdelt_export", newest)
    print(f"записано новых событий: {total}"
          + (f", пропущено уже загруженных срезов: {skipped}" if skipped else ""))


def cmd_pull_weights(args):
    """Доли населения, ВВП и военных расходов — веса последствий для GEI.

    Раз в год этого достаточно: доли меняются на десятые доли процента, а
    глобальный индекс к ним не чувствителен. Но без них он не считается вовсе.
    """
    con = db.connect(args.db)
    today = datetime.now(timezone.utc).date().isoformat()
    for key, code in worldbank.INDICATORS.items():
        vals = worldbank.fetch(code)
        sh = worldbank.shares(vals)
        for iso, share in sh.items():
            con.execute(
                "INSERT INTO series(source,series_key,as_of,value) VALUES(?,?,?,?) "
                "ON CONFLICT(source,series_key,as_of) DO UPDATE SET value=excluded.value",
                ("worldbank", f"share_{key}:{iso}", today, share))
        print(f"  {key} ({code}): стран {len(sh)}")
    con.commit()


def cmd_compute(args):
    """Пересчёт индикаторов и накала. Без него сайт остаётся пустым."""
    con = db.connect(args.db)
    r = comp.compute(con, days=args.days)
    if r.get("note"):
        print(f"расчёт не выполнен: {r['note']}")
        return
    print(f"прогон {r['run_id']}: диад {r['dyads']}, дней {r['days']}, "
          f"строк накала {r['heat_rows']}, смен фазы {r['phase_changes']}")
    print(f"  период данных: {r['span']}")


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
    n = con.execute("SELECT COUNT(*) c FROM heat_daily").fetchone()["c"]
    last = con.execute("SELECT MAX(day) d FROM heat_daily").fetchone()["d"]
    print(f"  накал рассчитан: строк {n}, последний день {last or '—'}")
    if not n:
        print("  ВНИМАНИЕ: расчёт ещё не выполнялся — сайт покажет пустой реестр.")
        print("            запустите: python -m escx.cli compute")


def main(argv=None):
    p = argparse.ArgumentParser(prog="escx")
    p.add_argument("--db", default="escx.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(fn=cmd_init)

    b = sub.add_parser("backfill-ucdp")
    b.add_argument("--start", required=True)
    b.add_argument("--end", required=True)
    b.set_defaults(fn=cmd_backfill_ucdp)

    lu = sub.add_parser("load-ucdp", help="полная история из открытой выгрузки")
    lu.add_argument("--start", default="", help="отсечь события раньше даты")
    lu.add_argument("--end", default="", help="отсечь события позже даты")
    lu.set_defaults(fn=cmd_load_ucdp)

    pc = sub.add_parser("pull-candidate", help="предварительные данные текущего года")
    pc.add_argument("--year", type=int)
    pc.add_argument("--month", type=int)
    pc.set_defaults(fn=cmd_pull_candidate)

    g = sub.add_parser("pull-gdelt")
    g.add_argument("--slices", type=int, default=4)
    g.set_defaults(fn=cmd_pull_gdelt)

    sub.add_parser("pull-sanctions",
                   help="дельта санкционного списка OFAC").set_defaults(fn=cmd_pull_sanctions)

    bg = sub.add_parser("backfill-gdelt",
                        help="история из суточных файлов GDELT 1.0")
    bg.add_argument("--start", required=True, help="YYYY-MM-DD")
    bg.add_argument("--end", required=True, help="YYYY-MM-DD")
    bg.set_defaults(fn=cmd_backfill_gdelt)

    e = sub.add_parser("llm-eval")
    e.add_argument("--gold", required=True, help="JSON с ручной разметкой")
    e.add_argument("--pred", required=True, help="JSON с разметкой модели")
    e.add_argument("--reject-rate", type=float, default=0.0)
    e.set_defaults(fn=cmd_llm_eval)

    sub.add_parser("pull-weights").set_defaults(fn=cmd_pull_weights)

    c = sub.add_parser("compute")
    c.add_argument("--days", type=int, default=comp.SERIES_DAYS,
                   help="сколько последних дней записать в витрину")
    c.set_defaults(fn=cmd_compute)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
