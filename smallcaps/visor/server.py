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
from chavineta import clasificar_apertura, operar  # noqa: E402
from etiquetas import TIPOS, Etiquetas  # noqa: E402

_ET = Etiquetas()

AQUI = Path(__file__).resolve().parent
ESTATICOS = AQUI / "static"
INDICE_CACHE = config.data_dir() / "visor_indice.json"

_CARTERA_CACHE = None
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


# El embudo de ESTRATEGIA.md, en el orden en que se aplica. Cada paso es
# observable en el momento en que se aplica — ninguno mira el resultado del día.
def _embudo(dia: Dia, en_censo: bool) -> dict:
    """Por qué un día es (o no es) un candidato. Se devuelven TODOS los pasos.

    Devolver solo el booleano final sería peor: cuando un día que parecía bueno
    no aparece en la lista, hay que poder ver en qué paso se cayó sin abrir el
    código.
    """
    exp = dia.expansion_pct
    ratio = dia.ratio_volumen
    p = dia.rth_open
    try:
        apertura = clasificar_apertura(dia)
    except Exception:
        apertura = None
    # Prefijo `ok_` a propósito: sin él, la clave booleana `expansion` chocaba
    # con la numérica del mismo nombre y el badge del panel quedaba siempre en
    # verde. Un embudo que dice que sí a todo es peor que no tener embudo.
    # Liquidez en el minuto de decisión (10 min previos), no del día entero:
    # un papel puede operar $39M en la jornada y $400 por minuto cuando entrás.
    liq = dia.liquidez_en(10.0)
    pasos = {
        "ok_liquidez": bool(liq and liq >= 2.5e5),
        "ok_censo": en_censo,
        "ok_precio": bool(p and p >= 3.0),
        "ok_volumen": bool(ratio and ratio >= 3),
        "ok_expansion": bool(exp is not None and exp >= 100),
        "ok_fade": apertura == "fade",
    }
    pasos["candidato"] = all(pasos.values())
    pasos["apertura"] = apertura
    return pasos


def _fila_indice(dia: Dia, es_evento: bool = True, en_censo: bool = False) -> dict:
    o, c = dia.rth_open, dia.rth_close
    return {
        **_embudo(dia, en_censo),
        "ticker": dia.ticker,
        "d": dia.d,
        "evento": es_evento,
        "expansion": round(dia.expansion_pct, 1) if dia.expansion_pct is not None else None,
        "ratio_vol": round(dia.ratio_volumen, 1) if dia.ratio_volumen else None,
        "liq_min": round(dia.liquidez_en(10.0) or 0),
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
    from dias import dias_de_poblacion
    from massive.minutes import MinuteStore
    store = MinuteStore()
    eventos = {(t, d) for t, d in dias_del_evento(store.conn)}
    store.close()
    censo = dias_de_poblacion()
    hist = _historial()

    filas = []
    for i, dia in enumerate(cargar(incluir_vecinos=True), 1):
        try:
            clave = (dia.ticker, dia.d)
            fila = _fila_indice(dia, clave in eventos, clave in censo)
            h, n_h = hist.get(clave, (None, 0))
            fila["hist"], fila["n_hist"] = h, n_h
            filas.append(fila)
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


@lru_cache(maxsize=1)
def _historial() -> dict:
    """Tasa de fallo previa por (ticker, día). Point-in-time: para cada evento
    solo cuentan los gaps ANTERIORES. Es el dato de nivel TICKER que el panel
    agrupado necesita — la ficha del papel, no la del día."""
    import sqlite3
    from collections import defaultdict
    db = sqlite3.connect(config.bars_db_path())
    previos, out = defaultdict(lambda: [0, 0]), {}
    for t, d, intra in db.execute(
        "SELECT ticker, d, intraday_pct FROM events WHERE gap_pct >= 20 "
        "AND intraday_pct IS NOT NULL ORDER BY ticker, d"
    ):
        n, fall = previos[t]
        out[(t, d)] = (100.0 * fall / n, n) if n else (None, 0)
        previos[t] = [n + 1, fall + (1 if intra < 0 else 0)]
    db.close()
    return out


@lru_cache(maxsize=1)
def _set_censo() -> frozenset:
    from dias import dias_de_poblacion
    return frozenset(dias_de_poblacion())


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
        "resumen": {**_fila_indice(dia, _es_evento(ticker, d),
                                   (ticker, d) in _set_censo()),
                    "hist": _historial().get((ticker, d), (None, 0))[0],
                    "n_hist": _historial().get((ticker, d), (None, 0))[1]},
        "ficha": _ficha(ticker, d),
        "anomalias": _anomalias(dia),
        "etiquetas": _con_ts(dia, _ET.de_dia(ticker, d)),
        "tipos": TIPOS,
        "trade": _simular(dia),
    }


