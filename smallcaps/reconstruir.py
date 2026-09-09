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


def del_censo_local(dia: str) -> list[str] | None:
    """Los papeles del censo de ESE dia, de la base local. None si no la cubre.

    ESTA ES LA FUENTE BUENA Y HAY QUE PREFERIRLA SIEMPRE. La tabla `events`
    sale de las barras diarias de TODO el mercado (`backfill_daily.py` +
    `detect_events.py`), asi que ve los ~15.000 tickers y no depende de que un
    papel siga moviendose hoy.

    El pool de Yahoo, en cambio, se ordena por el movimiento ACTUAL: un papel
    que gapeo 30% el martes y para el miercoles esta quieto no aparece. Medido
    el 2026-09-09: reconstruir el 8 por el pool devolvio CERO papeles, y el
    censo local devolvio cinco (ARBE, BNC, MOBX, PDSB, WYHG). No es que el
    martes no hubiera nada; es que el pool no lo veia.

    Devuelve None —no lista vacia— cuando la base no llega a ese dia, para que
    el que llama sepa la diferencia entre "no hubo" y "no se".
    """
    import sqlite3
    from escaner import GAP_MIN, LIQ_MIN, PRECIO_MAX, PRECIO_MIN
    db = sqlite3.connect(config.bars_db_path())
    try:
        tope = db.execute("SELECT max(d) FROM events").fetchone()[0]
        if not tope or dia > tope:
            return None
        return [t for (t,) in db.execute(
            """SELECT ticker FROM events
               WHERE d = ? AND gap_pct >= ? AND med_dollar_volume >= ?
                 AND prev_close BETWEEN ? AND ?
               ORDER BY gap_pct DESC""",
            (dia, GAP_MIN, LIQ_MIN, PRECIO_MIN, PRECIO_MAX))]
    except sqlite3.OperationalError:
        return None
    finally:
        db.close()


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
    # PRIMERO LA BASE LOCAL. Ve el mercado entero y no depende de que el papel
    # siga moviendose hoy; el pool de Yahoo es el plan B.
    locales = del_censo_local(dia)
    if locales is not None:
        if verboso:
            print(f"  censo local: {len(locales)} papeles el {dia} "
                  "(barras diarias de todo el mercado)")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            medidos = [m for m in ex.map(lambda t: gap_real(t, dia), locales) if m]
        salida = []
        for m in medidos:
            salida.append({"ticker": m["ticker"], "precio": m["cierre"] or m["apertura"],
                           "gap": m["gap"], "origen": "censo local",
                           "prev": m["prev"], "liq": None, "float": None,
                           "apertura": m["apertura"], "maximo": m["maximo"],
                           "cierre": m["cierre"]})
        salida.sort(key=lambda x: -x["gap"])
        return salida

    if verboso:
        print("  el censo local no llega a ese día: voy por el pool de Yahoo "
              "(puede faltar algún papel, ver el encabezado del archivo)")
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
        # EL PRECIO DE REFERENCIA ES EL ULTIMO, NO EL DE LA APERTURA.
        #
        # `vivo.papel_sospechoso` compara ese numero contra la ULTIMA vela del
        # feed para detectar que el simbolo no sea otro instrumento. Con la
        # apertura adentro, un papel que corrio 30% en el dia —o sea, todos los
        # nuestros— dispara la alarma solo. Paso con SUNE: abrio 3,00 y quedo en
        # 3,90, y la pantalla lo marco como "puede ser otro papel".
        salida.append({"ticker": m["ticker"], "precio": m["cierre"] or m["apertura"],
                       "gap": m["gap"], "origen": "velas 09:30",
                       "prev": m["prev"], "liq": liq, "apertura": m["apertura"],
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
                    help="deja watchlist.txt con lo reconstruido (sólo para HOY)")
    ap.add_argument("--velas", action="store_true",
                    help="además baja las barras de ese día al feed, para poder "
                         "navegarlo en /vivo")
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
        # DOS CAUSAS QUE NO SE PARECEN Y ANTES DECIAN LO MISMO. Si el censo
        # local SI tenia papeles ese dia y aun asi no salio ninguno, no es que
        # no hubo: es que Yahoo no da velas de minuto tan atras (guarda ~7
        # dias). Decir "ningun papel" ahi es afirmar algo falso sobre el
        # mercado cuando el problema es del proveedor.
        locales = del_censo_local(dia)
        if locales:
            print(f"El censo local dice que ese día hubo {len(locales)} papeles "
                  f"({', '.join(locales)}), pero Yahoo no devolvió velas de "
                  "minuto para ninguno.")
            print("  Yahoo guarda ~7 días de barras de 1 minuto. Para un día más "
                  "viejo hay que traerlas de Polygon:")
            print("    python poblacion_observable.py      (baja los minutos del censo)")
        else:
            print("Ningún papel del censo ese día (o el pool no lo alcanzó — ver "
                  "el límite en el encabezado del archivo).")
        return 0

    arriba = [p for p in papeles if p["precio"] >= a.piso]
    print(f"{len(papeles)} pasan el censo con el gap MEDIDO"
          + (f", {len(arriba)} además el piso de ${a.piso:.2f}" if len(arriba) != len(papeles) else "") + "\n")
    print(f"  {'papel':<7} {'prev':>8} {'abre 9:30':>10} {'GAP':>8} {'máx':>8} "
          f"{'último':>8} {'liquidez':>11}")
    for p in papeles:
        marca = " " if p["precio"] >= a.piso else "·"
        print(f"{marca} {p['ticker']:<7} ${p['prev']:>7.2f} ${p['apertura']:>9.2f} "
              f"{p['gap']:>+7.0f}% ${p['maximo']:>7.2f} ${p['cierre']:>7.2f} "
              + (f"${p['liq']/1e6:>9.1f}M" if p.get("liq") else f"{'—':>11}"))

    if a.velas:
        # UN DIA QUE NO TIENE BARRAS NO SE PUEDE NAVEGAR, Y NO AVISA: la flecha
        # de "día anterior" simplemente lo saltea. El 2026-09-08 quedó así
        # porque el feed no estaba corriendo, y desde /vivo se veía como si el
        # 9 viniera después del 4.
        #
        # Las barras se piden por ticker con `--dia`, que ya sabe sacar el
        # cierre previo correcto de la sesión anterior. No se toca
        # `watchlist.txt`: la watchlist es de HOY, y pisarla con la de un día
        # viejo dejaría el feed en vivo siguiendo papeles de otra fecha.
        tks = [x["ticker"] for x in papeles]
        print(f"\nBajando las velas del {dia} de {len(tks)} papeles...", flush=True)
        yf = _yf()
        total = 0
        for tk in tks:
            r = yf.pedir(tk, rango="5d")
            if not r:
                print(f"  {tk}: Yahoo no respondió")
                continue
            barras, _ = yf.barras_de(r, solo_dia=dia)
            pc = yf.cierre_oficial_previo(tk, dia)
            if not pc:
                print(f"  {tk}: sin cierre previo confiable, no lo escribo")
                continue
            ya = yf.ya_escritas()
            import json as _json
            lineas = []
            for b in barras:
                ts = b.pop("_ts")
                if ts <= ya.get(tk, 0):
                    continue
                lineas.append(_json.dumps(
                    {"t": b["t"], "s": tk, "o": b["o"], "h": b["h"], "l": b["l"],
                     "c": b["c"], "v": b["v"], "pc": pc}, separators=(",", ":")))
            yf.escribir(lineas)
            total += len(lineas)
            print(f"  {tk} {dia}: {len(barras)} barras, {len(lineas)} nuevas, pc {pc:.2f}")
        print(f"\n{total} barras nuevas. Ya se puede navegar el {dia} en /vivo.")

    if not a.escribir:
        print("\nNo se escribió nada. Para dejar la watchlist:")
        print(f"  python reconstruir.py{' --dia ' + a.dia if a.dia else ''} --escribir")
        return 0
    hoy = ahora.date().isoformat()
    if dia != hoy:
        print(f"\nNO escribo watchlist.txt: la lista es del {dia} y la watchlist "
              f"es la de HOY ({hoy}). Pisarla dejaría al feed en vivo siguiendo "
              "papeles de otra fecha.")
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
