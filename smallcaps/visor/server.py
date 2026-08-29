#!/usr/bin/env python3
"""Visor local de los días de evento. Sin dependencias: solo stdlib + un JS vendorizado.

Por qué un servidor y no un HTML suelto: los datos viven en dos SQLite de cientos
de MB. Servirlos por HTTP evita duplicarlos a JSON y deja pedir un día a la vez.

Por qué no se dibuja el gráfico a mano: `lightweight-charts` de TradingView
(Apache 2.0, 160 KB, sin build step) ya resuelve velas + volumen + zoom + crosshair.
Está vendorizado en `static/` a propósito — el visor tiene que abrir sin internet.

    python visor/server.py
    python visor/server.py --puerto 8899 --no-abrir
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import webbrowser
from datetime import date
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from dias import (APERTURA_RTH, CIERRE_RTH, Dia, cargar,  # noqa: E402
                  dias_del_evento, hora)

AQUI = Path(__file__).resolve().parent
ESTATICOS = AQUI / "static"
INDICE_CACHE = config.data_dir() / "visor_indice.json"

_RE_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def ts(dt) -> int:
    """Epoch en segundos DESPLAZADO al huso de Nueva York.

    lightweight-charts dibuja el eje en UTC y no acepta zona horaria. Sumarle el
    offset hace que 09:30 ET se dibuje como 09:30. Es el precio de no arrastrar
    una librería de fechas al front.
    """
    return int(dt.timestamp() + dt.utcoffset().total_seconds())


# ---------------------------------------------------------------- índice

_indice: list[dict] | None = None
_indice_listo = threading.Event()


def _fila_indice(dia: Dia, es_evento: bool = True) -> dict:
    o, c = dia.rth_open, dia.rth_close
    return {
        "ticker": dia.ticker,
        "d": dia.d,
        "evento": es_evento,
        "expansion": round(dia.expansion_pct, 1) if dia.expansion_pct is not None else None,
        "ratio_vol": round(dia.ratio_volumen, 1) if dia.ratio_volumen else None,
        "prev_close": dia.prev_close,
        "open": o,
        "close": c,
        "intradia": round((c / o - 1) * 100, 1) if o and c else None,
        "pm_high": dia.pm_high,
        "estado10": dia.estado_en(10.0),
        "estado12": dia.estado_en(12.0),
        "n_bars": len(dia.bars),
    }


def construir_indice(forzar: bool = False) -> list[dict]:
    global _indice
    if not forzar and INDICE_CACHE.exists():
        try:
            _indice = json.loads(INDICE_CACHE.read_text(encoding="utf-8"))
            _indice_listo.set()
            return _indice
        except Exception:
            pass
    from massive.minutes import MinuteStore
    store = MinuteStore()
    eventos = {(t, d) for t, d in dias_del_evento(store.conn)}
    store.close()

    filas = []
    for i, dia in enumerate(cargar(incluir_vecinos=True), 1):
        try:
            filas.append(_fila_indice(dia, (dia.ticker, dia.d) in eventos))
        except Exception:
            continue
        if i % 500 == 0:
            print(f"  indexando… {i} días", flush=True)
    filas.sort(key=lambda r: (r["d"], r["ticker"]), reverse=True)
    print(f"  índice listo: {len(filas)} días "
          f"({sum(1 for r in filas if r['evento'])} de evento)", flush=True)
    _indice = filas
    INDICE_CACHE.write_text(json.dumps(filas), encoding="utf-8")
    _indice_listo.set()
    return filas


# ---------------------------------------------------------------- un día

def _ficha(ticker: str, d: str) -> dict:
    import sqlite3
    db = sqlite3.connect(config.bars_db_path())
    out = {}
    ev = db.execute(
        "SELECT gap_pct,range_pct,rvol,dollar_volume,close_pos FROM events "
        "WHERE ticker=? AND d=?", (ticker, d)).fetchone()
    if ev:
        out["evento"] = dict(zip(("gap_pct", "range_pct", "rvol", "dollar_volume",
                                  "close_pos"), ev))
    st = db.execute(
        "SELECT dilution_12m_pct,dilution_3m_pct,reverse_splits_12m,runway_months,"
        "shelf_effective,pricing_filings_12m,dilutive_8k_12m,shares_outstanding,"
        "shares_stale_days FROM event_structure WHERE ticker=? AND d=?",
        (ticker, d)).fetchone()
    if st:
        out["estructura"] = dict(zip(
            ("dilution_12m_pct", "dilution_3m_pct", "reverse_splits_12m", "runway_months",
             "shelf_effective", "pricing_filings_12m", "dilutive_8k_12m",
             "shares_outstanding", "shares_stale_days"), st))
    db.close()
    return out


def _anomalias(dia: Dia, k: float = 5.0, ventana: int = 30) -> list[dict]:
    """Minutos con volumen o rango anómalos respecto de las 30 barras previas."""
    import statistics
    out = []
    for i, b in enumerate(dia.bars):
        if i < ventana or hora(b) < APERTURA_RTH or hora(b) > CIERRE_RTH:
            continue
        prev = dia.bars[i - ventana:i]
        vols = [x[5] or 0.0 for x in prev]
        rangos = [(x[2] - x[3]) / x[4] * 100 for x in prev if x[2] and x[3] and x[4]]
        if not vols or not rangos or not b[4]:
            continue
        mv, mr = statistics.median(vols), statistics.median(rangos)
        v = b[5] or 0.0
        r = (b[2] - b[3]) / b[4] * 100 if b[2] and b[3] else 0.0
        tipos = []
        if mv > 0 and v >= k * mv:
            tipos.append(f"vol {v/mv:.0f}x")
        if mr > 0 and r >= k * mr:
            tipos.append(f"rango {r/mr:.0f}x")
        if tipos:
            out.append({"time": ts(b[0]), "precio": b[4], "subio": bool(b[4] > b[1]),
                        "texto": " · ".join(tipos)})
    return out


@lru_cache(maxsize=1)
def _set_eventos() -> frozenset:
    from massive.minutes import MinuteStore
    store = MinuteStore()
    try:
        return frozenset(dias_del_evento(store.conn))
    finally:
        store.close()


def _es_evento(ticker: str, d: str) -> bool:
    return (ticker, d) in _set_eventos()


def payload_dia(ticker: str, d: str) -> dict | None:
    dias = list(cargar(solo={(ticker, d)}))
    if not dias:
        return None
    dia = dias[0]
    velas, vol, vwap = [], [], []
    for i, b in enumerate(dia.bars):
        t = ts(b[0])
        if None in (b[1], b[2], b[3], b[4]):
            continue
        velas.append({"time": t, "open": b[1], "high": b[2], "low": b[3], "close": b[4]})
        vol.append({"time": t, "value": b[5] or 0,
                    "color": "rgba(38,166,154,.5)" if b[4] >= b[1] else "rgba(239,83,80,.5)"})
        vwap.append({"time": t, "value": round(dia.vwap[i], 4)})

    b_ap = next((b for b in dia.bars if hora(b) >= APERTURA_RTH), None)
    b_ci = next((b for b in reversed(dia.bars) if hora(b) <= CIERRE_RTH), None)

    marcas = []
    for h, etiq in ((10.0, "10:00"), (12.0, "12:00")):
        i = dia.idx_en(h)
        if i is None:
            continue
        est = dia.estado_en(h)
        marcas.append({
            "time": ts(dia.bars[i][0]),
            "position": "belowBar" if est == "front" else "aboveBar",
            "color": "#26a69a" if est == "front" else "#ef5350",
            "shape": "arrowUp" if est == "front" else "arrowDown",
            "text": f"{etiq} {est}",
        })

    return {
        "ticker": ticker, "d": d,
        "velas": velas, "volumen": vol, "vwap": vwap, "marcas": marcas,
        "niveles": {"prev_close": dia.prev_close, "pm_high": dia.pm_high,
                    "rth_open": dia.rth_open},
        "sesion": {"apertura": ts(b_ap[0]) if b_ap else None,
                   "cierre": ts(b_ci[0]) if b_ci else None},
        "resumen": _fila_indice(dia, _es_evento(ticker, d)),
        "ficha": _ficha(ticker, d),
        "anomalias": _anomalias(dia),
    }


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # menos ruido en la consola
        pass

    def _json(self, obj, code=200):
        cuerpo = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _archivo(self, ruta: Path):
        if not ruta.exists() or not ruta.is_file():
            return self._json({"error": "no encontrado"}, 404)
        tipo = {".html": "text/html; charset=utf-8", ".js": "text/javascript",
                ".css": "text/css"}.get(ruta.suffix, "application/octet-stream")
        cuerpo = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        ruta = u.path

        if ruta in ("/", "/index.html"):
            return self._archivo(ESTATICOS / "index.html")
        if ruta.startswith("/static/"):
            nombre = os.path.basename(ruta)
            return self._archivo(ESTATICOS / nombre)

        if ruta == "/api/dias":
            if not _indice_listo.is_set():
                return self._json({"cargando": True, "dias": []})
            return self._json({"cargando": False, "dias": _indice})

        if ruta == "/api/dia":
            t = (q.get("ticker") or [""])[0].upper()
            d = (q.get("d") or [""])[0]
            if not _RE_TICKER.match(t) or not _RE_FECHA.match(d):
                return self._json({"error": "parámetros inválidos"}, 400)
            p = payload_dia(t, d)
            return self._json(p) if p else self._json({"error": "sin datos"}, 404)

        if ruta == "/api/bajar":
            t = (q.get("ticker") or [""])[0].upper()
            d = (q.get("d") or [""])[0]
            if not _RE_TICKER.match(t) or not _RE_FECHA.match(d):
                return self._json({"error": "parámetros inválidos"}, 400)
            try:
                from massive import MassiveClient
                from massive.minutes import MinuteStore, fetch_event
                store = MinuteStore()
                n, st = fetch_event(MassiveClient(), store, t, date.fromisoformat(d))
                store.close()
                if st == "ok":
                    construir_indice(forzar=True)
                return self._json({"barras": n, "estado": st})
            except Exception as exc:
                return self._json({"error": str(exc)}, 500)

        return self._json({"error": "ruta desconocida"}, 404)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Visor local de días de evento")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--no-abrir", action="store_true")
    ap.add_argument("--reindexar", action="store_true",
                    help="rehacer el índice aunque exista el cache")
    args = ap.parse_args(argv)

    hilo = threading.Thread(target=construir_indice, args=(args.reindexar,), daemon=True)
    hilo.start()

    url = f"http://127.0.0.1:{args.puerto}/"
    srv = ThreadingHTTPServer(("127.0.0.1", args.puerto), Handler)
    print("=" * 64)
    print("  VISOR DE EVENTOS")
    print(f"  {url}")
    print(f"  datos: {config.data_dir()}")
    print("  Ctrl+C para cortar")
    print("=" * 64, flush=True)
    if not args.no_abrir:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  cortado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
