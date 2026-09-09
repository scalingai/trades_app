#!/usr/bin/env python3
"""La watchlist del censo armada DESPUES, con el gap real medido en las velas.

POR QUE EXISTE. `escaner.py` lee el gap de un campo de Yahoo que sólo dice lo
que el censo mide mientras el día no arrancó: en pre-market o apenas abre. Más
tarde ese campo es el movimiento acumulado, y con el mercado cerrado es el día
entero. Por eso `escaner.py` ahora se niega a escribir fuera de hora.

Pero negarse no alcanza: si prendés la máquina a las 11 de Nueva York, te
quedás sin lista y sin día. Y el día igual pasó.

Acá el gap no se lee de ningún campo: **se mide**. Cierre oficial de la sesión
anterior contra la primera vela de las 09:30, las dos de las barras de un
minuto que Yahoo entrega hasta siete días para atrás. Eso es exactamente lo que
define `poblacion_observable.py`, y no depende de la hora a la que preguntes.

    python reconstruir.py                    # hoy
    python reconstruir.py --dia 2026-09-08   # un día que ya pasó
    python reconstruir.py --escribir         # además deja watchlist.txt

EL LIMITE, Y HAY QUE DECIRLO. El universo de candidatos sale igual del screener
de Yahoo, que ordena por movimiento ACTUAL. Un papel que gapeó 30% y para el
mediodía volvió a +2% puede no aparecer en el pool, y entonces no se reconstruye
aunque fuera del censo. Por eso el pool se pide con un umbral MUCHO más bajo que
el del censo (`POOL_GAP`): trae de más para no perder, y el filtro real lo hace
la medición sobre las velas. Aun así, la lista reconstruida es un PISO de lo que
hubo, no una garantía. La única fuente que no tiene este sesgo es el censo de
Polygon (`poblacion_observable.py`), que ve el mercado entero pero recién al día
siguiente.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(AQUI / "puente"))

import config
from escaner import (GAP_MIN, LIQ_MIN, NY, OTC, PISO_OPERATIVO, PRECIO_MAX,
                     PRECIO_MIN, Yahoo, escribir, liquidez_de)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# El pool se pide MUY por debajo del censo a propósito: el screener ordena por
# el movimiento de ahora, y un gapper que se desinfló queda abajo. Traer de más
# cuesta llamadas; perder un papel cuesta el día.
POOL_GAP = 5.0
MAX_CANDIDATOS = 70          # techo de llamadas: una por papel
APERTURA_H = 9.5


def _yf():
    """Import tardío: `yahoo_feed` importa de `escaner`, y esto de los dos."""
    import yahoo_feed
    return yahoo_feed


def gap_real(ticker: str, dia: str) -> dict | None:
    """El gap medido: primera vela de las 09:30 contra el cierre oficial previo.

    Devuelve None si falta cualquiera de los dos. No inventa: sin cierre previo
    no hay gap, y un gap inventado es peor que un papel de menos.
    """
    yf = _yf()
    hoy = datetime.now(NY).date().isoformat()
    r = yf.pedir(ticker, rango="1d" if dia == hoy else "5d")
    if not r:
        return None
    barras, _ = yf.barras_de(r, solo_dia=dia)
    if not barras:
        return None
    prev = yf.cierre_oficial_previo(ticker, dia)
    if not prev:
        return None

    # La hora de Nueva York de cada barra, del timestamp UTC del propio dato.
    from datetime import timezone
    rth = []
    pm_dolar = 0.0
    for b in barras:
        t = datetime.strptime(b["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).astimezone(NY)
        h = t.hour + t.minute / 60.0
        if h < APERTURA_H:
            pm_dolar += (b["v"] or 0) * (b["c"] or 0)
        else:
            rth.append(b)
    if not rth:
        return None
    apertura = rth[0]["o"]
    if not apertura:
        return None
    return {"ticker": ticker, "prev": prev, "apertura": float(apertura),
            "gap": (float(apertura) / prev - 1.0) * 100.0,
            "maximo": max((b["h"] or 0) for b in rth),
            "cierre": rth[-1]["c"], "pm_dolar": pm_dolar,
            "barras": len(barras)}


def candidatos(y: Yahoo, verboso: bool = False) -> dict[str, dict]:
    """Pool amplio de tickers con sus cotizaciones, para podar antes de medir."""
    pool: dict[str, dict] = {}
    for fila in y.screener(gap=POOL_GAP):
        if fila.get("symbol"):
            pool[fila["symbol"]] = fila
    n0 = len(pool)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for filas in ex.map(y.predefinido,
                            ("day_gainers", "small_cap_gainers", "most_actives")):
            for fila in filas:
                if fila.get("symbol"):
                    pool.setdefault(fila["symbol"], fila)
    if verboso:
        print(f"  pool: {n0} del screener (gap>={POOL_GAP:.0f}%) + "
              f"{len(pool)-n0} de los predefinidos = {len(pool)}")
    if not pool:
        return {}
    qs = {q["symbol"]: q for q in y.cotizaciones(sorted(pool)) if q.get("symbol")}
    return qs


def reconstruir(y: Yahoo, dia: str, *, gap_min: float, verboso: bool = False):
    qs = candidatos(y, verboso)
    if not qs:
        return []
    # Podar por lo que se puede saber sin bajar velas: OTC y banda de precio.
    # `regularMarketPreviousClose` sirve de proxy; el precio de verdad lo
    # confirma `gap_real` con el cierre oficial.
    previos = []
    for tk, q in qs.items():
        if (q.get("exchange") or "").upper() in OTC:
            continue
        prev = q.get("regularMarketPreviousClose")
        if prev and not (PRECIO_MIN * 0.5 <= float(prev) <= PRECIO_MAX * 2):
            continue
        previos.append((tk, abs(float(q.get("regularMarketChangePercent") or 0))))
    previos.sort(key=lambda x: -x[1])
    lista = [tk for tk, _ in previos[:MAX_CANDIDATOS]]
    if verboso:
        print(f"  midiendo el gap real de {len(lista)} papeles sobre sus velas...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        medidos = [m for m in ex.map(lambda t: gap_real(t, dia), lista) if m]

    salida, descartes = [], {}

    def fuera(por):
        descartes[por] = descartes.get(por, 0) + 1

    for m in medidos:
        q = qs.get(m["ticker"], {})
        if m["gap"] < gap_min:
            fuera(f"gap real < {gap_min:.0f}%"); continue
        if not (PRECIO_MIN <= m["prev"] <= PRECIO_MAX):
            fuera("precio previo fuera de $0.20–$20"); continue
        liq = liquidez_de(q)
        if liq is None or liq < LIQ_MIN:
            fuera("liquidez previa < $150k"); continue
        salida.append({"ticker": m["ticker"], "precio": m["apertura"],
                       "gap": m["gap"], "origen": "velas 09:30",
                       "prev": m["prev"], "liq": liq,
                       "float": q.get("sharesOutstanding"),
                       "maximo": m["maximo"], "cierre": m["cierre"]})
    if verboso and descartes:
        print("  descartes:", " · ".join(f"{v} por {k}" for k, v in
                                         sorted(descartes.items(), key=lambda x: -x[1])))
    salida.sort(key=lambda x: -x["gap"])
    return salida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Watchlist del censo, medida sobre las velas")
    ap.add_argument("--dia", help="YYYY-MM-DD (por defecto hoy)")
    ap.add_argument("--gap", type=float, default=GAP_MIN)
    ap.add_argument("--piso", type=float, default=PISO_OPERATIVO)
    ap.add_argument("--escribir", action="store_true",
                    help="deja watchlist.txt con lo reconstruido")
    a = ap.parse_args(argv)

    ahora = datetime.now(NY)
    dia = a.dia or ahora.date().isoformat()
    print(f"reconstruir · día {dia} · ahora {ahora:%H:%M} Nueva York")
    print(f"  el gap NO se lee de Yahoo: se mide (cierre oficial previo vs vela de 09:30)\n")

    y = Yahoo()
    y.autenticar()
    papeles = reconstruir(y, dia, gap_min=a.gap, verboso=True)
    print(f"  {y.llamadas} llamadas a Yahoo\n")

    if not papeles:
        print("Ningún papel del censo ese día (o el pool no lo alcanzó — ver el "
              "límite en el encabezado del archivo).")
        return 0

    arriba = [p for p in papeles if p["precio"] >= a.piso]
    print(f"{len(papeles)} pasan el censo con el gap MEDIDO"
          + (f", {len(arriba)} además el piso de ${a.piso:.2f}" if len(arriba) != len(papeles) else "") + "\n")
    print(f"  {'papel':<7} {'prev':>8} {'abre':>8} {'GAP':>8} {'máx':>8} "
          f"{'cierra':>8} {'liquidez':>11}")
    for p in papeles:
        marca = " " if p["precio"] >= a.piso else "·"
        print(f"{marca} {p['ticker']:<7} ${p['prev']:>7.2f} ${p['precio']:>7.2f} "
              f"{p['gap']:>+7.0f}% ${p['maximo']:>7.2f} ${p['cierre']:>7.2f} "
              f"${p['liq']/1e6:>9.1f}M")

    if not a.escribir:
        print("\nNo se escribió nada. Para dejar la watchlist:")
        print(f"  python reconstruir.py{' --dia ' + a.dia if a.dia else ''} --escribir")
        return 0
    ruta = Path(config.data_dir()) / "watchlist.txt"
    escribir(arriba, ruta, piso=a.piso,
             momento=f"RECONSTRUIDA del día {dia}: el gap sale de las velas de "
                     f"09:30, no del campo de Yahoo. Puede faltar algún papel "
                     f"que gapeó y se desinfló antes de que el pool lo viera.")
    print(f"\nEscritos {len(arriba)} papeles en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
