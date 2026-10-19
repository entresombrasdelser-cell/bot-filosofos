"""Registro de frases publicadas (published.json)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"published": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def published_ids(state: dict) -> set[str]:
    return {p["id"] for p in state["published"]}


def last_published_date(state: dict) -> date | None:
    if not state["published"]:
        return None
    return date.fromisoformat(state["published"][-1]["date"])


def record(path: Path, state: dict, quote_id: str, autor: str, day: date, media_id: str) -> None:
    state["published"].append(
        {"id": quote_id, "date": day.isoformat(), "autor": autor, "media_id": media_id}
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")
