#!/usr/bin/env python3
"""Etapa 5 — el peaje: ¿sobrevive el efecto después de pagar por operarlo?

Es la etapa que en la rama de bitcoin mató casi todo lo que se veía bien en
bruto. La lección de allá, textual: *"el peaje decide, no la señal"*.

**El trade que se modela.** Corto al cierre de D (que en el archivo es
D+1 00:00 UTC), cubrir al cierre de D+1. Se entra recién al cierre porque el
detector necesita el volumen del día completo: antes de eso no se sabe que D
fue un evento.

**Los costos son de futuros, no de contado.** Binance USDⓈ-M cobra 0,02% de
maker y 0,05% de taker. Entrar y salir "al cierre" es a mercado, así que son
dos taker: 0,10% de ida y vuelta. El contado cobraría el doble.

**El funding se MIDE, no se asume.** La rama de bitcoin usaba +0,006% por corte,
que es la media de BTC. En altcoins es mucho más variable y es plata real: con
tasa positiva el largo paga y **el corto cobra**. Se bajan las tasas reales por
símbolo y se suman los cortes que el trade efectivamente cruza.

Se cuentan solo los cortes **estrictamente interiores** a la ventana. Entrar
justo en un corte es ambiguo, y contarlo a favor sería inventar plata: para un
hold de 24h quedan 2 cortes (08 y 16 UTC) en vez de 3 o 4.

**El deslizamiento no se mide: se reporta la grilla entera.** Las barras son
OHLCV, sin bid/ask, así que el spread de una altcoin ilíquida es el supuesto
más grande de todo esto. Elegir la celda que conviene sería el sobreajuste que
venimos evitando; se muestran todas y que el número hable.

    python costos.py --bajar-funding
    python costos.py
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics as st
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import archivo
import config
from contraste import _baldes, cargar

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TAKER = 0.0005          # Binance USDⓈ-M, VIP0
MAKER = 0.0002

_SCHEMA = """
CREATE TABLE IF NOT EXISTS funding (
    simbolo TEXT NOT NULL,
    ts      TEXT NOT NULL,
    tasa    REAL,
    PRIMARY KEY (simbolo, ts)
) WITHOUT ROWID;
"""


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path(), timeout=60)
    con.executescript(_SCHEMA)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def bajar_funding(hilos: int = 16) -> None:
    """Solo de los símbolos que tienen eventos: el resto no se usa."""
    con = conectar()
    simbolos = [r[0] for r in con.execute(
        "SELECT DISTINCT simbolo FROM eventos "
        "WHERE rvol >= 5 AND quote_volume >= 2e6").fetchall()]
    ya = {r[0] for r in con.execute(
        "SELECT DISTINCT simbolo FROM funding").fetchall()}
    pendientes = [s for s in simbolos if s not in ya]
    print(f"símbolos con eventos: {len(simbolos)}  ·  pendientes: {len(pendientes)}")
    if not pendientes:
        print("nada que bajar")
        return

    desde, hasta = date(2025, 6, 1), date.today()

    def uno(s):
        try:
            return s, archivo.funding(s, desde, hasta)
        except Exception:
            return s, []

    hecho = total = 0
    with ThreadPoolExecutor(hilos) as ex:
        for fut in as_completed([ex.submit(uno, s) for s in pendientes]):
            s, filas = fut.result()
            hecho += 1
            if filas:
                con.executemany("INSERT OR REPLACE INTO funding VALUES (?,?,?)",
                                [(s, ts, t) for ts, t in filas])
                con.commit()
                total += len(filas)
            if hecho % 50 == 0 or hecho == len(pendientes):
                print(f"  {hecho}/{len(pendientes)}  ·  {total:,} cortes",
                      flush=True)
    print(f"listo: {total:,} tasas de funding")


def _mapa_funding(con) -> dict[str, list[tuple[str, float]]]:
    m: dict[str, list[tuple[str, float]]] = {}
    for s, ts, t in con.execute(
            "SELECT simbolo, ts, tasa FROM funding ORDER BY simbolo, ts"):
        m.setdefault(s, []).append((ts, t))
    return m


def funding_del_trade(serie, d: str, dias: int = 1) -> float:
    """Suma de tasas en los cortes estrictamente interiores al hold.

    Signo: tasa positiva → el largo paga y el corto cobra, así que para el
    corto esto entra sumando.

    `dias` es la duración REAL del hold. Se suman las tasas efectivamente
    publicadas en esa ventana en vez de extrapolar la del primer día: el
    funding de un día de evento extremo es anómalo y normaliza después, así
    que multiplicarlo por la duración exageraría el costo de los holds largos
    — y en un resultado negativo eso sería culpar al mercado de un artefacto
    propio.
    """
    import bisect
    entrada = datetime.fromisoformat(d).replace(tzinfo=timezone.utc) + timedelta(days=1)
    salida = entrada + timedelta(days=max(1, dias))
    claves = [x[0] for x in serie]
    i = bisect.bisect_right(claves, entrada.isoformat())
    j = bisect.bisect_left(claves, salida.isoformat())
    return sum(t for _, t in serie[i:j])


def analizar(min_rvol: float, min_vol: float) -> None:
    con = conectar()
    filas = cargar(con, "t1", min_rvol, min_vol, False)
    fmap = _mapa_funding(con)
    if not fmap:
        print("no hay funding — corré `python costos.py --bajar-funding`")
        return

    for f in filas:
        serie = fmap.get(f["simbolo"], [])
        f["funding"] = funding_del_trade(serie, f["d"]) if serie else 0.0

    con_funding = [f for f in filas if f["raw"] is not None]
    print("=" * 74)
    print("  COSTOS — corto al cierre de D, cubrir al cierre de D+1")
    print("=" * 74)
    print(f"\neventos            : {len(con_funding):,}")
    print(f"comisión           : taker {TAKER*100:.2f}% × 2 lados = "
          f"{TAKER*2*100:.2f}% ida y vuelta")

    fs = [f["funding"] for f in con_funding]
    print(f"funding cobrado    : mediana {st.median(fs)*100:+.4f}%   "
          f"media {st.fmean(fs)*100:+.4f}%   (a favor del corto si es positivo)")

    g = _baldes(con_funding, "crec")
    etiquetas = ["dil BAJA", "dil MEDIA", "dil ALTA"]

    print("\n\nBRUTO vs NETO por balde de dilución")
    print("(retorno del CORTO; positivo = ganancia)\n")
    print(f"  {'balde':<11} {'n':>5} {'bruto med':>11} {'neto med':>10} "
          f"{'neto medio':>11} {'sin top1%':>10}")
    for etq, gr in zip(etiquetas, g):
        r = [(-x["raw"]) for x in gr if x["raw"] is not None]
        neto = [(-x["raw"]) - 2 * TAKER + x["funding"]
                for x in gr if x["raw"] is not None]
        if not neto:
            continue
        neto_ord = sorted(neto)
        sin_cola = neto_ord[:int(len(neto_ord) * 0.99)]
        print(f"  {etq:<11} {len(r):>5} {st.median(r)*100:>10.2f}% "
              f"{st.median(neto)*100:>9.2f}% {st.fmean(neto)*100:>10.2f}% "
              f"{st.fmean(sin_cola)*100:>9.2f}%")

    print("\n\nSENSIBILIDAD AL DESLIZAMIENTO — balde de dilución ALTA")
    print("(el supuesto más grande: las barras no traen bid/ask)\n")
    alto = g[2]
    base = [(-x["raw"]) + x["funding"] for x in alto if x["raw"] is not None]
    print(f"  {'slip/lado':>10} {'costo total':>12} {'neto med':>10} "
          f"{'neto medio':>11} {'sin top1%':>10}")
    for slip in (0.0, 0.0005, 0.001, 0.002, 0.005):
        coste = 2 * TAKER + 2 * slip
        neto = [b - coste for b in base]
        ordenados = sorted(neto)
        sin_cola = ordenados[:int(len(ordenados) * 0.99)]
        print(f"  {slip*100:>9.2f}% {coste*100:>11.2f}% "
              f"{st.median(neto)*100:>9.2f}% {st.fmean(neto)*100:>10.2f}% "
              f"{st.fmean(sin_cola)*100:>9.2f}%")

    print("\n  El deslizamiento de una altcoin ilíquida en un día de volumen")
    print("  anómalo NO es el de BTC. Sin bid/ask medido, la fila que aplica")
    print("  es una de las de abajo, no la de arriba.")

    print("\n\nPOR LIQUIDEZ DEL EVENTO (volumen del día)")
    print("(el deslizamiento baja donde hay volumen: es la palanca real)\n")
    bandas = [("$2-10M", 2e6, 1e7), ("$10-50M", 1e7, 5e7),
              ("$50-200M", 5e7, 2e8), (">$200M", 2e8, 9e99)]
    print(f"  {'volumen':<10} {'n':>5} {'neto med':>10} {'neto medio':>11} "
          f"{'sin top1%':>10}")
    for nombre, lo, hi in bandas:
        sub = [x for x in alto if lo <= x["vol"] < hi and x["raw"] is not None]
        if len(sub) < 40:
            print(f"  {nombre:<10} {len(sub):>5}   (n insuficiente)")
            continue
        neto = [(-x["raw"]) + x["funding"] - 2 * TAKER - 2 * 0.001 for x in sub]
        ordenados = sorted(neto)
        sin_cola = ordenados[:int(len(ordenados) * 0.99)]
        print(f"  {nombre:<10} {len(sub):>5} {st.median(neto)*100:>9.2f}% "
              f"{st.fmean(neto)*100:>10.2f}% {st.fmean(sin_cola)*100:>9.2f}%")
    print("\n  (con deslizamiento de 0,10% por lado)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bajar-funding", action="store_true")
    p.add_argument("--min-rvol", type=float, default=5.0)
    p.add_argument("--min-vol", type=float, default=2e6)
    args = p.parse_args()

    if args.bajar_funding:
        bajar_funding()
    else:
        analizar(args.min_rvol, args.min_vol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
