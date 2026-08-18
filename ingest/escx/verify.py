"""Проверка кодировки GDELT языковой моделью.

Зачем. GDELT кодирует события автоматически, и на нашей выборке это видно
невооружённым глазом: статья про совместные учения США и Кореи закодирована
как 194 «бой», хотя учения — это 15, «демонстрация силы». У пары
Египет — Эфиопия пять событий из шести получили код 190 при споре о плотине.
Ошибки кодировки идут прямо в индикатор насилия и фазу.

Что это НЕ делает. Не правит данные и не пишет ничего в индекс. Это измеритель:
он собирает пары «код GDELT — вердикт модели» и складывает в файл, который
скармливается llm-eval. Пускать модель в индекс можно только после того, как
её согласие с ручной разметкой пройдёт порог (правило 7 в README ingest).

Про вежливость к источникам. Читаем robots.txt и подчиняемся ему, ходим по
одному запросу с паузой, представляемся в User-Agent и берём только текст,
из которого сохраняем одну цитату. Массового обхода здесь нет и не будет:
задача — проверить выборку, а не построить копию интернета.
"""
from __future__ import annotations
import html as _html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

# Только ASCII: заголовки HTTP кодируются latin-1, и кириллица в User-Agent
# роняет запрос ещё до отправки — на UnicodeEncodeError, а не на сети.
UA = "escx-verify/0.1 (+https://brink.watch; coding verification bot)"
_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def allowed(url: str, timeout: int = 10) -> bool:
    """Разрешает ли robots.txt читать этот адрес нашим агентом.

    Недоступный robots.txt трактуется как запрет, а не как разрешение: сайт,
    который не отвечает, мы не читаем. Осторожная сторона здесь дешевле.
    """
    try:
        p = urllib.parse.urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
    except ValueError:
        return False
    if root not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(root + "/robots.txt")
        try:
            rp.read()
            _robots[root] = rp
        except Exception:
            _robots[root] = None
    rp = _robots[root]
    if rp is None:
        return False
    try:
        return rp.can_fetch(UA, url)
    except Exception:
        return False


_TAGS = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_ALL = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def html_to_text(blob: bytes, limit: int = 4000) -> str:
    """Грубое извлечение текста. Без зависимостей — их в проекте нет.

    Точности библиотеки вроде readability здесь не требуется: модели нужен
    связный кусок про событие, а не идеально очищенная статья. Скрипты и стили
    вырезаются обязательно — иначе в промпт уезжает JSON аналитики на сотню
    килобайт и платится за него как за токены.
    """
    try:
        raw = blob.decode("utf-8", "replace")
    except Exception:
        return ""
    raw = _TAGS.sub(" ", raw)
    raw = _ALL.sub(" ", raw)
    return _WS.sub(" ", _html.unescape(raw)).strip()[:limit]


def fetch_article(url: str, timeout: int = 15, pause: float = 1.0) -> str | None:
    """Текст статьи или None. Пауза между запросами — не опция, а условие."""
    if not allowed(url):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return None
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "text" not in ctype:
                return None
            blob = r.read(600_000)      # обрезаем: страницы бывают гигантские
    except (urllib.error.URLError, OSError, ValueError):
        return None
    finally:
        time.sleep(pause)
    return html_to_text(blob) or None


# Корень CAMEO -> вид признака в нашей схеме. Нужно, чтобы сравнивать вердикт
# модели с кодировкой GDELT на одном языке.
CAMEO_TO_KIND = {
    "18": "armed_incident", "19": "armed_incident", "20": "armed_incident",
    "15": "exercise", "16": "sanctions", "17": "coercion",
    "13": "rhetoric", "12": "rhetoric", "11": "rhetoric", "10": "rhetoric",
    "05": "treaty", "06": "treaty", "04": "negotiation", "03": "negotiation",
    "02": "rhetoric", "01": "rhetoric",
}


def agrees(cameo_root: str, kind: str | None) -> bool | None:
    """Сходятся ли кодировка GDELT и вердикт модели. None — сравнивать не с чем."""
    want = CAMEO_TO_KIND.get(cameo_root)
    if not want or not kind:
        return None
    return want == kind
