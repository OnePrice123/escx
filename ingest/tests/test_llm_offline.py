"""Тесты LLM-контура. Сеть не нужна: провайдер подменяется детерминированным.

Проверяется ПАЙПЛАЙН, а не качество модели: схема, дословность цитаты, кэш,
лимит расходов, отбраковка брака, метрики согласия. Качество модели меряется
отдельно — на размеченной вручную выборке, харнессом agreement_report.
"""
import sys, pathlib, sqlite3, json, tempfile, os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from escx.llm import (MockProvider, Budget, BudgetExceeded, validate,
                      build_prompt, PROMPT_VERSION, prefilter, score_articles,
                      cohen_kappa, weighted_kappa, agreement_report, ADMISSION)
from escx.llm.schema import SchemaError
from escx.llm.extract import to_block_signal
from escx.llm.eval import instability, field_f1

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  [ok]   {name}")
    else:    fail += 1; print(f"  [FAIL] {name} {extra}")

TEXT = ("В приграничном районе произошла перестрелка, есть погибшие. "
        "Стороны обвинили друг друга в нарушении режима тишины.")
GOOD = {"actor_a":"IND","actor_b":"PAK","escalation_level":4,"deescalation_level":0,
        "indicator_kind":"armed_incident","actor_is_state":True,"reported_as":"fact",
        "evidence":"В приграничном районе произошла перестрелка, есть погибшие",
        "insufficient_evidence":False}

print("\n1. Схема: что модели запрещено")
check("корректный ответ проходит", validate(GOOD, TEXT).escalation_level == 4)
for bad, why in [
    ({**GOOD, "escalation_level": 7}, "уровень вне шкалы"),
    ({**GOOD, "escalation_level": "высокий"}, "уровень строкой"),
    ({**GOOD, "indicator_kind": "война"}, "неизвестный вид признака"),
    ({**GOOD, "reported_as": "правда"}, "неизвестный reported_as"),
    ({**GOOD, "actor_a": "Индия"}, "актор не в ISO3"),
    ({**GOOD, "evidence": "Модель сообщила о начале боевых действий"}, "выдуманная цитата"),
    ({**GOOD, "evidence": "коротко"}, "цитата слишком короткая"),
    ({**GOOD, "escalation_level": 2, "indicator_kind":"rhetoric",
      "insufficient_evidence": True}, "высокая оценка при нехватке сведений"),
    ({**GOOD, "indicator_kind": "rhetoric"}, "уровень 4 несовместим с риторикой"),
]:
    try:
        validate(bad, TEXT); check(why + " отбраковано", False, "прошло")
    except SchemaError:
        check(why + " отбраковано", True)

no_field = {k: v for k, v in GOOD.items() if k != "evidence"}
try:
    validate(no_field, TEXT); check("отсутствие поля отбраковано", False)
except SchemaError: check("отсутствие поля отбраковано", True)

extra_field = {**GOOD, "probability_of_war": 0.4}
try:
    validate(extra_field, TEXT); check("лишнее поле отбраковано", False, "прошло")
except SchemaError as e: check("лишнее поле отбраковано", "лишние поля" in str(e))

try:
    validate(GOOD, TEXT, known_iso3={"CHN"})
    check("код вне таблицы отбраковывается", False, "прошло")
except SchemaError:
    check("код вне таблицы отбраковывается", True)

print("\n2. Цитата: нормализация кавычек и пробелов")
t2 = 'Официальный представитель заявил: «мы оставляем за собой право на ответ».'
g2 = {**GOOD, "escalation_level":1, "indicator_kind":"rhetoric",
      "evidence":'мы  оставляем за  собой право на ответ'}
check("лишние пробелы не мешают", validate(g2, t2).escalation_level == 1)
g3 = {**g2, "evidence":'"мы оставляем за собой право на ответ"'}
check("тип кавычек не мешает", validate(g3, t2).escalation_level == 1)

print("\n3. Дешёвый фильтр")
check("релевантное пропускается", prefilter({"title":"", "body":TEXT}))
check("нерелевантное отсекается",
      not prefilter({"title":"Открыт новый маршрут", "body":"Стороны обсудили культурный обмен."}))
check("одна сторона — не диадное событие",
      not prefilter({"title":"", "body":TEXT}, actors={"IND"}))

print("\n4. Промпт детерминирован")
a = {"title":"т","body":TEXT,"published_at":"2026-08-01"}
check("два вызова дают идентичный промпт", build_prompt(a) == build_prompt(a))
check("версия промпта задана", PROMPT_VERSION.startswith("esc-extract-"))
check("в системном промпте есть запрет на прогноз",
      "не оценивай вероятности" in build_prompt(a)[0].lower())

print("\n5. Лимит расходов")
con = sqlite3.connect(":memory:"); con.row_factory = sqlite3.Row
b = Budget(con, daily_usd=0.01, prices={"mock": (0.15, 0.60)})
check("пустой бюджет — ноль потрачено", b.spent_today() == 0.0)
b.record("mock", 1_000_000, 0)
check("расход учтён", abs(b.spent_today() - 0.15) < 1e-9, b.spent_today())
try:
    b.check("mock", 1000, 100); check("превышение бросает исключение", False, "не бросило")
