"""Rellena las columnas `tema` y `escena` de frases.csv en las filas que las tengan vacías.

tema = "espiritual"  -> texto en tonos fríos; más probable que aparezca el mago
tema = "reflexion"   -> texto en tonos cálidos; más probable que aparezca el caballero

escena = contexto de los clips del video (ver ESCENAS en src/video.py):
    combate   lucha, fuerza, valor, guerra          demonios  sombra, mal, miedo, abismo
    asedio    conquista, poder, rebelión, ambición  fogata    amistad, amor, alegría, arte
    heridos   sufrimiento, dolor, pérdida, muerte   camino    búsqueda, soledad, tiempo, destino
    vigilia   alma, Dios, misterio, conciencia

Regla: autores de tradición mística/espiritual + palabras clave. Solo rellena lo vacío, así que
puedes corregir a mano el CSV y volver a ejecutarlo.
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

# la primera regla que encaje gana; si ninguna encaja -> "camino"
SCENE_WORDS = [(name, re.compile(rf"\b({words})\b", re.IGNORECASE)) for name, words in [
    ("demonios", r"demonio\w*|diablo\w*|infierno|monstruo\w*|abismo|sombra|maldad|mal|miedo\w*|temor|"
                 r"angustia|oscuridad|caos|locura|envidia|crueldad|mentira\w*"),
    ("heridos", r"sufr\w+|dolor\w*|herid\w+|muerte|morir|muere|perder|pérdida|desesperaci\w+|tormento|"
                r"derrota|cicatri\w+"),
    ("combate", r"lucha\w*|guerra|guerrero\w*|batalla|fuerza|fuerte|valor|valiente|venc\w+|enemig\w+|"
                r"combate|coraje|acción"),
    ("asedio", r"conquist\w+|poder|poderos\w+|rebeli\w+|revoluci\w+|ambici\w+|domin\w+|esclav\w+|"
               r"crea\w*|destru\w+"),
    ("fogata", r"amig\w+|amistad|amor|ama|amar|felicidad|feliz|música|arte|risa|alegría|niños?"),
    ("vigilia", r"alma|dios|divin\w+|espíritu|sagrad\w+|eterno|eternidad|fe|misterio|sueños?|conciencia|"
                r"infinito|oración"),
]]


def tema(frase: str, autor: str) -> str:
    if autor in SPIRITUAL_AUTHORS or SPIRITUAL_WORDS.search(frase):
        return "espiritual"
    return "reflexion"


def escena(frase: str) -> str:
    return next((name for name, rx in SCENE_WORDS if rx.search(frase)), "camino")


def main() -> int:
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    for col in ("tema", "escena"):
        if col not in fields:
            fields.append(col)
    for r in rows:
        if not (r.get("tema") or "").strip():
            r["tema"] = tema(r["frase"], r["autor"])
        if not (r.get("escena") or "").strip():
            r["escena"] = escena(r["frase"])
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    n_e = sum(r["tema"] == "espiritual" for r in rows)
    counts = {}
    for r in rows:
        counts[r["escena"]] = counts.get(r["escena"], 0) + 1
    print(f"{len(rows)} frases: {n_e} espiritual, {len(rows) - n_e} reflexion")
    print("escenas: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
