"""Video vertical (1080x1920, ~15 s) para Reels: UNA sola toma continua, nocturna y cinematográfica, del
caballero de armadura negra y/o el mago de túnica negra con sus gatos negros, + frase que aparece línea a línea.
La escena (combate, fogata, heridos…) sale de la columna `escena` de la frase.

Una toma = un clip de 5 s de assets/clips/ (`caballero-fogata-1.mp4`) + sus continuaciones (`…-1b.mp4`,
`…-1c.mp4`), cada una animada desde un fotograma del final de la anterior (ver tools/make_clips.py), así que
se encadenan sin cambiar de plano. Si la toma aún es corta, se ralentiza (cámara lenta interpolada) y el
video dura algo menos.

Pipeline: ffmpeg une los trozos de la toma, la ralentiza si hace falta y la escala -> Pillow superpone
viñeta, texto y grano en cada fotograma -> ffmpeg codifica H.264.
Sin audio por defecto (la música se elige en Instagram); con music=True lleva el rock original
sintetizado de src/music.py.
"""
from __future__ import annotations

import random
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .render import _available_families, _load, _rgb, _wrap

W, H = 1080, 1920
FPS = 30
DURATION = 15  # duración objetivo (s); una toma completa (3 trozos) dura ~14.6 s
MIN_SPEED = 0.5  # cámara lenta máxima para estirar una toma corta
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CLIPS_DIR = ASSETS / "clips"
CLIP_SECONDS = 5.0
CLIP_W, CLIP_H = 480, 832  # resolución de Wan 2.2
CONTINUATIONS = ("b", "c")  # sufijos de las continuaciones de cada toma
OVERLAP = 6  # fotogramas en que cada continuación se funde con el final del trozo anterior
HANDLE = "@entresombrasdelser"  # marca de agua

