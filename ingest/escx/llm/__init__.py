"""ИИ в контуре.

Одна фраза, определяющая всё остальное:

    МОДЕЛЬ ИЗВЛЕКАЕТ ФАКТЫ ИЗ ТЕКСТА. МОДЕЛЬ НЕ ПРОИЗВОДИТ ВЕРОЯТНОСТЬ.

Вероятность считает статистическая модель, обученная на исторических исходах и
проверяемая по Brier. Языковая модель превращает неструктурированный текст в
типизированные поля — и на этом её полномочия заканчиваются. Смешение этих двух
ролей и есть самый изощрённый способ ткнуть пальцем в небо: ответ звучит
аргументированно, но за числом нет частотной интерпретации.
"""
from .schema import Extraction, INDICATOR_KINDS, validate
from .rubric import ESCALATION_ANCHORS, build_prompt, PROMPT_VERSION
from .budget import Budget, BudgetExceeded
from .provider import (Provider, MockProvider, OpenAICompatProvider,
                       GeminiProvider, PRICES, make_provider)
from .extract import prefilter, score_articles
from .eval import cohen_kappa, weighted_kappa, field_f1, agreement_report, ADMISSION

__all__ = [
    "Extraction", "INDICATOR_KINDS", "validate",
    "ESCALATION_ANCHORS", "build_prompt", "PROMPT_VERSION",
    "Budget", "BudgetExceeded",
    "Provider", "MockProvider", "OpenAICompatProvider", "GeminiProvider",
    "PRICES", "make_provider",
    "prefilter", "score_articles",
    "cohen_kappa", "weighted_kappa", "field_f1", "agreement_report", "ADMISSION",
]
