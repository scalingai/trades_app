#!/usr/bin/env python3
"""El setup que pidió Agus: barrido de liquidez, VWAP, volumen anómalo y FVG.

Es vocabulario ICT y no de los indicadores clásicos, así que va aparte. Las tres
piezas, con su tesis declarada antes de medirlas:

  · BARRIDO DE LIQUIDEZ — el precio rompe un máximo previo (donde están los stops
    de los cortos y las órdenes de los que persiguen), agarra esa liquidez, y
    cierra de vuelta por debajo. La tesis: la ruptura no era demanda real sino
    ejecución contra órdenes en reposo, y cuando se acaban no queda quién compre.

  · FVG BAJISTA (fair value gap) — tres barras donde el mínimo de la primera
    queda por encima del máximo de la tercera. Hay un tramo de precio que se
    cruzó sin negociar. La tesis: el mercado tiende a volver a operar ahí, y
    entrar corto en ese hueco es entrar donde no hubo transacciones que sostengan.

  · VOLUMEN ANÓMALO — la barra opera muchas veces la mediana reciente. La tesis:
    es transferencia de posición del que entró temprano al que llega tarde.

**Y la parte que Agus pidió y que el álgebra dice que no puede funcionar.**
Stops cortos con targets cortos y alta exposición. El tamaño sale del riesgo:

    acciones = riesgo / (precio · stop%)      -> stop corto = MUCHAS acciones
    $/acción = precio · (cuánto cae capturado) -> target corto = POCOS centavos

El locate se cobra por acción. Así que stop corto multiplica el costo y target
corto divide el ingreso: las dos van en contra a la vez. Lo mido igual, porque
el álgebra dice que el punto de muerte baja pero NO dice cuánto, y si el acierto
sube lo suficiente podría compensar. Es exactamente la clase de cosa donde no
hay que confiar en el razonamiento.

    SMALLCAPS_CENSO=1 python fam_ict.py
"""

from __future__ import annotations

import random
import statistics
import sys

import motor
from chavineta import clasificar_apertura as _cl
from motor import jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES, R, PISO = 22.9, 50.0, 2.0
APERTURA_RTH = 9.5


# ------------------------------------------------------------------ señales
def sig_barrido(ventana=20, confirma=True):
    """Barrido de liquidez: rompe el máximo de las últimas `ventana` barras y
    cierra de vuelta por debajo. `confirma=False` entra en la ruptura misma,
    para separar "el barrido" de "la reversión del barrido"."""
    def f(dia):
        out = []
        for i, b in enumerate(dia.bars):
            h = _hora(b)
            if h < 10.0 or h > 15.9 or i < ventana:
                continue
            prev = dia.bars[i - ventana:i]
            techo = max((x[2] for x in prev if x[2]), default=None)
            if not techo or not (b[2] and b[4]):
                continue
            if b[2] > techo and (b[4] < techo if confirma else True):
                out.append(i)
        return out
    return f


def sig_fvg(minimo_pct=0.5):
    """FVG bajista: min(barra i-2) > max(barra i), o sea un hueco sin operar.
    Se entra en la barra que lo completa. `minimo_pct` descarta huecos
    insignificantes que son sólo ruido de un tick."""
    def f(dia):
        out = []
        for i in range(2, len(dia.bars)):
            b0, b2 = dia.bars[i - 2], dia.bars[i]
            h = _hora(b2)
            if h < 10.0 or h > 15.9:
                continue
            if not (b0[3] and b2[2] and b2[4]):
                continue
            if b0[3] > b2[2] and (b0[3] / b2[2] - 1) * 100 >= minimo_pct:
                out.append(i)
        return out
    return f


def sig_vol_anomalo(k=5, n=30):
    """Volumen anómalo: la barra opera >= k veces la mediana de las n previas."""
    def f(dia):
        out = []
        for i, b in enumerate(dia.bars):
            h = _hora(b)
            if h < 10.0 or h > 15.9 or i < n:
                continue
            m = statistics.median([x[5] or 0 for x in dia.bars[i - n:i]])
            if m > 0 and (b[5] or 0) >= k * m:
                out.append(i)
        return out
    return f


def _hora(b):
    from dias import hora
    return hora(b)


def con_piso(sig):
    return lambda d: [i for i in sig(d) if (d.bars[i][4] or 0) >= PISO]


def y(*sigs):
    """Intersección: la barra tiene que estar en TODAS las señales."""
    def f(d):
        s = set(sigs[0](d))
        for g in sigs[1:]:
            s &= set(g(d))
        return sorted(s)
    return f


def o(*sigs):
    """Unión: alcanza con estar en alguna."""
    def f(d):
        s = set()
        for g in sigs:
            s |= set(g(d))
        return sorted(s)
    return f


def bajo_vwap(sig):
    return lambda d: [i for i in sig(d)
                      if d.bars[i][4] and d.bars[i][4] < d.vwap[i]]


