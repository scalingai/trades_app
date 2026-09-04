#!/usr/bin/env python3
"""¿Comprar el gapper en pre-market, antes de shortearlo a las 10:00, deja plata?

LA IDEA (Agus, 2026-09-04): "si es potencial caída, seguro hay una subida desde
antes". Y la razón de fondo es de costos: lo que hunde la cuenta chica —el
locate y la comisión mínima— NO existe para un long de 100 acciones en
TradeZero. Si la subida de pre-market se puede comprar, sería plata casi sin
costo fijo.

LA DERIVA CRUDA ES ENORME Y ES TRAMPA. En los 1.522 papeles-día del censo, de
07:00 a 09:29 la mediana es +9,9% y el 71% sube. Pero el censo son papeles que
gaparon >=25% A LAS 09:30: a las 07:00 muchos todavía no lo habían hecho, y
"comprar a las 07:00 lo que va a gapear" es mirar el futuro. Acá la entrada
sólo se permite cuando el gap YA ES VISIBLE en esa barra (precio >= 1,25 x
cierre previo), que es lo que un scanner de pre-market mostraría.

LO QUE NO SE PUEDE MEDIR CON BARRAS DE 1 MINUTO: el spread y si te llenan. En
pre-market de small caps el spread es 1-3% y la cinta es finita. Se cobra un
spread por lado a elección (0,5%, 1%, 2%) y una liquidez mínima en los diez
minutos previos a la entrada. El resultado con 2% es el que hay que creer.

LAS REGLAS, simples a propósito —un scalping de tres minutos no se mide con
barras de un minuto—:

  base       comprar en la primera barra con gap visible; mide la deriva
  ruptura    cierre por arriba del máximo de pre-market, con ese máximo de al
             menos 15 minutos (una consolidación, no la barra anterior)
  vwap       cruce por arriba del VWAP acumulado, después de >=5 barras abajo
  retroceso  después de estar >=5% arriba del VWAP, toca el VWAP (1,5%) y
             cierra arriba

Salidas: stop fijo (3%, 5%, 8%) o la última barra antes de las 09:30. Una
entrada por papel-día. Placebo: los mismos días, la misma salida, la entrada
en un minuto al azar con gap visible — 100 sorteos. Si la regla no le gana al
placebo, la regla no es nada; la deriva es del papel, no de la regla.

    python test_premarket_long.py

RESULTADO (2026-09-04). Tres cosas, en orden de importancia:

1. **EL CENSO NO PUEDE MEDIR ESTO.** Los eventos del censo se eligen por gap
   >= 25% A LA APERTURA (RESEARCH.md §4.duovigies), y se verificó: de los 1.467
   papeles-día con gap visible a las 07:00, CERO abrieron abajo de +25%. Todo
   papel que subió 30% a las 07:00 y se derrumbó antes de las 09:30 quedó
   afuera de la muestra por construcción. Es sesgo de supervivencia en la
   dirección exacta del long: lo que se mide acá es un TECHO, no una
   estimación.

2. Aun con ese sesgo a favor, las reglas de entrada son PEORES que entrar al
   azar el mismo día (placebo p0): comprar la ruptura del máximo de pre-market
   da -2,4% a -3,0% de media. Es coherente con todo lo medido en el proyecto:
   el máximo de pre-market es lo que se fadea, no lo que se compra.

3. Lo único positivo es comprar en la PRIMERA barra con gap visible (mediana
   07:06) y aguantar hasta las 09:30 sin stop: +4,5% de media con 1% de
   spread por lado, +2,4% con 2%. Pero la mediana es NEGATIVA (-0,6%), el 5%
   mejor de los trades aporta el 99% del total, y un stop de 3-8% contra los
   mínimos del pre-market lo convierte en -2,4%. Es un billete de lotería
   medido sobre una muestra que no incluye los billetes perdedores.

Veredicto: no se implementa. Si se quiere medir de verdad hace falta una
población elegida A LAS 07:00 —el escáner en modo pre-market más el feed
desde las 07:00, día por día, con los que después se derrumban adentro—.
Eso es prospectivo: dos o tres meses de datos antes de volver a mirar.
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from chavineta import clasificar_apertura as _cl
from dias import APERTURA_RTH, hora
from motor import poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

H_INI, H_FIN = 7.0, 9.4          # ventana de entrada en pre-market
GAP_VISIBLE = 25.0               # % sobre el cierre previo, EN la barra de entrada
LIQ_MIN = 2_000.0                # $/minuto en los 10 minutos previos
COMISION_MIN, COMISION_ACC, LOTE = 0.49, 0.005, 100
SPREADS = (0.005, 0.01, 0.02)    # por lado
STOPS = (3.0, 5.0, 8.0)
SEMILLAS = 100


def gap_visible(dia, i):
    c = dia.bars[i][4]
    return bool(c and dia.prev_close and c / dia.prev_close - 1 >= GAP_VISIBLE / 100)


def _entrables(dia):
    """Las barras donde se puede entrar, calculadas UNA vez por dia.

    `Dia.liquidez_en(h)` busca el indice por hora recorriendo las barras desde
    el principio: llamado por cada barra es cuadratico, y multiplicado por
    doce combinaciones y cien sorteos del placebo no termina nunca. Aca la
    liquidez se mide por indice, con la misma definicion: la mediana de
    $/minuto de los diez minutos ANTERIORES."""
    if hasattr(dia, "_entr"):
        return dia._entr
    out = set()
    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h > H_FIN:
            break
        if h < H_INI or i < 10 or not gap_visible(dia, i):
            continue
        v = [(x[5] or 0) * (x[4] or 0) for x in dia.bars[i - 10:i]]
        if statistics.median(v) >= LIQ_MIN:
            out.add(i)
    dia._entr = out
    return out


def entrable(dia, i):
    return i in _entrables(dia)


def señal_base(dia, i):
    return True


def señal_ruptura(dia, i):
    if i == 0:
        return False
    c = dia.bars[i][4]
    return bool(c and c > dia.max_corriente[i - 1] and dia.edad_max[i - 1] >= 15)


def señal_vwap(dia, i):
    if i < 6:
        return False
    abajo = all((dia.bars[k][4] or 0) < dia.vwap[k] for k in range(i - 5, i))
    c = dia.bars[i][4]
    return bool(abajo and c and c > dia.vwap[i])


def señal_retroceso(dia, i):
    if i < 10:
        return False
    estuvo_arriba = any((dia.bars[k][4] or 0) >= dia.vwap[k] * 1.05
                        for k in range(max(0, i - 60), i))
    lo, c, v = dia.bars[i][3], dia.bars[i][4], dia.vwap[i]
    if not (estuvo_arriba and lo and c and v):
        return False
    return lo <= v * 1.015 and c > v


REGLAS = {"base": señal_base, "ruptura": señal_ruptura,
          "vwap": señal_vwap, "retroceso": señal_retroceso}


def simular(dia, i_ent, *, stop_pct, spread):
    """Un long desde el cierre de la barra `i_ent` hasta el stop o las 09:30.

    Devuelve (pct neto de spread, hora de salida, motivo). El stop se
    chequea contra el MINIMO de cada barra —si lo tocó, salió ahí— y el
    spread se paga en las dos puntas."""
    p_ent = dia.bars[i_ent][4] * (1 + spread)
    p_stop = p_ent * (1 - stop_pct / 100)
    ultimo = None
    for k in range(i_ent + 1, len(dia.bars)):
        b = dia.bars[k]
        if hora(b) >= APERTURA_RTH:
            break
        if not b[4]:
            continue
        ultimo = k
        if b[3] and b[3] <= p_stop:
            return (p_stop * (1 - spread) / p_ent - 1) * 100, hora(b), "stop"
    if ultimo is None:
        return None
    p_sal = dia.bars[ultimo][4] * (1 - spread)
    return (p_sal / p_ent - 1) * 100, hora(dia.bars[ultimo]), "09:30"


def entradas(dia, señal):
    """La primera barra entrable que dispara la señal, o None."""
    for i in range(len(dia.bars)):
        if hora(dia.bars[i]) > H_FIN:
            break
        if entrable(dia, i) and señal(dia, i):
            return i
    return None


def candidatas(dia):
    return sorted(_entrables(dia))


def dolares(pct, p_ent, *, riesgo, stop_pct):
    """Lo que deja el trade a un riesgo dado, con la comisión de TradeZero."""
    acc = riesgo / (p_ent * stop_pct / 100)
    com = 0.0 if acc >= LOTE else 2 * max(COMISION_MIN, acc * COMISION_ACC)
    return acc * p_ent * pct / 100 - com


def resumen(trades):
    """trades: lista de (fecha, pct, p_ent, stop_pct, apertura)."""
    if not trades:
        return None
    pcts = [t[1] for t in trades]
    fechas = sorted({t[0] for t in trades})
    mitad = fechas[len(fechas) // 2]
    a = [t[1] for t in trades if t[0] < mitad]
    b = [t[1] for t in trades if t[0] >= mitad]
    usd20 = sum(dolares(t[1], t[2], riesgo=20, stop_pct=t[3]) for t in trades)
    usd75 = sum(dolares(t[1], t[2], riesgo=75, stop_pct=t[3]) for t in trades)
    # drawdown de la curva en $ a riesgo 75, por trade
    eq = pico = dd = 0.0
    for t in sorted(trades):
        eq += dolares(t[1], t[2], riesgo=75, stop_pct=t[3])
        pico = max(pico, eq)
        dd = min(dd, eq - pico)
    return {"n": len(trades), "gana": 100 * sum(1 for p in pcts if p > 0) / len(pcts),
            "mediana": statistics.median(pcts), "media": statistics.mean(pcts),
            "m1": statistics.mean(a) if a else float("nan"),
            "m2": statistics.mean(b) if b else float("nan"),
            "usd20": usd20, "usd75": usd75, "dd75": dd,
            "reclaim": 100 * sum(1 for t in trades if t[4] == "reclaim") / len(trades)}


def correr(pob, señal, *, stop_pct, spread):
    out = []
    for d in pob:
        i = entradas(d, señal)
        if i is None:
            continue
        r = simular(d, i, stop_pct=stop_pct, spread=spread)
        if r is None:
            continue
        out.append((d.d, r[0], d.bars[i][4] * (1 + spread), stop_pct, d._apertura))
    return out


def placebo(pob, dias_regla, *, stop_pct, spread, semillas=SEMILLAS):
    """Los mismos dias que la regla, entrada al azar entre las barras entrables."""
    por_dia = {d.d + d.ticker: d for d in pob}
    cands = {k: candidatas(d) for k, d in por_dia.items() if k in dias_regla}
    medias = []
    for s in range(semillas):
        random.seed(s)
        pcts = []
        for k, cs in cands.items():
            if not cs:
                continue
            i = random.choice(cs)
            r = simular(por_dia[k], i, stop_pct=stop_pct, spread=spread)
            if r is not None:
                pcts.append(r[0])
        if pcts:
            medias.append(statistics.mean(pcts))
    return medias


if __name__ == "__main__":
    pob = list(poblacion(universo(), min_ratio_vol=0.0, min_expansion=0.0,
                         min_dolar=0.0, max_float=47e6))
    for d in pob:
        d._apertura = _cl(d, hasta=10.0)
    pob.sort(key=lambda d: (d.d, d.ticker))
    meses = len({d.d[:7] for d in pob})
    print(f"\n  LONG EN PRE-MARKET · {len(pob)} papeles-día · {meses} meses · entrada "
          f"{H_INI:.0f}:00–{int(H_FIN)}:{int(60*(H_FIN%1)):02d} con gap visible >= {GAP_VISIBLE:.0f}%"
          f" y >= ${LIQ_MIN:,.0f}/min · salida al stop o 09:30\n")

    spread = 0.01
    print(f"  == spread {100*spread:.1f}% por lado ==")
    print("  {:<10} {:>5} {:>5} {:>6} {:>5} {:>7} {:>7} {:>7} {:>8} {:>8} {:>8} {:>7} {:>9}".format(
        "regla", "stop", "n", "gana%", "recl%", "mediana", "media", "1ªmit", "2ªmit",
        "$@20", "$@75", "dd@75", "placebo"))
    print("  " + "-" * 108)
    for nombre, señal in REGLAS.items():
        for stop in STOPS:
            tr = correr(pob, señal, stop_pct=stop, spread=spread)
            r = resumen(tr)
            if not r:
                print(f"  {nombre:<10} {stop:>4.0f}%  sin trades")
                continue
            dias = {t[0] for t in tr}
            claves = {d.d + d.ticker for d in pob if d.d in dias and entradas(d, señal) is not None}
            pl = placebo(pob, claves, stop_pct=stop, spread=spread)
            pct_pl = 100 * sum(1 for m in pl if m < r["media"]) / len(pl) if pl else float("nan")
            mediana_pl = statistics.median(pl) if pl else float("nan")
            print("  {:<10} {:>4.0f}% {:>5} {:>5.0f}% {:>4.0f}% {:>+6.1f}% {:>+6.1f}% {:>+6.1f}% {:>+7.1f}%"
                  " {:>+8,.0f} {:>+8,.0f} {:>+8,.0f} {:>+5.1f}%/p{:.0f}".format(
                      nombre, stop, r["n"], r["gana"], r["reclaim"], r["mediana"], r["media"],
                      r["m1"], r["m2"], r["usd20"], r["usd75"], r["dd75"], mediana_pl, pct_pl))
    print()
    print("  placebo: media del placebo (misma frecuencia) y en qué percentil del placebo cae la regla.")
    print("  p50 es 'igual que al azar'; p95+ es que la regla agrega algo sobre la deriva del papel.")
    print("  recl%: cuántos de esos días terminaron siendo reclaim (los que se shortean a las 10:00).")

    print("\n  == la mejor regla, por spread ==")
    mejor = None
    for nombre, señal in REGLAS.items():
        for stop in STOPS:
            r = resumen(correr(pob, señal, stop_pct=stop, spread=spread))
            if r and (mejor is None or r["usd75"] > mejor[2]["usd75"]):
                mejor = (nombre, stop, r)
    if mejor:
        nombre, stop, _ = mejor
        print("  {:<10} {:>5} {:>7} {:>5} {:>7} {:>8} {:>8} {:>8}".format(
            "regla", "stop", "spread", "n", "media", "$@20", "$@75", "dd@75"))
        print("  " + "-" * 64)
        for sp in SPREADS:
            r = resumen(correr(pob, REGLAS[nombre], stop_pct=stop, spread=sp))
            print("  {:<10} {:>4.0f}% {:>6.1f}% {:>5} {:>+6.1f}% {:>+8,.0f} {:>+8,.0f} {:>+8,.0f}".format(
                nombre, stop, 100 * sp, r["n"], r["media"], r["usd20"], r["usd75"], r["dd75"]))
        print(f"\n  ${'{:,.0f}'.format(mejor[2]['usd75'])} a $75 en {meses} meses son "
              f"${mejor[2]['usd75'] * 12 / meses:,.0f}/año antes de nada más. "
              f"La estrategia short a $75 deja ~$3.600/año neto.")