def payload_vivo(riesgo: float, piso: float) -> dict:
    """La sesión de HOY, armada desde el feed que escribe la plataforma.

    Devuelve por papel exactamente la misma forma que `payload_dia` —velas,
    volumen, vwap, niveles, trades— para poder reusar `VisorGrafico.dibujar`
    sin tocarlo. Que la pantalla en vivo y la bitácora dibujen con el mismo
    código no es prolijidad: es lo que garantiza que la ejecución que mirás hoy
    se vea igual que la que vas a auditar mañana.

    Toda la decisión pasa por `puente.vivo.evaluar`, que a su vez llama a
    `motor.jornada`. Acá no se decide nada.
    """
    sys.path.insert(0, str(AQUI.parent / "puente"))
    import vivo as _vivo  # import tardío: el visor abre aunque no haya feed

    salida = {"riesgo": riesgo, "piso": piso, "feed": str(_vivo.FEED),
              "existe": _vivo.FEED.exists(), "papeles": [],
              "config": {"stop": _vivo.STOP_PCT, "desde": _vivo.DESDE,
                         "expansion": _vivo.EXPANSION_MIN,
                         "apertura": _vivo.APERTURA,
                       "mfe50": _vivo.MFE_P50, "mfe75": _vivo.MFE_P75,
                       "corte": _vivo.CORTE_H,
                       "corte_umbral": _vivo.CORTE_UMBRAL,
                       "rancio": _vivo.RANCIO_MIN}}
    if not salida["existe"]:
        return salida

    hoy = date.today().isoformat()
    refs = _vivo.referencias()
    for (tk, f), datos in sorted(_vivo.leer_feed().items()):
        if f != hoy:
            continue
        # El simbolo sale de un archivo en disco y termina en el DOM de la
        # vista (en innerHTML y en el id de cada nodo). Es el mismo validador
        # que usan las otras rutas: un feed corrupto tiene que dar una fila de
        # menos, no HTML inyectado en la pantalla con la que se opera.
        if not _RE_TICKER.match(tk):
            continue
        dia = _vivo.armar_dia(tk, f, datos)
        if not dia:
            continue
        # Mismo chequeo de procedencia que la pantalla de terminal: que el papel
        # del feed sea EL papel y no otro con el mismo simbolo.
        malo = _vivo.papel_sospechoso(dia, refs.get(tk))
        if malo:
            r = {"ticker": tk, "bars": len(dia.bars),
                 "hora": hora(dia.bars[-1]), "precio": dia.bars[-1][4],
                 "expansion": None, "apertura": None, "descartes": [malo],
                 "tramos": []}
        else:
            r = _vivo.evaluar(dia, riesgo, piso)

        velas, vol, vwap = [], [], []
        for i, b in enumerate(dia.bars):
            if None in (b[1], b[2], b[3], b[4]):
                continue
            t = ts(b[0])
            velas.append({"time": t, "open": b[1], "high": b[2],
                          "low": b[3], "close": b[4]})
            vol.append({"time": t, "value": b[5] or 0,
                        "color": "rgba(38,166,154,.5)" if b[4] >= b[1]
                        else "rgba(239,83,80,.5)"})
            vwap.append({"time": t, "value": round(dia.vwap[i], 4)})

        b_ap = next((b for b in dia.bars if hora(b) >= APERTURA_RTH), None)
        b_ci = next((b for b in reversed(dia.bars) if hora(b) <= CIERRE_RTH), None)

        # Los tramos se traducen al vocabulario que ya entiende `grafico.js`.
        trades = [{"hora_entrada": t["h"], "precio_entrada": t["precio"],
                   "hora_salida": None if t["viva"] else t["h_sal"],
                   "precio_salida": None if t["viva"] else t["p_sal"],
                   "motivo": "abierta" if t["viva"] else t["motivo"],
                   "pnl": t["pnl"], "acciones": t["acciones"],
                   "stop_pct": _vivo.STOP_PCT}
                  for t in (r.get("tramos") or [])]

        salida["papeles"].append({
            "ticker": tk, "d": f, "velas": velas, "volumen": vol, "vwap": vwap,
            "trades_estrategia": trades,
            "niveles": {"prev_close": dia.prev_close, "pm_high": dia.pm_high,
                        "rth_open": dia.rth_open},
            "sesion": {"apertura": ts(b_ap[0]) if b_ap else None,
                       "cierre": ts(b_ci[0]) if b_ci else None},
            "estado": {"hora": r.get("hora"), "precio": r.get("precio"),
                       "barras": r.get("bars"), "expansion": r.get("expansion"),
                       "apertura": r.get("apertura"),
                       "descartes": r.get("descartes") or [],
                       "pico": r.get("pico"), "vivas": r.get("vivas"),
                       "equity": r.get("equity"), "comision": r.get("comision"),
                       "limite": r.get("limite"),
                       "tope": r.get("cerca_del_limite"),
                       "atraso": _vivo.atraso_min(r.get("hora")),
                       "pnl_cerrado": r.get("pnl_cerrado"),
                       "pnl_abierto": r.get("pnl_abierto"),
                       "precio_prom": r.get("precio_prom"),
                       "stop_prom": r.get("stop_prom"),
                       "proy_50": r.get("proy_50"),
                       "proy_75": r.get("proy_75"),
                       "composicion": r.get("composicion") or []},
        })
    salida["papeles"].sort(
        key=lambda x: -len(x["trades_estrategia"]))
    return salida


