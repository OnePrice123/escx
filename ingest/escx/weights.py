"""Вес последствий диады c_d — знаменатель и числитель глобального индекса.

Формула из раздела 5A методологии:

    c_d = ( 0.25·pop + 0.30·gdp + 0.35·mil )^0.62 · N · A

Показатель 0.62 — сжатие. Без него три крупнейшие диады дают почти весь индекс,
и «глобальный» он только по названию.

Здесь же живут два списка, которые не берутся ни из какого API и потому заведены
руками: ядерные государства и договоры о взаимной обороне. Оба публичны, оба
меняются раз в десятилетие, и оба обязаны быть видимы в коде, а не спрятаны
в магических числах.
"""
from __future__ import annotations

# Государства, обладающие ядерным оружием: пятёрка ДНЯО плюс четыре де-факто.
# Список публичный и стабильный. Израиль включён по признанному де-факто
# статусу, хотя официально его не подтверждает, — методология опирается на
# фактическое обладание, а не на декларацию.
NUCLEAR = {"USA", "RUS", "CHN", "GBR", "FRA", "IND", "PAK", "PRK", "ISR"}

# Множитель по числу ядерных сторон в диаде: 0, 1, 2.
NUCLEAR_MULT = {0: 1.0, 1: 2.2, 2: 3.6}

# Число государств, связанных с данным договором о взаимной обороне.
# A_d = 1 + (число таких государств) / 45 — см. таблицу в разделе 5A.
DEFENCE_PACTS = {
    "nato": {"members": 32, "states": {
        "USA", "GBR", "FRA", "DEU", "ITA", "ESP", "POL", "TUR", "CAN", "NLD",
        "BEL", "PRT", "DNK", "NOR", "ISL", "LUX", "GRC", "CZE", "HUN", "SVK",
        "SVN", "HRV", "ALB", "BGR", "ROU", "EST", "LVA", "LTU", "MNE", "MKD",
        "FIN", "SWE"}},
    # Двусторонние договоры США в Азии — каждый связывает ровно два государства.
    "us_asia": {"members": 2, "states": {"JPN", "KOR", "PHL", "AUS", "THA"}},
    "csto": {"members": 6, "states": {"RUS", "BLR", "KAZ", "KGZ", "TJK", "ARM"}},
}


def nuclear_mult(side_a: str, side_b: str) -> float:
    n = (side_a in NUCLEAR) + (side_b in NUCLEAR)
    return NUCLEAR_MULT[n]


def alliance_density(side_a: str, side_b: str) -> float:
    """A_d = 1 + (число связанных договором государств) / 45.

    Считается по обеим сторонам: втягивание союзников — свойство диады, а не
    одного её участника. Государство, состоящее в двух пактах, учитывается
    по каждому: это и есть та связность, которую показатель измеряет.
    """
    linked = 0
    for pact in DEFENCE_PACTS.values():
        for side in (side_a, side_b):
            if side in pact["states"]:
                linked += pact["members"]
    return 1.0 + linked / 45.0


def consequence(side_a: str, side_b: str, shares: dict[str, dict[str, float]]) -> float | None:
    """Вес последствий. None, если долей нет — вес нельзя выдумывать.

    shares — {'pop': {ISO3: доля%}, 'gdp': {...}, 'mil': {...}}.
    Отсутствие данных по стороне возвращает None, и диада не участвует в
    глобальном индексе, а не входит в него с нулевым весом: нулевой вес — это
    утверждение «последствия нулевые», а мы всего лишь не знаем величины.
    """
    parts = {}
    for key, w in (("pop", 0.25), ("gdp", 0.30), ("mil", 0.35)):
        s = shares.get(key) or {}
        if side_a not in s or side_b not in s:
            return None
        parts[key] = w * (s[side_a] + s[side_b])
    base = sum(parts.values())
    if base <= 0:
        return None
    return (base ** 0.62) * nuclear_mult(side_a, side_b) * alliance_density(side_a, side_b)
