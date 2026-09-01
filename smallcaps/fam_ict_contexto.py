#!/usr/bin/env python3
"""ICT con contexto de sesión + patrones de vela, con la búsqueda controlada.

**Qué cambia respecto de `fam_ict.py`.** Aquella versión usaba niveles
arbitrarios —el máximo de las últimas 20 barras— y dio 8 centavos. Ésta usa los
niveles que pone el mercado, que es lo que distingue a ICT de un indicador
cualquiera:

    · máximo del PRE-MARKET
    · máximo del DÍA PREVIO
    · el hueco de valor (FVG) que NADIE rellenó

La lógica de barrido fallido viene de `test_ict.py`, de una ronda anterior de
este proyecto: no alcanza con romper el nivel, hay que romperlo y volver abajo.
Ahí está la tesis — la ruptura ejecutó contra órdenes en reposo y no contra
demanda real.

**Y el problema de método, que es el que importa.** Agus pidió "iterar en
distintos parámetros hasta encontrar uno". Con suficientes parámetros SIEMPRE
aparece uno: es el mecanismo por el que se fabrican estrategias que existen
sólo en el archivo donde se fabricaron. Ya sabemos que el hallazgo principal
del proyecto tiene p=0,6% y NO sobrevive la corrección por búsqueda múltiple.

La versión honesta de "iterar hasta encontrar" es ésta:

    1. la grilla se declara ENTERA antes de correr — está en CONFIGS
    2. se corre toda y se reporta toda, no sólo la mejor
    3. se generan EXACTAMENTE la misma cantidad de configuraciones AZAROSAS
    4. se compara el mejor real contra el mejor azaroso

Si el mejor real no le gana al mejor azaroso con los mismos tiros, lo que
encontramos fue la búsqueda. Sin el paso 3 el resultado no significa nada, por
lindo que se vea el número.

    SMALLCAPS_CENSO=1 python fam_ict_contexto.py
"""

from __future__ import annotations

import itertools
import random
import sqlite3
import statistics
import sys

import config
import motor
from chavineta import clasificar_apertura as _cl
from dias import APERTURA_RTH, hora
from motor import jornada, poblacion, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES, R, PISO, DESDE = 22.9, 50.0, 2.0, 10.0


# --------------------------------------------------- el máximo del día previo
def _maximos_previos():
    """{(ticker, fecha): máximo del día hábil anterior}. Es el nivel que ICT
    llama 'previous day high', y no se puede derivar de las barras de minuto
    del propio día — hay que ir a las diarias."""
    c = sqlite3.connect(config.bars_db_path())
    filas = c.execute("SELECT ticker, d, h FROM bars_daily ORDER BY ticker, d")
    out, prev_tk, prev_d, prev_h = {}, None, None, None
    for tk, d, h in filas:
        if tk == prev_tk and prev_h is not None:
            out[(tk, d)] = prev_h
        prev_tk, prev_d, prev_h = tk, d, h
    c.close()
    return out


MAX_PREV = None


# ------------------------------------------------------------------- señales
# Cada una devuelve los índices de barra donde ENTRAR. Sólo miran bars[:i+1].

def sig_barrido_premarket(dia):
    """Barrió el máximo del pre-market y volvió abajo. La tesis: arriba de ese
    nivel estaban los stops de los cortos de la madrugada; una vez ejecutados,
    no queda quién compre."""
    pre = [b[2] for b in dia.bars if hora(b) < APERTURA_RTH and b[2]]
    if not pre:
        return []
    nivel = max(pre)
    out, barrido = [], False
    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h < APERTURA_RTH:
            continue
        if b[2] and b[2] > nivel:
            barrido = True
        elif barrido and h >= DESDE and b[4] and b[4] < nivel:
            out.append(i)
    return out


def sig_barrido_dia_previo(dia):
    """Ídem con el máximo del día previo — el nivel más mirado de todos."""
    nivel = (MAX_PREV or {}).get((dia.ticker, dia.d))
    if not nivel:
        return []
    out, barrido = [], False
    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h < APERTURA_RTH:
            continue
        if b[2] and b[2] > nivel:
            barrido = True
        elif barrido and h >= DESDE and b[4] and b[4] < nivel:
            out.append(i)
    return out


