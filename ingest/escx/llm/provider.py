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

    def __init__(self, model: str = "gemini-2.5-flash", api_key: str | None = None,
                 temperature: float = 0.0, thinking_budget: int | None = 0,
                 base_url: str | None = None):
        self.name = model
        self.model = model
        self.base = (base_url or os.environ.get("ESCX_GEMINI_BASE", self.BASE)).rstrip("/")
        self.key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.temperature = temperature   # 0 обязателен: иначе кэш и воспроизводимость мертвы
        # Извлечение по жёсткой схеме — не та задача, где размышления окупаются.
        # Оплачиваются они как выходные токены, поэтому по умолчанию выключены.
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


# Цены за 1M токенов (вход, выход) для Budget. Сверяйтесь с ai.google.dev/pricing —
# тарифы меняются, а молча разъехавшийся прайс превращает дневной лимит в фикцию.
PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash":      (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro":        (1.25, 10.00),
    "mock":                  (0.00, 0.00),
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
        return GeminiProvider(os.environ.get("ESCX_LLM_MODEL", "gemini-2.5-flash"))
    if kind in ("openai", "openai-compat", "local"):
        return OpenAICompatProvider(os.environ.get("ESCX_LLM_MODEL", "local"))
    raise ValueError(f"неизвестный провайдер: {kind!r} (mock | gemini | openai)")
