"""Bot que publica una frase de filósofo en Instagram.

Uso:
    python bot.py --dry-run                 # genera output/*.jpg sin publicar
    python bot.py --dry-run --style 3       # fuerza un estilo (0-5)
    python bot.py --dry-run --date 2026-11-02
    python bot.py                           # publica (si toca; ver --force)
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

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "frases.csv"
STATE_PATH = ROOT / "published.json"
INTERVAL_DAYS = 2
HASHTAGS = "#filosofía #frases #reflexión #pensamiento #sabiduría #citas"


def build_caption(q) -> str:
    parts = [f"“{q.frase}”", f"— {q.autor}" + (f", {q.fuente}" if q.fuente else "")]
    return "\n\n".join(parts) + "\n\n" + HASHTAGS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="solo genera la imagen en output/")
    ap.add_argument("--force", action="store_true", help="ignora el intervalo de %d días" % INTERVAL_DAYS)
    ap.add_argument("--style", type=int, help="fuerza el estilo (0-%d)" % (len(STYLES) - 1))
    ap.add_argument("--date", help="fecha AAAA-MM-DD (por defecto, hoy en BOT_TZ)")
    args = ap.parse_args()

    tz = ZoneInfo(os.environ.get("BOT_TZ", "America/Santiago"))
    today = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()

    quotes = load_quotes(CSV_PATH)
    state = st.load_state(STATE_PATH)

    if not args.dry_run and not args.force:
        last = st.last_published_date(state)
        if last and (today - last).days < INTERVAL_DAYS:
            print(f"Última publicación: {last}. Aún no toca (cada {INTERVAL_DAYS} días). Nada que hacer.")
            return 0

    quote = pick_quote(quotes, st.published_ids(state), today.toordinal())
    style_idx = args.style if args.style is not None else len(state["published"]) % len(STYLES)
    style_name = STYLES[style_idx % len(STYLES)]["name"]

    folder = "output" if args.dry_run else "images"
    out = Path(folder) / f"{today.isoformat()}.jpg"
    render_image(quote.frase, quote.autor, quote.fuente, style_idx, today.toordinal(), ROOT / out)
    print(f"Imagen generada: {out} (estilo {style_idx}: {style_name}) — {quote.autor}")

    if args.dry_run:
        print("Modo prueba: no se publica ni se registra nada.")
        return 0

    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        print("Falta el secreto IG_ACCESS_TOKEN.", file=sys.stderr)
        return 1

    publish.refresh_token(token)
    user_id = publish.resolve_user_id(token)
    url = publish.push_image(out)
    publish.wait_until_public(url)
    media_id = publish.publish_image(token, user_id, url, build_caption(quote))
    st.record(STATE_PATH, state, quote.id, quote.autor, today, media_id)
    print(f"Publicado en Instagram (media {media_id}).")

    for old in (ROOT / "images").glob("*.jpg"):  # solo conservamos la última
        if old.name != out.name:
            old.unlink()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except publish.PublishError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
