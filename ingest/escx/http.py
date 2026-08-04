"""Тонкая обёртка над urllib: ретраи, экспоненциальный бэкофф, дисковый кэш.

Дисковый кэш здесь не оптимизация, а дисциплина: при отладке пайплайна один и тот же
запрос уходит десятки раз. Кэш экономит и трафик, и лимит запросов источника
(у UCDP это 5000 запросов в сутки на IP — исчерпывается быстрее, чем кажется).
"""
from __future__ import annotations
import gzip, hashlib, json, os, ssl, time, urllib.error, urllib.request
from pathlib import Path

UA = "escx-ingest/0.1 (+contact@example.org)"
CACHE = Path(os.environ.get("ESCX_CACHE", ".cache"))


def _key(url: str) -> Path:
    return CACHE / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".bin")


def get(url: str, *, retries: int = 4, timeout: int = 60,
        use_cache: bool = True, pause: float = 0.4) -> bytes:
    """GET с ретраями. Возвращает сырые байты.

    Осознанно НЕ поднимает исключение на 404: у файловых потоков (GDELT) отсутствие
    файла — штатная ситуация, а не сбой. Возвращает b'' и даёт вызывающему решить.
    """
    cp = _key(url)
    if use_cache and cp.exists():
        return cp.read_bytes()

    CACHE.mkdir(parents=True, exist_ok=True)
    ctx = ssl.create_default_context()
    last: Exception | None = None

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            if use_cache:
                cp.write_bytes(raw)
            time.sleep(pause)           # вежливость к источнику
            return raw
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return b""
            if e.code in (429, 500, 502, 503, 504):
                last = e
                time.sleep(2 ** attempt * 1.5)
                continue
            raise
        except Exception as e:            # сеть, таймаут, TLS
            last = e
            time.sleep(2 ** attempt * 1.5)

    raise RuntimeError(f"не удалось получить {url}: {last}")


def get_json(url: str, **kw) -> dict:
    body = get(url, **kw)
    return json.loads(body) if body else {}