def _simular(dia: Dia) -> dict | None:
    """Corre la Chavineta sobre el día y devuelve el trade listo para dibujar.

    Que el gráfico muestre las ejecuciones no es cosmética: la reducción
    intrabar —un tramo que se abría y se cerraba en el mismo minuto, en 646 de
    695 trades— se descubrió mirando los timestamps del registro, no las
    tablas agregadas.
    """
    import sqlite3
    db = sqlite3.connect(config.bars_db_path())
    try:
        prev = db.execute(
            "SELECT h FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT 1",
            (dia.ticker, dia.d)).fetchone()
        r = operar(dia, prev[0] if prev else None, costo_accion=0.003,
                   tope_perdida=20.0, quita_locate=0.20, gradual=True,
                   costo_salida=0.03)
    except Exception as exc:
        return {"operado": False, "motivo": f"error: {exc}"}
    finally:
        db.close()
    if not r.get("operado"):
        return {"operado": False, "motivo": r.get("motivo")}
    ejec = [{**e, "time": ts(e["ts"])} for e in r["registro"]]
    for e in ejec:
        e.pop("ts", None)
    # Línea escalonada del precio medio: es lo que hay que mirar para entender
    # si la construcción mejoró la posición o solo agrandó el problema.
    # Un punto por ejecución, con tiempos ESTRICTAMENTE crecientes y únicos.
    # Dos puntos con el mismo `time` dejan la serie mal formada, y el síntoma no
    # es un error: es que el eje de tiempo del gráfico deja de aceptar zoom.
    medio, visto = [], set()
    for e in ejec:
        if e["time"] in visto:
            medio[-1]["value"] = round(e["medio"], 4)
            continue
        visto.add(e["time"])
        medio.append({"time": e["time"], "value": round(e["medio"], 4)})
    return {"operado": True, "motivo": r["motivo"], "neto": r["neto"],
            "bruto": r["bruto"], "peor": r["peor"], "ejecuciones": r["ejecuciones"],
            "pasos": ejec, "medio": medio}


