"""Genera la biblioteca de clips de fondo (assets/clips/*.mp4): un caballero y un mago en escenas
medievales de estilo cinematográfico.

Todo gratis y sin clave: dos Spaces públicos de Hugging Face (ZeroGPU).
    1. FLUX.1-schnell  -> fotograma 864x1536 a partir del texto de la escena
    2. Wan 2.2 (I2V)    -> lo anima 5 s (480x832, 16 fps)
    3. ffmpeg           -> interpolación de movimiento a 30 fps, recorte exacto a 5 s

Uso (solo hace falta una vez; los clips quedan en el repo):
    pip install gradio_client
    python tools/make_clips.py               # genera los que falten
    python tools/make_clips.py nieve puente  # rehace esas escenas (borra output/stills/<escena>.png
                                            # para cambiar también el fotograma)
    python tools/make_clips.py --stills      # solo los fotogramas, para revisarlos antes
    python tools/make_clips.py --wait        # si se agota la cuota, espera y sigue

La cuota gratuita de ZeroGPU es limitada: si se agota, espera un rato y vuelve a ejecutar
(retoma donde lo dejó). Con una cuenta gratis de Hugging Face, `HF_TOKEN=...` da más cuota.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.video import CLIP_SECONDS, CLIPS_DIR, ffmpeg_exe  # noqa: E402

STILLS_DIR = ROOT / "output" / "stills"
FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
WAN_SPACE = "zerogpu-aoti/wan2-2-fp8da-aoti-faster"

STYLE = ("cinematic film still, photorealistic, epic dark fantasy, anamorphic 35mm, shallow depth of field, "
         "volumetric light, muted desaturated colors, film grain, vertical composition, the characters in the "
         "lower half of the frame, wide open sky or dark empty space in the upper half")
KNIGHT = "a medieval knight in battered steel plate armor and a dark fur cloak"
WIZARD = "an old bearded wizard in a long hooded grey robe holding a wooden staff"

# nombre -> (escena para FLUX, movimiento para Wan)
SCENES = {
    "nieve": (f"{KNIGHT} and {WIZARD} walking side by side across a snowy battlefield at dusk, a vast army "
              "with tattered banners behind them in the mist, falling snow, warm sunset rim light",
              "they walk slowly toward the camera through the snow, snow falling, cloaks and banners waving "
              "in the wind, breath vapor"),
    "bosque": (f"{KNIGHT} and {WIZARD} walking through an ancient misty forest of giant trees, shafts of "
               "pale morning light through the fog",
               "they walk slowly forward, mist drifting between the trees, slow dolly in"),
    "hoguera": (f"{KNIGHT} sitting by a campfire and {WIZARD} standing beside him at night, snowy mountains "
                "and a sky full of stars",
                "the fire flickers, embers rise into the night, the wizard's staff glows softly, gentle push in"),
    "castillo": (f"{KNIGHT} and {WIZARD} standing before the massive iron gates of a dark castle on a stormy "
                 "evening, burning torches on the walls, rain",
                 "torches flicker, rain falls, cloaks move in the wind, slow push in"),
    "acantilado": (f"{KNIGHT} and {WIZARD} seen from behind, standing on a cliff edge above a vast valley "
                   "with a distant castle at sunrise, sea of clouds",
                   "cloaks wave in the wind, clouds drift through the valley, slow push forward"),
    "ruinas": (f"{KNIGHT} and {WIZARD} walking through the burning ruins of a medieval village at night, "
               "glowing embers in the air, smoke",
               "they walk forward, embers float, flames flicker, smoke drifts"),
    "paso": (f"{KNIGHT} riding a black warhorse and {WIZARD} walking beside him along a snowy mountain pass "
             "in a blizzard",
             "the horse walks forward, snow blows sideways in the wind, cloaks whip"),
    "runas": (f"{WIZARD} casting a spell of glowing blue runes in the air while {KNIGHT} raises his shield to "
              "guard him, inside an ancient stone temple in darkness",
              "the runes glow and slowly swirl, blue light pulses on the armor, dust floats"),
    "lago": (f"{KNIGHT} kneeling with his sword planted in the ground beside {WIZARD}, on the shore of a "
             "misty lake at dawn, mountains in the distance",
             "mist drifts over the water, gentle ripples, soft light rising, very slow push in"),
    "tormenta": (f"{KNIGHT} and {WIZARD} standing on a hill under a dark stormy sky with lightning, a great "
                 "army camped in the plain below",
                 "lightning flashes in the clouds, cloaks whip in the strong wind, grass waves"),
    "torre": (f"{WIZARD} reading an ancient glowing book by candlelight in a stone tower library, {KNIGHT} "
              "standing guard by the arched window, night",
              "candle flames flicker, dust motes float in the light, the book glows softly"),
    "puente": (f"{KNIGHT} and {WIZARD} crossing an old stone bridge over a deep gorge in thick fog",
               "they walk forward across the bridge, fog flows through the gorge, slow dolly"),
    "catedral": (f"{KNIGHT} and {WIZARD} standing in a ruined gothic cathedral, beams of light through the "
                 "broken stained glass windows, snow falling inside",
                 "light rays shimmer, snow falls slowly, slow dolly forward"),
    "jinetes": (f"{KNIGHT} on a black warhorse and {WIZARD} on a white horse leading an army across a snowy "
                "plain, banners in the wind, overcast sky",
                "the horses walk toward the camera, banners wave, snow falls"),
    "luna": (f"silhouettes of {KNIGHT} and {WIZARD} on a rocky ridge under a huge full moon, night mist "
             "in the valley",
             "mist moves slowly, cloaks wave, the moonlight shimmers, slow push in"),
    "otono": (f"{KNIGHT} and {WIZARD} walking along a forest road with golden autumn leaves falling, "
              "golden hour light",
              "they walk forward, leaves fall and drift, warm light flickers through the trees"),
    "baston": (f"{WIZARD} raising his glowing staff in the dark, its white light illuminating the helmet of "
               f"{KNIGHT} beside him, night, falling snow",
               "the staff light grows brighter, snow falls through the light, slow push in"),
    "guardia": (f"{KNIGHT} with his sword drawn and {WIZARD} with his staff raised, back to back on a foggy "
                "battlefield in the snow, ready for battle",
                "snow falls, fog drifts, breath vapor, slow orbit around them"),
}


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


def make_still(name: str, seed: int) -> Path:
    from gradio_client import Client
    out = STILLS_DIR / f"{name}.png"
    if out.exists():
        return out
    prompt = f"{SCENES[name][0]}, {STYLE}"

    def run():
        client = Client(FLUX_SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
        img, _ = client.predict(prompt=prompt, seed=seed, randomize_seed=False, width=864, height=1536,
                                num_inference_steps=4, api_name="/infer")
        return img["path"] if isinstance(img, dict) else img
    path = _retry(run, f"FLUX {name}")
    STILLS_DIR.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.open(path).convert("RGB").save(out)
    return out


def make_clip(name: str, seed: int) -> Path:
    from gradio_client import Client, handle_file
    out = CLIPS_DIR / f"{name}.mp4"
    still = make_still(name, seed)

    def run():
        client = Client(WAN_SPACE, token=os.environ.get("HF_TOKEN") or None, verbose=False)
        vid, _ = client.predict(input_image=handle_file(str(still)), prompt=SCENES[name][1], steps=6,
                                duration_seconds=CLIP_SECONDS, seed=seed, randomize_seed=False,
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
    ap.add_argument("--wait", action="store_true", help="si se agota la cuota, espera y sigue (sin límite)")
    args = ap.parse_args()
    global WAIT_QUOTA
    WAIT_QUOTA = args.wait
    unknown = [n for n in args.names if n not in SCENES]
    if unknown:
        print(f"Escenas desconocidas: {', '.join(unknown)}. Disponibles: {', '.join(SCENES)}")
        return 1
    names = args.names or list(SCENES)
    for i, name in enumerate(names):
        seed = 1000 + list(SCENES).index(name)
        if args.stills:
            print(f"[{i + 1}/{len(names)}] {name}: {make_still(name, seed)}", flush=True)
        elif (CLIPS_DIR / f"{name}.mp4").exists() and not args.names:
            print(f"[{i + 1}/{len(names)}] {name}: ya existe", flush=True)
        else:
            t = time.time()
            print(f"[{i + 1}/{len(names)}] {name}: generando…", flush=True)
            print(f"  -> {make_clip(name, seed).relative_to(ROOT)} ({time.time() - t:.0f} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
