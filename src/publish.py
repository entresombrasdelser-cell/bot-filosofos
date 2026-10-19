"""Subida de la imagen (rama del repo público) y publicación con Instagram API (Instagram Login)."""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
GRAPH = f"https://graph.instagram.com/{API_VERSION}"


class PublishError(RuntimeError):
    pass


def _check(resp: requests.Response, what: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not resp.ok or "error" in data:
        err = data.get("error", {})
        raise PublishError(f"{what} falló ({resp.status_code}): {err.get('message', resp.text[:300])}")
    return data


# ---------------------------------------------------------------- hosting

def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def push_image(path: Path) -> str:
    """Sube la imagen al repo y devuelve su URL pública (raw.githubusercontent.com)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise PublishError("GITHUB_REPOSITORY no definido: ejecútalo desde GitHub Actions.")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    rel = path.as_posix()
    _git("add", rel)
    _git("commit", "-m", f"Imagen {path.name}")
    _git("pull", "--rebase", "origin", branch)
    _git("push", "origin", f"HEAD:{branch}")
    base = os.environ.get("IMAGE_BASE_URL", f"https://raw.githubusercontent.com/{repo}/{branch}")
    return f"{base}/{rel}"


def wait_until_public(url: str, timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.head(url, timeout=15, allow_redirects=True)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(5)
    raise PublishError(f"La imagen no es accesible públicamente: {url} (¿repo público?)")


# ---------------------------------------------------------------- Instagram

def resolve_user_id(token: str) -> str:
    explicit = os.environ.get("IG_USER_ID", "").strip()
    if explicit:
        return explicit
    data = _check(requests.get(f"{GRAPH}/me", params={"fields": "user_id,username", "access_token": token}, timeout=30),
                  "Consultar la cuenta")
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
            print("Aviso: no se pudo renovar el token:", data.get("error", {}).get("message", r.text[:150]))
    except requests.RequestException as e:
        print("Aviso: renovación de token fallida:", e)


def publish_image(token: str, user_id: str, image_url: str, caption: str) -> str:
    container = _check(requests.post(f"{GRAPH}/{user_id}/media", data={
        "image_url": image_url, "caption": caption, "access_token": token}, timeout=60),
        "Crear el contenedor")["id"]

    for _ in range(30):
        st = _check(requests.get(f"{GRAPH}/{container}", params={
            "fields": "status_code", "access_token": token}, timeout=30), "Consultar estado")
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise PublishError(f"El contenedor terminó con estado {code}")
        time.sleep(4)
    else:
        raise PublishError("El contenedor no terminó de procesarse a tiempo")

    media = _check(requests.post(f"{GRAPH}/{user_id}/media_publish", data={
        "creation_id": container, "access_token": token}, timeout=60), "Publicar")
    return str(media["id"])
