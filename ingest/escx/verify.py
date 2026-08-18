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

# Обвязка страницы: меню, шапка, подвал, боковые колонки, формы.
# Вырезается до извлечения текста — почему, см. html_to_text.
_CHROME = re.compile(r"<(nav|header|footer|aside|form|svg|figure|button|select)"
                     r"[^>]*>.*?</\1>", re.S | re.I)
# Основной блок статьи, если разметка его обозначила.
_MAIN = re.compile(r"<(article|main)[^>]*>(.*?)</\1>", re.S | re.I)
# Абзацы и заголовки: то, из чего состоит текст и не состоит меню.
_PARA = re.compile(r"<(p|h1|h2|h3)[^>]*>(.*?)</\1>", re.S | re.I)

# Страницы-заглушки вместо статьи. Отдаются с кодом 200, поэтому по статусу их
# не отличить, а по тексту — легко: он короткий и говорит сам за себя.
_STUB_MARKERS = (
    "one moment, please", "please wait while your request",
    "checking your browser", "verifying you are human", "are you a robot",
    "enable javascript", "javascript is disabled", "access denied",
    "attention required", "captcha", "ddos protection",
    "error 403", "error 404", "page not found", "site temporarily unavailable",
)
MIN_ARTICLE_CHARS = 400


def looks_like_stub(text: str) -> bool:
    """Отличает заглушку от статьи.

    Проверка защиты от ботов, страница ошибки и «включите JavaScript» приходят
    с кодом 200 и валидным HTML — от статьи их отделяет только содержание.

    Пропустить такую страницу дальше означает скормить модели десяток слов,
    получить честное «ничего по теме» и записать это как согласие с человеком,
    который увидел ровно то же самое. Согласие на пустоте завышает каппу и
    делает шлюз допуска мягче, чем он выглядит. Поймано на живой выборке:
    из шестнадцати статей одна оказалась проверкой «вы не робот».

    Порог по длине грубый намеренно: новостная заметка короче четырёхсот
    знаков не бывает, а заглушки почти всегда короче ста.
    """
    t = (text or "").strip()
    if len(t) < MIN_ARTICLE_CHARS:
        return True
    low = t[:400].lower()
    return any(m in low for m in _STUB_MARKERS)


def html_to_text(blob: bytes, limit: int = 4000) -> str:
    """Извлечение текста статьи. Без зависимостей — их в проекте нет.

    Первая версия просто срезала теги и брала первые 4000 знаков страницы.
    На живой выборке стало видно, чем это плохо: у современных изданий первые
    несколько сотен знаков — это меню. «Sections Search Sections Subscribe
    Subscribe Close Subscribe Home Latest Crosswords & Puzzles...» — так
    начинались три статьи из шестнадцати, и модель платила за это токенами,
    а конец статьи не помещался в лимит. Шлюз допуска в такой постановке
    измерял бы, насколько хорошо модель читает навигацию.

    Поэтому три шага, каждый с откатом на предыдущий, если не сработал:
      1. вырезать обвязку — nav, header, footer, aside, формы;
      2. взять содержимое <article> или <main>, если разметка их обозначила;
      3. собрать текст из <p> и заголовков — меню состоит из ссылок в списках,
         а не из абзацев, и этим отсеивается само.
    Если абзацев в странице нет вовсе (бывает у совсем старых шаблонов),
    возвращаемся к прежнему поведению: весь текст подряд. Лучше шумно,
    чем пусто.

    Точности readability здесь не требуется: модели нужен связный кусок про
    событие, а не идеально очищенная статья.
    """
    try:
        raw = blob.decode("utf-8", "replace")
    except Exception:
        return ""

    raw = _TAGS.sub(" ", raw)
    raw = _CHROME.sub(" ", raw)

    m = _MAIN.search(raw)
    body = m.group(2) if m else raw

    paras = [_WS.sub(" ", _html.unescape(_ALL.sub(" ", p[1]))).strip()
             for p in _PARA.findall(body)]
    # Обрывки в один-два слова — подписи к картинкам и остатки меню.
    text = " ".join(p for p in paras if len(p) > 40)

    if len(text) < MIN_ARTICLE_CHARS:
        text = _WS.sub(" ", _html.unescape(_ALL.sub(" ", body))).strip()

    return text[:limit]


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

    # Заглушка — это отсутствие статьи, а не короткая статья. Возвращаем None,
    # и вызывающий считает её непрочитанной: пустой текст не должен ни попадать
    # в промпт, ни оказываться в выборке для сверки с человеком.
    text = html_to_text(blob)
    return None if looks_like_stub(text) else text


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
