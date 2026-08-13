"""Cliente HTTP para SEC EDGAR — solo stdlib.

La SEC no pide API key, pero exige:
  - header `User-Agent` con contacto real (si no, 403)
  - <= 10 requests/segundo

Este módulo centraliza ambas cosas + cache en disco, para que ningún otro
módulo pueda pegarle a la SEC sin throttle.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# La SEC rechaza requests sin contacto. Sale de `.env` vía config, con
# fallback a la variable de entorno si este módulo se usa suelto.
try:
    import config as _cfg

    USER_AGENT = _cfg.sec_user_agent()
    _CACHE_DIR_FN = _cfg.cache_dir
except ImportError:  # edgar/ usado fuera del paquete smallcaps
    USER_AGENT = os.environ.get(
        "SEC_USER_AGENT",
        "AlgoTrade smallcaps research (agustinp.mktdigital@gmail.com)",
    )
    _CACHE_DIR_FN = None

# 10 req/s es el límite publicado. Vamos a 8 para dejar margen.
_MAX_RPS = 8.0
_MIN_INTERVAL = 1.0 / _MAX_RPS

# Fuera del worktree cuando config está disponible (ver config.data_dir).
CACHE_DIR = (
    _CACHE_DIR_FN()
    if _CACHE_DIR_FN
    else Path(__file__).resolve().parent.parent / "data" / "cache"
)


class RateLimitError(RuntimeError):
    """La SEC nos cortó (403/429). Casi siempre: User-Agent o exceso de rate."""


class _Throttle:
    """Serializa las llamadas a la SEC a <= _MAX_RPS, thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - delta)
            self._last = time.monotonic()


_throttle = _Throttle()


def _cache_path(url: str) -> Path:
    # El hash evita nombres de archivo inválidos y colisiones de path.
    import hashlib

    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    return CACHE_DIR / f"{digest}.json.gz"


def fetch(url: str, *, cache_hours: float = 12.0, retries: int = 3) -> bytes:
    """GET con throttle, User-Agent y cache en disco.

    `cache_hours=0` fuerza el fetch (para feeds que cambian minuto a minuto).
    """
    path = _cache_path(url)
    if cache_hours > 0 and path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600.0
        if age_h < cache_hours:
            with gzip.open(path, "rb") as fh:
                return fh.read()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            # data.sec.gov exige Host explícito en algunos proxies corporativos.
            "Accept": "application/json, text/html, */*",
        },
    )

    last_err: Exception | None = None
    for attempt in range(retries):
        _throttle.wait()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                # Backoff exponencial: la SEC banea IPs que insisten.
                last_err = RateLimitError(
                    f"SEC devolvió {exc.code} para {url}. "
                    f"Revisá SEC_USER_AGENT (debe tener un email real)."
                )
                time.sleep(2 ** attempt)
                continue
            if exc.code == 404:
                raise FileNotFoundError(f"404 en {url}") from exc
            last_err = exc
            time.sleep(2 ** attempt)
            continue
        except (urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            time.sleep(2 ** attempt)
            continue

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Escritura atómica: si el proceso muere a mitad, no queda un
        # .json.gz corrupto que el próximo run lea como cache válido.
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as fh:
            fh.write(raw)
        tmp.replace(path)
        return raw

    raise last_err if last_err else RuntimeError(f"fetch falló: {url}")


def fetch_json(url: str, *, cache_hours: float = 12.0) -> dict:
    return json.loads(fetch(url, cache_hours=cache_hours))
