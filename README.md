# Bot de frases de filósofos para Instagram (Reels)

Prepara **cada día a las 22:00** un **Reel de 30 s** (1080×1920) con una frase de `frases.csv` y te lo manda
**como borrador a Telegram**, con la descripción lista para copiar. Tú lo compartes a Instagram, eliges la música
y publicas. Todo gratis: GitHub Actions (repo público = minutos ilimitados) + bot de Telegram.

> Instagram no permite que una app deje borradores dentro de la cuenta (su API solo publica al instante y no
> puede añadir música de su biblioteca); por eso el borrador llega a Telegram.

- **Escenas cinematográficas de un caballero y un mago** (nieve, bosques, ruinas, castillos…): clips de 5 s de
  `assets/clips/`, encadenados con fundidos (7 por video, en orden distinto cada día).
- Frase que aparece línea a línea en el tercio superior, autor y fuente, viñeta y grano de película.
- **Sin audio**: la música se añade al subirlo en Instagram. El color del texto depende del `tema` de la frase
  (`reflexion` → cálido, `espiritual` → frío).

## Cómo funciona
1. El workflow `daily.yml` se lanza cada hora entre 00 y 06 UTC; solo continúa si en `BOT_TZ` son las 22:00 o más.
2. `bot.py` comprueba en `published.json` si ya se mandó el borrador de hoy (1 por día).
3. Elige una frase aún no usada, renderiza el video (~2 min) y lo manda a Telegram: el video (con miniatura) y,
   aparte, la descripción en un bloque que se copia con un toque.
4. Se registra la frase en `published.json` (no se repite).

**En el móvil:** abre el video en Telegram → Compartir → Instagram (Reels) → añade la música → pega la descripción.

## Configuración de Telegram (una vez)
1. En Telegram, abre **@BotFather** → `/newbot` → elige nombre y usuario → copia el **token**.
2. Abre tu bot nuevo y pulsa **Iniciar** (sin esto el bot no puede escribirte).
3. Abre **@userinfobot** y copia tu **Id** (un número).
4. En GitHub (**Settings → Secrets and variables → Actions → New repository secret**):

| Nombre | Valor |
|---|---|
| `TELEGRAM_BOT_TOKEN` | el token de @BotFather |
| `TELEGRAM_CHAT_ID` | tu Id de @userinfobot |

Variable opcional `BOT_TZ` (por defecto `America/Santiago`). **Settings → Actions → General → Workflow permissions:
Read and write.**

Para probar: **Actions → Borrador diario (Telegram) → Run workflow**, desmarcando *Solo generar el video* (y marcando
*Enviar aunque ya se haya mandado* si hoy ya llegó uno).

## Probar en local
```bash
pip install -r requirements.txt
python bot.py --dry-run                      # output/AAAA-MM-DD.mp4, sin enviar ni registrar
python bot.py --dry-run --theme espiritual   # fuerza una frase espiritual
python bot.py --dry-run --format image       # solo la imagen 1080x1350
```

## Biblioteca de clips
`tools/make_clips.py` genera los clips gratis con dos Spaces públicos de Hugging Face: **FLUX.1-schnell** crea el
fotograma de cada escena y **Wan 2.2** lo anima 5 s; ffmpeg lo interpola a 30 fps. Las escenas (texto de cada una)
están en `SCENES` dentro del script: añade o cambia las que quieras.
```bash
pip install gradio_client
python tools/make_clips.py --stills    # solo los fotogramas (output/stills/), para revisarlos
python tools/make_clips.py --wait      # genera los clips que falten; si se agota la cuota, espera y sigue
python tools/make_clips.py nieve       # rehace una escena
```
La cuota gratuita de GPU de Hugging Face es pequeña (unos pocos clips seguidos y luego hay que esperar a que se
recargue); con una cuenta gratis y `HF_TOKEN=...` da algo más.

## Frases y temas
`frases.csv`: columnas `frase, autor, fuente, tema`. `python tools/tag_quotes.py` rellena los temas vacíos
(autores místicos y palabras clave → `espiritual`; el resto → `reflexion`). Puedes corregir cualquier fila a mano.

## Publicación directa (opcional, no se usa a diario)
`python bot.py --publish` publica en Instagram con música rock original sintetizada (`src/music.py`), alojando el
video en la rama `media`. Necesita el secreto `IG_ACCESS_TOKEN` (app de Meta con `instagram_business_content_publish`).
El workflow *Preflight (no publica)* comprueba ese camino sin publicar nada.

## Mantenimiento
- GitHub puede retrasar los cron unos minutos; el margen 22:00–23:59 lo absorbe.
- GitHub desactiva los workflows tras 60 días sin actividad; el bot hace commits cada día, así que no ocurre.
