# Bot de frases de filósofos para Instagram (Reels)

Publica un **Reel de 30 s** (1080×1920) con una frase de `frases.csv` **cada 2 días a las 22:00**, gratis:
GitHub Actions (repo público = minutos ilimitados) + API oficial de Instagram (Instagram Login).

- **Escena según el tema de la frase** (columna `tema` del CSV):
  `reflexion` → caballero a caballo (grabado de Dürer, 1513) · `espiritual` → mago/alquimista (grabado de Rembrandt, c. 1652).
- Frase que aparece línea a línea, autor y fuente, partículas y niebla, grano de película y música rock original.
- Imágenes de `assets/`: dominio público (CC0), de la National Gallery of Art vía Wikimedia Commons.
- Música: **original y sintetizada por código** (`src/music.py`), sin derechos de terceros.

## Cómo funciona
1. El workflow `daily.yml` se lanza cada hora entre 00 y 06 UTC; solo continúa si en `BOT_TZ` son las 22:00 o más.
2. `bot.py` comprueba en `published.json` si han pasado ≥ 2 días desde la última publicación.
3. Elige una frase aún no publicada, renderiza el video (~2 min) y lo sube a la rama **`media`**
   (rama huérfana que se reemplaza en cada publicación: el repo no crece).
4. Instagram descarga el video desde `raw.githubusercontent.com`, lo procesa, y se publica el Reel.
5. Se registra la frase en `published.json` (no se repite).

## Probar sin publicar
```bash
pip install -r requirements.txt
python bot.py --dry-run                      # output/AAAA-MM-DD.mp4
python bot.py --dry-run --theme espiritual   # fuerza la escena del mago
python bot.py --dry-run --format image       # solo la imagen 1080x1350
```
**Preflight en GitHub** (Actions → *Preflight (no publica)* → Run workflow): renderiza, aloja el video y deja que
Instagram lo procese como borrador (contenedor sin publicar). Confirma que el token, el alojamiento y el formato
del video funcionan **sin publicar nada**.

## Configuración
Consulta la guía de Meta: crear app → caso de uso *Administrar mensajes y contenido en Instagram* → permisos
`instagram_business_basic` + `instagram_business_content_publish` → añadir la cuenta como **Evaluador de Instagram**
(y aceptar la invitación en Instagram → Apps y sitios web → Invitaciones para evaluadores) → **Generar token**.

Secretos en GitHub (**Settings → Secrets and variables → Actions**):
| Nombre | Valor |
|---|---|
| `IG_ACCESS_TOKEN` | token de Instagram (dura 60 días; el bot lo renueva en cada publicación) |
| `IG_USER_ID` | *(opcional)* ID de la cuenta; si falta se consulta con `/me` |

Variable opcional `BOT_TZ` (por defecto `America/Santiago`). **Settings → Actions → General → Workflow permissions:
Read and write.**

## Frases y temas
`frases.csv`: columnas `frase, autor, fuente, tema`. `python tools/tag_quotes.py` rellena los temas vacíos
(autores místicos y palabras clave → `espiritual`; el resto → `reflexion`). Puedes corregir cualquier fila a mano.

## Mantenimiento
- Si pasas más de 60 días sin publicar el token caduca: genera uno nuevo y actualiza `IG_ACCESS_TOKEN`.
- GitHub puede retrasar los cron unos minutos; el margen 22:00–23:59 lo absorbe.
- GitHub desactiva los workflows tras 60 días sin actividad; el bot hace commits cada 2 días, así que no ocurre.
