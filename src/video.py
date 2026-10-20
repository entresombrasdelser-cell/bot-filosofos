"""Video vertical (1080x1920, 30 s) para Reels: clips cinematográficos nocturnos del caballero de
armadura negra y/o el mago de túnica negra, con sus gatos negros, + frase que aparece línea a línea.
La escena de los clips (combate, fogata, heridos…) sale de la columna `escena` de la frase.

Pipeline: ffmpeg encadena clips de assets/clips/ (ver tools/make_clips.py) con fundidos y los escala
-> Pillow superpone viñeta, texto y grano en cada fotograma -> ffmpeg codifica H.264.
Sin audio por defecto (la música se elige en Instagram); con music=True lleva el rock original
sintetizado de src/music.py.
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .render import _available_families, _load, _rgb, _wrap

W, H = 1080, 1920
FPS = 30
DURATION = 30
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CLIPS_DIR = ASSETS / "clips"
CLIP_SECONDS = 5.0
XFADE = 0.6  # fundido entre clips (s)

PERSONAJES = ("caballero", "mago", "ambos")
ESCENAS = ("combate", "demonios", "asedio", "fogata", "heridos", "camino", "vigilia")
# escenas que completan el video tras la de la frase, en orden (la última suele cerrar la "historia")
AFINES = {
    "combate": ("asedio", "heridos", "demonios"),
    "demonios": ("combate", "heridos", "vigilia"),
    "asedio": ("combate", "heridos", "fogata"),
    "fogata": ("camino", "vigilia", "heridos"),
    "heridos": ("fogata", "camino", "combate"),
    "camino": ("fogata", "vigilia", "heridos"),
    "vigilia": ("camino", "fogata", "demonios"),
}

PALETTES = {
    "reflexion": {"text": "#f6ecd9", "muted": "#cdb893", "accent": "#e0a64a"},
    "espiritual": {"text": "#eef3ff", "muted": "#a9b9e6", "accent": "#8fd3ff"},
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

def pick_personaje(tema: str, seed: int) -> str:
    """Quién sale en el video, al azar (fijo por semilla): el mago es más probable con frases espirituales,
    el caballero con el resto, y juntos aparecen 1 de cada 5 veces."""
    weights = (0.3, 0.5, 0.2) if tema == "espiritual" else (0.5, 0.3, 0.2)
    return random.Random(seed * 7 + 1).choices(PERSONAJES, weights)[0]


def _tags(clip: Path) -> tuple[str, str]:
    """caballero-combate-2.mp4 -> ("caballero", "combate")."""
    parts = clip.stem.split("-")
    return (parts[0], parts[1]) if len(parts) == 3 else ("", "")


def pick_clips(seed: int, escena: str, personaje: str, duration: float = DURATION) -> list[Path]:
    """Clips para cubrir `duration` (orden fijo para cada semilla): primero los del personaje en la escena
    de la frase; luego los suyos en escenas afines (p. ej. combate -> asedio -> heridos); si aún faltan
    (biblioteca incompleta), cualquiera."""
    clips = sorted(CLIPS_DIR.glob("*.mp4"))
    if not clips:
        raise RuntimeError("No hay clips en assets/clips/: genera la biblioteca con tools/make_clips.py.")
    n = math.ceil((duration - XFADE) / (CLIP_SECONDS - XFADE))
    rng = random.Random(seed)
    tags = {c: _tags(c) for c in clips}

    def group(people: tuple[str, ...], esc: str | None = None) -> list[Path]:
        g = [c for c in clips if tags[c][0] in people and (esc is None or tags[c][1] == esc)]
        rng.shuffle(g)
        return g

    tiers = [group((personaje,), escena)]
    if personaje == "ambos":  # juntos hay menos clips: se completa con cada uno por separado
        tiers.append(group(("caballero", "mago"), escena))
    tiers += [group((personaje,), e) for e in AFINES.get(escena, ())]
    tiers += [group((personaje,)), clips[:]]
    order: list[Path] = []
    for g in tiers:
        order += [c for c in g if c not in order]
        if len(order) >= n:
            break
    while len(order) < n:  # biblioteca muy pequeña: se repiten
        order += order[:n - len(order)]
    return order[:n]


def _background(clips: list[Path], duration: float) -> subprocess.Popen:
    """ffmpeg que entrega por stdout los fotogramas RGB 1080x1920 del fondo encadenado."""
    cmd = [ffmpeg_exe(), "-loglevel", "error"]
    for c in clips:
        cmd += ["-i", str(c)]
    parts = [f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
             f"setsar=1,tpad=stop_mode=clone:stop_duration=1,trim=duration={CLIP_SECONDS},"
             f"setpts=PTS-STARTPTS,fps={FPS}[v{i}]" for i in range(len(clips))]
    last = "v0"
    for i in range(1, len(clips)):
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={XFADE}:"
                     f"offset={i * (CLIP_SECONDS - XFADE):.3f}[x{i}]")
        last = f"x{i}"
    parts.append(f"[{last}]unsharp=5:5:0.6:5:5:0,format=rgb24[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-t", str(duration),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE)


def _vignette() -> Image.Image:
    return Image.radial_gradient("L").resize((W, H), Image.BILINEAR).point(lambda v: int(v * 0.55))


# ------------------------------------------------------------------ texto

def _text_layers(frase: str, autor: str, fuente: str, theme: str, seed: int):
    """Devuelve ([(RGBA_línea, y)], RGBA_autor, y_autor, (y0, y1) del bloque).

    El bloque va en el tercio superior: los personajes ocupan la mitad inferior de los clips."""
    pal = PALETTES[theme]
    rng = random.Random(seed)
    fams = _available_families()
    reg, ital = rng.choice(fams) if fams else (None, None)
    qpath = ital or reg
    max_w, max_h = W - 2 * 120, 680
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
    y0 = max(int(H * 0.29 - total / 2), 240)  # 240: lo que recorta la cuadrícula 3:4 del perfil
    text_c, muted_c, acc_c = _rgb(pal["text"]), _rgb(pal["muted"]), _rgb(pal["accent"])

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
    ImageDraw.Draw(m).rectangle((0, y0 - 120, W, y1 + 100), fill=125)
    return m.filter(ImageFilter.GaussianBlur(90))


def _ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ------------------------------------------------------------------ render

def render_video(frase: str, autor: str, fuente: str, theme: str, seed: int, out_path: Path,
                 escena: str = "camino", personaje: str = "caballero", duration: int = DURATION,
                 music: bool = False, progress: bool = True) -> Path:
    theme = theme if theme in PALETTES else "reflexion"
    vign = _vignette()
    items, auth_layer, y_auth, (ty0, ty1) = _text_layers(frase, autor, fuente, theme, seed)
    backdrop = _text_backdrop(ty0, ty1)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    grains = [Image.effect_noise((W, H), 4.5).convert("RGB") for _ in range(6)]

    n_frames = duration * FPS
    t_line0, t_gap = 1.6, 0.9  # el texto empieza a los 1.6 s, una línea cada 0.9 s
    t_auth = t_line0 + t_gap * len(items) + 0.6

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    wav = out_path.with_suffix(".music.wav")
    if music:
        from .music import make_track
        make_track(theme, seed, wav)
        cmd += ["-i", str(wav), "-map", "0:v", "-map", "1:a"]
    cmd += ["-t", str(duration),
            "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
            "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-tune", "film",
            "-profile:v", "high", "-level", "4.2", "-maxrate", "8M", "-bufsize", "16M",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-g", "60", "-movflags", "+faststart"]
    cmd += ["-c:a", "aac", "-b:a", "256k", "-shortest"] if music else ["-an"]
    cmd.append(str(out_path))

    bg = _background(pick_clips(seed, escena, personaje, duration), duration)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    size = W * H * 3
    buf = b""
    try:
        for i in range(n_frames):
            t = i / FPS
            chunk = bg.stdout.read(size)
            if len(chunk) == size:
                buf = chunk
            elif not buf:
                raise RuntimeError("ffmpeg no generó el fondo (¿algún clip dañado en assets/clips?)")
            frame = Image.frombytes("RGB", (W, H), buf)  # si el fondo acaba antes, repite el último

            # viñeta + franja oscura tras el texto
            a = _ease((t - 0.6) / 1.2)
            mask = ImageChops.lighter(vign, backdrop if a >= 1 else backdrop.point(lambda v: int(v * a)))
            frame = Image.composite(black, frame, mask)

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
        bg.kill()
        bg.wait()
        wav.unlink(missing_ok=True)
    if rc != 0:
        raise RuntimeError(f"ffmpeg terminó con código {rc}")
    return out_path


def render_poster(video_path: Path, out_path: Path, at: float = 12.0) -> None:
    """Extrae un fotograma (por defecto a los 12 s) para previsualizar."""
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(at), "-i", str(video_path),
                    "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", str(out_path)], check=True)
