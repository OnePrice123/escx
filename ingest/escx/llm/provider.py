"""Провайдеры модели. Абстракция нужна ровно для двух вещей:
сменить поставщика без переписывания пайплайна и тестировать всё офлайн.
"""
from __future__ import annotations
import json, os, urllib.request, ssl, hashlib
from typing import Protocol


class Provider(Protocol):
    name: str
    def complete(self, system: str, user: str) -> tuple[str, int, int]: ...


def approx_tokens(s: str) -> int:
    """Грубая оценка: ~3.4 символа на токен для кириллицы, ~4 для латиницы.
    Нужна только для проверки лимита ДО запроса, поэтому намеренно завышена."""
    return int(len(s) / 3.2) + 16


class MockProvider:
    """Детерминированный провайдер для тестов и локальной отладки.

    Не имитирует «интеллект» — он реализует простое правило по ключевым словам.
    Это осознанно: тесты должны проверять ПАЙПЛАЙН (схему, кэш, лимит, валидацию),
    а не качество модели. Качество модели проверяется отдельно, на размеченной
    выборке, харнессом из eval.py.
    """
    name = "mock"

    RULES = [
        (("перестрел", "обстрел", "погиб", "удар", "столкновени"), 4, "armed_incident"),
        (("учени", "переброск", "мобилизац", "боеготовн", "воздушн"), 3, "exercise"),
        (("санкц", "экспортн", "запрет", "ограничени"), 2, "sanctions"),
        (("протест", "осуди", "заяви", "посл"), 1, "rhetoric"),
    ]
    DEESC = ("переговор", "перемири", "соглашени", "диалог", "посредник")

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        # ВАЖНО: смотрим только на текст сообщения, а не на весь промпт.
        # В промпте есть примеры к ступеням рубрики («перестрелка», «погибшие»),
        # и наивный поиск по всей строке помечал бы КАЖДОЕ сообщение как
        # применение силы. Ошибка неочевидная и попалась на тестах — она же
        # возможна в любом постпроцессинге, который читает промпт целиком.
        article = user.split("ТЕКСТ СООБЩЕНИЯ:", 1)[-1]
        low = article.lower()
        esc, kind = 0, "none"
        for keys, lvl, k in self.RULES:
            if any(x in low for x in keys):
                esc, kind = lvl, k
                break
        de = 2 if any(x in low for x in self.DEESC) else 0
        body = article.split("Текст: ", 1)[-1]
        sentence = next((s.strip() for s in body.replace("\n", " ").split(".")
                         if len(s.strip()) >= 12), "")
        insufficient = esc == 0 and not sentence
        out = {
            "actor_a": "IND" if "инди" in low else None,
            "actor_b": "PAK" if "пакистан" in low else None,
            "escalation_level": esc, "deescalation_level": de,
            "indicator_kind": kind, "actor_is_state": True,
            "reported_as": "rumor" if "сообщают источники" in low else "fact",
            "evidence": sentence if not insufficient else "",
            "insufficient_evidence": insufficient,
        }
        s = json.dumps(out, ensure_ascii=False)
        return s, approx_tokens(system + user), approx_tokens(s)


