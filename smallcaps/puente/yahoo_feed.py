#!/usr/bin/env python3
"""El feed en vivo desde Yahoo: las barras de 1 minuto de la watchlist, al mismo archivo.

POR QUE EXISTE. El feed lo escribia `TTPFeedMulti.cs`, un indicador adentro de
la plataforma de Trade The Pool. Desde el 2026-09-03 no se opera ahi
(OPERATIVA.md §0), y la plataforma de TradeZero no tiene scripting. Sin
plataforma no hay barras, y sin barras la pantalla en vivo no dice nada.

Yahoo entrega las barras de 1 minuto del dia con sesion extendida —desde las
04:00— y con la ultima barra al minuto (medido el 2026-09-04 a las 09:27:41 NY:
la ultima barra era la de las 09:27). Es la misma API no oficial que ya usa
`escaner.py` para la watchlist; si un dia se cae, se cae el escaner tambien.

QUE ESCRIBE. Exactamente lo que escribia el indicador, linea por linea:

    {"t": "2026-09-04T13:31:00Z", "s": "CHPT", "o": .., "h": .., "l": .., "c": .., "v": .., "pc": 9.07}

`t` en UTC, `pc` el cierre de la sesion anterior. `vivo.leer_feed` no distingue
quien escribio la linea, y es a proposito: la pantalla, el motor y la
bitacora no cambian. Si el indicador de la plataforma y esto escriben a la vez
las lineas repetidas se deduplican por (simbolo, minuto) al leer.

LA BARRA EN CURSO NO SE ESCRIBE. `leer_feed` se queda con la PRIMERA linea de
cada minuto, asi que una barra escrita a medio minuto quedaria congelada con
el maximo y el minimo incompletos. Se escriben solo los minutos terminados: la
pantalla va un minuto atras del mercado, y eso es exacto en vez de rapido.

    python puente/yahoo_feed.py                 # en vivo, hasta Ctrl+C
    python puente/yahoo_feed.py --dia 2026-09-03 --tickers CHPT,AEHL   # rellenar un dia
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI))

import config
import vivo
from escaner import NY, UA

FEED = vivo.FEED
WATCHLIST = vivo.WATCHLIST
INTERVALO_S = 15.0          # entre ciclos; Yahoo entrega la barra al minuto
ULTIMA_H_NY = 20.0          # despues del post-market no hay nada que leer


def leer_watchlist(ruta=WATCHLIST) -> dict[str, float]:
    """TICKER precio, ignorando comentarios. Se relee en cada ciclo, igual que
    hacia el indicador: agregar un papel a mitad de rueda lo mete solo."""
    out: dict[str, float] = {}
    if not ruta.exists():
        return out
    for linea in ruta.read_text(encoding="utf-8", errors="replace").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        partes = linea.split()
        try:
            out[partes[0].upper()] = float(partes[1]) if len(partes) > 1 else 0.0
        except ValueError:
            continue
    return out


def pedir(ticker: str, rango: str = "1d") -> dict | None:
    """Las barras de 1 minuto con sesion extendida, crudas, o None si fallo."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1m&range={rango}&includePrePost=true")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        return (d.get("chart", {}).get("result") or [None])[0]
    except Exception:
        return None


