"""Genera la biblioteca de clips de fondo (assets/clips/*.mp4): el caballero de armadura negra con su
gato acorazado y el mago de túnica negra con su gato negro, en escenas medievales nocturnas.

Cada clip se llama <personaje>-<escena>-<n>.mp4:
    personaje: caballero, mago o ambos
    escena:    combate, demonios, asedio, fogata, heridos, camino, vigilia (ver ESCENAS en src/video.py)

Todo gratis y sin clave: dos Spaces públicos de Hugging Face (ZeroGPU).
    1. FLUX.1-schnell  -> fotograma 864x1536 a partir del texto de la escena
    2. Wan 2.2 (I2V)    -> lo anima 5 s (480x832, 16 fps)
    3. ffmpeg           -> interpolación de movimiento a 30 fps, recorte exacto a 5 s

Uso:
    pip install gradio_client
    python tools/make_clips.py                       # genera los que falten (primero una variante de cada)
    python tools/make_clips.py mago-fogata-1         # rehace esa escena
    python tools/make_clips.py --stills --limit 4    # solo fotogramas (output/stills/), para revisarlos
    python tools/make_clips.py --wait                # si se agota la cuota, espera y sigue
    python tools/make_clips.py --list                # lista todas las escenas

La cuota gratuita de ZeroGPU da para ~1 clip por vez; el workflow `clips.yml` completa la biblioteca
desde GitHub. Si cambias el texto de una escena, el fotograma se regenera solo (su nombre lleva un hash
del texto); para rehacer el clip, bórralo de assets/clips/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.video import CLIP_SECONDS, CLIPS_DIR, ESCENAS, PERSONAJES, ffmpeg_exe  # noqa: E402

STILLS_DIR = ROOT / "output" / "stills"
FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
WAN_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"

STYLE = ("cinematic film still, photorealistic, dark medieval fantasy, at night, anamorphic 35mm, "
         "shallow depth of field, volumetric light, muted colors, film grain, vertical composition, "
         "the characters in the lower half of the frame, dark night sky or darkness in the upper half")
K = "a knight in black plate armor and a long black cape holding a longsword"
KC = "his black cat wearing tiny black plate armor and a small helmet"
W = ("a wizard in a long black hooded robe with a long grey beard holding a gnarled wooden staff "
     "topped with a glowing crystal")
WC = "his black cat with glowing golden eyes"
CATS = "their two black cats, one wearing tiny black armor"

# escena -> personaje -> (acción para FLUX, movimiento para Wan), y "lugares": un clip por lugar
# ("ambos" usa solo los dos primeros lugares: aparecen juntos con menos frecuencia)
CATALOGO = {
    "combate": {
        "caballero": (f"{K}, swinging his sword in fierce combat against enemy soldiers, {KC} charging "
                      "into the fight beside him",
                      "fierce sword fight, the knight strikes, sparks fly, enemies charge, embers and rain, "
                      "dynamic camera"),
        "mago": (f"{W}, blasting enemy soldiers with lightning from his staff, {WC} hissing beside him "
                 "with its back arched",
                 "lightning bursts from the staff, enemies are thrown back, sparks and embers fly, dynamic camera"),
        "ambos": (f"{K} and {W} fighting back to back against enemy soldiers, the knight with his sword and "
                  f"the wizard casting fire, {CATS} beside them",
                  "fierce battle, sword strikes and bursts of fire, sparks and embers fly, dynamic camera"),
        "lugares": ["on a muddy battlefield lit by burning fires", "on an old stone bridge in the rain",
                    "in the burning streets of a medieval village"],
    },
    "demonios": {
        "caballero": (f"{K}, fighting a huge horned demon of fire with his sword, {KC} snarling beside him",
                      "the knight swings his sword at the roaring demon, fire and embers swirl, dramatic camera"),
        "mago": (f"{W}, holding back a huge horned demon of shadow and fire with a shield of blue light "
                 f"from his staff, {WC} at his feet",
                 "blue magic light pulses against the demon's fire, the demon roars, sparks swirl"),
        "ambos": (f"{K} and {W} facing a giant horned demon of fire, the knight raising his sword and the "
                  f"wizard his glowing staff, {CATS} at their feet",
                  "fire and blue magic clash, the demon roars, embers swirl, dramatic camera"),
        "lugares": ["in the ruins of a burning cathedral", "at the mouth of a hellish cave glowing red",
                    "in a dead forest under a blood red moon"],
    },
    "asedio": {
        "caballero": (f"{K}, leading soldiers with siege ladders in an assault on the gates of a dark castle, "
                      f"{KC} at his side",
                      "the soldiers charge toward the castle, flaming arrows fly, fire and smoke rise, "
                      "epic camera push"),
        "mago": (f"{W}, hurling a huge fireball from his staff at the walls of a dark castle under siege, "
                 f"{WC} beside him",
                 "the fireball flies and explodes against the walls, fire and smoke rise, embers fly"),
        "ambos": (f"{K} and {W} leading an army to conquer a dark castle, siege towers and burning arrows, "
                  f"{CATS} with them",
                  "the army advances on the castle, flaming arrows fly, fire and smoke rise, epic camera push"),
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
        "caballero": (f"{K}, wounded and exhausted, kneeling on one knee and leaning on his sword, his black "
                      f"armor dented and bloodied, {KC} with a torn cloak beside him",
                      "heavy breathing, smoke drifts, embers float, the cape moves in the wind, slow push in"),
        "mago": (f"{W}, wounded and exhausted, leaning on his staff, his black robe torn and bloodied, "
                 f"{WC} limping beside him",
                 "heavy breathing, smoke drifts, embers float, the robe moves in the wind, slow push in"),
        "ambos": (f"{K} and {W} wounded after the battle, the wizard helping the knight to stand, {CATS} "
                  "beside them",
                  "they slowly stand up, smoke drifts, embers float, slow push in"),
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
                out[f"{pers}-{esc}-{n}"] = (f"{action}, {lugar}, {STYLE}", motion, (n, pi, ei))
    return dict(sorted(out.items(), key=lambda kv: kv[1][2]))


SCENES = _catalog()
WAIT_QUOTA = False  # --wait: en vez de salir, espera a que se recargue la cuota


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


def make_clip(name: str) -> Path:
    from gradio_client import Client, handle_file
    out = CLIPS_DIR / f"{name}.mp4"
    still = make_still(name)

    def run():
        client = Client(WAN_SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
        vid, _ = client.predict(input_image=handle_file(str(still)), prompt=SCENES[name][1], steps=6,
                                duration_seconds=CLIP_SECONDS, seed=_seed(name), randomize_seed=False,
                                api_name="/generate_video")
        return vid["video"] if isinstance(vid, dict) else vid
    raw = _retry(run, f"Wan {name}")
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")  # si se corta a medias, no queda un .mp4 roto
    subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-i", raw, "-t", str(CLIP_SECONDS), "-an",
                    "-vf", "minterpolate=fps=30:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-f", "mp4", str(part)], check=True)
    part.replace(out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="escenas a generar (por defecto, todas las que falten)")
    ap.add_argument("--stills", action="store_true", help="solo genera los fotogramas en output/stills/")
    ap.add_argument("--limit", type=int, help="como mucho N escenas")
    ap.add_argument("--wait", action="store_true", help="si se agota la cuota, espera y sigue (sin límite)")
    ap.add_argument("--missing", action="store_true", help="solo imprime cuántos clips faltan")
    ap.add_argument("--list", action="store_true", help="lista las escenas y si ya tienen clip")
    args = ap.parse_args()
    global WAIT_QUOTA
    WAIT_QUOTA = args.wait
    missing = [n for n in SCENES if not (CLIPS_DIR / f"{n}.mp4").exists()]
    if args.missing:
        print(len(missing))
        return 0
    if args.list:
        for n in SCENES:
            print(("  " if n in missing else "✓ ") + n)
        return 0
    unknown = [n for n in args.names if n not in SCENES]
    if unknown:
        print(f"Escenas desconocidas: {', '.join(unknown)} (ver --list)")
        return 1
    names = args.names or (list(SCENES) if args.stills else missing)
    names = names[:args.limit] if args.limit else names
    for i, name in enumerate(names):
        t = time.time()
        if args.stills:
            print(f"[{i + 1}/{len(names)}] {name}: {make_still(name).name}", flush=True)
        else:
            print(f"[{i + 1}/{len(names)}] {name}: generando…", flush=True)
            print(f"  -> {make_clip(name).relative_to(ROOT)} ({time.time() - t:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
