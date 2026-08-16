#!/usr/bin/env python3
"""Генератор фирменного знака brink.watch.

Идея знака: он не придуман отдельно от продукта, а взят из него.
Главный визуальный элемент интерфейса — дуга, которая разгорается к текущему
значению и заканчивается угольком. Знак — это она же, сведённая к минимуму.

    python3 brand/make_logo.py     # пересобрать все файлы в brand/
"""
from __future__ import annotations
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent

COLD = "#7E8B92"   # пепел — холодный конец шкалы
WARM = "#C4703B"   # глина — тёплый конец, он же акцент бренда
INK  = "#191817"
CX = CY = 50


def polar(r: float, deg: float) -> tuple[float, float]:
    a = (deg - 90) * math.pi / 180
    return CX + r * math.cos(a), CY + r * math.sin(a)


def arc_path(r: float, a0: float, a1: float) -> str:
    x0, y0 = polar(r, a0)
    x1, y1 = polar(r, a1)
    large = 1 if (a1 - a0) > 180 else 0
    return f"M {x0:.2f} {y0:.2f} A {r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}"


def mark(a0: float, a1: float, *, r=31.0, sw=10.0, uid="a",
         grad=True, halo=True, color: str | None = None) -> str:
    """Дуга + уголёк. Всё остальное — параметры одной и той же формы."""
    ex, ey = polar(r, a1)
    solid = color or WARM
    defs = []

    if grad:
        gx0, _ = polar(r, a0)
        defs.append(
            f'<linearGradient id="g{uid}" gradientUnits="userSpaceOnUse" '
            f'x1="{gx0:.1f}" y1="0" x2="{ex:.1f}" y2="0">'
            f'<stop offset="0" stop-color="{COLD}" stop-opacity=".28"/>'
            f'<stop offset=".55" stop-color="{WARM}" stop-opacity=".72"/>'
            f'<stop offset="1" stop-color="{WARM}"/></linearGradient>')
    if halo:
        defs.append(
            f'<radialGradient id="h{uid}">'
            f'<stop offset="0" stop-color="{WARM}" stop-opacity=".45"/>'
            f'<stop offset="1" stop-color="{WARM}" stop-opacity="0"/></radialGradient>')

    stroke = f"url(#g{uid})" if grad else solid
    body = (f'<path d="{arc_path(r, a0, a1)}" fill="none" stroke="{stroke}" '
            f'stroke-width="{sw}" stroke-linecap="round"/>')
    if halo:
        body += f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{sw * 1.75:.1f}" fill="url(#h{uid})"/>'
    body += f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{sw / 2:.1f}" fill="{solid}"/>'

    return (f'<defs>{"".join(defs)}</defs>{body}') if defs else body


def dark_mark(p: dict) -> str:
    """Тот же знак для тёмного фона: холодный конец светлее, чтобы не тонул."""
    a0, a1, r, sw = p["a0"], p["a1"], p["r"], p["sw"]
    ex, ey = polar(r, a1)
    gx0, _ = polar(r, a0)
    return (
        f'<defs><linearGradient id="gd" gradientUnits="userSpaceOnUse" '
        f'x1="{gx0:.1f}" y1="0" x2="{ex:.1f}" y2="0">'
        f'<stop offset="0" stop-color="#B9BEC4" stop-opacity=".34"/>'
        f'<stop offset=".55" stop-color="#D8823F" stop-opacity=".78"/>'
        f'<stop offset="1" stop-color="#E08A45"/></linearGradient>'
        f'<radialGradient id="hd"><stop offset="0" stop-color="#E08A45" stop-opacity=".5"/>'
        f'<stop offset="1" stop-color="#E08A45" stop-opacity="0"/></radialGradient></defs>'
        f'<path d="{arc_path(r, a0, a1)}" fill="none" stroke="url(#gd)" '
        f'stroke-width="{sw}" stroke-linecap="round"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{sw * 1.75:.1f}" fill="url(#hd)"/>'
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="{sw / 2:.1f}" fill="#E08A45"/>')


def svg(inner: str, size=100, vb="0 0 100 100") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
            f'width="{size}" height="{size}" fill="none" '
            f'role="img" aria-label="brink.watch">{inner}</svg>')


# --------------------------------------------------------------------------
# Три варианта формы. Отличаются только углами — это один и тот же знак.
# --------------------------------------------------------------------------
VARIANTS = {
    # Разомкнутая дуга: уголёк на верхнем правом краю, разрыв внизу.
    # Читается как шкала, не дошедшая до конца, — и как край, к которому идут.
    "open":  dict(a0=-150, a1=55,  r=31, sw=10),
    # Почти сомкнутое кольцо с узким разрывом — «на грани замыкания».
    "ring":  dict(a0=-170, a1=150, r=31, sw=9),
    # Короткий сегмент: минимум, только намёк на шкалу.
    "short": dict(a0=-60,  a1=60,  r=32, sw=11),
}
PRIMARY = "open"


def build() -> list[str]:
    made = []

    for name, p in VARIANTS.items():
        (OUT / f"mark-{name}.svg").write_text(svg(mark(uid=name, **p)), encoding="utf-8")
        made.append(f"mark-{name}.svg")

    p = VARIANTS[PRIMARY]

    # Основной знак
    (OUT / "mark.svg").write_text(svg(mark(uid="m", **p)), encoding="utf-8")

    # Фавикон. Здесь недостаточно просто убрать градиент: на 16 пикселях тонкая
    # дуга радиусом 30 превращается в еле заметный крючок. Мелкая версия рисуется
    # заметно компактнее и толще — радиус меньше, штрих вдвое шире. Силуэт тот же,
    # но он занимает всю площадь и читается в панели вкладок.
    (OUT / "favicon.svg").write_text(
        svg(mark(a0=p["a0"], a1=p["a1"], r=26, sw=20, uid="f", grad=False, halo=False)),
        encoding="utf-8")

    # Версия для тёмного фона: холодный конец дуги осветляется, иначе он сливается
    # с фоном и от знака остаётся только оранжевый огрызок.
    (OUT / "mark-dark.svg").write_text(svg(dark_mark(p)), encoding="utf-8")
    made.append("mark-dark.svg")

    # Одноцветный: наследует цвет текста. Для печати, тёмного фона, штампов.
    (OUT / "mark-mono.svg").write_text(
        svg(mark(uid="mo", grad=False, halo=False, color="currentColor", **p)),
        encoding="utf-8")

    made += ["mark.svg", "favicon.svg", "mark-mono.svg"]

    # Логотип со словом. Точка в brink.watch — это и есть уголёк:
    # знак и написание оказываются одним и тем же объектом.
    ex, ey = polar(p["r"], p["a1"])
    lock = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 100" width="420" height="100"
  fill="none" role="img" aria-label="brink.watch">
  <g>{mark(uid="L", **p)}</g>
  <text x="122" y="63" font-family="Inter,-apple-system,Segoe UI,Roboto,sans-serif"
        font-size="34" font-weight="300" letter-spacing="-1.1" fill="{INK}">brink</text>
  <circle cx="204" cy="56" r="4.5" fill="{WARM}"/>
  <text x="216" y="63" font-family="Inter,-apple-system,Segoe UI,Roboto,sans-serif"
        font-size="34" font-weight="300" letter-spacing="-1.1" fill="{INK}">watch</text>
</svg>'''
    (OUT / "logo.svg").write_text(lock, encoding="utf-8")
    made.append("logo.svg")
    return made


if __name__ == "__main__":
    for f in build():
        print("  ", f)
