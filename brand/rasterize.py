#!/usr/bin/env python3
"""Растеризация фирменных файлов: PNG-иконки и картинка для соцсетей.

Отдельный скрипт, а не часть make_logo.py, намеренно: make_logo.py обязан
работать на голой стандартной библиотеке, потому что его гоняет CI. Здесь
нужен настоящий браузер, и запускать это надо руками — раз в тысячу лет,
когда меняется сам знак.

    pip install playwright && playwright install chromium
    python3 brand/rasterize.py

Зачем PNG, если SVG-фавикон уже есть: Safari до 17 и часть Android-оболочек
SVG-иконку игнорируют и показывают пустой лист. apple-touch-icon вообще
обязан быть растровым и непрозрачным — iOS сама подложит чёрный фон, если
дать прозрачный.
"""
from __future__ import annotations
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
PAPER = "#FBFAF7"
INK = "#191817"
WARM = "#C4703B"

# (файл, размер, фон) — прозрачный фон только там, где он допустим
ICONS = [
    ("icon-32.png", 32, None),
    ("icon-180.png", 180, PAPER),   # apple-touch-icon: прозрачность запрещена
    ("icon-512.png", 512, PAPER),   # манифест / установка на домашний экран
]


def page_html(svg: str, size: int, bg: str | None) -> str:
    fill = bg or "transparent"
    pad = round(size * 0.16) if bg else 0     # у touch-иконки поля обязательны
    inner = size - pad * 2
    return (f'<!doctype html><meta charset="utf-8">'
            f'<body style="margin:0;width:{size}px;height:{size}px;background:{fill};'
            f'display:flex;align-items:center;justify-content:center">'
            f'<div style="width:{inner}px;height:{inner}px">{svg}</div>')


def cover_html(mark: str) -> str:
    """1200×630 для превью ссылки. Без чисел: их на сайте ещё нет,
    а картинка с выдуманным индексом разойдётся по соцсетям навсегда.

    В стек шрифтов вписан 'DejaVu Sans Light': если Inter в системе нет
    (сборочная машина, контейнер), обычный fallback подставит нормальное
    начертание, и лёгкий логотип превратится в жирный. Light-запасной
    держит вес близким к задуманному."""
    return f'''<!doctype html><meta charset="utf-8">
<body style="margin:0;width:1200px;height:630px;background:{PAPER};overflow:hidden;
  font-family:Inter,'DejaVu Sans Light',-apple-system,Segoe UI,Roboto,sans-serif;color:{INK}">
<div style="position:absolute;inset:0;
  background:radial-gradient(60% 70% at 78% 22%,rgba(196,112,59,.13),transparent 70%)"></div>
<div style="position:absolute;left:96px;top:198px;display:flex;align-items:center;gap:34px">
  <div style="width:132px;height:132px">{mark}</div>
  <div>
    <div style="font-size:64px;font-weight:200;letter-spacing:-.04em">brink<span
      style="color:{WARM}">·</span>watch</div>
    <div style="font-size:25px;font-weight:300;color:#5C5854;margin-top:14px;letter-spacing:-.01em">
      индекс эскалации конфликтов</div>
  </div>
</div>
<div style="position:absolute;left:98px;bottom:78px;font-size:17px;font-weight:300;color:#8A847E">
  открытые данные · публичная методология · каждое число раскрывается до события</div>'''


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("нужен playwright: pip install playwright && playwright install chromium",
              file=sys.stderr)
        return 1

    mark = (OUT / "mark.svg").read_text(encoding="utf-8")
    favicon = (OUT / "favicon.svg").read_text(encoding="utf-8")
    # SVG приходит с width/height — в вёрстке они мешают, растягиваем по контейнеру
    fit = lambda s: s.replace('width="100" height="100"', 'width="100%" height="100%"')

    made = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name, size, bg in ICONS:
            # мелкие иконки берут утолщённый силуэт фавикона, крупные — основной знак
            src = fit(favicon if size <= 64 else mark)
            p = b.new_page(viewport={"width": size, "height": size})
            p.set_content(page_html(src, size, bg))
            p.screenshot(path=str(OUT / name), omit_background=bg is None)
            p.close()
            made.append(name)

        p = b.new_page(viewport={"width": 1200, "height": 630})
        p.set_content(cover_html(fit(mark)))
        p.screenshot(path=str(OUT / "og-cover.png"))
        p.close()
        made.append("og-cover.png")
        b.close()

    for f in made:
        print("  ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
