"""Generación de la imagen 1080x1350 con Pillow."""
from __future__ import annotations

import math
import os
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
MARGIN_X = 130
ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- fondos

def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _linear(top: str, bottom: str, angle: float = 0.0) -> Image.Image:
    """Degradado lineal; angle=0 vertical, en grados para inclinarlo."""
    d = int(math.hypot(W, H)) + 4
    mask = Image.linear_gradient("L").resize((d, d), Image.BILINEAR)
    mask = mask.rotate(angle, resample=Image.BICUBIC)
    left, upper = (d - W) // 2, (d - H) // 2
    mask = mask.crop((left, upper, left + W, upper + H))
    return Image.composite(
        Image.new("RGB", (W, H), _rgb(bottom)), Image.new("RGB", (W, H), _rgb(top)), mask
    )


def _vignette(img: Image.Image, color: str, strength: float) -> Image.Image:
    mask = Image.radial_gradient("L").resize((W, H), Image.BILINEAR)
    mask = mask.point(lambda v: int(v * strength))
    return Image.composite(Image.new("RGB", (W, H), _rgb(color)), img, mask)


def _noise(img: Image.Image, amount: float) -> Image.Image:
    noise = Image.effect_noise((W, H), 60).convert("RGB")
    return Image.blend(img, noise, amount)


STYLES = [
    {   # 0 noche
        "name": "noche",
        "bg": lambda: _vignette(_linear("#14213d", "#050810"), "#000000", 0.55),
        "text": "#f3ead7", "muted": "#a89f8a", "accent": "#d4af37", "frame": False,
    },
    {   # 1 papel
        "name": "papel",
        "bg": lambda: _vignette(_noise(_linear("#f4ecda", "#e0d0ae", 12), 0.07), "#a58c5a", 0.35),
        "text": "#2b2118", "muted": "#6e5c47", "accent": "#8c2f2f", "frame": True,
    },
    {   # 2 carbón
        "name": "carbon",
        "bg": lambda: _noise(_vignette(Image.new("RGB", (W, H), _rgb("#2a2a2e")), "#0a0a0c", 0.85), 0.05),
        "text": "#f5f5f0", "muted": "#9d9da3", "accent": "#e8e8e0", "frame": False,
    },
    {   # 3 burdeos
        "name": "burdeos",
        "bg": lambda: _vignette(_linear("#5c1a2b", "#1c0710", 35), "#000000", 0.4),
        "text": "#f6e9dc", "muted": "#c7a89a", "accent": "#e0b26a", "frame": True,
    },
    {   # 4 mármol claro
        "name": "marmol",
        "bg": lambda: _noise(_linear("#f6f6f4", "#cfd0cf", -20), 0.05),
        "text": "#16181d", "muted": "#5a5e66", "accent": "#16181d", "frame": True,
    },
    {   # 5 océano
        "name": "oceano",
        "bg": lambda: _vignette(_linear("#0f4c5c", "#0b132b", -30), "#000000", 0.35),
        "text": "#f1f7f6", "muted": "#9cc3c2", "accent": "#7fd1c7", "frame": False,
    },
]

# ---------------------------------------------------------------- fuentes

_FONT_DIRS = [
    ROOT / "fonts",
    Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
    Path("/System/Library/Fonts"), Path("/Library/Fonts"),
]

# (regular, cursiva): se usa la primera pareja encontrada de cada familia
FAMILIES = [
    (["ebgaramond12-regular.otf", "ebgaramond-regular.otf", "ebgaramond12-regular.ttf"],
     ["ebgaramond12-italic.otf", "ebgaramond-italic.otf", "ebgaramond12-italic.ttf"]),
    (["pala.ttf", "linlibertine_r.otf", "libertinusserif-regular.otf"],
     ["palai.ttf", "linlibertine_ri.otf", "libertinusserif-italic.otf"]),
    (["georgia.ttf", "dejavuserif.ttf"],
     ["georgiai.ttf", "dejavuserif-italic.ttf"]),
    (["times.ttf", "liberationserif-regular.ttf"],
     ["timesi.ttf", "liberationserif-italic.ttf"]),
]


@lru_cache(maxsize=1)
def _font_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for base in _FONT_DIRS:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix.lower() in (".ttf", ".otf"):
                index.setdefault(p.name.lower(), str(p))
    return index


def _first(names: list[str]) -> str | None:
    idx = _font_index()
    return next((idx[n] for n in names if n in idx), None)


def _available_families() -> list[tuple[str, str | None]]:
    out = []
    for regular, italic in FAMILIES:
        r = _first(regular)
        if r:
            out.append((r, _first(italic)))
    return out


def _load(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)  # Pillow >= 10.1


# ---------------------------------------------------------------- texto

def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render_image(frase: str, autor: str, fuente: str, style_idx: int, seed: int, out_path: Path) -> Path:
    rng = random.Random(seed)
    style = STYLES[style_idx % len(STYLES)]
    img = style["bg"]()
    draw = ImageDraw.Draw(img)
    text_c, muted_c, accent_c = _rgb(style["text"]), _rgb(style["muted"]), _rgb(style["accent"])

    families = _available_families()
    reg_path, ital_path = rng.choice(families) if families else (None, None)
    quote_path = ital_path if (ital_path and rng.random() < 0.5) else reg_path

    if style["frame"]:
        draw.rectangle((50, 50, W - 50, H - 50), outline=accent_c, width=2)
        draw.rectangle((62, 62, W - 62, H - 62), outline=accent_c, width=1)

    max_w, max_h = W - 2 * MARGIN_X, 620
    text = frase.strip()
    for size in range(92, 37, -2):
        font = _load(quote_path, size)
        lines = _wrap(draw, text, font, max_w)
        line_h = int(size * 1.3)
        if len(lines) * line_h <= max_h:
            break
    block_h = len(lines) * line_h

    author_font = _load(reg_path, 40)
    source_font = _load(ital_path or reg_path, 30)
    mark_h, gap_line, gap_author = 120, 70, 60
    total = mark_h + block_h + gap_line + 46 + (50 if fuente else 0) + gap_author - 40
    y = (H - total) // 2

    # comilla decorativa
    mark_font = _load(reg_path, 220)
    draw.text((W // 2, y - 30), "\u201c", font=mark_font, fill=accent_c, anchor="ma")
    y += mark_h

    for line in lines:
        draw.text((W // 2, y), line, font=font, fill=text_c, anchor="ma")
        y += line_h

    y += gap_line // 2
    draw.line((W // 2 - 60, y, W // 2 + 60, y), fill=accent_c, width=3)
    y += gap_line // 2

    if autor:
        draw.text((W // 2, y), f"\u2014 {autor}", font=author_font, fill=text_c, anchor="ma")
        y += 56
    if fuente:
        draw.text((W // 2, y), fuente, font=source_font, fill=muted_c, anchor="ma")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "JPEG", quality=92, subsampling=0, optimize=True)
    return out_path
