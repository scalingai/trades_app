"""Configuración y rutas — solo stdlib.

Misma decisión que en `smallcaps/config.py`: el código vive en un worktree
descartable y los datos no van en git, así que los datos viven FUERA del
worktree o se pierden en cada limpieza.

A diferencia de small caps, acá **no hace falta ninguna API key** para la
Etapa 0: el archivo de Binance es abierto y CoinGecko sirve 365 días sin
registro. `COINGECKO_API_KEY` es opcional y solo sube el límite de peticiones.

Precedencia: variable de entorno real > `.env` > default.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"

_DEFAULT_DATA_DIR = Path.home() / "Apps" / "algotrade-data" / "cripto"


@lru_cache(maxsize=1)
def _load_env_file() -> dict[str, str]:
    path = ENV_PATH if ENV_PATH.exists() else _DEFAULT_DATA_DIR / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key.strip()] = val
    return values


def get(key: str, default: str | None = None) -> str | None:
    if key in os.environ and os.environ[key].strip():
        return os.environ[key]
    val = _load_env_file().get(key)
    return val if val else default


def data_dir() -> Path:
    """Dónde vive la data. Movible con `CRIPTO_DATA_DIR`.

    Todo lo que hay acá es reproducible desde el archivo público; lo que se
    pierde al borrarlo es tiempo de descarga, no información.
    """
    raw = get("CRIPTO_DATA_DIR")
    path = Path(raw).expanduser() if raw else _DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    d = data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "cripto.sqlite"


def coingecko_key() -> str | None:
    """Opcional. Sin key el free tier alcanza, solo hay que ir más lento."""
    return get("COINGECKO_API_KEY")


def coingecko_rate_limit() -> int:
    """Peticiones por minuto. El free tier sin key tolera ~10-30; usamos 10
    porque un 429 a mitad de una descarga de 500 monedas cuesta más que ir
    lento, y el proceso es resumable de todos modos."""
    try:
        return max(1, int(get("COINGECKO_RATE_LIMIT_PER_MIN", "10")))
    except (TypeError, ValueError):
        return 10