def _cierre_previo(res: dict, solo_dia: str | None) -> float:
    """El cierre de la sesion ANTERIOR al dia que se esta pidiendo.

    NO es `chartPreviousClose`. Ese campo es "el cierre anterior al COMIENZO DE
    LA VENTANA del grafico": con `range=1d` coincide con el de ayer, pero con
    `range=5d` —el que usa `--dia`— es el cierre de hace SEIS ruedas. Medido el
    2026-09-09: FTFT devolvia 1.82 cuando el cierre previo real era 1.31, un
    39% de error.

    No es cosmetico. `pc` es `Dia.prev_close`, que es el denominador de
    `expansion_pct`, que es UNO DE LOS DOS FILTROS de la operativa. Con el pc
    equivocado el filtro decide sobre un numero inventado, y ese dia queda
    mal medido sin que nada avise.

    `previousClose` si es siempre el de ayer, pero "ayer" es ayer de HOY: para
    rellenar un dia pasado tampoco sirve. Por eso, cuando se pide un dia
    concreto, el cierre previo se saca de las barras que ya vinieron en la
    misma respuesta —el ultimo cierre de sesion regular anterior a ese dia—,
    que no depende de como Yahoo llame a sus campos.
    """
    meta = res.get("meta", {})
    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    if solo_dia:
        previo = None
        for i, t in enumerate(ts):
            c = (q.get("close") or [None])[i]
            if c is None:
                continue
            t_ny = datetime.fromtimestamp(t, NY)
            if t_ny.date().isoformat() >= solo_dia:
                continue
            # Solo sesion regular: el ultimo print del post-market no es el
            # cierre, y el censo compara contra el cierre.
            if not (9.5 <= t_ny.hour + t_ny.minute / 60.0 <= 16.0):
                continue
            previo = float(c)
        if previo:
            return previo
        # El dia pedido es el primero de la ventana y no hay sesion anterior
        # adentro. Si es HOY, `previousClose` es exactamente lo que hace falta.
        if solo_dia == datetime.now(NY).date().isoformat():
            return float(meta.get("previousClose") or 0.0)
        return 0.0
    return float(meta.get("previousClose")
                 or meta.get("chartPreviousClose") or 0.0)


def cierre_oficial_previo(ticker: str, dia: str) -> float:
    """El cierre OFICIAL de la sesion anterior a `dia`, del grafico diario.

    `_cierre_previo` lo deriva de las barras de un minuto y eso es una
    aproximacion: la ultima vela del minuto no es el cierre oficial, que sale
    de la subasta. Medido el 2026-09-09 sobre los cinco papeles del dia, cuatro
    coincidian al centavo y SUNE daba 2.40 contra 2.37 — 1,3% de diferencia en
    el denominador del filtro de pre-market.

    Una llamada mas por papel, solo en el camino `--dia`, que no corre contra
    el reloj del mercado. Devuelve 0.0 si no se pudo: el que llama decide.
    """
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&range=1mo")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        res = (d.get("chart", {}).get("result") or [None])[0]
        ts = res.get("timestamp") or []
        cierres = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        previo = 0.0
        for i, t in enumerate(ts):
            if i >= len(cierres) or cierres[i] is None:
                continue
            if datetime.fromtimestamp(t, NY).date().isoformat() >= dia:
                continue
            previo = float(cierres[i])
        return previo
    except Exception:
        return 0.0


def barras_de(res: dict, *, hasta_ts: int | None = None,
              solo_dia: str | None = None) -> tuple[list[dict], float]:
    """Las barras terminadas (ts < hasta_ts) y el cierre previo.

    Los minutos sin operaciones vienen con precios nulos y se saltean: el
    indicador tampoco los escribia, y el motor camina las barras que hay.
    """
    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    pc = _cierre_previo(res, solo_dia)
    out = []
    for i, t in enumerate(ts):
        if hasta_ts is not None and t >= hasta_ts:
            continue
        c = (q.get("close") or [None])[i]
        if c is None:
            continue
        t_ny = datetime.fromtimestamp(t, NY)
        if solo_dia and t_ny.date().isoformat() != solo_dia:
            continue
        out.append({
            "t": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": c,
            "v": q["volume"][i] or 0, "_ts": t,
        })
    return out, pc


def ya_escritas(ruta=FEED) -> dict[str, int]:
    """El ultimo minuto ya escrito por simbolo, para no repetir lineas."""
    out: dict[str, int] = {}
    if not ruta.exists():
        return out
    for (tk, _f), datos in vivo.leer_feed(ruta).items():
        if datos["bars"]:
            t = int(datos["bars"][-1][0].timestamp())
            out[tk] = max(out.get(tk, 0), t)
    return out


def escribir(lineas: list[str], ruta=FEED) -> None:
    if not lineas:
        return
    with open(ruta, "a", encoding="utf-8") as fh:
        fh.write("".join(l + "\n" for l in lineas))