def _con_ts(dia: Dia, marcas: list[dict]) -> list[dict]:
    """Le agrega a cada etiqueta el timestamp de la barra que le corresponde.

    La etiqueta se guarda por HORA decimal, no por timestamp: así sobrevive a
    que se rebaje el día con otra granularidad. El visor necesita el ts para
    dibujarla, y ese sí depende de las barras.
    """
    out = []
    for m in marcas:
        i = dia.idx_en(m["hora"])
        if i is None:
            continue
        out.append({**m, "time": ts(dia.bars[i][0])})
    return out


# ---------------------------------------------------------------- historial

def _conn_trades():
    import sqlite3
    p = config.data_dir() / "trades.sqlite"
    if not p.exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def _metricas(pnls: list[float]) -> dict:
    """Las métricas de una curva. Profit factor y drawdown incluidos.

    El drawdown se calcula sobre el ORDEN CRONOLÓGICO de los trades, que es lo
    único que lo hace significar algo: la suma es la misma en cualquier orden,
    la caída máxima no.
    """
    if not pnls:
        return {}
    gan = [x for x in pnls if x > 0]
    per = [x for x in pnls if x <= 0]
    acum, pico, dd = 0.0, 0.0, 0.0
    curva = []
    for x in pnls:
        acum += x
        pico = max(pico, acum)
        dd = min(dd, acum - pico)
        curva.append(round(acum, 2))
    return {
        "n": len(pnls), "total": round(sum(pnls), 2),
        "media": round(sum(pnls) / len(pnls), 3),
        "gana": round(100 * len(gan) / len(pnls), 1),
        "gan_medio": round(sum(gan) / len(gan), 2) if gan else 0,
        "per_medio": round(sum(per) / len(per), 2) if per else 0,
        # Profit factor: cuánto gana por cada dólar que pierde. Debajo de 1 la
        # estrategia pierde, y no hay calibración que lo arregle.
        "pf": round(sum(gan) / abs(sum(per)), 2) if per and sum(per) else None,
        "dd": round(dd, 2),
        "curva": curva,
    }


def _estrategias() -> list[dict]:
    c = _conn_trades()
    if not c:
        return []
    # Fecha de medición: ver el comentario en /api/bitacora. Se agrega acá
    # también porque /historial es donde se comparan estrategias entre sí, que
    # es exactamente donde mezclar eras hace más daño.
    try:
        medido = {r[0]: r[1] for r in c.execute(
            "SELECT nombre, creado FROM estrategia")}
    except sqlite3.Error:
        medido = {}
    out = []
    for (e,) in c.execute("SELECT DISTINCT estrategia FROM trades"):
        pn = [r[0] for r in c.execute(
            "SELECT pnl FROM trades WHERE estrategia=? ORDER BY d, hora_entrada", (e,))]
        m = _metricas(pn)
        m.pop("curva", None)
        out.append({"estrategia": e, "medido": medido.get(e), **m})
    c.close()
    return sorted(out, key=lambda x: -(x.get("total") or 0))