class OpenAICompatProvider:
    """Любой эндпоинт, совместимый с /v1/chat/completions.

    Подходит и для облачных поставщиков, и для локальной модели (llama.cpp, vLLM,
    Ollama) — что для этого проекта важно: объём скоринга большой, а задача
    (извлечение по жёсткой схеме) не требует топовой модели. Локальный запуск
    убирает основную статью расходов целиком.
    """
    def __init__(self, model: str, base_url: str | None = None,
                 api_key: str | None = None, temperature: float = 0.0):
        self.name = model
        self.model = model
        self.base = (base_url or os.environ.get("ESCX_LLM_BASE",
                                                "http://localhost:8080/v1")).rstrip("/")
        self.key = api_key or os.environ.get("ESCX_LLM_KEY", "")
        self.temperature = temperature   # 0 обязателен: иначе кэш и воспроизводимость мертвы

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        payload = json.dumps({
            "model": self.model,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=payload,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.key}"})
        with urllib.request.urlopen(req, timeout=120,
                                    context=ssl.create_default_context()) as r:
            data = json.loads(r.read())
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        return (text,
                usage.get("prompt_tokens", approx_tokens(system + user)),
                usage.get("completion_tokens", approx_tokens(text)))


class GeminiProvider:
    """Google Gemini через generateContent.

    Отдельный класс, а не настройка OpenAICompatProvider: у Gemini другая форма
    запроса (системная инструкция вынесена из messages), другое место ответа и
    другие имена полей расхода. Совместимый с OpenAI слой у Google есть, но он
    не отдаёт thoughtsTokenCount — а без него оплаченные размышления не попадают
    в бюджет, и дневной лимит начинает врать в меньшую сторону.

    Ключ уходит заголовком, а не параметром адреса: query string оседает в логах
    прокси и в истории браузера, заголовок — нет.
    """
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, model: str = "gemini-flash-lite-latest", api_key: str | None = None,
                 temperature: float = 0.0, thinking_budget: int | None = None,
                 base_url: str | None = None):
        self.name = model
        self.model = model
        self.base = (base_url or os.environ.get("ESCX_GEMINI_BASE", self.BASE)).rstrip("/")
        self.key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.temperature = temperature   # 0 обязателен: иначе кэш и воспроизводимость мертвы
        # thinkingConfig по умолчанию НЕ отправляется. Проверено на живом API:
        # lite-модели (gemini-3.5-flash-lite, gemini-flash-lite-latest) отвечают
        # на этот параметр 400 INVALID_ARGUMENT, хотя размышлений и так не тратят.
        # А gemini-flash-latest параметр принимает, но соблюдает лишь частично:
        # на реальном промпте всё равно уходит под две сотни токенов размышлений.
        # Отсюда правило: для извлечения по схеме берём lite-модель и молчим про
        # thinking, а не пытаемся его выключить.
        self.thinking_budget = thinking_budget

    def complete(self, system: str, user: str) -> tuple[str, int, int]:
        if not self.key:
            raise RuntimeError(
                "GEMINI_API_KEY не задан. Локально: export GEMINI_API_KEY=...; "
                "в GitHub Actions: Settings → Secrets and variables → Actions.")

        cfg: dict = {"temperature": self.temperature,
                     "responseMimeType": "application/json"}
        if self.thinking_budget is not None:
            cfg["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}

        payload = json.dumps({
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": cfg,
        }).encode()

        req = urllib.request.Request(
            f"{self.base}/models/{self.model}:generateContent", data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        with urllib.request.urlopen(req, timeout=120,
                                    context=ssl.create_default_context()) as r:
            data = json.loads(r.read())

        cands = data.get("candidates") or []
        if not cands:
            # Сработал фильтр безопасности. Сообщения про обстрелы и погибших
            # попадают под него регулярно, и молчаливый пустой ответ превратился
            # бы в «событий нет». Пусть лучше статья уйдёт в брак с причиной.
            fb = (data.get("promptFeedback") or {}).get("blockReason", "нет кандидатов")
            raise RuntimeError(f"Gemini не вернул ответ: {fb}")

        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)

        u = data.get("usageMetadata") or {}
        tok_in = u.get("promptTokenCount", approx_tokens(system + user))
        # Размышления оплачиваются по цене выходных токенов, но лежат в отдельном
        # поле. Без них бюджет считал бы расход заниженным.
        tok_out = (u.get("candidatesTokenCount", approx_tokens(text))
                   + u.get("thoughtsTokenCount", 0))
        return text, tok_in, tok_out


# Цены за 1M токенов (вход, выход) для Budget.
#
# ВНИМАНИЕ: значения ниже — оценка СВЕРХУ, а не выписка из прайс-листа. Занижать
# здесь нельзя ни при каких обстоятельствах: лимит считается по этим числам, и
# заниженная цена означает перерасход втрое молча. Завышенная — лишь то, что
# прогон остановится раньше, чем мог бы. Из двух ошибок допустима вторая.
#
# Сверьте с ai.google.dev/pricing и поправьте — тарифы меняются, а модели
# снимаются: gemini-2.5-* на этом ключе уже отвечают 404 «no longer available
# to new users», Google отсылает к gemini-3.6-flash и gemini-3.5-flash-lite.
PRICES: dict[str, tuple[float, float]] = {
    # lite-класс: то, что нужно для извлечения по жёсткой схеме
    "gemini-3.5-flash-lite":    (0.10, 0.40),
    "gemini-3.1-flash-lite":    (0.10, 0.40),
    "gemini-flash-lite-latest": (0.10, 0.40),
    # flash-класс
    "gemini-3.5-flash":         (0.30, 2.50),
    "gemini-3.6-flash":         (0.30, 2.50),
    "gemini-3.7-flash":         (0.30, 2.50),
    "gemini-flash-latest":      (0.30, 2.50),
    # pro-класс: для скоринга не нужен, оставлен ради полноты
    "gemini-pro-latest":        (1.25, 10.00),
    "mock":                     (0.00, 0.00),
}


def make_provider(name: str | None = None) -> Provider:
    """Провайдер по переменным окружения.

    По умолчанию mock: прогон без ключа обязан проходить и не ходить в сеть.
    Тихо подставленный платный провайдер — худший из возможных дефолтов.
    """
    kind = (name or os.environ.get("ESCX_LLM_PROVIDER", "mock")).strip().lower()
    if kind == "mock":
        return MockProvider()
    if kind == "gemini":
        # По умолчанию lite: скоринг идёт по жёсткой схеме и большого разума
        # не требует, зато объём большой и цена важнее. gemini-2.5-flash,
        # стоявший здесь раньше, снят Google и отвечает 404.
        return GeminiProvider(os.environ.get("ESCX_LLM_MODEL", "gemini-flash-lite-latest"))
    if kind in ("openai", "openai-compat", "local"):
        return OpenAICompatProvider(os.environ.get("ESCX_LLM_MODEL", "local"))
    raise ValueError(f"неизвестный провайдер: {kind!r} (mock | gemini | openai)")