def sig_fvg_sin_rellenar(dia):
    """FVG bajista que nadie rellenó todavía: el hueco sigue abierto EN ESE
    MINUTO. Es la diferencia con la versión de `fam_ict.py`, que sólo miraba
    que el hueco existiera."""
    out = []
    for i in range(2, len(dia.bars)):
        h = hora(dia.bars[i])
        if h < DESDE or h > 15.9:
            continue
        a = dia.bars[i - 2]
        c = dia.bars[i]
        if not (a[3] and c[2]) or a[3] <= c[2]:
            continue
        # ¿alguien volvió a operar dentro del hueco entre que se formó y ahora?
        relleno = any(x[2] and x[2] >= a[3] for x in dia.bars[i - 1:i + 1])
        if not relleno:
            out.append(i)
    return out


# ------------------------------------------------------- patrones de vela
def _pat(fn):
    def f(dia):
        return [i for i in range(2, len(dia.bars))
                if DESDE <= hora(dia.bars[i]) <= 15.9 and fn(dia.bars, i)]
    return f


def _envolvente(bars, i):
    """Envolvente bajista: la vela abarca entera a la anterior y cierra abajo."""
    a, b = bars[i - 1], bars[i]
    if not all((a[1], a[4], b[1], b[4])):
        return False
    return a[4] > a[1] and b[4] < b[1] and b[1] >= a[4] and b[4] <= a[1]


def _mecha_superior(bars, i):
    """Estrella fugaz: la mecha de arriba es al menos el doble del cuerpo."""
    b = bars[i]
    if not all((b[1], b[2], b[3], b[4])) or b[2] <= b[3]:
        return False
    cuerpo = abs(b[4] - b[1])
    mecha = b[2] - max(b[1], b[4])
    return cuerpo > 0 and mecha >= 2 * cuerpo and mecha >= 0.5 * (b[2] - b[3])


def _doji(bars, i):
    """Doji: cuerpo menor al 10% del rango. Indecisión después de una corrida."""
    b = bars[i]
    if not all((b[1], b[2], b[3], b[4])) or b[2] <= b[3]:
        return False
    return abs(b[4] - b[1]) <= 0.1 * (b[2] - b[3])


def _outside_bajista(bars, i):
    """Barra externa bajista: hace máximo más alto y mínimo más bajo, cierra abajo."""
    a, b = bars[i - 1], bars[i]
    if not all((a[2], a[3], b[2], b[3], b[1], b[4])):
        return False
    return b[2] > a[2] and b[3] < a[3] and b[4] < b[1]


SEÑALES = [
    ("barrido premarket", sig_barrido_premarket),
    ("barrido dia previo", sig_barrido_dia_previo),
    ("FVG sin rellenar", sig_fvg_sin_rellenar),
    ("vela: envolvente bajista", _pat(_envolvente)),
    ("vela: mecha superior", _pat(_mecha_superior)),
    ("vela: doji", _pat(_doji)),
    ("vela: outside bajista", _pat(_outside_bajista)),
]


# ------------------------------------------------------------ combinadores
def con_piso(sig):
    return lambda d: [i for i in sig(d) if (d.bars[i][4] or 0) >= PISO]


def union(*sigs):
    def f(d):
        s = set()
        for g in sigs:
            s |= set(g(d))
        return sorted(s)
    return f


def cerca(sig_a, sig_b, minutos=5):
    """A confirmado por B dentro de `minutos`. Es la forma en que un operador
    usa dos señales: no exige que caigan en el mismo minuto exacto, que es
    demasiado estricto y por eso las intersecciones puras dan muestra cero."""
    def f(d):
        bs = set(sig_b(d))
        return [i for i in sig_a(d)
                if any((i + k) in bs for k in range(-minutos, minutos + 1))]
    return f


