"""Соответствие систем кодов стран.

САМАЯ ЧАСТАЯ ОШИБКА в этой задаче: источники используют РАЗНЫЕ системы кодов.
  UCDP   -> Gleditsch & Ward (GW) numbers      : 750 = Индия
  GDELT  -> CAMEO country codes (по сути FIPS) : IND = Индия
  SIPRI, Comtrade, IMF -> ISO 3166-1 alpha-3   : IND = Индия

Совпадение 'IND' у CAMEO и ISO3 для Индии — случайность. Для десятков стран
коды расходятся (Германия: GW 260/255, CAMEO GER, ISO3 DEU).

Без явной таблицы соответствий события будут молча приписываться не тем диадам,
и это НЕ вызовет ошибки — просто испортит все расчёты. Поэтому таблица ведётся
руками, версионируется и покрывается тестом на полноту.
"""
from __future__ import annotations

# iso3 -> (gw_number, cameo_code, русское название)
COUNTRY = {
    "IND": (750, "IND", "Индия"),
    "PAK": (770, "PAK", "Пакистан"),
    "CHN": (710, "CHN", "Китай"),
    "TWN": (713, "TWN", "Тайвань"),
    "RUS": (365, "RUS", "Россия"),
    "UKR": (369, "UKR", "Украина"),
    "USA": (2,   "USA", "США"),
    "IRN": (630, "IRN", "Иран"),
    "ISR": (666, "ISR", "Израиль"),
    "PRK": (731, "PRK", "КНДР"),
    "KOR": (732, "KOR", "Республика Корея"),
    "JPN": (740, "JPN", "Япония"),
    "PHL": (840, "RP",  "Филиппины"),
    "VEN": (101, "VEN", "Венесуэла"),
    "GUY": (110, "GUY", "Гайана"),
    "ARM": (371, "ARM", "Армения"),
    "AZE": (373, "AJ",  "Азербайджан"),
    "SRB": (340, "SR",  "Сербия"),
    "XKX": (347, "KV",  "Косово"),
    "GRC": (350, "GR",  "Греция"),
    "TUR": (640, "TU",  "Турция"),
    "DEU": (260, "GER", "Германия"),
    "EGY": (651, "EGY", "Египет"),
    "ETH": (530, "ETH", "Эфиопия"),
    "ERI": (531, "ERI", "Эритрея"),
    "THA": (800, "THA", "Таиланд"),
    "KHM": (811, "CB",  "Камбоджа"),
    "DZA": (615, "AG",  "Алжир"),
    "MAR": (600, "MO",  "Марокко"),
    "COD": (490, "CG",  "ДР Конго"),
    "RWA": (517, "RW",  "Руанда"),
}

GW_TO_ISO3 = {gw: iso for iso, (gw, _, _) in COUNTRY.items()}
CAMEO_TO_ISO3 = {cam: iso for iso, (_, cam, _) in COUNTRY.items()}


def from_gw(gw: int) -> str | None:
    """UCDP -> ISO3."""
    return GW_TO_ISO3.get(int(gw)) if gw is not None else None


def from_cameo(code: str | None) -> str | None:
    """GDELT -> ISO3. Пустая строка и None означают 'актор не государство'."""
    if not code:
        return None
    return CAMEO_TO_ISO3.get(code.strip().upper())


def name(iso3: str) -> str:
    rec = COUNTRY.get(iso3)
    return rec[2] if rec else iso3