# ------------------------------------------------------------------ medición
def medir(pob, sig, stop, objetivo=None):
    S = []
    for d in pob:
        j = jornada(d, sig, lado="short", stop_pct=stop, riesgo=R,
                    max_trades=40, objetivo_pct=objetivo)
        if not j:
            continue
        ev = []
        for t in j["detalle"]:
            ev.append((t["h_ent"], +t["acciones"]))
            ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0,
                       -t["acciones"]))
        ev.sort(key=lambda x: (x[0], -x[1]))
        a = pa = 0.0
        for _, da in ev:
            a += da
            pa = max(pa, a)
        gan = sum(1 for t in j["detalle"] if t["pnl"] > 0)
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"],
                  "gan": gan})
    if len(S) < 15:
        return None

    def c(g):
        if len(g) < 12:
            return None
        b = statistics.mean(x["pnl"] for x in g)
        a = statistics.mean(x["acc"] for x in g)
        return 100 * b / a if a else 0

    b = statistics.mean(x["pnl"] for x in S)
    acc = statistics.mean(x["acc"] for x in S)
    ses = len({x["d"] for x in S}) / MESES
    tr = sum(x["tr"] for x in S)
    return {"n": len(S), "ses": ses, "tr": tr / MESES, "acc": acc,
            "cents": 100 * b / acc if acc else 0, "mes": b * ses,
            "acierto": 100 * sum(x["gan"] for x in S) / tr if tr else 0,
            "p1": c([x for x in S if x["d"] < motor.CORTE]),
            "p2": c([x for x in S if x["d"] >= motor.CORTE])}


def fila(lab, r):
    f1 = f"{r['p1']:>6.0f}c" if r["p1"] is not None else f"{'s/dato':>7}"
    f2 = f"{r['p2']:>6.0f}c" if r["p2"] is not None else f"{'s/dato':>7}"
    return (f"  {lab:<34} {r['ses']:>6.1f} {r['tr']:>6.0f} {r['acierto']:>6.0f}% "
            f"{r['acc']:>7.0f} {r['cents']:>7.0f}c {f1} {f2} {r['mes']:>+10.2f}")


def main() -> int:
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    print(f"  POBLACIÓN: reclaim · sin expansión · precio ≥ ${PISO:.0f} · {len(pob)} días\n")
    cab = (f"  {'setup':<34} {'ses/m':>6} {'tr/m':>6} {'acier':>6} {'acc':>7} "
           f"{'muerte':>8} {'P1':>7} {'P2':>7} {'bruto/mes':>10}")

    print("  1) LAS SEÑALES SUELTAS, con el stop y la salida de la casa (45%, al cierre)\n")
    print(cab)
    print("  " + "-" * 100)
    base = medir(pob, con_piso(señales_swing_10), 45.0)
    if base:
        print(fila("swing (la base)", base))
    SEÑALES = [
        ("barrido de liquidez (confirmado)", con_piso(sig_barrido(20, True))),
        ("barrido sin confirmar", con_piso(sig_barrido(20, False))),
        ("FVG bajista", con_piso(sig_fvg())),
        ("volumen anómalo 5x", con_piso(sig_vol_anomalo(5))),
        ("volumen anómalo 3x", con_piso(sig_vol_anomalo(3))),
        ("barrido + bajo vwap", bajo_vwap(con_piso(sig_barrido(20, True)))),
        ("FVG + bajo vwap", bajo_vwap(con_piso(sig_fvg()))),
        ("barrido O FVG O vol5x",
         con_piso(o(sig_barrido(20, True), sig_fvg(), sig_vol_anomalo(5)))),
    ]
    guardados = {}
    for lab, s in SEÑALES:
        r = medir(pob, s, 45.0)
        if not r:
            print(f"  {lab:<34}   (muestra corta)")
            continue
        guardados[lab] = s
        print(fila(lab, r))

    print("\n  2) STOPS Y TARGETS CORTOS con alta exposición — lo que pidió Agus\n")
    print("  El álgebra dice que stop corto multiplica las acciones y target corto")
    print("  divide los centavos. Acá se ve cuánto de cada cosa.\n")
    print(cab)
    print("  " + "-" * 100)
    combo = con_piso(o(sig_barrido(20, True), sig_fvg(), sig_vol_anomalo(5)))
    for stop, obj in ((45.0, None), (20.0, None), (12.0, None), (8.0, None),
                      (5.0, None), (12.0, 12.0), (8.0, 8.0), (5.0, 5.0),
                      (5.0, 10.0), (8.0, 16.0)):
        r = medir(pob, combo, stop, obj)
        if not r:
            continue
        lab = f"stop {stop:.0f}%" + (f" · target {obj:.0f}%" if obj else " · al cierre")
        print(fila(lab, r))

    print("\n  3) EL NULO: entradas al azar con la misma frecuencia\n")
    nulos = []
    for s in range(20):
        rnd = random.Random(s)
        def azar(d, _rnd=rnd):
            cand = [i for i in range(len(d.bars))
                    if 10.0 <= _hora(d.bars[i]) <= 15.9
                    and (d.bars[i][4] or 0) >= PISO]
            k = max(1, len(cand) // 12)
            return sorted(_rnd.sample(cand, min(k, len(cand))))
        r = medir(pob, azar, 45.0)
        if r:
            nulos.append(r["cents"])
    nulos.sort()
    if nulos:
        print(f"  {len(nulos)} corridas al azar · p50 {nulos[len(nulos)//2]:.0f}c "
              f"· MÁXIMO {nulos[-1]:.0f}c")
        print("\n  Cualquier setup que no supere ese máximo no está aportando nada")
        print("  que no aporte tirar la moneda con la misma frecuencia.")
    return 0


def señales_swing_10(d):
    return señales_swing(d, desde=10.0)


if __name__ == "__main__":
    raise SystemExit(main())