def _trades(estrategia: str) -> dict:
    c = _conn_trades()
    if not c:
        return {"filas": [], "metricas": {}}
    filas = [dict(r) for r in c.execute(
        "SELECT * FROM trades WHERE estrategia=? ORDER BY d, hora_entrada",
        (estrategia,))]
    c.close()
    m = _metricas([f["pnl"] for f in filas])
    # La curva por FECHA, no por trade: es como se vive el resultado.
    por_dia, acum = {}, 0.0
    for f in filas:
        por_dia[f["d"]] = por_dia.get(f["d"], 0.0) + f["pnl"]
    curva = []
    for d in sorted(por_dia):
        acum += por_dia[d]
        curva.append({"d": d, "pnl": round(por_dia[d], 2), "acum": round(acum, 2)})
    m.pop("curva", None)
    return {"filas": filas, "metricas": m, "curva": curva}


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

    def do_POST(self):
        """Lo unico que se escribe desde la app: la watchlist del dia.

        POR QUE EXISTE. La watchlist se editaba a mano en un archivo, o peor,
        clickeando menus en la plataforma. Cada mañana. Que la unica pantalla
        con la que se opera no pueda cambiar lo que mira es un agujero de
        diseño, no una comodidad que falta.

        El servidor escucha solo en 127.0.0.1 y esto escribe UN archivo de
        texto en el directorio de datos. Aun asi se valida el formato: un
        ticker mal escrito no falla ruidosamente, deja un papel afuera en
        silencio — que es la peor clase de error para una pantalla de operar.
        """
        u = urlparse(self.path)
        if u.path != "/api/watchlist":
            return self._json({"error": "no existe"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            datos = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json({"error": f"cuerpo invalido: {e}"}, 400)

        lineas, malas = [], []
        for cruda in (datos.get("texto") or "").splitlines():
            cruda = cruda.strip()
            if not cruda or cruda.startswith("#"):
                continue
            partes = cruda.replace(",", " ").replace(";", " ").split()
            tk = partes[0].upper()
            if not _RE_TICKER.match(tk):
                malas.append(cruda)
                continue
            # El precio NO es opcional en la practica: sin el, un simbolo que
            # existe en varios mercados se resuelve al que venga primero. Se
            # acepta sin precio pero se avisa.
            px = None
            if len(partes) > 1:
                try:
                    px = float(partes[1])
                except ValueError:
                    malas.append(cruda)
                    continue
            lineas.append(f"{tk} {px:g}" if px else tk)

        if malas:
            return self._json({"error": "lineas invalidas: " + "; ".join(malas)}, 400)

        ruta = Path(config.data_dir()) / "watchlist.txt"
        cab = chr(10).join([
            f"# Watchlist escrita desde el visor · {date.today().isoformat()}",
            "# TICKER precio_de_referencia",
            "#",
            "# El precio distingue papeles con el mismo simbolo en distintos",
            "# mercados. SSM resolvia a uno de $59 cuando el nuestro estaba",
            "# a $3,85.",
            "",
        ])
        ruta.write_text(cab + chr(10).join(lineas) + chr(10), encoding="utf-8")
        return self._json({"ok": True, "papeles": len(lineas),
                           "sin_precio": sum(1 for x in lineas if " " not in x)})

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        ruta = u.path

        if ruta in ("/", "/index.html"):
            return self._archivo(ESTATICOS / "index.html")
        if ruta == "/favicon.ico":
            return self._archivo(ESTATICOS / "favicon.ico")
        if ruta.startswith("/static/"):
            nombre = os.path.basename(ruta)
            return self._archivo(ESTATICOS / nombre)

        if ruta == "/historial" or ruta == "/historial.html":
            return self._archivo(ESTATICOS / "historial.html")

        if ruta == "/papeles" or ruta == "/papeles.html":
            return self._archivo(ESTATICOS / "papeles.html")

        if ruta == "/cartera" or ruta == "/cartera.html":
            return self._archivo(ESTATICOS / "cartera.html")

        if ruta == "/vivo" or ruta == "/vivo.html":
            return self._archivo(ESTATICOS / "vivo.html")

        if ruta == "/api/watchlist":
            f = Path(config.data_dir()) / "watchlist.txt"
            txt = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""
            # Se devuelven solo las lineas utiles: los comentarios los reescribe
            # el POST, y mostrarlos invita a editarlos.
            utiles = [x.strip() for x in txt.splitlines()
                      if x.strip() and not x.strip().startswith("#")]
            return self._json({"texto": chr(10).join(utiles), "ruta": str(f)})

        if ruta == "/api/vivo":
            try:
                riesgo = float((q.get("riesgo") or ["400"])[0])
                piso = float((q.get("piso") or ["2"])[0])
            except ValueError:
                return self._json({"error": "riesgo/piso inválidos"}, 400)
            try:
                return self._json(payload_vivo(riesgo, piso))
            except Exception as e:
                return self._json({"error": str(e)}, 500)

        if ruta == "/replay" or ruta == "/replay.html":
            return self._archivo(ESTATICOS / "replay.html")

        if ruta == "/api/replay":
            # Todo lo necesario para REPRODUCIR un tramo del calendario, en
            # orden. El cliente anima; el servidor sólo entrega el material.
            # Se manda el día completo de barras (no sólo los minutos con
            # trade) porque la gracia de mirar la reproducción es ver lo que
            # pasaba ALREDEDOR de la ejecución, no la ejecución sola.
            e = (q.get("estrategia") or [""])[0]
            desde = (q.get("desde") or ["0000-00-00"])[0]
            hasta = (q.get("hasta") or ["9999-99-99"])[0]
            if not (_RE_FECHA.match(desde) and _RE_FECHA.match(hasta)):
                return self._json({"error": "fechas inválidas"}, 400)
            c = _conn_trades()
            if not c:
                return self._json({"error": "sin base de trades"}, 404)
            cols = [x[1] for x in c.execute("PRAGMA table_info(trades)")]
            filas = [dict(zip(cols, r)) for r in c.execute(
                "SELECT * FROM trades WHERE estrategia=? AND d BETWEEN ? AND ? "
                "ORDER BY d, ticker, hora_entrada", (e, desde, hasta))]
            # `lado` no se puede asumir: de las 413 estrategias medidas, 135
            # son LARGAS (la familia que midió si existe un edge comprador) y
            # 278 cortas. Sin este campo, una vista que marque el PnL a mercado
            # mostraría un cuarto de las estrategias con el signo invertido
            # durante toda la reproducción.
            fila_e = c.execute(
                "SELECT lado, familia, creado FROM estrategia WHERE nombre=?",
                (e,)).fetchone()
            lado = (fila_e[0] if fila_e else None) or "short"
            ses = {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT d,pnl_R,nominal_R FROM sesion WHERE estrategia=? "
                "AND d BETWEEN ? AND ?", (e, desde, hasta))}
            c.close()

            jornadas, vistos = [], set()
            for f in filas:
                k = (f["ticker"], f["d"])
                if k in vistos:
                    continue
                vistos.add(k)
                p = payload_dia(f["ticker"], f["d"])
                if not p:
                    continue
                s2 = ses.get(f["d"])
                jornadas.append({
                    "d": f["d"], "ticker": f["ticker"],
                    "velas": p["velas"], "volumen": p["volumen"],
                    "vwap": p["vwap"], "niveles": p["niveles"],
                    "sesion": p["sesion"], "resumen": p["resumen"],
                    "trades": [x for x in filas
                               if x["ticker"] == f["ticker"] and x["d"] == f["d"]],
                    "pnl_R": s2[0] if s2 else None,
                    "nominal_R": s2[1] if s2 else None,
                })
            jornadas.sort(key=lambda x: (x["d"], x["ticker"]))
            return self._json({"estrategia": e, "lado": lado,
                               "familia": fila_e[1] if fila_e else None,
                               "medido": fila_e[2] if fila_e else None,
                               "desde": desde, "hasta": hasta,
                               "jornadas": jornadas})

        if ruta == "/api/replay/meses":
            # Qué meses tienen material, para no ofrecer un rango vacío.
            e = (q.get("estrategia") or [""])[0]
            c = _conn_trades()
            if not c:
                return self._json({"meses": []})
            meses = [{"mes": r[0], "jornadas": r[1], "trades": r[2],
                      "pnl": round(r[3] or 0, 2)}
                     for r in c.execute(
                         "SELECT substr(d,1,7), COUNT(DISTINCT d), COUNT(*), SUM(pnl) "
                         "FROM trades WHERE estrategia=? GROUP BY 1 ORDER BY 1", (e,))]
            c.close()
            return self._json({"estrategia": e, "meses": meses})

        if ruta == "/bitacora" or ruta == "/bitacora.html":
            return self._archivo(ESTATICOS / "bitacora.html")

        if ruta == "/api/bitacora":
            # El diario de operación: un renglón por jornada, en orden
            # cronológico. Es la vista que contesta "¿qué hago un martes?",
            # que las tablas agregadas no contestan.
            e = (q.get("estrategia") or [""])[0]
            c = _conn_trades()
            if not c:
                return self._json({"dias": [], "estrategias": []})
            # Las 'limpio·' primero: son las únicas medidas sin look-ahead,
            # o sea las únicas que se pueden operar de verdad.
            ests = [r[0] for r in c.execute(
                "SELECT nombre FROM estrategia "
                "ORDER BY (nombre LIKE 'limpio%') DESC, ret_nom DESC")]
            # Cuándo se midió cada una. El motor se corrigió varias veces
            # (look-ahead en la apertura, nominal por exposición simultánea,
            # look-ahead en el presupuesto), así que dos estrategias medidas en
            # días distintos NO son comparables aunque estén en la misma tabla.
            # Sin este dato la única defensa es acordarse, y no alcanza.
            medido = {r[0]: r[1] for r in c.execute(
                "SELECT nombre, creado FROM estrategia")}
            if not e and ests:
                e = ests[0]
            dias = []
            for d, n, pnl, tks in c.execute(
                    "SELECT d, COUNT(*), SUM(pnl), GROUP_CONCAT(DISTINCT ticker) "
                    "FROM trades WHERE estrategia=? GROUP BY d ORDER BY d", (e,)):
                dias.append({"d": d, "trades": n, "pnl": round(pnl or 0, 2),
                             "tickers": (tks or "").split(",")})
            ses = {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT d,pnl_R,nominal_R FROM sesion WHERE estrategia=?", (e,))}
            for x in dias:
                s2 = ses.get(x["d"])
                x["pnl_R"] = round(s2[0], 3) if s2 else None
                x["nominal_R"] = round(s2[1], 3) if s2 else None
            c.close()
            return self._json({"estrategia": e, "estrategias": ests,
                               "medido": medido, "dias": dias})

        if ruta == "/api/bitacora/dia":
            d = (q.get("d") or [""])[0]
            e = (q.get("estrategia") or [""])[0]
            if not _RE_FECHA.match(d):
                return self._json({"error": "fecha inválida"}, 400)
            c = _conn_trades()
            if not c:
                return self._json({"error": "sin base de trades"}, 404)
            cols = [x[1] for x in c.execute("PRAGMA table_info(trades)")]
            filas = [dict(zip(cols, r)) for r in c.execute(
                "SELECT * FROM trades WHERE d=? AND estrategia=? "
                "ORDER BY ticker, hora_entrada", (d, e))]
            c.close()
            # Un payload de gráfico por papel operado ese día.
            papeles = []
            for tk in sorted({f["ticker"] for f in filas}):
                p = payload_dia(tk, d)
                if not p:
                    continue
                p["trades_estrategia"] = [f for f in filas if f["ticker"] == tk]
                papeles.append(p)
            return self._json({"d": d, "estrategia": e, "papeles": papeles,
                               "trades": filas})

        if ruta == "/api/cartera":
            # Cacheado por mtime del sqlite: recalcular la matriz completa
            # cuesta 132 s y 8,4 MB, y los datos sólo cambian cuando alguna
            # corrida escribe la base. Sin esto la página queda dos minutos en
            # blanco y ningún trabajo de diseño la salva.
            global _CARTERA_CACHE
            try:
                sello = os.path.getmtime(config.data_dir() / "trades.sqlite")
            except OSError:
                sello = 0
            if _CARTERA_CACHE and _CARTERA_CACHE[0] == sello:
                return self._json(_CARTERA_CACHE[1])
            # Métricas por estrategia + matriz de correlación + ranking de
            # combinaciones. Todo sale de lo que persistió `motor.evaluar()`;
            # el ranking lo produce `cartera.py` y se lee de su JSON.
            import itertools
            import json as _json
            try:
                from cartera import cargar, correlacion, solape
            except Exception as exc:
                return self._json({"error": f"cartera.py: {exc}"}, 500)
            ests = cargar(max_brecha=1e9)      # acá se muestran TODAS
            # La matriz es cuadrática: 398 estrategias son 158.404 celdas y el
            # navegador no las pinta. Se correlacionan sólo las de mayor
            # ret/nom; la tabla de arriba sigue listando todas.
            nombres = sorted(ests, key=lambda n: -(ests[n]["ret_nom"] or 0))[:40]
            nombres.sort()
            mat = []
            for a in nombres:
                fila = []
                for b in nombres:
                    if a == b:
                        fila.append({"c": 1.0, "s": 1.0})
                    else:
                        fila.append({
                            "c": correlacion(ests[a]["serie"], ests[b]["serie"]),
                            "s": round(solape(ests[a]["serie"], ests[b]["serie"]), 3)})
                mat.append(fila)
            ranking = []
            rp = config.data_dir() / "cartera.json"
            if rp.exists():
                try:
                    ranking = _json.loads(rp.read_text(encoding="utf-8"))[:40]
                except Exception:
                    ranking = []
            payload = {
                "estrategias": [
                    {k: v for k, v in ests[n].items() if k != "serie"} |
                    {"serie": [[d, v[0]] for d, v in sorted(ests[n]["serie"].items())]}
                    for n in nombres],
                "nombres": nombres, "matriz": mat, "ranking": ranking}
            _CARTERA_CACHE = (sello, payload)
            return self._json(payload)

        if ruta == "/api/estrategias":
            return self._json({"estrategias": _estrategias()})

        if ruta == "/api/trades":
            e = (q.get("estrategia") or [""])[0]
            return self._json({"trades": _trades(e)})

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

        if ruta == "/api/marcas":
            # Cuántas marcas tiene cada día, para el panel agrupado. Se pide
            # aparte del índice porque cambia todo el tiempo y el índice no.
            cuenta = {}
            for e in _ET.todas():
                k = f"{e['ticker']}|{e['d']}"
                cuenta[k] = cuenta.get(k, 0) + 1
            return self._json({"marcas": cuenta})

        if ruta == "/api/etiquetar":
            t = (q.get("ticker") or [""])[0].upper()
            d = (q.get("d") or [""])[0]
            tipo = (q.get("tipo") or [""])[0]
            nota = (q.get("nota") or [""])[0][:500]
            try:
                h = float((q.get("hora") or ["-1"])[0])
            except ValueError:
                h = -1.0
            if not _RE_TICKER.match(t) or not _RE_FECHA.match(d) or not 0 <= h <= 24:
                return self._json({"error": "parámetros inválidos"}, 400)
            try:
                return self._json({"id": _ET.marcar(t, d, h, tipo, nota)})
            except ValueError as exc:
                return self._json({"error": str(exc)}, 400)

        if ruta == "/api/desetiquetar":
            try:
                _ET.borrar(int((q.get("id") or ["0"])[0]))
            except ValueError:
                return self._json({"error": "id inválido"}, 400)
            return self._json({"ok": True})

        if ruta == "/api/etiquetas":
            return self._json({"etiquetas": _ET.todas(), "resumen": _ET.resumen()})

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
