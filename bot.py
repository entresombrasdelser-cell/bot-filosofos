"""Bot que publica una frase de filósofo en Instagram (Reel de 30 s por defecto).

Uso:
    python bot.py --dry-run                    # genera output/*.mp4 sin publicar
    python bot.py --dry-run --theme espiritual # fuerza la escena del mago
    python bot.py --dry-run --format image     # solo la imagen 1080x1350
    python bot.py --dry-run --date 2026-11-02
    python bot.py                              # publica (si toca; ver --force)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src import publish, state as st
from src.quotes import load_quotes, pick_quote
from src.render import STYLES, render_image
from src.video import render_video

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "frases.csv"
STATE_PATH = ROOT / "published.json"
INTERVAL_DAYS = 1
HASHTAGS = "#filosofía #frases #reflexión #pensamiento #sabiduría #citas #reels"


def build_caption(q) -> str:
    parts = [f"“{q.frase}”", f"— {q.autor}" + (f", {q.fuente}" if q.fuente else "")]
    return "\n\n".join(parts) + "\n\n" + HASHTAGS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="solo genera el archivo en output/")
    ap.add_argument("--force", action="store_true", help="ignora el intervalo de %d días" % INTERVAL_DAYS)
    ap.add_argument("--preflight", action="store_true",
                    help="renderiza, aloja y deja que Instagram procese el video, pero NO publica")
    ap.add_argument("--format", choices=["video", "image"], default="video")
    ap.add_argument("--theme", choices=["reflexion", "espiritual"], help="fuerza la escena del video")
    ap.add_argument("--style", type=int, help="fuerza el estilo de imagen (0-%d)" % (len(STYLES) - 1))
    ap.add_argument("--date", help="fecha AAAA-MM-DD (por defecto, hoy en BOT_TZ)")
    args = ap.parse_args()

    tz = ZoneInfo(os.environ.get("BOT_TZ", "America/Santiago"))
    today = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()

    quotes = load_quotes(CSV_PATH)
    state = st.load_state(STATE_PATH)

    if not args.dry_run and not args.force and not args.preflight:
        last = st.last_published_date(state)
        if last and (today - last).days < INTERVAL_DAYS:
            print(f"Última publicación: {last}. Aún no toca (cada {INTERVAL_DAYS} días). Nada que hacer.")
            return 0

    pool = [q for q in quotes if not args.theme or q.tema == args.theme]
    quote = pick_quote(pool, st.published_ids(state), today.toordinal())

    folder = "output" if args.dry_run else "media"
    ext = "mp4" if args.format == "video" else "jpg"
    out = Path(folder) / f"{today.isoformat()}.{ext}"
    if args.format == "video":
        print(f"Generando video ({quote.tema})… puede tardar un par de minutos")
        render_video(quote.frase, quote.autor, quote.fuente, quote.tema, today.toordinal(), ROOT / out)
        print(f"Video generado: {out} — {quote.autor} [{quote.tema}]")
    else:
        style_idx = args.style if args.style is not None else len(state["published"]) % len(STYLES)
        render_image(quote.frase, quote.autor, quote.fuente, style_idx, today.toordinal(), ROOT / out)
        print(f"Imagen generada: {out} (estilo {style_idx}) — {quote.autor}")

    if args.dry_run:
        print("Modo prueba: no se publica ni se registra nada.")
        return 0

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        print("Falta el secreto IG_ACCESS_TOKEN.", file=sys.stderr)
        return 1

    info = publish.account_info(token)
    print(f"Cuenta de Instagram: @{info.get('username')} (tipo {info.get('account_type', '?')})")
    user_id = publish.resolve_user_id(token)
    url = publish.host_file(out)
    meta = publish.wait_until_public(url)
    print(f"Archivo público: {meta['bytes'] / 1e6:.1f} MB, Content-Type: {meta['content_type']}")

    if args.preflight:  # todo menos publicar: Instagram procesa el video como borrador
        container = publish.create_container(token, user_id, publish.reel_fields(url, build_caption(quote)))
        print(f"Contenedor creado ({container}); esperando a que Instagram procese el video…")
        publish.wait_container(token, container, tries=90)
        print("PREFLIGHT OK: Instagram aceptó y procesó el video. No se ha publicado nada.")
        return 0

    publish.refresh_token(token)
    if args.format == "video":
        media_id = publish.publish_reel(token, user_id, url, build_caption(quote))
    else:
        media_id = publish.publish_image(token, user_id, url, build_caption(quote))
    st.record(STATE_PATH, state, quote.id, quote.autor, today, media_id)
    print(f"Publicado en Instagram (media {media_id}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except publish.PublishError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