except BudgetExceeded: check("превышение бросает исключение", True)
check("остаток не уходит в минус", b.remaining() == 0.0)

print("\n6. Прогон целиком: кэш, отбраковка, свёртка")
tmp = tempfile.mktemp(suffix=".db")
con2 = sqlite3.connect(tmp); con2.row_factory = sqlite3.Row
bud = Budget(con2, daily_usd=5.0, prices={"mock": (0.15, 0.60)})
arts = [
  {"article_id":"1","title":"Перестрелка на границе","body":TEXT},
  {"article_id":"2","title":"Учения","body":"Объявлены внеплановые учения в приграничном округе."},
  {"article_id":"3","title":"Санкции","body":"Введены ограничения на экспорт двух товарных групп."},
  {"article_id":"4","title":"Культура","body":"Открылась выставка современного искусства."},
  {"article_id":"5","title":"Переговоры","body":"Объявлены переговоры при посредничестве третьей стороны."},
]
s1 = score_articles(con2, MockProvider(), arts, budget=bud)
check("нерелевантное отсеяно до оплаты", s1["prefiltered"] == 1, s1)
check("остальное размечено", s1["scored"] == 4, s1)
check("брака нет", s1["rejected"] == 0, s1)
usd1 = s1["usd"]
s2 = score_articles(con2, MockProvider(), arts, budget=bud)
check("повторный прогон берётся из кэша", s2["cached"] == 4 and s2["scored"] == 0, s2)
check("кэш не тратит деньги", s2["usd"] == 0.0, s2["usd"])

sig = to_block_signal(s1["extractions"])
check("кинетика попала в свой блок", sig.get("kinetic", 0) > 0, sig)
check("военные приготовления в свой блок", sig.get("military", 0) > 0, sig)
check("санкции в экономический блок", sig.get("economic", 0) > 0, sig)
check("переговоры демпфируют дипломатию", sig.get("diplomatic", 0) < 0, sig)

class BrokenProvider:
    name = "broken"
    def complete(self, s, u): return ('{"escalation_level": 9}', 10, 5)
s3 = score_articles(con2, BrokenProvider(), arts[:1], budget=bud)
check("кривой ответ отбракован, а не «починен»", s3["rejected"] == 1 and s3["scored"] == 0, s3)
r = con2.execute("SELECT reason FROM llm_rejects").fetchone()
check("причина отбраковки сохранена", r is not None and len(r[0]) > 0)

class HallucinatingProvider:
    name = "halluc"
    def complete(self, s, u):
        return (json.dumps({**GOOD, "evidence":"По данным разведки, готовится вторжение"},
                           ensure_ascii=False), 10, 5)
s4 = score_articles(con2, HallucinatingProvider(), arts[:1], budget=bud)
check("выдуманная цитата ловится на проде", s4["rejected"] == 1, s4)
con2.close(); os.unlink(tmp)

print("\n7. Метрики согласия с ручной разметкой")
check("идеальное согласие = 1", abs(weighted_kappa([0,1,2,3,4],[0,1,2,3,4],k=5) - 1.0) < 1e-9)
check("систематическое расхождение < 0", weighted_kappa([0,0,0,4],[4,4,4,0],k=5) < 0)
check("ошибка на 1 ступень мягче ошибки на 4",
      weighted_kappa([0,1,2,3,4],[1,2,3,4,3],k=5) > weighted_kappa([0,1,2,3,4],[4,3,2,1,0],k=5))
check("каппа Коэна на номинальных метках",
      abs(cohen_kappa(["a","a","b","b"],["a","a","b","b"]) - 1.0) < 1e-9)
check("нестабильность считается", abs(instability([[0,1,2],[0,1,3]]) - 1/3) < 1e-9)
check("детерминированный прогон стабилен", instability([[0,1,2],[0,1,2]]) == 0.0)
f = field_f1([4,4,0,0],[4,0,0,0],4)
check("F1 по редкому классу", abs(f["f1"] - 2/3) < 1e-9, f)

print("\n8. Правило допуска индикатора в индекс")
gold = [{"escalation_level":l,"indicator_kind":k} for l,k in
        [(4,"armed_incident"),(3,"exercise"),(2,"sanctions"),(1,"rhetoric"),
         (0,"none"),(4,"armed_incident"),(1,"rhetoric"),(0,"none"),
         (3,"exercise"),(2,"sanctions")]]
good_pred = [dict(g) for g in gold]
good_pred[3] = {"escalation_level":2,"indicator_kind":"rhetoric"}   # одна ошибка на ступень
rep = agreement_report(gold, good_pred, repeat_runs=[[0]*10,[0]*10], reject_rate=0.01)
check("хорошая модель допускается", rep["admitted"], rep["verdict"])
check("отчёт содержит взвешенную каппу", rep["weighted_kappa_escalation"] > 0.9)

