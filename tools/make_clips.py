"""Genera la biblioteca de clips de fondo (assets/clips/*.mp4): el caballero de armadura negra con su
gato acorazado y el mago de túnica negra con su gato negro, en escenas medievales nocturnas.

Cada escena es una toma continua de ~15 s en tres trozos de 5 s:
    <personaje>-<escena>-<n>.mp4     el inicio
    <personaje>-<escena>-<n>b.mp4    continuación animada desde un fotograma del final del anterior
    <personaje>-<escena>-<n>c.mp4    ídem desde el final de la b
    personaje: caballero, mago o ambos
    escena:    combate, demonios, asedio, fogata, heridos, camino, vigilia (ver ESCENAS en src/video.py)

Todo gratis y sin clave: dos Spaces públicos de Hugging Face (ZeroGPU).
    1. FLUX.1-schnell  -> fotograma 864x1536 a partir del texto de la escena
    2. Wan 2.2 (I2V)    -> lo anima 5 s (480x832, 16 fps); las continuaciones parten del fotograma del trozo
                           anterior que está OVERLAP fotogramas antes de su final (src/video.py los funde ahí)
    3. ffmpeg           -> interpolación de movimiento a 30 fps, recorte exacto a 5 s

Uso:
    pip install gradio_client
    python tools/make_clips.py                       # genera lo que falte, por orden (ver pending())
    python tools/make_clips.py mago-fogata-1         # rehace esa escena desde el inicio (borra sus continuaciones)
    python tools/make_clips.py mago-fogata-1c        # rehace solo esa continuación
    python tools/make_clips.py --stills --limit 4    # solo fotogramas (output/stills/), para revisarlos
    python tools/make_clips.py --wait                # si se agota la cuota, espera y sigue
    python tools/make_clips.py --list                # lista todas las escenas y sus trozos

La cuota gratuita de ZeroGPU da para ~1-2 trozos por vez; el workflow `clips.yml` completa la biblioteca
desde GitHub. Si cambias el texto de una escena, el fotograma se regenera solo (su nombre lleva un hash
del texto); para rehacer el clip, bórralo de assets/clips/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.video import (CLIP_SECONDS, CLIPS_DIR, CONTINUATIONS, ESCENAS, OVERLAP, PERSONAJES,  # noqa: E402
                       clip_frames, ffmpeg_exe)

STILLS_DIR = ROOT / "output" / "stills"
FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
WAN_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"

STYLE = ("cinematic film still, photorealistic, dark medieval fantasy, at night, anamorphic 35mm, "
         "shallow depth of field, volumetric light, muted colors, film grain, vertical composition, "
         "the characters in the lower half of the frame, dark night sky or darkness in the upper half")
K = "a knight in black plate armor and a long black cape holding a longsword"
KC = ("his warrior black cat clad in a miniature suit of black plate armor with a tiny knight helmet and "
      "a small black cloak")
W = ("a wizard in a long black hooded robe with a long grey beard holding a gnarled wooden staff "
     "topped with a glowing crystal")
WC = "his black cat with glowing golden eyes"
CATS = ("only two black cats: a warrior cat in miniature black plate armor and a tiny helmet, and a black cat "
        "with glowing golden eyes")
# se añade a todos los movimientos: los gatos son aliados (en batalla, el enemigo siempre delante del
# héroe y el gato a su lado; si el gato queda delante, Wan hace que la espada lo golpee) y movimiento
# pausado, que Wan resuelve sin manchas ni deformaciones
MOTION = ("the cat is his loyal companion and stays close to him, slow cinematic movement, smooth natural motion, "
          "steady camera, realistic, highly detailed")

# escena -> personaje -> (acción para FLUX, movimiento para Wan), y "lugares": un clip por lugar
# ("ambos" usa solo los dos primeros lugares: aparecen juntos con menos frecuencia)
CATALOGO = {
    "combate": {
        "caballero": (f"{K}, blocking the sword of an enemy soldier who attacks him from the front, more enemy "
                      f"soldiers in front of him, {KC} standing loyally at his side and facing the enemies with him",
                      "the knight clashes swords with the enemy soldier in front of him while his armored cat "
                      "stands guard at his side, both facing the enemy, rain and embers drift"),
        "mago": (f"{W}, blasting the enemy soldiers in front of him with lightning from his staff, {WC} standing "
                 "loyally at his side and hissing at the enemies",
                 "lightning arcs from the staff toward the enemy soldiers in the distance, his cat stays at his "
                 "side, embers drift"),
        "ambos": (f"{K} and {W} standing side by side against enemy soldiers who charge from the front, the knight "
                  f"blocking an enemy sword and the wizard casting fire at the enemies, {CATS}, one at each "
                  "hero's side, all facing the enemies",
                  "the knight clashes swords with an enemy soldier and the wizard hurls fire at the enemies in "
                  "front of them, their cats stay at their sides facing the enemy, embers drift"),
        "lugares": ["on a muddy battlefield lit by burning fires", "on an old stone bridge in the rain",
                    "in the burning streets of a medieval village"],
    },
    "demonios": {
        "caballero": (f"{K}, standing between {KC} and a huge horned demon of fire, raising his sword toward "
                      "the demon to protect his loyal cat",
                      "the knight raises his sword toward the roaring demon in front of him, protecting his "
                      "armored cat beside him, fire and embers swirl"),
        "mago": (f"{W}, holding back a huge horned demon of shadow and fire with a shield of blue light "
                 f"from his staff, {WC} at his feet",
                 "blue magic light pulses against the demon's fire in front of him, the demon roars, embers swirl"),
        "ambos": (f"{K} and {W} facing a giant horned demon of fire, the knight raising his sword and the "
                  f"wizard his glowing staff, {CATS} at their feet",
                  "fire and blue magic clash with the demon in front of them, the demon roars, embers swirl"),
        "lugares": ["in the ruins of a burning cathedral", "at the mouth of a hellish cave glowing red",
                    "in a dead forest under a blood red moon"],
    },
    "asedio": {
        "caballero": (f"{K}, leading soldiers with siege ladders in an assault on the gates of a dark castle, "
                      f"{KC} at his side",
                      "the soldiers charge toward the distant castle, flaming arrows fly over them, fire and smoke "
                      "rise in the distance, his cat walks beside him, slow epic camera push"),
        "mago": (f"{W}, hurling a huge fireball from his staff at the walls of a dark castle under siege, "
                 f"{WC} beside him",
                 "the fireball flies far away and explodes against the distant castle walls, fire and smoke rise "
                 "in the distance, his cat stays at his side"),
        "ambos": (f"{K} and {W} leading an army to conquer a dark castle, siege towers and burning arrows, "
                  f"{CATS} with them",
                  "the army advances on the distant castle, flaming arrows fly over them, fire and smoke rise, "
                  "slow epic camera push"),
        "lugares": ["under a stormy night sky", "under a night sky full of burning arrows",
                    "in the snow at night"],
    },
    "fogata": {
        "caballero": (f"{K}, resting by a campfire with his helmet on the ground beside him, a tired scarred "
                      f"face, {KC} curled up by the fire",
                      "the fire crackles and flickers, embers rise into the night, slow push in"),
        "mago": (f"{W}, sitting by a campfire smoking a long pipe, {WC} curled up beside the fire",
                 "the fire crackles and flickers, pipe smoke and embers rise into the night, slow push in"),
        "ambos": (f"{K} and {W} sitting together around a campfire, {CATS}, curled up by the fire",
                  "the fire crackles and flickers, embers rise into the night, slow push in"),
        "lugares": ["in a dark forest", "under a sky full of stars in the mountains", "among old stone ruins"],
    },
    "heridos": {
        "caballero": (f"{K}, badly wounded and exhausted after the battle, kneeling on one knee and leaning on "
                      f"his sword, his black armor cracked and covered in blood, blood dripping, {KC} with a "
                      "torn cloak sitting beside him",
                      "heavy breathing, smoke drifts, embers float, the cape moves in the wind, slow push in"),
        "mago": (f"{W}, badly wounded and exhausted after the battle, leaning on his staff, his black robe torn "
                 f"and covered in blood, a bleeding cut on his face, {WC} limping beside him",
                 "heavy breathing, smoke drifts, embers float, the robe moves in the wind, slow push in"),
        "ambos": (f"{K}, badly wounded and bleeding, sitting on the ground, and {W} kneeling beside him healing "
                  f"his wounds with a soft glowing light from his hand, {CATS} beside them",
                  "the healing light glows softly, smoke drifts, embers float, slow push in"),
        "lugares": ["on a smoking battlefield after the battle under a cold moon, fallen banners and broken "
                    "spears", "in the rain on a battlefield strewn with fallen shields", "among burning ruins"],
    },
    "camino": {
        "caballero": (f"{K}, walking slowly, {KC} walking beside him",
                      "they walk slowly toward the camera, mist drifts, the cape moves in the wind"),
        "mago": (f"{W}, walking slowly with his staff lighting the way, {WC} walking beside him",
                 "they walk slowly toward the camera, the crystal glows, mist drifts, the robe moves in the wind"),
        "ambos": (f"{K} and {W} walking side by side, {CATS} walking with them",
                  "they walk slowly toward the camera, mist drifts, capes and robes move in the wind"),
        "lugares": ["through a misty forest under the full moon", "along a snowy mountain path",
                    "through the ruins of an abandoned city"],
    },
    "vigilia": {
        "caballero": (f"{K}, kneeling in prayer with his sword planted in the ground before him, {KC} sitting "
                      "still beside him",
                      "candle flames flicker, dust floats in the light, very slow push in"),
        "mago": (f"{W}, performing a ritual with glowing runes floating in the air around him, {WC} watching",
                 "the glowing runes slowly swirl and pulse, light flickers, very slow push in"),
        "ambos": (f"{W} performing a ritual of glowing runes while {K} kneels beside him with his sword, "
                  f"{CATS} watching",
                  "the glowing runes slowly swirl and pulse, light flickers, very slow push in"),
        "lugares": ["inside a ruined chapel lit by candles", "in a circle of ancient standing stones under the stars",
                    "on a mountain top under a huge full moon"],
    },
}


def _catalog() -> dict[str, tuple[str, str, tuple[int, int, int]]]:
    """nombre -> (texto FLUX, movimiento Wan, clave de orden). Primero una variante de cada combinación."""
    out = {}
    for ei, esc in enumerate(ESCENAS):
        spec = CATALOGO[esc]
        for pi, pers in enumerate(PERSONAJES):
            action, motion = spec[pers]
            lugares = spec["lugares"][:2] if pers == "ambos" else spec["lugares"]
            for n, lugar in enumerate(lugares, 1):
                out[f"{pers}-{esc}-{n}"] = (f"{action}, {lugar}, {STYLE}", f"{motion}, {MOTION}", (n, pi, ei))
    return dict(sorted(out.items(), key=lambda kv: kv[1][2]))


SCENES = _catalog()
SEGMENTS = 1 + len(CONTINUATIONS)  # trozos por toma
WAIT_QUOTA = False  # --wait: en vez de salir, espera a que se recargue la cuota


def seg_name(name: str, k: int) -> str:
    """Trozo k de la toma: 0 -> "mago-fogata-1", 1 -> "mago-fogata-1b", 2 -> "mago-fogata-1c"."""
    return name + ("", *CONTINUATIONS)[k]


def seg_path(name: str, k: int) -> Path:
    return CLIPS_DIR / f"{seg_name(name, k)}.mp4"


def n_segments(name: str) -> int:
    """Trozos seguidos que ya tiene la toma."""
    k = 0
    while k < SEGMENTS and seg_path(name, k).exists():
        k += 1
    return k


def pending() -> list[tuple[str, int]]:
    """El siguiente trozo que falta de cada toma, por orden: primero se completan las tomas del lugar 1 de
    todas las escenas (inicios, luego las continuaciones b, luego las c), después las del lugar 2, etc."""
    jobs = []
    for name, (_, _, (n, pi, ei)) in SCENES.items():
        k = n_segments(name)
        if k < SEGMENTS:
            jobs.append(((n, k, pi, ei), name, k))
    return [(name, k) for _, name, k in sorted(jobs)]


def _retry(fn, what: str, tries: int = 4):
    k = 0
    while True:
        try:
            return fn()
        except Exception as e:  # el Space puede estar en cola, dormido o sin cuota
            msg = str(e).splitlines()[0][:200] if str(e) else type(e).__name__
            if "quota" in msg.lower():
                if not WAIT_QUOTA:
                    raise SystemExit(f"Cuota gratuita de ZeroGPU agotada ({what}). Vuelve a ejecutar más tarde.")
                print(f"  {what}: cuota agotada — espero 10 min", flush=True)
                time.sleep(600)
                continue
            k += 1
            if k == tries:
                raise
            print(f"  {what}: {msg} — reintento en {20 * k} s", flush=True)
            time.sleep(20 * k)


def _seed(name: str) -> int:
    return zlib.crc32(name.encode()) % 2_000_000_000


def make_still(name: str) -> Path:
    from gradio_client import Client
    prompt = SCENES[name][0]
    out = STILLS_DIR / f"{name}-{zlib.crc32(prompt.encode()):08x}.jpg"  # cambia si cambia el texto
    if out.exists():
        return out

    def run():
        client = Client(FLUX_SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
        img, _ = client.predict(prompt=prompt, seed=_seed(name), randomize_seed=False, width=864, height=1536,
                                num_inference_steps=4, api_name="/infer")
        return img["path"] if isinstance(img, dict) else img
    path = _retry(run, f"FLUX {name}")
    STILLS_DIR.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.open(path).convert("RGB").save(out, quality=93)
    return out


def _animate(image: Path, name: str, k: int) -> Path:
    """Anima `image` 5 s con Wan (el movimiento de la escena) y lo guarda como el trozo k de la toma."""
    from gradio_client import Client, handle_file
    out = seg_path(name, k)

    def run():
        client = Client(WAN_SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
        vid, _ = client.predict(input_image=handle_file(str(image)), prompt=SCENES[name][1], steps=6,
                                duration_seconds=CLIP_SECONDS, seed=_seed(name) + k, randomize_seed=False,
                                api_name="/generate_video")
        return vid["video"] if isinstance(vid, dict) else vid
    raw = _retry(run, f"Wan {out.stem}")
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")  # si se corta a medias, no queda un .mp4 roto
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", raw, "-t", str(CLIP_SECONDS), "-an",
                    "-vf", "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-f", "mp4", str(part)], check=True)
    part.replace(out)
    return out


def make_clip(name: str, k: int = 0) -> Path:
    """Trozo k de la toma: el inicio sale del fotograma de FLUX; cada continuación, del fotograma del trozo
    anterior que está OVERLAP fotogramas antes de su final (ahí la funde src/video.py)."""
    if k == 0:
        return _animate(make_still(name), name, 0)
    prev = seg_path(name, k - 1)
    idx = clip_frames(prev) - OVERLAP
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "inicio.png"
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(prev), "-vf", f"select=eq(n\\,{idx})",
                        "-frames:v", "1", str(frame)], check=True)
        if not frame.exists():
            raise RuntimeError(f"No se pudo extraer el fotograma {idx} de {prev.name}")
        return _animate(frame, name, k)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*",
                    help="escenas (mago-fogata-1) o continuaciones (mago-fogata-1c) a rehacer; por defecto, lo que falte")
    ap.add_argument("--stills", action="store_true", help="solo genera los fotogramas en output/stills/")
    ap.add_argument("--limit", type=int, help="como mucho N trozos (o fotogramas)")
    ap.add_argument("--wait", action="store_true", help="si se agota la cuota, espera y sigue (sin límite)")
    ap.add_argument("--missing", action="store_true", help="solo imprime cuántos trozos faltan")
    ap.add_argument("--list", action="store_true", help="lista las escenas y cuántos trozos tienen")
    args = ap.parse_args()
    global WAIT_QUOTA
    WAIT_QUOTA = args.wait
    if args.missing:
        print(sum(SEGMENTS - n_segments(n) for n in SCENES))
        return 0
    if args.list:
        for n in SCENES:
            k = n_segments(n)
            print("#" * k + "." * (SEGMENTS - k) + " " + n)
        return 0

    if args.stills:
        unknown = [n for n in args.names if n not in SCENES]
        if unknown:
            print(f"Escenas desconocidas: {', '.join(unknown)} (ver --list)")
            return 1
        names = args.names or list(SCENES)
        names = names[:args.limit] if args.limit else names
        for i, name in enumerate(names):
            print(f"[{i + 1}/{len(names)}] {name}: {make_still(name).name}", flush=True)
        return 0

    jobs = []  # (escena, trozo) pedidos a mano: se rehacen y se borran los trozos que venían detrás
    for arg in args.names:
        if arg in SCENES:
            jobs.append((arg, 0))
        elif arg[:-1] in SCENES and arg[-1] in CONTINUATIONS:
            jobs.append((arg[:-1], CONTINUATIONS.index(arg[-1]) + 1))
        else:
            print(f"Escena desconocida: {arg} (ver --list)")
            return 1
    done = 0
    while not args.limit or done < args.limit:
        if args.names:
            if not jobs:
                break
            name, k = jobs.pop(0)
            if k > n_segments(name):
                print(f"{seg_name(name, k)}: falta el trozo anterior ({seg_name(name, k - 1)})")
                return 1
        else:
            todo = pending()
            if not todo:
                print("Biblioteca completa.")
                break
            name, k = todo[0]
        t = time.time()
        print(f"[{done + 1}] {seg_name(name, k)}: generando…", flush=True)
        print(f"  -> {make_clip(name, k).relative_to(ROOT)} ({time.time() - t:.0f} s)", flush=True)
        for j in range(k + 1, SEGMENTS):  # rehecho a mano: los trozos que venían detrás ya no encajan
            seg_path(name, j).unlink(missing_ok=True)
        done += 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
