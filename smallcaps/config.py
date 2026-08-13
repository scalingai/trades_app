"""Carga de configuración desde `.env` — solo stdlib.

No usa python-dotenv a propósito: el módulo `edgar/` no tiene dependencias y
conviene mantener esa propiedad mientras se pueda.

Precedencia: variable de entorno real > valor en `.env`. Así podés pisar
cualquier cosa desde la shell sin editar archivos.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_PATH = HERE / ".env"


class MissingConfig(RuntimeError):
    """Falta un valor obligatorio. El mensaje dice exactamente cómo arreglarlo."""


@lru_cache(maxsize=1)
def _load_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        # Sacar comillas si el valor viene entrecomillado.
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key.strip()] = val
    return values


def get(key: str, default: str | None = None) -> str | None:
    """Valor de config. El entorno real gana sobre el `.env`."""
    if key in os.environ and os.environ[key].strip():
        return os.environ[key]
    val = _load_env_file().get(key)
    return val if val else default


def require(key: str, *, hint: str = "") -> str:
    val = get(key)
    if not val:
        raise MissingConfig(
            f"falta {key}.\n"
            f"  1. copiá smallcaps/.env.example a smallcaps/.env\n"
            f"  2. completá {key}=\n"
            + (f"  {hint}\n" if hint else "")
        )
    return val


def polygon_api_key() -> str:
    return require(
        "POLYGON_API_KEY",
        hint="sacala gratis en https://massive.com (no pide tarjeta)",
    )


def polygon_rate_limit() -> int:
    """Llamadas por minuto permitidas. Free = 5."""
    raw = get("POLYGON_RATE_LIMIT_PER_MIN", "5")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 5


def sec_user_agent() -> str:
    return get(
        "SEC_USER_AGENT",
        "AlgoTrade smallcaps research (agustinp.mktdigital@gmail.com)",
    )
