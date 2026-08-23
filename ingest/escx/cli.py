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
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

from . import calibrate, compute as comp, db, dyads as dy, match, verify
from .sources import ucdp, gdelt, worldbank, simple, adsb
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


def cmd_pull_adsb(args):
    """Снимок военной авиации по зонам наблюдения.

    Пишется ПОЧАСОВО и с заменой, а не накоплением: два запуска в один час
    описывают одно и то же небо, и складывать их значило бы удваивать зону
    из-за повторного запуска, а не из-за самолётов.

    Ноль в зоне НЕ записывается как ноль, если зона вообще не наблюдается:
    отсутствие приёмников и отсутствие авиации — разные вещи, и различить их
    потом будет уже нечем.

    ЧЕМ ИЗМЕРЯЕТСЯ НАБЛЮДАЕМОСТЬ. Раньше — числом военных бортов из той же
    ленты, и это не работало в принципе: ноль военных над Тайванем означает и
    «военных нет», и «приёмников нет». Теперь по каждой зоне отдельно берётся
    ВЕСЬ трафик, гражданский в том числе: он есть всюду, где есть приёмники,
    и потому разделяет эти два случая. Это лишний запрос на зону в час —
    четырнадцать запросов, для волонтёрской сети терпимо.

    Пишутся два ряда: obs — сколько бортов видно вообще, mil — сколько из них
    значимых по типу.
    """
    con = db.connect(args.db)
    zones = adsb_zones()
    if not zones:
        print("нет config/zones.json — пропуск"); return

    ac = adsb.fetch_military()
    if not ac:
        print("сеть ADS-B не ответила или пуста — пропуск"); return

    hour = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    counts = adsb.count_by_zone(ac, zones)
    observed = 0
    for dyad_id, (in_zone, sig) in sorted(counts.items()):
        box = zones[dyad_id].get("box")
        traffic = adsb.zone_traffic(box) if box else 0
        db.set_series(con, "adsb", f"obs:{dyad_id}", hour, float(traffic))
        db.set_series(con, "adsb", f"mil:{dyad_id}", hour, float(sig))
        if traffic:
            observed += 1
        mark = "" if traffic else "  ЗОНА НЕ НАБЛЮДАЕТСЯ"
        print(f"  {dyad_id:9} всего бортов {traffic:4}, военных {in_zone:3}, "
              f"значимых {sig}{mark}")
    print(f"снимок {hour}Z: военных бортов в мире {len(ac)}, "
          f"зон под наблюдением {observed} из {len(counts)}")


def adsb_zones() -> dict:
    import json as _json
    p = Path(__file__).resolve().parent.parent / "config" / "zones.json"
    if not p.exists():
        return {}
    return _json.loads(p.read_text(encoding="utf-8")).get("zones", {})


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


def cmd_calibrate(args):
    """Обратный прогон по конфликтам с известным исходом."""
    import json as _json
    con = db.connect(args.db)
    rep = calibrate.run(con)
    print(f"порог {rep['threshold']}, окно {rep['window_months']} мес., "
          f"блок — {rep['block']}")
    print(f"{'конфликт':26} {'исход':11} {'пик':>6} {'опережение':>26}")
    for r in rep["conflicts"]:
        if r.get("lead") is None:
            note = r.get("why") or r.get("note", "")
            print(f"  {r['name']:26} {r['outcome']:11} "
                  f"{str(r.get('peak','—')):>6} {note:>26}")
        else:
            print(f"  {r['name']:26} {r['outcome']:11} {r['peak']:>6} "
                  f"{str(r['lead']) + ' мес.':>26}")
    print(f"\nсигнал был у {rep['with_signal']} из {rep['n']}"
          + (f", медианное опережение {rep['median_lead']:.0f} мес."
             if rep["median_lead"] is not None else ""))
    ctl = calibrate.control(con)
    print(f"\nКОНТРОЛЬНАЯ ГРУППА: все переходы порога по полной истории")
    print(f"{'конфликт':26} {'мес.':>6} {'переходов':>10} {'из них ложных':>14}")
    for r in sorted(ctl["conflicts"], key=lambda x: -x["false"]):
        if r["crossings"]:
            print(f"  {r['name']:26} {r['months']:>6} {r['crossings']:>10} {r['false']:>14}")
    if ctl["precision"] is not None:
        print(f"\nвсего переходов {ctl['crossings']}: попаданий {ctl['hits']}, "
              f"ложных {ctl['false']} — доля попаданий {ctl['precision']:.0%} "
              f"при горизонте {ctl['horizon_m']} мес.")
    rep["control"] = ctl

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            _json.dump(rep, f, ensure_ascii=False, indent=1)
        print(f"отчёт сохранён: {args.out}")