def ciclo(ultimo: dict[str, int], tickers: list[str]) -> tuple[int, int | None]:
    """Un ciclo: pide todos los papeles en paralelo y escribe lo nuevo.

    Devuelve (barras escritas, minuto mas reciente escrito)."""
    ahora = int(time.time())
    minuto_actual = ahora - ahora % 60
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        res = dict(zip(tickers, ex.map(pedir, tickers)))
    lineas, n, reciente = [], 0, None
    for tk in tickers:
        r = res.get(tk)
        if not r:
            continue
        barras, pc = barras_de(r, hasta_ts=minuto_actual)
        for b in barras:
            if b["_ts"] <= ultimo.get(tk, 0):
                continue
            ts = b.pop("_ts")
            lineas.append(json.dumps({"t": b["t"], "s": tk, "o": b["o"], "h": b["h"],
                                      "l": b["l"], "c": b["c"], "v": b["v"], "pc": pc},
                                     separators=(",", ":")))
            ultimo[tk] = ts
            reciente = max(reciente or 0, ts)
            n += 1
    escribir(lineas)
    return n, reciente


def en_vivo() -> int:
    print(f"  feed Yahoo -> {FEED}")
    print(f"  watchlist: {WATCHLIST}  (se relee en cada ciclo)")
    ultimo = ya_escritas()
    while True:
        t_ny = datetime.now(NY)
        if t_ny.hour + t_ny.minute / 60.0 >= ULTIMA_H_NY:
            print(f"  {t_ny:%H:%M} NY: cerro el post-market, no hay mas barras hoy.")
            return 0
        tickers = sorted(leer_watchlist())
        if not tickers:
            print(f"  {t_ny:%H:%M} NY: watchlist vacia, espero.", flush=True)
            time.sleep(INTERVALO_S)
            continue
        n, _ = ciclo(ultimo, tickers)
        # La edad de la barra mas nueva que HAY, se haya escrito en este ciclo o
        # antes: es el numero que dice si el feed esta vivo o congelado.
        reciente = max((ultimo.get(tk, 0) for tk in tickers), default=0)
        edad = (f"{(time.time() - reciente) / 60:.1f} min" if reciente else "—")
        print(f"  {t_ny:%H:%M:%S} NY · {len(tickers)} papeles · {n} barras nuevas"
              f" · ultima barra hace {edad}", flush=True)
        time.sleep(INTERVALO_S)


def rellenar(dia: str, tickers: list[str]) -> int:
    """Un dia pasado, completo, para los papeles pedidos. Yahoo da 1 minuto
    hasta ~30 dias atras (7 por pedido); se pide `5d` y se filtra el dia."""
    ultimo = ya_escritas()
    total = 0
    for tk in tickers:
        r = pedir(tk, rango="5d")
        if not r:
            print(f"  {tk}: Yahoo no respondio")
            continue
        barras, pc = barras_de(r, solo_dia=dia)
        # El oficial gana sobre el derivado de las velas; el derivado queda de
        # red por si el grafico diario no responde.
        pc = cierre_oficial_previo(tk, dia) or pc
        if not pc:
            print(f"  {tk}: sin cierre previo confiable para {dia} — NO se escribe. "
                  "Sin `pc` el filtro de pre-market decide sobre un numero vacio.")
            continue
        lineas = []
        for b in barras:
            if b["_ts"] <= ultimo.get(tk, 0):
                continue
            b.pop("_ts")
            lineas.append(json.dumps({**{"t": b["t"], "s": tk}, **{k: b[k] for k in "ohlcv"},
                                      "pc": pc}, separators=(",", ":")))
        escribir(lineas)
        total += len(lineas)
        print(f"  {tk} {dia}: {len(barras)} barras, {len(lineas)} nuevas, pc {pc}")
    return 0 if total else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Feed en vivo desde Yahoo")
    ap.add_argument("--dia", help="rellenar un dia pasado (YYYY-MM-DD) en vez de vivo")
    ap.add_argument("--tickers", help="para --dia: lista separada por comas")
    args = ap.parse_args(argv)
    if args.dia:
        tks = [t.strip().upper() for t in (args.tickers or "").split(",") if t.strip()]
        if not tks:
            tks = sorted(leer_watchlist())
        return rellenar(args.dia, tks)
    try:
        return en_vivo()
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
