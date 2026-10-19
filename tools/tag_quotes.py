"""Añade/actualiza la columna `tema` de frases.csv.

tema = "espiritual"  -> escena del mago
tema = "reflexion"   -> escena del caballero a caballo

Regla: autores de tradición mística/espiritual + palabras clave. Solo rellena las filas
que no tienen tema, así que puedes corregir a mano el CSV y volver a ejecutarlo.
"""
import csv
import re
import sys
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "frases.csv"

SPIRITUAL_AUTHORS = {
    "George Ivanovich Gurdjieff", "Carl Gustav Jung", "Plotino", "Laozi", "Meister Eckhart",
    "Simone Weil", "San Agustín de Hipona", "Tomás de Aquino", "San Anselmo de Canterbury",
    "Pitágoras", "Heráclito", "Baruch Spinoza", "Blaise Pascal", "Antoine de Saint-Exupéry",
}
SPIRITUAL_WORDS = re.compile(
    r"\b(alma|almas|espíritu|espiritual|espirituales|dios|divin\w+|sagrad\w+|eterno|eterna|eternidad|"
    r"cosmos|universo|silencio|luz|conciencia|oración|rezar|infinito|misterio|despertar|"
    r"interior|ser\s+interior|trascend\w+|milagro|cielo|estrellas?)\b",
    re.IGNORECASE,
)


def tema(frase: str, autor: str) -> str:
    if autor in SPIRITUAL_AUTHORS or SPIRITUAL_WORDS.search(frase):
        return "espiritual"
    return "reflexion"


def main() -> int:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if "tema" not in fields:
        fields.append("tema")
    for r in rows:
        if not (r.get("tema") or "").strip():
            r["tema"] = tema(r["frase"], r["autor"])
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    n_e = sum(r["tema"] == "espiritual" for r in rows)
    print(f"{len(rows)} frases: {n_e} espiritual, {len(rows) - n_e} reflexion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
