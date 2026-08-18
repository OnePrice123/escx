"""Источники, которые тянутся одним файлом: GPR, санкционные списки, голосования ООН.

Общее у них то, что они НЕ потоковые. Их не нужно опрашивать каждые 15 минут —
достаточно раз в сутки или раз в месяц. Это важно для расходов и для расписания:
половина пайплайна может ходить в источники редко.
"""
from __future__ import annotations
import csv, io, json, re
from ..http import get

# --------------------------------------------------------------------------
# GPR — Geopolitical Risk Index (Caldara & Iacoviello, Federal Reserve Board)
# Лицензия CC BY: использовать можно, атрибуция обязательна.
# Месячный ряд с 1900 и дневной с 1985, плюс индексы по 44 странам.
# Ценность для нас: готовый внешний ориентир для блока 5 и калибровки собственного
# медиа-индикатора. Если наш инфоблок расходится с GPR в разы — ошибка у нас.
# --------------------------------------------------------------------------
GPR_PAGE = "https://www.matteoiacoviello.com/gpr.htm"
GPR_DAILY_XLSX = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
GPR_MONTHLY_XLSX = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"

# --------------------------------------------------------------------------
# Санкции. Публичные реестры, обновляются по мере введения мер.
# Нужны не сами списки лиц, а ФАКТ и ДАТА введения мер между сторонами диады —
# то есть событие, а не справочник. Поэтому мы считаем дельту списка ко вчерашнему.
# --------------------------------------------------------------------------
OFAC_SDN_CSV = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_SDN_XML = "https://www.treasury.gov/ofac/downloads/sdn.xml"
OFAC_CONS_CSV = "https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv"
UK_OFSI_CSV = "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.csv"


def sanctions_delta(prev_ids: set[str], curr_ids: set[str]) -> dict:
    """Дельта санкционного списка = событие блока 4.

    Смысл: сам по себе список из тысяч записей — не индикатор. Индикатор — это
    сколько записей ДОБАВИЛОСЬ и СНЯЛОСЬ за период, потому что именно добавление
    меры является событием эскалации, а снятие — деэскалации.
    """
    return {
        "added": sorted(curr_ids - prev_ids),
        "removed": sorted(prev_ids - curr_ids),
        "n_added": len(curr_ids - prev_ids),
        "n_removed": len(prev_ids - curr_ids),
    }


def parse_ofac_sdn_csv(blob: bytes) -> set[str]:
    """У sdn.csv нет заголовка; первое поле — ent_num."""
    return {r["ent_num"] for r in parse_ofac_sdn_rows(blob)}


# Колонки sdn.csv, порядок задан спецификацией OFAC. Заголовка в файле нет.
SDN_COLS = ["ent_num", "sdn_name", "sdn_type", "program", "title",
            "call_sign", "vess_type", "tonnage", "grt", "vess_flag",
            "vess_owner", "remarks"]


def parse_ofac_sdn_rows(blob: bytes) -> list[dict]:
    """Записи SDN с программами.

    Страны в файле нет вовсе — есть ПРОГРАММА, и это единственная зацепка для
    привязки записи к конфликту. Поле выглядит как «IRAN] [IFSR» и содержит
    несколько программ сразу, поэтому разбирается, а не сравнивается целиком.

    Кодировка latin-1, а не utf-8: файл ведётся в ней десятилетиями, и utf-8
    падает на первом же имени с диакритикой.
    """
    out = []
    for row in csv.reader(io.StringIO(blob.decode("latin-1", "replace"))):
        if not row or not row[0].strip().isdigit():
            continue
        r = dict(zip(SDN_COLS, [c.strip() for c in row]))
        progs = [p.strip() for p in r.get("program", "").replace("[", "").split("]")]
        out.append({"ent_num": r["ent_num"],
                    "name": r.get("sdn_name", ""),
                    "sdn_type": r.get("sdn_type", ""),
                    "programs": [p for p in progs if p and p != "-0-"]})
    return out


# --------------------------------------------------------------------------
# Голосования Генассамблеи ООН.
# Индикатор блока 3: расхождение в голосованиях — медленный, но чистый сигнал
# дипломатического отдаления. Готовый машиночитаемый набор ведёт Эрик Вутен
# (Harvard Dataverse, ежегодное обновление); первичный источник — UN Digital Library.
# --------------------------------------------------------------------------
UN_VOTES_DATAVERSE = "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/LEJUQZ"
UN_DIGITAL_LIBRARY = "https://digitallibrary.un.org/collection/Voting%20Data"


def vote_agreement(votes_a: dict[str, int], votes_b: dict[str, int]) -> float | None:
    """Доля совпавших позиций по общим резолюциям. 1.0 = полное совпадение.

    Коды: 1 = за, 2 = воздержался, 3 = против. Отсутствие в голосовании не считается.
    """
    common = set(votes_a) & set(votes_b)
    if not common:
        return None
    same = sum(1 for k in common if votes_a[k] == votes_b[k])
    return same / len(common)


# --------------------------------------------------------------------------
# SIPRI — военные расходы и поставки вооружений. Годовой такт, файлы XLSX.
# Медленный сигнал: в 30-дневном окне бесполезен, в 5-летнем — базовая линия
# и один из компонентов веса последствий диады в глобальном индексе.
# --------------------------------------------------------------------------
SIPRI_MILEX = "https://www.sipri.org/databases/milex"
SIPRI_ARMS_TRANSFERS = "https://www.sipri.org/databases/armstransfers"

# --------------------------------------------------------------------------
# NOTAM / NAVTEX — закрытие воздушного пространства и морских районов.
# Блок 2, один из самых ранних наблюдаемых признаков военных приготовлений:
# закрытие района публикуется ДО учений, а не после.
# Единого мирового бесплатного API нет; собирается по национальным AIS/AIP,
# у США — FAA NOTAM API (требует бесплатной регистрации).
# --------------------------------------------------------------------------
FAA_NOTAM_API = "https://external-api.faa.gov/notamapi/v1/notams"  # нужен api key
EUROCONTROL_EAD = "https://www.ead.eurocontrol.int/"               # регистрация
