"""Alojamiento público del archivo (rama `media` del repo) y publicación con la API de Instagram
(Instagram Login)."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
GRAPH = f"https://graph.instagram.com/{API_VERSION}"
MEDIA_BRANCH = "media"


class PublishError(RuntimeError):
    pass


def _scrub(text: str) -> str:
    """Quita tokens de cualquier texto que vayamos a imprimir."""
    for key in ("IG_ACCESS_TOKEN", "GITHUB_TOKEN"):
        val = os.environ.get(key, "").strip()
        if val:
            text = text.replace(val, "***")
    return text


def _check(resp: requests.Response, what: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok or "error" in data:
        err = data.get("error", {})
        raise PublishError(f"{what} falló ({resp.status_code}): {_scrub(err.get('message', resp.text[:300]))}")
    return data


# ---------------------------------------------------------------- hosting

def host_file(path: Path) -> str:
    """Sube `path` a la rama huérfana `media` (se reemplaza en cada publicación, así el repo no crece)
    y devuelve su URL pública en raw.githubusercontent.com."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repo or not token:
        raise PublishError("Faltan GITHUB_REPOSITORY / GITHUB_TOKEN: ejecútalo desde GitHub Actions.")
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()

    def git(*args: str, cwd: str) -> None:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        if r.returncode != 0:
            raise PublishError(f"git {args[0]} falló: {_scrub(r.stderr.strip())[:400]}")

    with tempfile.TemporaryDirectory() as d:
        shutil.copy(path, Path(d) / path.name)
        git("init", "-q", "-b", MEDIA_BRANCH, cwd=d)
        git("config", "user.name", "github-actions[bot]", cwd=d)
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=d)
        git("add", path.name, cwd=d)
        git("commit", "-q", "-m", f"media {path.name}", cwd=d)
        git("-c", f"http.extraheader=AUTHORIZATION: basic {auth}", "push", "--force",
            f"https://github.com/{repo}.git", f"HEAD:refs/heads/{MEDIA_BRANCH}", cwd=d)
    return f"https://raw.githubusercontent.com/{repo}/{MEDIA_BRANCH}/{path.name}"


def wait_until_public(url: str, timeout: int = 180) -> dict:
    """Espera a que la URL responda 200 y devuelve {'content_type', 'bytes'}."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.head(url, timeout=15, allow_redirects=True)
            if r.status_code == 200:
                return {"content_type": r.headers.get("Content-Type", "?"),
                        "bytes": int(r.headers.get("Content-Length", 0))}
        except requests.RequestException:
            pass
        time.sleep(5)
    raise PublishError(f"El archivo no es accesible públicamente: {url} (¿repo público?)")


# ---------------------------------------------------------------- Instagram

def account_info(token: str) -> dict:
    return _check(requests.get(f"{GRAPH}/me", params={
        "fields": "user_id,username,account_type", "access_token": token}, timeout=30), "Consultar la cuenta")


def resolve_user_id(token: str) -> str:
    explicit = os.environ.get("IG_USER_ID", "").strip()
    if explicit:
        return explicit
    data = account_info(token)
    return str(data.get("user_id") or data["id"])


def refresh_token(token: str) -> None:
    """Renueva (best-effort) el token de larga duración para que no caduque."""
    try:
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": token}, timeout=30)
        data = r.json()
        if r.ok and "access_token" in data:
            days = int(data.get("expires_in", 0)) // 86400
            same = data["access_token"] == token
            print(f"Token renovado: caduca en ~{days} días"
                  + ("" if same else " (¡el token ha cambiado! actualiza el secreto IG_ACCESS_TOKEN)"))
        else:
            print("Aviso: no se pudo renovar el token:", _scrub(data.get("error", {}).get("message", r.text[:150])))
    except requests.RequestException as e:
        print("Aviso: renovación de token fallida:", _scrub(str(e))[:200])


def create_container(token: str, user_id: str, fields: dict) -> str:
    return _check(requests.post(f"{GRAPH}/{user_id}/media", data={**fields, "access_token": token}, timeout=60),
                  "Crear el contenedor")["id"]


def wait_container(token: str, container: str, tries: int) -> None:
    for _ in range(tries):
        st = _check(requests.get(f"{GRAPH}/{container}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30), "Consultar estado")
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise PublishError(f"El contenedor terminó con estado {code}: {st.get('status', '')}")
        time.sleep(5)
    raise PublishError("El contenedor no terminó de procesarse a tiempo")


def reel_fields(video_url: str, caption: str) -> dict:
    return {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}


def publish_container(token: str, user_id: str, container: str) -> str:
    media = _check(requests.post(f"{GRAPH}/{user_id}/media_publish", data={
        "creation_id": container, "access_token": token}, timeout=60), "Publicar")
    return str(media["id"])


def publish_image(token: str, user_id: str, image_url: str, caption: str) -> str:
    c = create_container(token, user_id, {"image_url": image_url, "caption": caption})
    wait_container(token, c, tries=30)
    return publish_container(token, user_id, c)


def publish_reel(token: str, user_id: str, video_url: str, caption: str) -> str:
    """Publica un Reel (el procesado del video puede tardar unos minutos)."""
    c = create_container(token, user_id, reel_fields(video_url, caption))
    wait_container(token, c, tries=90)
    return publish_container(token, user_id, c)
