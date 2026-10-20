"""Envío del borrador (video + descripción) a un chat de Telegram con la API de bots (gratis).

Instagram no permite que una app deje borradores en la cuenta, así que el bot manda el video al
teléfono: desde Telegram se comparte a Instagram, se añade la música y se pega la descripción.
"""
from __future__ import annotations

import html
import tempfile
from pathlib import Path

import requests
from PIL import Image

from .video import render_poster

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, **kwargs) -> dict:
    try:
        resp = requests.post(API.format(token=token, method=method), timeout=300, **kwargs)
    except requests.RequestException as e:  # el mensaje incluye la URL, que lleva el token
        raise TelegramError(f"Telegram {method}: {str(e).replace(token, '***')}") from None
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not data.get("ok"):
        desc = data.get("description", resp.text[:300]).replace(token, "***")
        raise TelegramError(f"Telegram {method} falló ({resp.status_code}): {desc}")
    return data["result"]


def send_draft(token: str, chat_id: str, video: Path, title: str, caption: str, duration: int) -> None:
    """Manda el video (con miniatura de un fotograma con la frase) y, aparte, la descripción en un
    bloque que se copia con un toque."""
    with tempfile.TemporaryDirectory() as tmp:
        thumb = Path(tmp) / "thumb.jpg"
        render_poster(video, thumb)
        Image.open(thumb).resize((180, 320), Image.LANCZOS).save(thumb, quality=85)
        with open(video, "rb") as v, open(thumb, "rb") as t:
            _call(token, "sendVideo",
                  data={"chat_id": chat_id, "caption": title, "duration": duration,
                        "width": 1080, "height": 1920, "supports_streaming": "true"},
                  files={"video": (video.name, v, "video/mp4"), "thumbnail": ("thumb.jpg", t, "image/jpeg")})
    _call(token, "sendMessage",
          json={"chat_id": chat_id, "parse_mode": "HTML", "text": f"<pre>{html.escape(caption)}</pre>"})
