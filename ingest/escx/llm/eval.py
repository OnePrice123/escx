"""Проверка качества разметки: согласие модели с человеком.

Без этого блока весь LLM-контур — вера. С ним — измеряемый компонент, у которого
есть порог допуска в индекс.

Ключевая метрика — каппа Коэна, а не «точность». Точность обманчива при
несбалансированных классах: если 90 % сообщений имеют эскалацию 0, модель,
всегда отвечающая 0, покажет 90 % точности и нулевую пользу. Каппа вычитает
согласие, достижимое случайно.

Для порядковой шкалы 0–4 используется каппа с квадратичными весами: ошибка
«поставил 4 вместо 0» должна штрафоваться сильнее, чем «3 вместо 4».
"""
from __future__ import annotations
from collections import Counter

# Порог допуска индикатора в индекс. Значения по шкале Лэндиса–Коха:
# 0.61–0.80 — «существенное согласие», ниже — недостаточно для автоматики.
ADMISSION = {
    "weighted_kappa_min": 0.65,   # согласие по уровню эскалации
    "kind_kappa_min": 0.60,       # согласие по виду признака
    "reject_rate_max": 0.05,      # доля ответов, не прошедших схему
    "instability_max": 0.10,      # доля расхождений при повторном прогоне
}


def cohen_kappa(a: list, b: list) -> float:
    """Каппа Коэна для номинальных меток."""
    if len(a) != len(b) or not a:
        raise ValueError("нужны непустые списки равной длины")
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def weighted_kappa(a: list[int], b: list[int], *, k: int = 5, power: int = 2) -> float:
    """Каппа с весами для порядковой шкали 0..k-1. power=2 — квадратичные веса."""
    if len(a) != len(b) or not a:
        raise ValueError("нужны непустые списки равной длины")
    n = len(a)
    w = [[abs(i - j) ** power / (k - 1) ** power for j in range(k)] for i in range(k)]
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[x][y] += 1
    ca, cb = Counter(a), Counter(b)
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * ca[i] * cb[j] / n for i in range(k) for j in range(k))
    return 1.0 if den == 0 else 1 - num / den


def field_f1(gold: list, pred: list, label) -> dict:
    """Точность, полнота и F1 по одной метке."""
    tp = sum(1 for g, p in zip(gold, pred) if g == label and p == label)
    fp = sum(1 for g, p in zip(gold, pred) if g != label and p == label)
    fn = sum(1 for g, p in zip(gold, pred) if g == label and p != label)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"label": label, "precision": prec, "recall": rec, "f1": f1,
            "support": tp + fn}


def instability(runs: list[list[int]]) -> float:
    """Доля позиций, где повторные прогоны разошлись.

    Прогоняем одну и ту же выборку дважды. При температуре 0 расхождение должно
    быть нулевым; ненулевое означает либо недетерминизм поставщика, либо
    чувствительность к порядку — и то и другое делает кэш и воспроизводимость
    фикцией. Это отдельная проверка, потому что она ловит проблему, которую
    каппа не видит.
    """
    if len(runs) < 2:
        return 0.0
    n = len(runs[0])
    diff = sum(1 for i in range(n) if len({r[i] for r in runs}) > 1)
    return diff / n if n else 0.0


# Одно и то же поле называется по-разному по разные стороны сравнения:
# verify-coding пишет вердикт модели как llm_escalation/llm_kind (рядом лежат
# gdelt_kind и cameo_root, и без приставки непонятно, чьё это мнение), а схема
# разметки называет их escalation_level/indicator_kind. Пока это не сводилось
# здесь, задокументированная связка verify-coding -> llm-eval падала на
# KeyError: команды никогда не стыковались, потому что вместе их не гоняли.
_ALIASES = {
    "escalation_level": ("escalation_level", "llm_escalation"),
    "indicator_kind": ("indicator_kind", "llm_kind"),
}


def _field(row: dict, name: str):
    for key in _ALIASES[name]:
        if key in row:
            return row[key]
    raise KeyError(
        f"в записи нет поля {name} (искали: {', '.join(_ALIASES[name])}); "
        f"есть: {', '.join(sorted(row))}")


def agreement_report(gold: list[dict], pred: list[dict],
                     repeat_runs: list[list[int]] | None = None,
                     reject_rate: float = 0.0) -> dict:
    """Полный отчёт согласия. Решение о допуске принимается автоматически."""
    # Сравнение идёт по позициям, поэтому расхождение длин — не мелочь:
    # zip молча обрежет список по короткому, и каппа посчитается по части
    # выборки, ничем этого не показав.
    if len(gold) != len(pred):
        raise ValueError(
            f"разметки разной длины: ручная {len(gold)}, модель {len(pred)}. "
            f"Записи нельзя ни удалять, ни переставлять — непрочитанные статьи "
            f"остаются на месте.")

    ge = [_field(g, "escalation_level") for g in gold]
    pe = [_field(p, "escalation_level") for p in pred]
    gk = [_field(g, "indicator_kind") for g in gold]
    pk = [_field(p, "indicator_kind") for p in pred]

    rep = {
        "n": len(gold),
        "exact_match": sum(1 for x, y in zip(ge, pe) if x == y) / len(ge),
        "within_one": sum(1 for x, y in zip(ge, pe) if abs(x - y) <= 1) / len(ge),
        "weighted_kappa_escalation": weighted_kappa(ge, pe, k=5),
        "kappa_kind": cohen_kappa(gk, pk),
        "reject_rate": reject_rate,
        "instability": instability(repeat_runs or []),
        "per_level": [field_f1(ge, pe, lvl) for lvl in range(5)],
    }

    checks = {
        "weighted_kappa": rep["weighted_kappa_escalation"] >= ADMISSION["weighted_kappa_min"],
        "kind_kappa": rep["kappa_kind"] >= ADMISSION["kind_kappa_min"],
        "reject_rate": rep["reject_rate"] <= ADMISSION["reject_rate_max"],
        "instability": rep["instability"] <= ADMISSION["instability_max"],
    }
    rep["checks"] = checks
    rep["admitted"] = all(checks.values())
    rep["verdict"] = ("индикатор допускается в индекс" if rep["admitted"] else
                      "индикатор НЕ допускается: " +
                      ", ".join(k for k, v in checks.items() if not v))
    return rep
