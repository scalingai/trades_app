#!/usr/bin/env python3
"""Sonda del tier gratis de Massive (ex Polygon) — ¿qué trae realmente?

Contesta la pregunta que bloquea el diseño de la etapa 2: **¿las velas de
minuto incluyen extended hours (pre-market)?** Para small caps el gap y el
volumen pre-market son el criterio central del scanner. Si no vienen, el
scanner tiene que apoyarse en otra cosa.

De paso mide profundidad de histórico real y cobertura en un micro cap
(que es distinto de la cobertura en un líquido).

    python probe_polygon.py

Gasta ~4 llamadas. El tier free permite 5/min.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

ET = ZoneInfo("America/New_York")
_HOSTS = ("https://api.polygon.io", "https://api.massive.com")

_last_call = 0.0


def _throttle() -> None:
    """Respeta el límite del plan (free = 5/min → 1 cada 12s)."""
    global _last_call
    min_gap = 60.0 / config.polygon_rate_limit()
    delta = time.monotonic() - _last_call
    if delta < min_gap:
        time.sleep(min_gap - delta)
    _last_call = time.monotonic()


def call(path: str, **params) -> dict:
    key = config.polygon_api_key()
    params["apiKey"] = key
    qs = urllib.parse.urlencode(params)
    last_err = None
    for host in _HOSTS:
        url = f"{host}{path}?{qs}"
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "smallcaps-probe/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()[:200].decode("utf-8", "replace")
            # Nunca eco de la URL: lleva la apiKey en el query string.
            last_err = f"HTTP {exc.code} en {host}{path} — {body}"
            if exc.code in (401, 403):
                break  # key inválida: probar otro host no ayuda
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__} en {host}: {exc}"
    raise RuntimeError(last_err or "sin respuesta")


def _session_of(ts_ms: int) -> str:
    t = datetime.fromtimestamp(ts_ms / 1000, tz=ET).time()
    if t < datetime.strptime("09:30", "%H:%M").time():
        return "pre"
    if t < datetime.strptime("16:00", "%H:%M").time():
        return "rth"
    return "post"


def probe_minutes(ticker: str, day: date) -> None:
    d = day.isoformat()
    res = call(f"/v2/aggs/ticker/{ticker}/range/1/minute/{d}/{d}",
               adjusted="false", sort="asc", limit=50000)
    bars = res.get("results") or []
    print(f"\n  {ticker}  {d}   status={res.get('status')}  barras={len(bars)}")
    if not bars:
        print("    (sin datos — feriado, deslistado, o fuera del histórico del plan)")
        return

    counts = {"pre": 0, "rth": 0, "post": 0}
    vol = {"pre": 0.0, "rth": 0.0, "post": 0.0}
    for b in bars:
        s = _session_of(b["t"])
        counts[s] += 1
        vol[s] += b.get("v", 0)

    first = datetime.fromtimestamp(bars[0]["t"] / 1000, tz=ET)
    last = datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=ET)
    print(f"    primera {first:%H:%M} ET   última {last:%H:%M} ET")
    tot = sum(vol.values()) or 1
    for s, label in (("pre", "pre-market  04:00-09:30"),
                     ("rth", "regular     09:30-16:00"),
                     ("post", "after-hours 16:00-20:00")):
        print(f"    {label}   {counts[s]:>4} barras   "
              f"vol {vol[s]:>14,.0f}  ({100*vol[s]/tot:4.1f}%)")

    if counts["pre"] or counts["post"]:
        print("    → EXTENDED HOURS: SÍ vienen")
    else:
        print("    → EXTENDED HOURS: NO — solo sesión regular")


def probe_history_depth() -> None:
    """¿Hasta dónde llega el histórico del plan? Sondea con grouped daily."""
    today = date.today()
    for years, label in ((1, "1 año"), (2, "2 años"), (3, "3 años")):
        d = today - timedelta(days=int(365.25 * years))
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        try:
            res = call(f"/v2/aggs/grouped/locale/us/market/stocks/{d}",
                       adjusted="false", include_otc="true")
            n = len(res.get("results") or [])
            print(f"    {label:8} atrás ({d}): {n:,} tickers"
                  + ("  ← vacío/fuera de plan" if n == 0 else ""))
        except RuntimeError as exc:
            print(f"    {label:8} atrás ({d}): {exc}")


def main() -> int:
    try:
        config.polygon_api_key()
    except config.MissingConfig as exc:
        print(exc, file=sys.stderr)
        return 1

    print("=" * 62)
    print("  SONDA — tier free de Massive (ex Polygon)")
    print(f"  throttle: {config.polygon_rate_limit()} llamadas/min")
    print("=" * 62)

    # Día hábil reciente, con margen para que EOD ya esté publicado.
    day = date.today() - timedelta(days=5)
    while day.weekday() >= 5:
        day -= timedelta(days=1)

    print("\n[1] ¿Vienen extended hours en las velas de minuto?")
    probe_minutes("AAPL", day)   # líquido: control del mecanismo
    probe_minutes("HSCS", day)   # micro cap: cobertura real

    print("\n[2] Profundidad de histórico (grouped daily)")
    probe_history_depth()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