def cmd_verify_coding(args):
    """Сверка кодировки GDELT с вердиктом модели на выборке событий.

    Ничего не пишет в индекс — это измеритель. Выход: JSON с парами
    «код GDELT / вид по модели», который скармливается llm-eval вместе с
    ручной разметкой. Пока согласие не пройдёт порог, модель в индекс не идёт.
    """
    import json as _json
    from .llm import build_prompt, validate, make_provider, Budget, PRICES
    from .llm.extract import _parse_json

    con = db.connect(args.db)
    # ВЫБОРКА РАЗНОСИТСЯ ПО СЮЖЕТАМ, а не берётся подряд с конца.
    #
    # Прежний запрос брал самые свежие события — и первый же живой прогон дал
    # шестнадцать записей на две новости: удары по Подмосковью в пересказе
    # девяти изданий и сокращение учений с Кореей в пересказе семи. Согласие
    # модели с человеком считалось по двум сюжетам, а выглядело как шестнадцать
    # независимых случаев; каппа при этом вышла 1.000 и не значила ничего.
    #
    # Поэтому по одному событию на (пара, день, корень CAMEO). Один и тот же
    # инцидент, размноженный лентами, схлопывается в одну запись, а выборка
    # растягивается по парам, датам и типам действия — то есть по тому, на чём
    # модель как раз и может расходиться с человеком.
    rows = list(con.execute(
        "SELECT dyad_id, occurred_at, cameo_code, event_type, payload FROM ("
        "  SELECT *, ROW_NUMBER() OVER ("
        "      PARTITION BY dyad_id, occurred_at, substr(event_type,7,2)"
        "      ORDER BY source_id) rn"
        "    FROM raw_events"
        "   WHERE source='gdelt_export'"
        "     AND substr(event_type,7,2) IN ('18','19','20','15')"
        ") WHERE rn = 1 "
        "ORDER BY occurred_at DESC, dyad_id, substr(event_type,7,2) "
        "LIMIT ?", (args.limit * 4,)))
    if not rows:
        print("нет событий для проверки"); return

    provider = make_provider(args.provider)
    bud = Budget(con, daily_usd=args.budget, prices=PRICES)
    print(f"модель {provider.name}, лимит ${args.budget}")

    out, seen_urls = [], set()
    agree = disagree = unread = 0
    for r in rows:
        if len(out) >= args.limit:
            break
        url = (_json.loads(r["payload"] or "{}") or {}).get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        text = verify.fetch_article(url)
        if not text:
            unread += 1
            continue

        root = (r["event_type"] or "").replace("cameo:", "")[:2]
        art = {"title": "", "body": text}
        system, user = build_prompt(art, None)
        try:
            raw, ti, to = provider.complete(system, user)
            bud.record(provider.name, ti, to)
            ex = validate(_parse_json(raw), text)
            kind = ex.indicator_kind
        except Exception as e:
            print(f"  {r['dyad_id']:9} {root} — модель не дала разметки: {str(e)[:70]}")
            continue

        ok = verify.agrees(root, kind)
        mark = "=" if ok else "РАСХОЖДЕНИЕ"
        if ok is True:
            agree += 1
        elif ok is False:
            disagree += 1
        print(f"  {r['dyad_id']:9} GDELT {root}->{verify.CAMEO_TO_KIND.get(root)}"
              f"  модель->{kind}  {mark}")
        out.append({"dyad_id": r["dyad_id"], "day": r["occurred_at"], "url": url,
                    "cameo_root": root, "gdelt_kind": verify.CAMEO_TO_KIND.get(root),
                    "llm_kind": kind, "llm_escalation": ex.escalation_level,
                    "evidence": ex.evidence})

    total = agree + disagree
    print(f"\nсверено {total}, совпало {agree}, разошлось {disagree}"
          + (f" ({100*disagree/total:.0f}% расхождений)" if total else "")
          + f", не прочитано {unread}")
    print(f"потрачено ${bud.spent_today():.5f}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            _json.dump(out, f, ensure_ascii=False, indent=1)
        print(f"разметка сохранена: {args.out}")


def cmd_pull_gpr(args):
    """Индекс геополитического риска Caldara & Iacoviello — для СВЕРКИ.

    Это единственный источник в пайплайне, который не участвует в расчёте
    индекса вовсе. Он лежит рядом и отвечает на вопрос, который иначе задать
    некому: а наш-то инфопоток не врёт?

    Инфополе целиком стоит на GDELT — один проект, одна автоматическая
    кодировка, одна точка доверия. GPR считается независимой академической
    группой по газетным архивам, другим методом и с опубликованной
    методологией. Совпадают движения — обоим можно верить. Разошлись —
    это повод разбираться, а не публиковать.

    Пускать его в индекс без прохождения того же порога согласия нельзя:
    это был бы ещё один медиаисточник, посчитанный как независимый блок.
    """
    from .sources import gpr

    con = db.connect(args.db)
    blob = gpr.fetch()
    if not blob:
        print("GPR недоступен — пропуск"); return

    since = None
    if args.since:
        y, _, m = args.since.partition("-")
        since = date(int(y), int(m or 1), 1)

    n = 0
    last: dict[str, tuple[str, float]] = {}
    for key, ym, value in gpr.iter_series(blob, since=since):
        db.set_series(con, "gpr", key, ym, value)
        last[key] = (ym, value)
        n += 1
    con.commit()

    g = last.get("global")
    print(f"записано значений: {n}, рядов: {len(last)}"
          + (f", глобальный GPR на {g[0]}: {g[1]:.1f}" if g else ""))
    print("  источник: Caldara & Iacoviello, matteoiacoviello.com/gpr.htm — "
          "использование свободное при указании авторов")


def cmd_pull_unvotes(args):
    """Расстояние внешнеполитических позиций по голосованиям Генассамблеи ООН.

    Единственный источник в пайплайне, который меряет ДИПЛОМАТИЮ, а не её
    отражение в прессе. Такт годовой — сессия ГА проходит раз в год, — поэтому
    сигнал медленный и суточной динамики не даёт. Он даёт другое: разницу
    МЕЖДУ парами, и она немаленькая. Иран и США расходятся на 4.0, Индия и
    Пакистан — на 0.02: воюют, но в ООН голосуют почти одинаково. Ни один
    медиапоток такого не скажет.

    Берётся готовый файл по парам (Voeten, Harvard Dataverse), а не сырые
    голосования: идеальные точки уже посчитаны опубликованным методом, и
    пересчитывать их самим значило бы заводить вторую методологию.
    """
    con = db.connect(args.db)
    ds = dy.load()
    want = {frozenset((d["side_a"], d["side_b"])) for d in ds}
    by_key = {frozenset((d["side_a"], d["side_b"])): d["dyad_id"] for d in ds}

    blob = simple.get(simple.UN_DYADS_FILE, use_cache=True)
    if not blob or len(blob) < 10_000_000:
        print(f"файл ООН недоступен или обрезан ({len(blob or b'')} байт) — пропуск")
        return
    found = simple.parse_un_dyads(blob, want)
    print(f"пар в реестре {len(want)}, найдено в ООН {len(found)}")

    for key, (year, val) in sorted(found.items(), key=lambda x: x[1][0]):
        dyad_id = by_key[key]
        db.set_series(con, "unvotes", dyad_id, f"{year}-12-31", val)
        print(f"  {dyad_id:9} {year}  расстояние {val:.3f}")

    missing = sorted(by_key[k] for k in want - set(found))
    if missing:
        # Косово не член ООН — его пары в этом источнике не появятся никогда.
        # Это не сбой, но и молчать нельзя: пара останется без блока.
        print(f"  нет в источнике: {', '.join(missing)}")


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

    cb = sub.add_parser("calibrate", help="обратный прогон по завершённым конфликтам")
    cb.add_argument("--out", default="")
    cb.set_defaults(fn=cmd_calibrate)

    vc = sub.add_parser("verify-coding", help="сверить кодировку GDELT с моделью")
    vc.add_argument("--limit", type=int, default=20)
    vc.add_argument("--budget", type=float, default=0.50)
    vc.add_argument("--provider", default=None, help="mock | gemini | openai")
    vc.add_argument("--out", default="", help="куда сложить разметку для llm-eval")
    vc.set_defaults(fn=cmd_verify_coding)

    sub.add_parser("pull-adsb",
                   help="снимок военной авиации по зонам").set_defaults(fn=cmd_pull_adsb)

    sub.add_parser("pull-unvotes",
                   help="расстояние позиций в ООН").set_defaults(fn=cmd_pull_unvotes)

    pg = sub.add_parser("pull-gpr", help="индекс геополитического риска для сверки")
    pg.add_argument("--since", default="", help="с какого месяца, ГГГГ-ММ (пусто — всё)")
    pg.set_defaults(fn=cmd_pull_gpr)

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
