"""Пайплайн LLM-скоринга: дёшево отсеять, дорого разметить, всё проверить.

Порядок шагов задан экономикой, а не удобством. В сыром потоке GDELT релевантных
сообщений единицы процентов; платить за токены на всём потоке нельзя. Поэтому:

  1. prefilter    — правила, ноль стоимости, отсекает ~95 %
  2. cache        — по хэшу текста и версии промпта, не платим дважды
  3. budget.check — оценка сверху ДО запроса
  4. LLM          — строго температура 0, ответ строго JSON
  5. validate     — схема + дословная цитата; брак отбраковывается целиком
  6. store        — в SQLite вместе с моделью и версией промпта

Шаг 5 нельзя ослаблять. Молчаливое «починить кривой JSON» — это способ протащить
галлюцинацию в индекс так, что её никто не заметит.
"""
from __future__ import annotations
import hashlib, json, re, sqlite3
from .rubric import build_prompt, PROMPT_VERSION
from .schema import validate, SchemaError, Extraction
from .budget import Budget, BudgetExceeded
from .provider import Provider, approx_tokens

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_scores (
  cache_key      TEXT PRIMARY KEY,
  article_id     TEXT NOT NULL,
  model          TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  payload        TEXT NOT NULL,
  scored_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS llm_rejects (
  article_id TEXT, model TEXT, reason TEXT, raw TEXT,
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Дешёвый фильтр. Намеренно ШИРОКИЙ: пропустить лишнее дешевле, чем потерять событие.
TRIGGERS = re.compile(
    r"санкц|эмбарго|экспортн\w* контрол|посол|демарш|протест|ультиматум|"
    r"учени|манёвр|мобилизац|переброск|боеготовн|воздушн\w* пространств|"
    r"обстрел|перестрел|удар|столкновени|погиб|ранен|захват|"
    r"перемири|переговор|соглашени|денонсац|разрыв отношени|граница закрыт",
    re.IGNORECASE)


def prefilter(article: dict, actors: set[str] | None = None) -> bool:
    """Правило: в тексте есть эскалационный маркер И минимум два государства.

    Второе условие важнее первого: сообщение про одну страну — не диадное событие,
    сколько бы тревожных слов в нём ни было.
    """
    text = f"{article.get('title','')} {article.get('body', article.get('snippet',''))}"
    if not TRIGGERS.search(text):
        return False
    if actors is not None:
        return len(actors) >= 2
    return True


def _key(article: dict, model: str) -> str:
    body = article.get("body", article.get("snippet", ""))
    h = hashlib.sha256(f"{article.get('title','')}\n{body}".encode()).hexdigest()[:32]
    return f"{h}:{model}:{PROMPT_VERSION}"


def _parse_json(text: str) -> dict:
    """Достаёт объект JSON. Никакого «чинения» — только вырезание обёртки."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\s*|\s*```$", "", t, flags=re.IGNORECASE | re.MULTILINE)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < 0:
        raise SchemaError("в ответе нет объекта JSON")
    return json.loads(t[i:j + 1])


def score_articles(con: sqlite3.Connection, provider: Provider, articles: list[dict],
                   *, budget: Budget, known_iso3: set[str] | None = None,
                   dyad_hints: dict[str, str] | None = None) -> dict:
    """Возвращает статистику прогона. Ничего не бросает, кроме исчерпания лимита."""
    con.executescript(SCHEMA)
    stats = {"seen": len(articles), "prefiltered": 0, "cached": 0,
             "scored": 0, "rejected": 0, "usd": 0.0, "stopped_by_budget": False}
    out: list[Extraction] = []

    for a in articles:
        aid = str(a.get("article_id") or a.get("url") or id(a))
        if not prefilter(a):
            stats["prefiltered"] += 1
            continue

        ck = _key(a, provider.name)
        row = con.execute("SELECT payload FROM llm_scores WHERE cache_key=?", (ck,)).fetchone()
        if row:
            stats["cached"] += 1
            out.append(Extraction(**json.loads(row[0])))
            continue

        system, user = build_prompt(a, (dyad_hints or {}).get(aid))
        try:
            budget.check(provider.name, approx_tokens(system + user), 220)
        except BudgetExceeded:
            stats["stopped_by_budget"] = True
            break

        text, ti, to = provider.complete(system, user)
        stats["usd"] += budget.record(provider.name, ti, to)

        source_text = f"{a.get('title','')} {a.get('body', a.get('snippet',''))}"
        try:
            ex = validate(_parse_json(text), source_text, known_iso3=known_iso3)
        except (SchemaError, json.JSONDecodeError) as e:
            stats["rejected"] += 1
            con.execute("INSERT INTO llm_rejects(article_id,model,reason,raw) VALUES(?,?,?,?)",
                        (aid, provider.name, str(e)[:300], text[:2000]))
            con.commit()
            continue

        ex = Extraction(**{**ex.as_dict(), "article_id": aid,
                           "model": provider.name, "prompt_version": PROMPT_VERSION})
        con.execute("INSERT OR REPLACE INTO llm_scores"
                    "(cache_key,article_id,model,prompt_version,payload) VALUES(?,?,?,?,?)",
                    (ck, aid, provider.name, PROMPT_VERSION,
                     json.dumps(ex.as_dict(), ensure_ascii=False)))
        con.commit()
        stats["scored"] += 1
        out.append(ex)

    stats["extractions"] = out
    stats["reject_rate"] = stats["rejected"] / max(1, stats["scored"] + stats["rejected"])
    return stats


def to_block_signal(extractions: list[Extraction]) -> dict[str, float]:
    """Свёртка разметки в сигналы блоков методологии.

    Слухи (reported_as='rumor') весят вчетверо меньше подтверждённых сообщений,
    а не отбрасываются: всплеск слухов сам по себе является сигналом, просто слабым.
    """
    agg: dict[str, float] = {}
    for e in extractions:
        b = e.block()
        if not b or e.insufficient_evidence:
            continue
        w = {"fact": 1.0, "claim": 0.5, "rumor": 0.25}[e.reported_as]
        agg[b] = agg.get(b, 0.0) + e.escalation_level * w
    # деэскалация — демпфер блока «дипломатия», прямо как в разделе 4 методологии
    damp = sum(e.deescalation_level for e in extractions if not e.insufficient_evidence)
    if damp:
        agg["diplomatic"] = agg.get("diplomatic", 0.0) - 0.6 * damp
    return agg