PERSONAJES = ("caballero", "mago", "ambos")
ESCENAS = ("combate", "demonios", "asedio", "fogata", "heridos", "camino", "vigilia")
# escenas de reserva si aún no hay ninguna toma del personaje en la escena de la frase
AFINES = {
    "combate": ("asedio", "demonios", "heridos"),
    "demonios": ("combate", "asedio", "vigilia"),
    "asedio": ("combate", "demonios", "heridos"),
    "fogata": ("vigilia", "camino", "heridos"),
    "heridos": ("fogata", "camino", "combate"),
    "camino": ("fogata", "vigilia", "heridos"),
    "vigilia": ("fogata", "camino", "demonios"),
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


def clip_frames(clip: Path) -> int:
    """Número de fotogramas (a FPS) de un clip, según la duración que informa ffmpeg."""
    err = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(clip)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if not m:
        raise RuntimeError(f"No se pudo leer la duración de {clip.name}")
    h, mi, sec = m.groups()
    return round((int(h) * 3600 + int(mi) * 60 + float(sec)) * FPS)


# ------------------------------------------------------------------ fondo

def pick_personaje(tema: str, seed: int) -> str:
    """Quién sale en el video, al azar (fijo por semilla): el mago es más probable con frases espirituales,
    el caballero con el resto, y juntos aparecen 1 de cada 5 veces."""
    weights = (0.3, 0.5, 0.2) if tema == "espiritual" else (0.5, 0.3, 0.2)
    return random.Random(seed * 7 + 1).choices(PERSONAJES, weights)[0]


def take_segments(base: Path) -> list[Path]:
    """caballero-fogata-1.mp4 -> [ese clip, …-1b.mp4, …-1c.mp4] (las continuaciones que existan, en orden)."""
    segs = [base]
    for suf in CONTINUATIONS:
        nxt = base.with_name(f"{base.stem}{suf}.mp4")
        if not nxt.exists():
            break
        segs.append(nxt)
    return segs


def _takes() -> dict[Path, tuple[str, str]]:
    """Clip inicial de cada toma -> (personaje, escena): caballero-combate-2.mp4 -> ("caballero", "combate")."""
    out = {}
    for c in sorted(CLIPS_DIR.glob("*.mp4")):
        parts = c.stem.split("-")
        if len(parts) == 3 and parts[2].isdigit():  # las continuaciones (…-2b) no empiezan toma
            out[c] = (parts[0], parts[1])
    return out


def pick_take(seed: int, escena: str, personaje: str) -> list[Path]:
    """Trozos de UNA sola toma (fija para cada semilla): del personaje en la escena de la frase; si no hay, de
    cada uno por separado (si son "ambos"), luego en escenas afines y, por último, cualquiera. Entre las
    candidatas, de las más largas (con más continuaciones)."""
    takes = _takes()
    if not takes:
        raise RuntimeError("No hay clips en assets/clips/: genera la biblioteca con tools/make_clips.py.")
    tiers = [[(personaje, escena)]]
    if personaje == "ambos":  # juntos hay menos tomas: si falta, uno de los dos en esa escena
        tiers.append([("caballero", escena), ("mago", escena)])
    tiers += [[(personaje, e)] for e in AFINES.get(escena, ())]
    tiers += [[(personaje, e) for e in ESCENAS]]
    rng = random.Random(seed)
    for wanted in tiers:
        cands = [take_segments(c) for c, tag in takes.items() if tag in wanted]
        if cands:
            longest = max(len(t) for t in cands)
            return rng.choice([t for t in cands if len(t) == longest])
    return take_segments(rng.choice(sorted(takes)))


def take_plan(segments: list[Path], duration: float = DURATION) -> tuple[list[int], float, float]:
    """(fotogramas de cada trozo, velocidad, duración del video). Una toma corta se ralentiza (hasta
    MIN_SPEED) para acercarse a `duration`; si ya casi llega (>= 85 %), va a velocidad real."""
    frames = [clip_frames(s) for s in segments]
    length = (sum(frames) - OVERLAP * (len(frames) - 1)) / FPS
    speed = min(max(length / duration, MIN_SPEED), 1.0)
    if speed >= 0.85:
        speed = 1.0
    return frames, speed, min(length / speed, duration)


def _background(segments: list[Path], frames: list[int], speed: float, duration: float) -> subprocess.Popen:
    """ffmpeg que entrega por stdout los fotogramas RGB 1080x1920 de la toma: une los trozos (cada continuación
    empieza en el fotograma del trozo anterior del que se animó y se funde con él durante OVERLAP fotogramas),
    la ralentiza con interpolación de movimiento si speed < 1 y la escala."""
    cmd = [ffmpeg_exe(), "-loglevel", "error"]
    for c in segments:
        cmd += ["-i", str(c)]
    parts = [f"[{i}:v]scale={CLIP_W}:{CLIP_H}:force_original_aspect_ratio=increase,crop={CLIP_W}:{CLIP_H},"
             f"setsar=1,setpts=PTS-STARTPTS,fps={FPS}[v{i}]" for i in range(len(segments))]
    last, offset = "v0", 0
    for i in range(1, len(segments)):
        offset += frames[i - 1] - OVERLAP
        parts.append(f"[{last}][v{i}]xfade=transition=fade:duration={OVERLAP / FPS:.4f}:"
                     f"offset={offset / FPS:.4f}[x{i}]")
        last = f"x{i}"
    slow = (f"setpts=PTS/{speed:.4f},minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1,"
            if speed < 1 else "")
    # limpia el ruido de compresión antes de escalar y luego realza bordes sin halos (CAS)
    parts.append(f"[{last}]{slow}hqdn3d=1.5:1.5:3:3,tpad=stop_mode=clone:stop_duration=1,"
                 f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},"
                 f"cas=0.7,format=rgb24[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-t", f"{duration:.3f}",
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


def _watermark(theme: str, seed: int) -> tuple[Image.Image, int]:
    """Nombre de la cuenta, pequeño y semitransparente, centrado sobre la zona que tapa la descripción del
    Reel (abajo) y lejos de los botones (derecha)."""
    fams = _available_families()
    reg = random.Random(seed).choice(fams)[0] if fams else None  # misma familia que el autor
    font, track = _load(reg, 34), 5
    widths = [font.getlength(ch) for ch in HANDLE]
    x = (W - (sum(widths) + track * (len(HANDLE) - 1))) / 2
    layer = Image.new("RGBA", (W, 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for ch, w in zip(HANDLE, widths):  # espaciado entre letras
        d.text((x + 2, 12), ch, font=font, fill=(0, 0, 0, 120))
        d.text((x, 10), ch, font=font, fill=_rgb(PALETTES[theme]["text"]) + (150,))
        x += w + track
    return layer, int(H * 0.765)


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
                 escena: str = "camino", personaje: str = "caballero", duration: float = DURATION,
                 music: bool = False, progress: bool = True) -> float:
    """Genera el video y devuelve su duración en segundos (la toma decide: ~10-15 s)."""
    theme = theme if theme in PALETTES else "reflexion"
    segments = pick_take(seed, escena, personaje)
    frames, speed, duration = take_plan(segments, duration)
    if progress:
        print(f"  toma: {' + '.join(s.name for s in segments)} ({duration:.1f} s"
              + (f", cámara lenta x{speed:.2f})" if speed < 1 else ")"), flush=True)
    vign = _vignette()
    items, auth_layer, y_auth, (ty0, ty1) = _text_layers(frase, autor, fuente, theme, seed)
    backdrop = _text_backdrop(ty0, ty1)
    mark, y_mark = _watermark(theme, seed)
    black = Image.new("RGB", (W, H), (0, 0, 0))
    grains = [Image.effect_noise((W, H), 4.5).convert("RGB") for _ in range(6)]

    n_frames = round(duration * FPS)
    # el texto empieza a los 1.4 s, una línea cada 0.9 s como mucho: toda la frase a la vista antes de la
    # mitad del video, para que dé tiempo a leerla
    t_line0 = 1.4
    t_gap = min(0.9, (duration * 0.45 - t_line0) / max(len(items), 1))
    t_auth = t_line0 + t_gap * len(items) + 0.5

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

    bg = _background(segments, frames, speed, duration)
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
            frame.paste(mark, (0, y_mark), mark)

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
    return duration


def render_poster(video_path: Path, out_path: Path, at: float = 8.0) -> None:
    """Extrae un fotograma (por defecto a los 8 s, con la frase ya completa) para previsualizar."""
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-ss", str(at), "-i", str(video_path),
                    "-frames:v", "1", "-pix_fmt", "yuvj420p", "-q:v", "2", str(out_path)], check=True)