bad_pred = [{"escalation_level":0,"indicator_kind":"none"} for _ in gold]
rep2 = agreement_report(gold, bad_pred, reject_rate=0.0)
check("модель «всегда ноль» НЕ допускается", not rep2["admitted"], rep2["verdict"])
check("точность обманчива, каппа — нет",
      rep2["exact_match"] > 0.15 and rep2["weighted_kappa_escalation"] < 0.3,
      (rep2["exact_match"], rep2["weighted_kappa_escalation"]))

rep3 = agreement_report(gold, good_pred, repeat_runs=[[0,1],[1,0]], reject_rate=0.01)
check("нестабильность блокирует допуск", not rep3["admitted"], rep3["verdict"])
rep4 = agreement_report(gold, good_pred, repeat_runs=[[0]*10,[0]*10], reject_rate=0.30)
check("высокая доля брака блокирует допуск", not rep4["admitted"], rep4["verdict"])

print("\n9. Границы полномочий модели")
check("в схеме нет поля вероятности",
      "probability" not in str(GOOD.keys()) and "forecast" not in str(GOOD.keys()))
from escx.llm import schema as S
check("в наборе видов признаков нет прогнозных",
      not any("forecast" in k or "prob" in k for k in S.INDICATOR_KINDS))
check("порог допуска задан явно", ADMISSION["weighted_kappa_min"] >= 0.6)

print("\n10. Провайдер Gemini (сеть подменена)")
from escx.llm import GeminiProvider, PRICES, make_provider
from escx.llm import provider as P

sent = {}
class _Resp:
    def __init__(self, body): self.body = json.dumps(body).encode()
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *a): return False

def fake_urlopen(reply):
    def _f(req, timeout=None, context=None):
        sent["url"] = req.full_url
        sent["headers"] = {k.lower(): v for k, v in req.headers.items()}
        sent["body"] = json.loads(req.data)
        return _Resp(reply)
    return _f

REPLY = {"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}],
         "usageMetadata": {"promptTokenCount": 1200, "candidatesTokenCount": 90,
                           "thoughtsTokenCount": 40}}

real_urlopen = P.urllib.request.urlopen
P.urllib.request.urlopen = fake_urlopen(REPLY)
try:
    g = GeminiProvider("gemini-2.5-flash", api_key="k-test")
    text, ti, to = g.complete("СИСТЕМА", "ТЕКСТ СООБЩЕНИЯ: " + TEXT)

    check("ключ уходит заголовком, а не в адресе",
          sent["headers"].get("x-goog-api-key") == "k-test" and "k-test" not in sent["url"])
    check("температура 0 — иначе кэш и воспроизводимость мертвы",
          sent["body"]["generationConfig"]["temperature"] == 0.0)
    check("ответ затребован строго как JSON",
          sent["body"]["generationConfig"]["responseMimeType"] == "application/json")
    check("размышления выключены по умолчанию",
          sent["body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0)
    check("системная инструкция вынесена из contents",
          sent["body"]["systemInstruction"]["parts"][0]["text"] == "СИСТЕМА"
          and "СИСТЕМА" not in json.dumps(sent["body"]["contents"], ensure_ascii=False))
    check("ответ разбирается в валидную разметку", validate(json.loads(text), TEXT).escalation_level == 4)
    check("размышления учтены в расходе (90+40, а не 90)", (ti, to) == (1200, 130), (ti, to))

    # Фильтр безопасности: сообщения про обстрелы и погибших блокируются регулярно.
    P.urllib.request.urlopen = fake_urlopen({"promptFeedback": {"blockReason": "SAFETY"}})
    try:
        GeminiProvider("gemini-2.5-flash", api_key="k").complete("s", "u")
        check("пустой ответ не выдаётся за «событий нет»", False)
    except RuntimeError as e:
        check("пустой ответ не выдаётся за «событий нет»", "SAFETY" in str(e))
finally:
    P.urllib.request.urlopen = real_urlopen

os.environ.pop("GEMINI_API_KEY", None)
try:
    GeminiProvider("gemini-2.5-flash").complete("s", "u")
    check("без ключа падаем до сети, а не в сети", False)
except RuntimeError as e:
    check("без ключа падаем до сети, а не в сети", "GEMINI_API_KEY" in str(e))

os.environ.pop("ESCX_LLM_PROVIDER", None)
check("по умолчанию провайдер mock, а не платный", make_provider().name == "mock")
check("gemini выбирается явно", make_provider("gemini").name == "gemini-2.5-flash")
try:
    make_provider("qwen")
    check("неизвестный провайдер — ошибка, а не тихий mock", False)
except ValueError:
    check("неизвестный провайдер — ошибка, а не тихий mock", True)

bud = Budget(sqlite3.connect(":memory:"), daily_usd=3.0, prices=PRICES)
check("цена gemini известна бюджету", bud.cost("gemini-2.5-flash", 1_000_000, 0) > 0)
check("бюджет режет прогон до запроса, а не после",
      bud.cost("gemini-2.5-flash", 20_000_000, 1_000_000) > 3.0)

print(f"\n{'='*46}\nпройдено {ok}, провалено {fail}\n{'='*46}")
sys.exit(1 if fail else 0)
