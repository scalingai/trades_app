"""Cliente HTTP de Massive (ex Polygon.io) — solo stdlib.

El throttle sale de `POLYGON_RATE_LIMIT_PER_MIN` del `.env`: free = 5/min.
El día que pases a un plan pago, cambiás ese número y nada más.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

import config

# Tras el rebrand a Massive el host viejo sigue respondiendo. Probamos ambos
# para no depender de cuál queda vivo.
_HOSTS = ("https://api.polygon.io", "https://api.massive.com")


class MassiveError(RuntimeError):
    """Fallo de la API. El mensaje nunca incluye la URL: lleva la apiKey."""


class NotAuthorized(MassiveError):
    """Fuera de lo que cubre el plan (típicamente: histórico más viejo)."""


class MassiveClient:
    def __init__(self, *, rate_per_min: int | None = None) -> None:
        self._key = config.polygon_api_key()
        self._rate = rate_per_min or config.polygon_rate_limit()
        self._min_gap = 60.0 / max(1, self._rate)
        self._lock = threading.Lock()
        self._last = 0.0
        self.calls_made = 0

    def _throttle(self) -> None:
        with self._lock:
            delta = time.monotonic() - self._last
            if delta < self._min_gap:
                time.sleep(self._min_gap - delta)
            self._last = time.monotonic()

    def get(self, path: str, *, retries: int = 3, **params) -> dict:
        params["apiKey"] = self._key
        qs = urllib.parse.urlencode(params)
        last_err: Exception | None = None

        for attempt in range(retries):
            for host in _HOSTS:
                self._throttle()
                self.calls_made += 1
                try:
                    req = urllib.request.Request(
                        f"{host}{path}?{qs}",
                        headers={"User-Agent": "smallcaps/0.1", "Accept": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        return json.loads(resp.read())
                except urllib.error.HTTPError as exc:
                    body = exc.read()[:300].decode("utf-8", "replace")
                    if exc.code == 403 and "NOT_AUTHORIZED" in body:
                        # Fuera del plan: reintentar no sirve, y probar el otro
                        # host tampoco. Es una respuesta definitiva.
                        raise NotAuthorized(f"fuera del plan en {path}: {body}") from exc
                    if exc.code == 429:
                        # El límite es por CUENTA, no por host: probar el otro
                        # host no ayuda y gasta un turno de throttle al pepe.
                        # Se espera y se reintenta el mismo host. (Esto causó
                        # un stall que duplicó el ETA en el backfill de minutos.)
                        time.sleep(15 * (attempt + 1))
                        last_err = MassiveError(f"429 rate limit en {path}")
                        break
                    if exc.code == 401:
                        raise MassiveError(
                            "401: la API key no es válida. Revisá POLYGON_API_KEY en el .env"
                        ) from exc
                    last_err = MassiveError(f"HTTP {exc.code} en {path}: {body}")
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                    last_err = MassiveError(f"{type(exc).__name__} en {path}: {exc}")
            time.sleep(2 ** attempt)

        raise last_err or MassiveError(f"sin respuesta para {path}")

    def grouped_daily(self, day: date, *, include_otc: bool = True) -> list[dict]:
        """OHLCV de TODOS los tickers de US para una fecha, en una sola llamada.

        `adjusted=false` es deliberado: el ajuste por splits de Massive usa la
        vista de HOY, o sea que mete conocimiento del futuro en los precios
        pasados. Los splits los manejamos nosotros, explícitamente.

        Además, al preguntar por FECHA en vez de por ticker, las empresas que
        después se deslistaron aparecen solas — el universo es
        survivorship-free por construcción, no por promesa del proveedor.
        """
        res = self.get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}",
            adjusted="false",
            include_otc="true" if include_otc else "false",
        )
        return res.get("results") or []
