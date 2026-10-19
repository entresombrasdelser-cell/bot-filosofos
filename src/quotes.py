"""Lectura de frases.csv y elección de una frase no publicada."""
from __future__ import annotations

import csv
import hashlib
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Quote:
    id: str
    frase: str
    autor: str
    fuente: str
    tema: str = "reflexion"


def quote_id(frase: str) -> str:
    norm = " ".join(frase.lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def load_quotes(path: Path) -> list[Quote]:
    """Lee el CSV (columnas frase, autor, fuente). Descarta vacías y duplicadas."""
    quotes: list[Quote] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            frase = row.get("frase", "")
            if not frase:
                continue
            qid = quote_id(frase)
            if qid in seen:
                continue
            seen.add(qid)
            tema = row.get("tema", "") or "reflexion"
            quotes.append(Quote(qid, frase, row.get("autor", ""), row.get("fuente", ""), tema))
    return quotes


def pick_quote(quotes: list[Quote], published_ids: set[str], seed: int) -> Quote:
    pending = [q for q in quotes if q.id not in published_ids]
    if not pending:
        raise RuntimeError(
            "No quedan frases sin publicar. Añade más filas a frases.csv "
            "(o vacía published.json para empezar otra vuelta)."
        )
    return random.Random(seed).choice(pending)
