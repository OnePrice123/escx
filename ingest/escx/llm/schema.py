"""Строгая схема ответа модели и её валидация.

Схема — не формальность, а граница ответственности. В ней НЕТ полей probability,
forecast, risk_level и recommendation, и это сделано намеренно: нельзя случайно
использовать то, чего модель не может отдать.

Валидация жёсткая: любое отклонение отбраковывается целиком, а не «чинится».
Молчаливое исправление кривого ответа — способ протащить галлюцинацию в данные.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict, field

INDICATOR_KINDS = {
    "rhetoric", "sanctions", "treaty", "mobilization", "exercise",
    "airspace", "readiness", "armed_incident", "negotiation", "other", "none",
}
REPORTED_AS = {"fact", "claim", "rumor"}

# К какому блоку методологии относится извлечённый признак.
KIND_TO_BLOCK = {
    "armed_incident": "kinetic",
    "mobilization": "military", "exercise": "military",
    "airspace": "military", "readiness": "military",
    "treaty": "diplomatic", "negotiation": "diplomatic", "rhetoric": "diplomatic",
    "sanctions": "economic",
    "other": "informational", "none": None,
}


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class Extraction:
    actor_a: str | None
    actor_b: str | None
    escalation_level: int
    deescalation_level: int
    indicator_kind: str
    actor_is_state: bool
    reported_as: str
    evidence: str
    insufficient_evidence: bool
    # служебное, заполняется пайплайном, не моделью
    article_id: str = ""
    model: str = ""
    prompt_version: str = ""

    def block(self) -> str | None:
        return KIND_TO_BLOCK.get(self.indicator_kind)

    def as_dict(self) -> dict:
        return asdict(self)


def validate(raw: dict, source_text: str, *, known_iso3: set[str] | None = None) -> Extraction:
    """Проверяет ответ модели. Бросает SchemaError при любом нарушении.

    Главная проверка — evidence должна дословно встречаться в исходном тексте.
    Это дешёвый и на удивление действенный детектор выдумок: модель, сочинившая
    факт, почти всегда сочиняет и подтверждающую цитату, и цитата не находится.
    """
    if not isinstance(raw, dict):
        raise SchemaError("ответ не является объектом")

    need = {"actor_a", "actor_b", "escalation_level", "deescalation_level",
            "indicator_kind", "actor_is_state", "reported_as",
            "evidence", "insufficient_evidence"}
    missing = need - set(raw)
    if missing:
        raise SchemaError(f"нет обязательных полей: {sorted(missing)}")
    extra = set(raw) - need
    if extra:
        raise SchemaError(f"лишние поля (модель вышла за схему): {sorted(extra)}")

    esc, de = raw["escalation_level"], raw["deescalation_level"]
    if not isinstance(esc, int) or not 0 <= esc <= 4:
        raise SchemaError(f"escalation_level вне 0..4: {esc!r}")
    if not isinstance(de, int) or not 0 <= de <= 3:
        raise SchemaError(f"deescalation_level вне 0..3: {de!r}")

    if raw["indicator_kind"] not in INDICATOR_KINDS:
        raise SchemaError(f"неизвестный indicator_kind: {raw['indicator_kind']!r}")
    if raw["reported_as"] not in REPORTED_AS:
        raise SchemaError(f"неизвестный reported_as: {raw['reported_as']!r}")
    if not isinstance(raw["actor_is_state"], bool) or not isinstance(
            raw["insufficient_evidence"], bool):
        raise SchemaError("actor_is_state и insufficient_evidence должны быть булевыми")

    for k in ("actor_a", "actor_b"):
        v = raw[k]
        if v is None:
            continue
        if not isinstance(v, str) or len(v) != 3 or not v.isupper():
            raise SchemaError(f"{k} не похоже на ISO3: {v!r}")
        if known_iso3 is not None and v not in known_iso3:
            raise SchemaError(f"{k}={v} отсутствует в таблице кодов")

    ev = raw["evidence"]
    if not isinstance(ev, str):
        raise SchemaError("evidence должна быть строкой")
    if not raw["insufficient_evidence"]:
        if len(ev.strip()) < 12:
            raise SchemaError("evidence слишком короткая для подтверждения")
        if _norm(ev) not in _norm(source_text):
            raise SchemaError("evidence не найдена в исходном тексте дословно")

    # Внутренняя непротиворечивость: заявлено применение силы, но вид признака не тот.
    if esc == 4 and raw["indicator_kind"] not in {"armed_incident", "other"}:
        raise SchemaError(
            f"escalation_level=4 несовместим с indicator_kind={raw['indicator_kind']!r}")
    if raw["insufficient_evidence"] and esc > 1:
        raise SchemaError("нельзя ставить высокую эскалацию при нехватке сведений")

    return Extraction(
        actor_a=raw["actor_a"], actor_b=raw["actor_b"],
        escalation_level=esc, deescalation_level=de,
        indicator_kind=raw["indicator_kind"],
        actor_is_state=raw["actor_is_state"], reported_as=raw["reported_as"],
        evidence=ev, insufficient_evidence=raw["insufficient_evidence"])


def _norm(s: str) -> str:
    """Нормализация для сравнения цитаты: пробелы, кавычки, тире, регистр."""
    s = " ".join(s.split()).lower()
    for a, b in (("«", '"'), ("»", '"'), ("“", '"'), ("”", '"'),
                 ("’", "'"), ("—", "-"), ("–", "-"), (" ", " ")):
        s = s.replace(a, b)
    return s