# ------------------------------------------------------------------ medición
def medir(pob, sig, stop=45.0, objetivo=None):
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
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"],
                  "gan": sum(1 for t in j["detalle"] if t["pnl"] > 0)})
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
    return (f"  {lab:<38} {r['ses']:>6.1f} {r['tr']:>6.0f} {r['acierto']:>5.0f}% "
            f"{r['acc']:>6.0f} {r['cents']:>7.0f}c {f1} {f2} {r['mes']:>+9.2f}")


def main() -> int:
    global MAX_PREV
    MAX_PREV = _maximos_previos()
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    print(f"  POBLACIÓN: reclaim · precio ≥ ${PISO:.0f} · {len(pob)} días")
    print(f"  máximos del día previo disponibles: {len(MAX_PREV):,}\n")
    cab = (f"  {'setup':<38} {'ses/m':>6} {'tr/m':>6} {'acier':>6} {'acc':>6} "
           f"{'muerte':>8} {'P1':>7} {'P2':>7} {'bruto/mes':>9}")

    # --- la grilla, declarada entera antes de correr -----------------------
    CONFIGS = []
    for lab, s in SEÑALES:
        CONFIGS.append((lab, con_piso(s)))
    for (la, sa), (lb, sb) in itertools.combinations(SEÑALES, 2):
        CONFIGS.append((f"{la} + {lb} (5 min)",
                        con_piso(cerca(sa, sb, 5))))
    CONFIGS.append(("las 3 de ICT (unión)",
                    con_piso(union(sig_barrido_premarket,
                                   sig_barrido_dia_previo,
                                   sig_fvg_sin_rellenar))))
    CONFIGS.append(("las 4 velas (unión)",
                    con_piso(union(*[s for l, s in SEÑALES if l.startswith("vela")]))))
    print(f"  GRILLA DECLARADA: {len(CONFIGS)} configuraciones\n")

    print("  1) TODA LA GRILLA — ordenada por centavos por acción\n")
    print(cab)
    print("  " + "-" * 104)
    from sesion import señales_swing
    base = medir(pob, con_piso(lambda d: señales_swing(d, desde=DESDE)))
    if base:
        print(fila("swing (la base del proyecto)", base))
        print()
    res = []
    for lab, s in CONFIGS:
        r = medir(pob, s)
        if r:
            res.append((r["cents"], lab, r))
    res.sort(reverse=True)
    for c, lab, r in res:
        print(fila(lab, r))

    # --- el nulo, con EXACTAMENTE la misma cantidad de intentos ------------
    print(f"\n  2) EL NULO — {len(CONFIGS)} configuraciones AZAROSAS, "
          "una por cada real\n")
    tasas = [r["tr"] for _, _, r in res] or [50]
    nulos = []
    for k in range(len(CONFIGS)):
        rnd = random.Random(1000 + k)
        objetivo = tasas[k % len(tasas)]
        def azar(d, _r=rnd, _o=objetivo):
            cand = [i for i in range(len(d.bars))
                    if DESDE <= hora(d.bars[i]) <= 15.9
                    and (d.bars[i][4] or 0) >= PISO]
            if not cand:
                return []
            k2 = max(1, int(len(cand) * min(1.0, _o / 300.0)))
            return sorted(_r.sample(cand, min(k2, len(cand))))
        r = medir(pob, azar)
        if r:
            nulos.append(r["cents"])
    nulos.sort()
    if nulos and res:
        q = lambda p: nulos[int(p * (len(nulos) - 1))]
        print(f"  {len(nulos)} nulos · p50 {q(.50):.0f}c · p90 {q(.90):.0f}c · "
              f"MÁXIMO {nulos[-1]:.0f}c")
        print(f"\n  mejor de la grilla real:  {res[0][1]:<34} {res[0][0]:.0f}c")
        print(f"  mejor de la grilla azar:  {'(sin tesis)':<34} {nulos[-1]:.0f}c")
        gana = res[0][0] > nulos[-1]
        print(f"  -> {'LE GANA' if gana else 'NO le gana'} al azar con la misma "
              "cantidad de intentos")
        if base:
            print(f"\n  y contra lo que ya teníamos: {base['cents']:.0f}c de la base")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
