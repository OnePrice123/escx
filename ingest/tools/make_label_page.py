"""Собирает страницу ручной разметки из pred.json.

Зачем отдельный инструмент. Шлюз ADMISSION сравнивает разметку модели с
разметкой человека, и всё его значение держится на том, что вторую делает
человек. Значит она должна быть выполнима: править JSON руками по двадцати
статьям человек либо не станет, либо станет невнимательно — и то и другое
портит измерение сильнее, чем отсутствие измерения.

Два решения, которые здесь важнее удобства:

1. РАЗМЕЧАЕТСЯ ТОТ ЖЕ ТЕКСТ, что читала модель. Поэтому статьи скачиваются той
   же функцией fetch_article и кладутся в страницу целиком, а не оставляются
   ссылкой. Если человек прочитает статью на сайте, а модель читала её же в
   виде текста без навигации и врезок — сравниваются два разных входа, и каппа
   меряет уже не согласие, а разницу вёрстки.

2. ОТВЕТ МОДЕЛИ СКРЫТ, а его показ ЗАПИРАЕТ ответ человека. Увидев чужую
   оценку, разметчик к ней подстраивается — привязка известна и сильна.
   В первой версии ответ открывался сам после выбора обоих полей, а кнопки
   оставались нажимаемыми: можно было посмотреть и молча поправить себя.
   Первый живой прогон дал 15 совпадений из 16, и отличить «случаи простые»
   от «разметчик подстроился» стало нельзя. Теперь показ — отдельная кнопка,
   после неё выбор не меняется.

3. ПЕРЕВОД (--translate) — уступка, а не улучшение. Ленты GDELT почти целиком
   англоязычные, и разметчик, читающий по-английски с трудом, ошибётся сильнее,
   чем ошибётся переводчик. Но платить за это приходится: модель размечала
   оригинал, а человек читает пересказ, и перевод способен сгладить или усилить
   ровно те формулировки, от которых зависит ступень. Поэтому оригинал остаётся
   на странице в один клик, цитата модели показывается как есть, а перевод
   просят делать буквальным. Если английский читается свободно — не включайте.

Запуск из папки ingest:

    python tools/make_label_page.py --pred pred.json --out label.html
    python tools/make_label_page.py --translate          # то же, но с переводом

Дальше страница открывается двойным кликом, размечается, кнопка сохраняет
gold.json рядом. Проверка согласия:

    python -m escx.cli llm-eval --gold gold.json --pred pred.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from escx import verify                                    # noqa: E402
from escx.llm.rubric import ESCALATION_ANCHORS             # noqa: E402
from escx.llm.schema import INDICATOR_KINDS                # noqa: E402

# Порядок видов в интерфейсе — от мирного к силовому, а не по алфавиту:
# так список читается как шкала и рука сама идёт в нужную сторону.
KIND_ORDER = ["none", "rhetoric", "negotiation", "treaty", "sanctions",
              "exercise", "mobilization", "readiness", "airspace",
              "armed_incident", "other"]

KIND_RU = {
    "none": "ничего по теме",
    "rhetoric": "риторика",
    "negotiation": "переговоры",
    "treaty": "соглашение",
    "sanctions": "санкции",
    "exercise": "учения",
    "mobilization": "мобилизация",
    "readiness": "боеготовность",
    "airspace": "воздушное пространство",
    "armed_incident": "вооружённый инцидент",
    "other": "другое",
}


TRANSLATE_SYSTEM = (
    "Ты переводчик новостных сообщений с английского на русский.\n"
    "Переводи БУКВАЛЬНО и полностью. Не пересказывай, не сокращай, не обобщай.\n"
    "Особенно точно передавай слова, обозначающие действие и его силу: удар, "
    "обстрел, учения, переброска, протест, санкции, погибшие, раненые. Не смягчай "
    "и не усиливай их — от выбора слова здесь зависит оценка события.\n"
    "Имена, названия ведомств и географию оставляй узнаваемыми.\n"
    "В ответе — только перевод, без пояснений и заголовков."
)


def translate_all(items: list[dict], cache_path: Path, budget_usd: float) -> None:
    """Перевод текстов на русский с кэшем по адресу статьи.

    Кэш нужен не ради денег (перевод шестнадцати статей стоит меньше цента),
    а ради повторных запусков: страницу пересобирают, поправив разметку или
    выборку, и платить заново за то же самое незачем.
    """
    from escx.llm.provider import GeminiProvider, PRICES

    cache: dict[str, str] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))

    provider = GeminiProvider()
    pin, pout = PRICES.get(provider.model, (0.0, 0.0))
    spent = 0.0

    for i, it in enumerate(items, 1):
        if not it["text"]:
            continue
        if it["url"] in cache:
            it["text_ru"] = cache[it["url"]]
            print(f"  {i:2}/{len(items)}  из кэша")
            continue
        if spent >= budget_usd:
            print(f"  {i:2}/{len(items)}  пропуск: исчерпан лимит ${budget_usd}")
            continue
        try:
            out, ti, to = provider.complete(TRANSLATE_SYSTEM, it["text"])
            spent += ti / 1e6 * pin + to / 1e6 * pout
            it["text_ru"] = out.strip()
            cache[it["url"]] = it["text_ru"]
            print(f"  {i:2}/{len(items)}  переведено")
        except Exception as e:
            # Непереведённая статья — не повод останавливать всю сборку:
            # на странице она просто останется на языке оригинала.
            print(f"  {i:2}/{len(items)}  не переведено: {str(e)[:70]}")

    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"  потрачено на перевод: ${spent:.5f}")


def collect(pred: list[dict], pause: float) -> list[dict]:
    """Скачивает тексты статей. Пропущенные не выбрасываются молча."""
    items, missed = [], 0
    for i, p in enumerate(pred, 1):
        text = verify.fetch_article(p["url"], pause=pause)
        status = "ок" if text else "не открылась"
        print(f"  {i:2}/{len(pred)}  {p['dyad_id']:9} {status}  {p['url'][:70]}")
        if not text:
            missed += 1
        items.append({
            "dyad_id": p["dyad_id"],
            "day": p.get("day", ""),
            "url": p["url"],
            "text": text or "",
            "text_ru": "",
            "cameo_root": p.get("cameo_root", ""),
            "gdelt_kind": p.get("gdelt_kind"),
            "llm_kind": p.get("llm_kind"),
            "llm_escalation": p.get("llm_escalation"),
            "evidence": p.get("evidence") or "",
        })
    if missed:
        print(f"\n  не открылось статей: {missed}. Разметить их нельзя — в странице "
              f"они помечены и пропускаются, но из pred.json НЕ удаляются: "
              f"llm-eval сравнивает списки по позициям.")
    return items


def render(items: list[dict]) -> str:
    anchors = [{"level": lvl, "title": a[0], "desc": a[1], "example": a[2]}
               for lvl, a in sorted(ESCALATION_ANCHORS.items())]
    kinds = [{"id": k, "ru": KIND_RU.get(k, k)} for k in KIND_ORDER
             if k in INDICATOR_KINDS]
    data = {"items": items, "anchors": anchors, "kinds": kinds}
    return TEMPLATE.replace("/*DATA*/", json.dumps(data, ensure_ascii=False))


TEMPLATE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Разметка для допуска модели — ESCX</title>
<style>
  :root {
    --paper:#FBFAF8; --ink:#14181A; --ink-2:#4A5257; --ink-3:#7C8489;
    --hair:#E4E0DA; --raised:#FFFFFF; --warm:#C4703B; --hot:#A83F2B;
  }
  @media (prefers-color-scheme: dark) {
    :root { --paper:#141618; --ink:#ECEAE6; --ink-2:#A8AEB2; --ink-3:#7C8489;
            --hair:#2A2E31; --raised:#1B1E21; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
         font:400 15px/1.6 -apple-system,"Segoe UI",Roboto,sans-serif; }
  .wrap { max-width:1180px; margin:0 auto; padding:22px 20px 80px; }
  h1 { font:400 24px/1.2 Georgia,serif; margin:0 0 4px; }
  .lede { color:var(--ink-2); font-size:13.5px; margin:0 0 18px; }
  .bar { display:flex; align-items:center; gap:14px; flex-wrap:wrap;
         padding:12px 0; border-bottom:1px solid var(--hair); margin-bottom:18px; }
  .count { font-variant-numeric:tabular-nums; color:var(--ink-2); font-size:13px; }
  .prog { flex:1; height:3px; background:var(--hair); border-radius:2px; min-width:120px; }
  .prog i { display:block; height:100%; background:var(--warm); border-radius:2px; }
  .cols { display:grid; grid-template-columns:1.35fr 1fr; gap:26px; align-items:start; }
  @media (max-width:900px) { .cols { grid-template-columns:1fr; } }
  .art { background:var(--raised); border:1px solid var(--hair); border-radius:4px;
         padding:18px 20px; max-height:70vh; overflow:auto; }
  .meta { font-size:12px; color:var(--ink-3); margin-bottom:10px;
          display:flex; gap:12px; flex-wrap:wrap; }
  .meta a { color:var(--ink-3); }
  .text { white-space:pre-wrap; font-size:14.5px; line-height:1.7; }
  .empty { color:var(--hot); }
  .warn { margin:0 0 12px; padding-left:10px; border-left:2px solid var(--warm);
          font-size:12.5px; color:var(--ink-3); }
  .meta button { background:none; border:0; padding:0; cursor:pointer; font:inherit;
                 font-size:12px; color:var(--ink-3); text-decoration:underline;
                 text-underline-offset:3px; }
  .meta button:hover { color:var(--ink); }
  fieldset { border:0; padding:0; margin:0 0 22px; }
  legend { font:600 10px/1 sans-serif; letter-spacing:.16em; text-transform:uppercase;
           color:var(--ink-3); margin-bottom:10px; }
  .opt { display:block; width:100%; text-align:left; cursor:pointer; margin-bottom:6px;
         background:var(--raised); color:var(--ink); border:1px solid var(--hair);
         border-radius:4px; padding:9px 12px; font:inherit; }
  .opt:hover { border-color:var(--ink-3); }
  .opt[aria-pressed="true"] { border-color:var(--ink); background:var(--ink); color:var(--paper); }
  .opt b { font-weight:600; }
  .opt small { display:block; color:var(--ink-3); font-size:12px; margin-top:2px; }
  .opt[aria-pressed="true"] small { color:rgba(255,255,255,.7); }
  .kinds { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
  .kinds .opt { margin:0; padding:7px 10px; font-size:13.5px; }
  .act { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:6px; }
  button.go { background:var(--ink); color:var(--paper); border:1px solid var(--ink);
              border-radius:4px; padding:11px 20px; font:500 14px sans-serif; cursor:pointer; }
  button.go:disabled { opacity:.4; cursor:default; }
  button.ghost { background:transparent; color:var(--ink-2); border:1px solid var(--hair);
                 border-radius:4px; padding:11px 16px; font:400 13px sans-serif; cursor:pointer; }
  .reveal { margin-top:16px; padding:12px 14px; border-left:2px solid var(--warm);
            font-size:13px; color:var(--ink-2); background:var(--raised); }
  .reveal.same { border-left-color:var(--ink-3); }
  .reveal b { color:var(--ink); font-weight:600; }
  .done { text-align:center; padding:50px 20px; }
  .done h2 { font:400 22px Georgia,serif; }
  textarea { width:100%; height:220px; font:12px/1.5 ui-monospace,Consolas,monospace;
             background:var(--raised); color:var(--ink); border:1px solid var(--hair);
             border-radius:4px; padding:10px; }
  .hint { font-size:12.5px; color:var(--ink-3); margin-top:10px; }
  code { background:var(--raised); border:1px solid var(--hair); border-radius:3px;
         padding:1px 5px; font:12px ui-monospace,Consolas,monospace; }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<div class="wrap">

  <h1>Разметка для допуска модели</h1>
  <p class="lede">Прочитайте текст и поставьте свою оценку. Ответ модели закрыт до вашего выбора — это не игра, а условие измерения: увидев чужую оценку заранее, вы будете к ней подстраиваться, согласие окажется завышенным и шлюз пропустит то, что пропускать нельзя.</p>

  <div id="work">
    <div class="bar">
      <span class="count" id="count"></span>
      <span class="prog"><i id="prog"></i></span>
      <button class="ghost" id="back">Назад</button>
      <button class="ghost" id="save">Сохранить черновик</button>
    </div>

    <div class="cols">
      <div class="art">
        <div class="meta" id="meta"></div>
        <p class="warn" id="warn" hidden>Вы читаете перевод. Модель размечала английский оригинал — если формулировка выглядит решающей для оценки, откройте оригинал.</p>
        <div class="text" id="text"></div>
      </div>

      <div>
        <fieldset>
          <legend>Ступень эскалации</legend>
          <div id="levels"></div>
        </fieldset>

        <fieldset>
          <legend>Вид признака</legend>
          <div class="kinds" id="kinds"></div>
        </fieldset>

        <div class="act">
          <button class="go" id="next" disabled>Дальше</button>
          <button class="ghost" id="peek" hidden>Показать ответ модели</button>
          <span class="hint" id="need">выберите ступень и вид</span>
        </div>

        <div class="reveal" id="reveal" hidden></div>
      </div>
    </div>
  </div>

  <div class="done" id="done" hidden>
    <h2>Разметка готова</h2>
    <p class="lede" id="doneStat"></p>
    <p><button class="go" id="dl">Скачать gold.json</button>
       <button class="ghost" id="again">Разметить заново</button></p>
    <p class="hint">Если кнопка не сработала — скопируйте содержимое поля ниже и сохраните как <code>gold.json</code> рядом с <code>pred.json</code>, затем запустите:<br>
      <code>python -m escx.cli llm-eval --gold gold.json --pred pred.json</code></p>
    <textarea id="out" readonly></textarea>
  </div>

</div>
<script>
const DATA = /*DATA*/;
const KEY = 'escx-gold-draft';
const LANG = 'escx-show-original';
const $ = s => document.querySelector(s);
let orig = !!localStorage.getItem(LANG);   // читать оригинал вместо перевода

let marks = JSON.parse(localStorage.getItem(KEY) || 'null')
         || DATA.items.map(() => ({ escalation_level: null, indicator_kind: null }));
if (marks.length !== DATA.items.length) marks = DATA.items.map(() => ({ escalation_level: null, indicator_kind: null }));

// Начинаем с первого неразмеченного, а не с нуля: прерваться и вернуться
// человек захочет обязательно, двадцать статей за один присест читают редко.
let i = Math.max(0, marks.findIndex(m => m.escalation_level === null));
if (i === -1) i = DATA.items.length - 1;

function optButton(cls, pressed, html) {
  const b = document.createElement('button');
  b.className = cls; b.type = 'button';
  b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
  b.innerHTML = html;
  return b;
}

function paint() {
  if (marks.every(m => m.escalation_level !== null && m.indicator_kind)) return finish();

  const it = DATA.items[i], m = marks[i];
  $('#count').textContent = `${i + 1} из ${DATA.items.length}`;
  $('#prog').style.width = (100 * marks.filter(x => x.escalation_level !== null).length / marks.length) + '%';

  $('#meta').innerHTML = '';
  const meta = [it.dyad_id, it.day, 'код CAMEO ' + it.cameo_root];
  meta.forEach(t => { const s = document.createElement('span'); s.textContent = t; $('#meta').appendChild(s); });
  const a = document.createElement('a');
  a.href = it.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'источник';
  $('#meta').appendChild(a);

  if (it.text_ru) {
    const t = document.createElement('button');
    t.type = 'button';
    t.textContent = orig ? 'показать перевод' : 'показать оригинал';
    t.onclick = () => { orig = !orig; localStorage.setItem(LANG, orig ? '1' : ''); paint(); };
    $('#meta').appendChild(t);
  }

  // Перевод показываем по умолчанию, но предупреждение о нём — только когда
  // человек действительно читает перевод, а не оригинал.
  const body = (it.text_ru && !orig) ? it.text_ru : it.text;
  $('#warn').hidden = !(it.text_ru && !orig);
  $('#text').className = 'text' + (body ? '' : ' empty');
  $('#text').textContent = body
    || 'Статья не открылась — разметить нечего. Поставьте «ничего по теме» и ступень 0: запись обязана остаться на месте, llm-eval сравнивает списки по позициям.';

  $('#levels').innerHTML = '';
  DATA.anchors.forEach(a => {
    const b = optButton('opt', m.escalation_level === a.level,
      `<b>${a.level} — ${a.title}</b><small>${a.desc}<br>Пример: ${a.example}</small>`);
    b.onclick = () => { m.escalation_level = a.level; sync(); };
    $('#levels').appendChild(b);
  });

  $('#kinds').innerHTML = '';
  DATA.kinds.forEach(k => {
    const b = optButton('opt', m.indicator_kind === k.id, k.ru);
    b.onclick = () => { m.indicator_kind = k.id; sync(); };
    $('#kinds').appendChild(b);
  });

  $('#reveal').hidden = true;
  $('#back').disabled = i === 0;
  sync(false);
}

function sync(repaint = true) {
  const m = marks[i];
  const ready = m.escalation_level !== null && !!m.indicator_kind;
  $('#next').disabled = !ready;
  $('#peek').hidden = !ready || m.locked;
  $('#need').textContent = ready ? '' : 'выберите ступень и вид';
  localStorage.setItem(KEY, JSON.stringify(marks));

  if (m.locked) reveal();
  if (repaint) {
    document.querySelectorAll('#levels .opt').forEach((b, k) =>
      b.setAttribute('aria-pressed', marks[i].escalation_level === DATA.anchors[k].level));
    document.querySelectorAll('#kinds .opt').forEach((b, k) =>
      b.setAttribute('aria-pressed', marks[i].indicator_kind === DATA.kinds[k].id));
  }
}

/**
 * Показ ответа модели ЗАПИРАЕТ ответ человека.
 *
 * В первой версии ответ открывался сам, как только выбраны оба поля, а кнопки
 * оставались нажимаемыми — то есть можно было увидеть чужую оценку и молча
 * подогнать свою. Первый живой прогон дал 15 совпадений из 16, и отличить
 * «случаи были простые» от «разметчик подстроился» стало невозможно. Теперь
 * показ добровольный и необратимый: не хотите запирать — просто жмите «Дальше».
 */
function reveal() {
  const m = marks[i], it = DATA.items[i];
  m.locked = true;
  localStorage.setItem(KEY, JSON.stringify(marks));
  document.querySelectorAll('#levels .opt, #kinds .opt').forEach(b => b.disabled = true);
  $('#peek').hidden = true;

  const same = it.llm_escalation === m.escalation_level && it.llm_kind === m.indicator_kind;
  const ru = id => (DATA.kinds.find(k => k.id === id) || {}).ru || id;
  $('#reveal').className = 'reveal' + (same ? ' same' : '');
  $('#reveal').innerHTML =
    (same ? `Модель ответила так же: <b>${it.llm_escalation}</b>, <b>${ru(it.llm_kind)}</b>.`
          : `Модель: <b>${it.llm_escalation}</b>, <b>${ru(it.llm_kind)}</b>. `
            + `GDELT кодировал как <b>${ru(it.gdelt_kind)}</b>.`)
    + (it.evidence ? `<br>Цитата, на которую сослалась модель: «${it.evidence}»` : '')
    + `<br><span style="color:var(--ink-3)">Ваш ответ записан и больше не меняется.</span>`;
  $('#reveal').hidden = false;
}

function finish() {
  $('#work').hidden = true;
  $('#done').hidden = false;
  const gold = marks.map(m => ({ escalation_level: m.escalation_level, indicator_kind: m.indicator_kind }));
  const agreeE = gold.filter((g, k) => g.escalation_level === DATA.items[k].llm_escalation).length;
  const agreeK = gold.filter((g, k) => g.indicator_kind === DATA.items[k].llm_kind).length;
  $('#doneStat').textContent =
    `Совпало с моделью: по ступени ${agreeE} из ${gold.length}, по виду ${agreeK} из ${gold.length}. `
    + `Каппу и вердикт посчитает llm-eval — простая доля совпадений завышает согласие.`;
  $('#out').value = JSON.stringify(gold, null, 1);
}

$('#peek').onclick = reveal;
$('#next').onclick = () => {
  if (i < DATA.items.length - 1) { i++; paint(); } else finish();
};
$('#back').onclick = () => { if (i > 0) { i--; paint(); } };
$('#save').onclick = () => { localStorage.setItem(KEY, JSON.stringify(marks)); $('#need').textContent = 'черновик сохранён'; };
$('#again').onclick = () => { localStorage.removeItem(KEY);
  marks = DATA.items.map(() => ({ escalation_level: null, indicator_kind: null }));
  i = 0; $('#done').hidden = true; $('#work').hidden = false; paint(); };
$('#dl').onclick = () => {
  const b = new Blob([$('#out').value], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b); a.download = 'gold.json'; a.click();
  URL.revokeObjectURL(a.href);
};

paint();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="страница ручной разметки из pred.json")
    ap.add_argument("--pred", default="pred.json")
    ap.add_argument("--out", default="label.html")
    ap.add_argument("--pause", type=float, default=1.0,
                    help="пауза между запросами к сайтам, секунды")
    ap.add_argument("--translate", action="store_true",
                    help="перевести статьи на русский (нужен GEMINI_API_KEY)")
    ap.add_argument("--translate-budget", type=float, default=0.20,
                    help="потолок расходов на перевод, доллары")
    args = ap.parse_args()

    pred = json.loads(Path(args.pred).read_text(encoding="utf-8"))
    if not pred:
        print("pred.json пуст — сначала verify-coding --out pred.json")
        return 1

    print(f"скачиваю тексты {len(pred)} статей (это те же тексты, что читала модель)")
    items = collect(pred, args.pause)

    if args.translate:
        print("\nперевожу на русский")
        translate_all(items, Path(args.out).with_name("label_cache.json"),
                      args.translate_budget)

    Path(args.out).write_text(render(items), encoding="utf-8")
    ready = sum(1 for x in items if x["text"])
    ru = sum(1 for x in items if x.get("text_ru"))
    print(f"\nстраница готова: {args.out}  ({ready} статей с текстом из {len(items)}"
          + (f", переведено {ru}" if args.translate else "") + ")")
    print("откройте её двойным кликом, разметьте, сохраните gold.json рядом с pred.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
