# Bot de frases de filósofos para Instagram

Publica una imagen (1080×1350) con una frase de `frases.csv` **cada 2 días a las 22:00**, gratis:
GitHub Actions (repo público = minutos ilimitados) + imagen alojada en el propio repo + API oficial de Instagram.

## Cómo funciona
1. Cada hora entre 00 y 06 UTC se lanza el workflow; solo continúa si en `BOT_TZ` son las 22:00 o más.
2. `bot.py` comprueba en `published.json` si han pasado ≥ 2 días desde la última publicación.
3. Elige una frase aún no publicada, genera la imagen (6 estilos que rotan) y la sube a `images/`.
4. Espera a que `raw.githubusercontent.com` la sirva y publica con la API de Instagram.
5. Registra la frase en `published.json` (no se repite) y borra imágenes antiguas.

## Probar sin publicar
```bash
pip install -r requirements.txt
python bot.py --dry-run               # crea output/AAAA-MM-DD.jpg
python bot.py --dry-run --style 3     # fuerza un estilo (0-5)
python bot.py --dry-run --date 2026-12-01
```
En GitHub: pestaña **Actions → Publicar frase en Instagram → Run workflow** con *dry_run* marcado;
la imagen se descarga como artefacto `imagen-prueba`.

## Configuración paso a paso

### A. Repositorio (gratis)
1. Crea en GitHub un repositorio **público** y sube esta carpeta (`git init`, `git add .`, `git commit`, `git push`).
   Debe ser público: Instagram descarga la imagen desde `raw.githubusercontent.com`.
2. **Settings → Actions → General → Workflow permissions → Read and write permissions** → Save.

### B. App de Meta (Instagram Login)
Tu cuenta debe ser **profesional** (Instagram → Configuración → Tipo de cuenta → Cambiar a profesional; Creador o Empresa). No hace falta página de Facebook.
1. Entra en <https://developers.facebook.com/> con tu cuenta de Facebook y acepta ser desarrollador.
2. **Mis apps → Crear app**. Nombre libre; en casos de uso elige **Otro** y tipo **Empresa** (Business).
3. En el panel de la app: **Añadir producto → Instagram → Configurar** y abre **API setup with Instagram login**.
4. **Roles → Roles → Añadir personas → Instagram Testers**: añade tu cuenta de Instagram. Luego, en Instagram (web) ve a
   *Configuración → Apps y sitios web → Invitaciones de evaluador* y **acepta**.
5. Vuelve a *API setup with Instagram login* → paso **Generate access tokens** → junto a tu cuenta, **Generate token**,
   inicia sesión y acepta los permisos `instagram_business_basic` e `instagram_business_content_publish`.
   Copia el token (dura 60 días). Anota también el **Instagram account ID** que aparece junto a la cuenta (opcional).
6. Con la app en modo *Desarrollo* y tu cuenta como tester **puedes publicar en tu propia cuenta sin App Review**.

### C. Secretos en GitHub
**Settings → Secrets and variables → Actions → New repository secret**:
| Nombre | Valor |
|---|---|
| `IG_ACCESS_TOKEN` | el token del paso B.5 |
| `IG_USER_ID` | *(opcional)* el ID de la cuenta; si falta, el bot lo consulta con `/me` |

Pestaña **Variables** (opcional): `BOT_TZ` = tu zona horaria (por defecto `America/Santiago`; p. ej. `America/Mexico_City`, `America/Argentina/Buenos_Aires`).
El token nunca se escribe en el código ni se imprime en los logs.

### D. Primera prueba real
1. Ejecuta el workflow manualmente con *dry_run* **desmarcado** y *force* marcado: publica una frase ya.
2. A partir de ahí se ejecuta solo cada 2 días a las 22:00.

## Mantenimiento
- **Token:** en cada publicación el bot lo renueva (`refresh_access_token`), lo que extiende su validez otros 60 días;
  si el token devuelto fuese distinto, el log avisa de que debes actualizar el secreto. Si pasas más de 60 días sin
  publicar, hay que generar uno nuevo (paso B.5).
- **Frases:** añade filas a `frases.csv` (`frase,autor,fuente`). Si se agotan, el workflow falla con un mensaje claro.
- **Horario:** GitHub puede retrasar los cron unos minutos; el margen 22:00–23:59 lo absorbe.
  Si el cron llega después de medianoche local, se publica al día siguiente.
- **Fuentes:** el workflow instala EB Garamond y similares. Para usar otras, copia `.ttf/.otf` en `fonts/` y añádelas a `FAMILIES` en `src/render.py`.
- GitHub desactiva los workflows tras 60 días sin actividad del repo; como el bot hace commits cada 2 días, no ocurre.
