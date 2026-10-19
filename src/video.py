"""Video vertical (1080x1920, 30 s) para Reels: escena animada + frase que aparece línea a línea.

Pipeline: Pillow compone cada fotograma -> ffmpeg (por stdin) codifica H.264 + un pad de audio
ambiente sintetizado (sin copyright).

Escenas (tema de la frase):
    reflexion -> caballero a caballo   (assets/knight.jpg)
    espiritual -> mago                 (assets/mage.jpg)
Si falta la imagen se usa un paisaje procedural, para que el pipeline nunca falle.
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .render import _available_families, _load, _rgb, _wrap

W, H = 1080, 1920
FPS = 30
DURATION = 30
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

SCENES = {
    "reflexion": {
        "file": "knight.jpg", "tint": "#2a1a0f", "tint_amt": 0.28, "fog": "#b9a58a",
        "particles": "#ffb347", "text": "#f6ecd9", "muted": "#cdb893", "accent": "#e0a64a",
        "sky": ("#1b1410", "#6b3f1f"), "gallop": True, "duo": ("#120a05", "#f2d9a8"),
    },
    "espiritual": {
        "file": "mage.jpg", "tint": "#0d1030", "tint_amt": 0.30, "fog": "#8aa0d8",
        "particles": "#9be7ff", "text": "#eef3ff", "muted": "#a9b9e6", "accent": "#8fd3ff",
        "sky": ("#070a1f", "#27306b"), "gallop": False, "duo": ("#050818", "#b9d3ff"),
    },
}


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("No se encontró ffmpeg (instala ffmpeg o `pip install imageio-ffmpeg`).") from e


# ------------------------------------------------------------------ fondo

def _procedural_scene(theme: str, seed: int) -> Image.Image:
    """Paisaje de respaldo: cielo degradado, luna/sol y cordilleras en capas."""
    sc = SCENES[theme]
    rng = random.Random(seed)
    w, h = int(W * 1.35), int(H * 1.35)
    top, bottom = _rgb(sc["sky"][0]), _rgb(sc["sky"][1])
    grad = Image.linear_gradient("L").resize((w, h))
    img = Image.composite(Image.new("RGB", (w, h), bottom), Image.new("RGB", (w, h), top), grad)
    d = ImageDraw.Draw(img)
    cx, cy, r = int(w * 0.68), int(h * 0.30), 170
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse((cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    img = Image.composite(Image.new("RGB", (w, h), _rgb(sc["accent"])), img, glow)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_rgb(sc["text"]))
    for i, (base, shade) in enumerate([(0.60, 0.75), (0.70, 0.45), (0.82, 0.22)]):
        pts, x = [(0, h)], 0
        y = h * base
        while x <= w + 80:
            y += rng.uniform(-70, 70)
            y = min(max(y, h * (base - 0.08)), h * (base + 0.06))
            pts.append((x, y))
            x += rng.randint(60, 140)
        pts += [(w, h)]
        col = tuple(int(c * shade) for c in _rgb(sc["sky"][1]))
        d.polygon(pts, fill=col)
    return img


def _load_scene(theme: str, seed: int) -> tuple[Image.Image, bool]:
    """Devuelve (lienzo 1.3x del video, es_arte). El arte se ajusta al ancho y el resto se rellena
    con una versión difuminada de sí mismo, para no recortar al caballero/mago."""
    cw, ch = int(W * 1.3), int(H * 1.3)
    path = ASSETS / SCENES[theme]["file"]
    if not path.exists():
        img = _procedural_scene(theme, seed)
        scale = max(cw / img.width, ch / img.height)
        return img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS), False

    from PIL import ImageOps
    art = Image.open(path).convert("L")  # grabado: se tiñe después
    mx, my = int(art.width * 0.04), int(art.height * 0.04)  # quita margen de papel / huella de plancha
    art = art.crop((mx, my, art.width - mx, art.height - my))
    fit =art.resize((cw, int(art.height * cw / art.width)), Image.LANCZOS)
    if fit.height >= ch:  # más alto que el lienzo: recorte centrado
        top = (fit.height - ch) // 2
        return fit.crop((0, top, cw, top + ch)).convert("RGB"), True

    # El hueco arriba/abajo se rellena con el propio grabado reflejado (continuo en la costura),
    # difuminado y oscurecido progresivamente hacia los bordes.
    y = (ch - fit.height) // 2
    flip = ImageOps.flip(fit)
    ext = Image.new("L", (cw, ch), 0)
    ext.paste(flip, (0, y - fit.height))
    ext.paste(flip, (0, y + fit.height))
    ext = ext.filter(ImageFilter.GaussianBlur(16))
    dark = Image.new("L", (cw, ch), 255)
    dd = ImageDraw.Draw(dark)
    for r in range(y):
        dd.line((0, r, cw, r), fill=int(255 * (0.5 + 0.5 * (r / max(y, 1)) ** 1.3)))
    for r in range(y + fit.height, ch):
        dd.line((0, r, cw, r), fill=int(255 * (0.5 + 0.5 * ((ch - 1 - r) / max(ch - y - fit.height, 1)) ** 1.3)))
    ext = ImageChops.multiply(ext, dark)

    feather = Image.new("L", fit.size, 255)  # unión de 40 px para evitar cualquier salto
    fd = ImageDraw.Draw(feather)
    for k in range(40):
        v = int(255 * (k / 40))
        fd.line((0, k, fit.width, k), fill=v)
        fd.line((0, fit.height - 1 - k, fit.width, fit.height - 1 - k), fill=v)
    ext.paste(fit, (0, y), feather)
    return ext.convert("RGB"), True


def _grade(img: Image.Image, theme: str, is_art: bool) -> Image.Image:
    sc = SCENES[theme]
    if is_art:  # grabado en escala de grises -> duotono (sombras, luces)
        from PIL import ImageOps
        img = ImageOps.colorize(ImageOps.autocontrast(img.convert("L"), cutoff=1),
                                black=sc["duo"][0], white=sc["duo"][1])
        return Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.12)
    tint = Image.new("RGB", img.size, _rgb(sc["tint"]))
    img = Image.blend(img, tint, sc["tint_amt"])
    return Image.blend(img, Image.new("RGB", img.size, (0, 0, 0)), 0.10)


def _vignette() -> Image.Image:
    m = Image.radial_gradient("L").resize((W, H), Image.BILINEAR).point(lambda v: int(v * 0.6))
    return m


def _fog_layer(seed: int) -> Image.Image:
    rng = random.Random(seed)
    n = Image.effect_noise((270, 240), 70 + rng.randint(0, 10)).filter(ImageFilter.GaussianBlur(6))
    return n.resize((W * 2, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(40))


# ------------------------------------------------------------------ texto

def _text_layers(frase: str, autor: str, fuente: str, theme: str, seed: int):
    """Devuelve ([(RGBA_línea, y)], RGBA_autor, y_autor, (y0, y1) del bloque)."""
    sc = SCENES[theme]
    rng = random.Random(seed)
    fams = _available_families()
    reg, ital = rng.choice(fams) if fams else (None, None)
    qpath = ital or reg
    max_w, max_h = W - 2 * 120, 760
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for size in range(96, 41, -2):
        font = _load(qpath, size)
        lines = _wrap(probe, frase.strip(), font, max_w)
        lh = int(size * 1.34)
        if len(lines) * lh <= max_h:
            break
    block = len(lines) * lh
    a_font, s_font = _load(reg, 46), _load(ital or reg, 34)
    total = block + 90 + 60 + (50 if fuente else 0)
    y0 = int(H * 0.46 - total / 2)
    text_c, muted_c, acc_c = _rgb(sc["text"]), _rgb(sc["muted"]), _rgb(sc["accent"])

    items = []
    y = y0
    for line in lines:
        layer = Image.new("RGBA", (W, lh + 20), (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        # sombra suave para legibilidad
        dl.text((W // 2 + 3, 13 + 3), line, font=_load(qpath, size), fill=(0, 0, 0, 170), anchor="ma")
        dl.text((W // 2, 13), line, font=_load(qpath, size), fill=text_c + (255,), anchor="ma")
        items.append((layer, y))
        y += lh
    y_auth = y + 40
    layer = Image.new("RGBA", (W, 190), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    dl.line((W // 2 - 70, 8, W // 2 + 70, 8), fill=acc_c + (255,), width=4)
    if autor:
        dl.text((W // 2 + 2, 42 + 2), f"— {autor}", font=a_font, fill=(0, 0, 0, 170), anchor="ma")
        dl.text((W // 2, 42), f"— {autor}", font=a_font, fill=text_c + (255,), anchor="ma")
    if fuente:
        dl.text((W // 2, 104), fuente, font=s_font, fill=muted_c + (255,), anchor="ma")
    return items, layer, y_auth, (y0, y_auth + 190)


def _text_backdrop(y0: int, y1: int) -> Image.Image:
    """Franja oscura difuminada tras el texto (máscara L)."""
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rectangle((0, y0 - 120, W, y1 + 100), fill=115)
    return m.filter(ImageFilter.GaussianBlur(90))


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ------------------------------------------------------------------ audio

def _audio_args(theme: str, duration: int) -> list[str]:
    """Pad ambiente sintetizado con ffmpeg (tres senos + trémolo + fundidos)."""
    base = 98.0 if theme == "reflexion" else 130.81  # sol grave / do: más "místico"
    freqs = [base, base * 1.5, base * 2.0]
    ins = []
    for f in freqs:
        ins += ["-f", "lavfi", "-t", str(duration), "-i", f"sine=frequency={f:.2f}:sample_rate=44100"]
    flt = (
        "[1:a][2:a][3:a]amix=inputs=3:normalize=0,volume=0.20,tremolo=f=0.25:d=0.5,"
        f"lowpass=f=900,afade=t=in:d=3,afade=t=out:st={duration - 3}:d=3[a]"
    )
    return ins, flt  # type: ignore[return-value]


# ------------------------------------------------------------------ render

def render_video(frase: str, autor: str, fuente: str, theme: str, seed: int, out_path: Path,
                 duration: int = DURATION, progress: bool = True) -> Path:
    theme = theme if theme in SCENES else "reflexion"
    sc = SCENES[theme]
    rng = random.Random(seed)

    scene, is_art = _load_scene(theme, seed)
    scene = _grade(scene, theme, is_art)
    vign = _vignette()
    fog = _fog_layer(seed)
    fog_col = Image.new("RGB", (W, H), _rgb(sc["fog"]))
    items, auth_layer, y_auth, (ty0, ty1) = _text_layers(frase, autor, fuente, theme, seed)
    backdrop = _text_backdrop(ty0, ty1)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    grains = [Image.effect_noise((W, H), 4.5).convert("RGB") for _ in range(6)]

    parts =[(rng.random(), rng.random(), rng.uniform(18, 60), rng.uniform(1.5, 4.2), rng.random() * 6.28)
             for _ in range(70)]
    p_col = _rgb(sc["particles"])

    sw, sh = scene.size
    zoom0, zoom1 = 1.0, 1.14
    max_x, max_y = sw - W, sh - H
    n_frames = duration * FPS
    t_line0, t_gap = 2.2, 0.9  # el texto empieza a los 2.2 s, una línea cada 0.9 s
    t_auth = t_line0 + t_gap * len(items) + 0.6

    from .music import make_track
    wav = out_path.with_suffix(".music.wav")
    make_track(theme, seed, wav)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(wav),
           "-map", "0:v", "-map", "1:a", "-t", str(duration),
           "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-tune", "film",
           "-profile:v", "high", "-level", "4.2", "-maxrate", "8M", "-bufsize", "16M",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-g", "60", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "256k", "-shortest", str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    try:
        for i in range(n_frames):
            t = i / FPS
            k = i / (n_frames - 1)
            zoom = zoom0 + (zoom1 - zoom0) * k
            cw, ch = min(sw, W * 1.3 / zoom), min(sh, H * 1.3 / zoom)
            # paneo lento + vaivén de "galope" en la escena del caballero
            px = 0.5 + 0.18 * math.sin(k * math.pi) - 0.09
            bob = (math.sin(t * 7.5) * 6 + math.sin(t * 3.1) * 4) if sc["gallop"] else 0.0
            sway = (math.sin(t * 7.5 + 1.2) * 5) if sc["gallop"] else 0.0
            x0 = min(max((sw - cw) * px + sway, 0), sw - cw)
            y0 = min(max((sh - ch) * 0.5 + bob, 0), sh - ch)
            frame = scene.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))

            # niebla desplazándose
            off = int((t * (90 if sc["gallop"] else 35)) % W)
            fm = fog.crop((off, 0, off + W, H)).point(lambda v: int(v * 0.55))
            frame = Image.composite(fog_col, frame, fm)

            # partículas (brasas que suben / destellos que flotan)
            d = ImageDraw.Draw(frame)
            for (px0, py0, spd, size, ph) in parts:
                if sc["gallop"]:
                    x = (px0 * W - t * 120 * (spd / 40) ) % W
                    y = (py0 * H - t * spd) % H
                else:
                    x = px0 * W + math.sin(t * 0.8 + ph) * 30
                    y = (py0 * H - t * spd * 0.5) % H
                tw = 0.5 + 0.5 * math.sin(t * 3 + ph)
                col = tuple(int(c * (0.4 + 0.6 * tw)) for c in p_col)
                s = size * (0.7 + 0.5 * tw)
                if sc["gallop"]:  # estela horizontal: polvo y brasas arrastrados por el galope
                    ln = 14 + spd * 1.6
                    d.line((x, y, x + ln, y - ln * 0.06), fill=col, width=max(int(s * 0.8), 1))
                else:
                    d.ellipse((x - s, y - s, x + s, y + s), fill=col)

            # viñeta + franja oscura tras el texto
            frame = Image.composite(black, frame, vign)
            bd = backdrop.point(lambda v: int(v * _ease((t - 1.0) / 1.2)))
            frame = Image.composite(black, frame, bd)

            # texto: aparece línea a línea con ligero ascenso
            for idx, (layer, y) in enumerate(items):
                a = _ease((t - (t_line0 + idx * t_gap)) / 0.9)
                if a <= 0:
                    continue
                lay = layer.copy()
                lay.putalpha(lay.getchannel("A").point(lambda v, a=a: int(v * a)))
                frame.paste(lay, (0, int(y + (1 - a) * 28)), lay)
            a = _ease((t - t_auth) / 1.0)
            if a > 0:
                lay = auth_layer.copy()
                lay.putalpha(lay.getchannel("A").point(lambda v, a=a: int(v * a)))
                frame.paste(lay, (0, int(y_auth + (1 - a) * 20)), lay)

            # fundido de entrada/salida
            fade = min(_ease(t / 1.0), _ease((duration - t) / 1.5))
            if fade < 1.0:
                frame = Image.blend(black, frame, fade)

            # grano de película sutil (evita bandas en degradados oscuros al comprimir)
            frame = ImageChops.add(frame, grains[i % len(grains)], 1, -128)

            proc.stdin.write(frame.tobytes())
            if progress and i % (FPS * 5) == 0:
                print(f"  fotograma {i}/{n_frames}", flush=True)
    finally:
        proc.stdin.close()
        rc = proc.wait()
        wav.unlink(missing_ok=True)
    if rc != 0:
        raise RuntimeError(f"ffmpeg terminó con código {rc}")
    return out_path


def render_poster(video_path: Path, out_path: Path, at: float = 12.0) -> None:
    """Extrae un fotograma (por defecto a los 12 s) para previsualizar."""
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(at), "-i", str(video_path),
                    "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", str(out_path)], check=True)
