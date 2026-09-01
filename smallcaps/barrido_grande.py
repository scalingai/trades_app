#!/usr/bin/env python3
"""El barrido grande, con el nulo emparejado por frecuencia.

Agus pidió iterar parámetros hasta encontrar uno que funcione. Con suficientes
intentos siempre aparece; la pregunta es si aparece MÁS SEGUIDO de lo que
aparecería tirando la moneda. Este archivo lo contesta bien.

**Por qué el nulo tiene que estar emparejado por frecuencia, y no sólo ser
grande.** En la corrida anterior ganó una configuración de 0,8 sesiones al mes
con 18 centavos, y su primera mitad ni siquiera tenía muestra para medirse. No
ganó por buena: ganó porque con pocos trades la varianza es enorme y el máximo
de una muestra chica es alto por construcción. Compararla contra un nulo de
frecuencia promedio la favorece de arriba.

Así que el nulo se construye POR TRAMO DE FRECUENCIA: para cada configuración
real se mira la distribución de los nulos que operan aproximadamente la misma
cantidad, y de ahí sale su percentil. Una configuración de 20 trades al mes se
compara contra nulos de 20 trades al mes, no contra el promedio de todos.

El estadístico que se reporta es el percentil de cada configuración dentro de su
propio tramo, y después el MÁXIMO de esos percentiles sobre toda la grilla — que
es lo que hay que comparar contra lo que da el máximo de una grilla de puro azar
del mismo tamaño.

    SMALLCAPS_CENSO=1 python barrido_grande.py
    SMALLCAPS_CENSO=1 python barrido_grande.py --nulos 400
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import statistics
import sys
from collections import defaultdict

import config
import motor
from chavineta import clasificar_apertura as _cl
from dias import APERTURA_RTH, hora
from fam_ict_contexto import _maximos_previos
from motor import jornada, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
MESES, R, PISO, DESDE = 22.9, 50.0, 2.0, 10.0
MAX_PREV = {}


# ---------------------------------------------------------- señales con parámetro
def barrido(nivel_de, holgura_pct=0.0, confirma_min=0):
    """Barrido de un nivel: lo supera y vuelve abajo. `holgura_pct` exige que lo
    supere por un margen; `confirma_min` exige que siga abajo N minutos."""
    def f(dia):
        niv = nivel_de(dia)
        if not niv:
            return []
        techo = niv * (1 + holgura_pct / 100.0)
        out, barrido_ya, bajo_desde = [], False, None
        for i, b in enumerate(dia.bars):
            h = hora(b)
            if h < APERTURA_RTH:
                continue
            if b[2] and b[2] > techo:
                barrido_ya, bajo_desde = True, None
            elif barrido_ya and b[4] and b[4] < niv:
                if bajo_desde is None:
                    bajo_desde = i
                if h >= DESDE and (i - bajo_desde) >= confirma_min:
                    out.append(i)
        return out
    return f


def niv_premarket(dia):
    v = [b[2] for b in dia.bars if hora(b) < APERTURA_RTH and b[2]]
    return max(v) if v else None


def niv_dia_previo(dia):
    return MAX_PREV.get((dia.ticker, dia.d))


def niv_apertura(dia, minutos=15):
    v = [b[2] for b in dia.bars
         if APERTURA_RTH <= hora(b) < APERTURA_RTH + minutos / 60.0 and b[2]]
    return max(v) if v else None


def fvg(min_pct=0.5, exigir_sin_rellenar=True):
    def f(dia):
        out = []
        for i in range(2, len(dia.bars)):
            h = hora(dia.bars[i])
            if h < DESDE or h > 15.9:
                continue
            a, c = dia.bars[i - 2], dia.bars[i]
            if not (a[3] and c[2]) or a[3] <= c[2]:
                continue
            if (a[3] / c[2] - 1) * 100 < min_pct:
                continue
            if exigir_sin_rellenar and any(
                    x[2] and x[2] >= a[3] for x in dia.bars[i - 1:i + 1]):
                continue
            out.append(i)
        return out
    return f


def vela(tipo, k=2.0):
    def f(dia):
        out = []
        for i in range(2, len(dia.bars)):
            h = hora(dia.bars[i])
            if h < DESDE or h > 15.9:
                continue
            a, b = dia.bars[i - 1], dia.bars[i]
            if not all((b[1], b[2], b[3], b[4])) or b[2] <= b[3]:
                continue
            rango, cuerpo = b[2] - b[3], abs(b[4] - b[1])
            if tipo == "envolvente":
                ok = (all((a[1], a[4])) and a[4] > a[1] and b[4] < b[1]
                      and b[1] >= a[4] and b[4] <= a[1])
            elif tipo == "mecha":
                ok = cuerpo > 0 and (b[2] - max(b[1], b[4])) >= k * cuerpo
            elif tipo == "doji":
                ok = cuerpo <= (k / 100.0) * rango
            elif tipo == "outside":
                ok = (all((a[2], a[3])) and b[2] > a[2] and b[3] < a[3]
                      and b[4] < b[1])
            elif tipo == "cierre_bajo":
                ok = (b[4] - b[3]) / rango <= k
            else:
                ok = False
            if ok:
                out.append(i)
        return out
    return f


def con_piso(sig):
    return lambda d: [i for i in sig(d) if (d.bars[i][4] or 0) >= PISO]


def cerca(a, b, minutos):
    def f(d):
        s = set(b(d))
        return [i for i in a(d)
                if any((i + k) in s for k in range(-minutos, minutos + 1))]
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
        S.append({"d": d.d, "pnl": j["pnl"], "acc": pa, "tr": j["trades"]})
    if len(S) < 15:
        return None
    b = statistics.mean(x["pnl"] for x in S)
    acc = statistics.mean(x["acc"] for x in S)

    def c(g):
        if len(g) < 12:
            return None
        bb = statistics.mean(x["pnl"] for x in g)
        aa = statistics.mean(x["acc"] for x in g)
        return 100 * bb / aa if aa else 0

    return {"n": len(S), "ses": len({x["d"] for x in S}) / MESES,
            "tr": sum(x["tr"] for x in S) / MESES,
            "cents": 100 * b / acc if acc else 0, "mes": b * len({x["d"] for x in S}) / MESES,
            "p1": c([x for x in S if x["d"] < motor.CORTE]),
            "p2": c([x for x in S if x["d"] >= motor.CORTE])}


def construir_grilla():
    """LA GRILLA ENTERA, declarada antes de correr nada."""
    base = []
    for nom, niv in (("pre", niv_premarket), ("prev", niv_dia_previo),
                     ("or15", lambda d: niv_apertura(d, 15)),
                     ("or30", lambda d: niv_apertura(d, 30))):
        for hol in (0.0, 0.5, 1.0):
            for conf in (0, 2, 5):
                base.append((f"barrido {nom} h{hol} c{conf}",
                             barrido(niv, hol, conf)))
    for p in (0.2, 0.5, 1.0, 2.0):
        for sr in (True, False):
            base.append((f"fvg {p}% {'sin-rell' if sr else 'con-rell'}",
                         fvg(p, sr)))
    for t, ks in (("envolvente", [0]), ("mecha", [1.5, 2.0, 3.0]),
                  ("doji", [5, 10, 20]), ("outside", [0]),
                  ("cierre_bajo", [0.2, 0.33, 0.5])):
        for k in ks:
            base.append((f"vela {t} k{k}", vela(t, k)))

    grilla = [(l, con_piso(s)) for l, s in base]
    # pares con ventana de confirmación
    fuertes = [x for x in base if x[0].startswith(("barrido pre h0.0 c0",
                                                   "barrido prev h0.0 c0",
                                                   "fvg 0.5", "vela envolvente",
                                                   "vela mecha k2.0"))]
    for (la, sa), (lb, sb) in itertools.combinations(fuertes, 2):
        for m in (3, 5, 10):
            grilla.append((f"{la} + {lb} ({m}m)", con_piso(cerca(sa, sb, m))))
    return grilla


def main(argv=None) -> int:
    global MAX_PREV
    ap = argparse.ArgumentParser(description="Barrido grande con nulo emparejado")
    ap.add_argument("--nulos", type=int, default=300)
    args = ap.parse_args(argv)

    MAX_PREV = _maximos_previos()
    dias = universo()
    pob = [d for d in poblacion(dias, min_ratio_vol=0.0, min_expansion=0.0,
                                min_dolar=0.0, max_float=47e6)
           if _cl(d, hasta=10.0) == "reclaim"]
    grilla = construir_grilla()
    print(f"  POBLACIÓN: reclaim · precio ≥ ${PISO:.0f} · {len(pob)} días")
    print(f"  GRILLA: {len(grilla)} configuraciones · NULOS: {args.nulos}\n", flush=True)

    base = medir(pob, con_piso(lambda d: señales_swing(d, desde=DESDE)))
    if base:
        print(f"  la base del proyecto: {base['cents']:.0f}c · "
              f"{base['ses']:.1f} ses/mes · {base['tr']:.0f} tr/mes\n", flush=True)

    print("  corriendo la grilla...", flush=True)
    reales = []
    for k, (lab, s) in enumerate(grilla, 1):
        r = medir(pob, s)
        if r:
            reales.append((lab, r))
        if k % 25 == 0:
            print(f"    {k}/{len(grilla)}", flush=True)
    print(f"    {len(reales)} con muestra suficiente\n", flush=True)

    print(f"  corriendo {args.nulos} nulos...", flush=True)
    nulos = []
    for k in range(args.nulos):
        rnd = random.Random(90000 + k)
        frac = 10 ** rnd.uniform(-2.4, -0.3)      # cubre todo el rango de frecuencia

        def azar(d, _r=rnd, _f=frac):
            cand = [i for i in range(len(d.bars))
                    if DESDE <= hora(d.bars[i]) <= 15.9
                    and (d.bars[i][4] or 0) >= PISO]
            if not cand:
                return []
            n = max(1, int(len(cand) * _f))
            return sorted(_r.sample(cand, min(n, len(cand))))
        r = medir(pob, azar)
        if r:
            nulos.append(r)
        if (k + 1) % 50 == 0:
            print(f"    {k + 1}/{args.nulos}", flush=True)
    print(f"    {len(nulos)} nulos válidos\n", flush=True)

    # ---- percentil de cada real dentro de su TRAMO de frecuencia
    def tramo(tr):
        if tr < 15: return "  <15 tr/mes"
        if tr < 40: return " 15-40 tr/mes"
        if tr < 100: return " 40-100 tr/mes"
        if tr < 200: return "100-200 tr/mes"
        return "  >200 tr/mes"

    por_tramo = defaultdict(list)
    for r in nulos:
        por_tramo[tramo(r["tr"])].append(r["cents"])
    for t in por_tramo:
        por_tramo[t].sort()

    print("  EL NULO POR TRAMO DE FRECUENCIA — la varianza depende de cuántos trades\n")
    print(f"  {'tramo':<16} {'nulos':>6} {'p50':>8} {'p90':>8} {'p99':>8} {'máximo':>8}")
    print("  " + "-" * 60)
    for t in sorted(por_tramo):
        v = por_tramo[t]
        if len(v) < 5:
            print(f"  {t:<16} {len(v):>6}   (pocos)")
            continue
        q = lambda p: v[int(p * (len(v) - 1))]
        print(f"  {t:<16} {len(v):>6} {q(.50):>7.0f}c {q(.90):>7.0f}c "
              f"{q(.99):>7.0f}c {v[-1]:>7.0f}c")

    def percentil(r):
        v = por_tramo.get(tramo(r["tr"]), [])
        if len(v) < 5:
            return None
        return 100 * sum(1 for x in v if x < r["cents"]) / len(v)

    marcados = [(percentil(r), lab, r) for lab, r in reales]
    marcados = [(p, l, r) for p, l, r in marcados if p is not None]
    marcados.sort(reverse=True)

    print(f"\n  LAS 15 MEJORES POR PERCENTIL DENTRO DE SU TRAMO\n")
    print(f"  {'setup':<44} {'ses/m':>6} {'tr/m':>6} {'muerte':>8} "
          f"{'P1':>7} {'P2':>7} {'pctil':>7}")
    print("  " + "-" * 92)
    for p, lab, r in marcados[:15]:
        f1 = f"{r['p1']:>6.0f}c" if r["p1"] is not None else f"{'s/dato':>7}"
        f2 = f"{r['p2']:>6.0f}c" if r["p2"] is not None else f"{'s/dato':>7}"
        print(f"  {lab[:44]:<44} {r['ses']:>6.1f} {r['tr']:>6.0f} "
              f"{r['cents']:>7.0f}c {f1} {f2} {p:>6.1f}%")

    # ---- el veredicto: ¿cuántas superan lo que superaría el azar?
    print(f"""
  EL VEREDICTO

  Con {len(marcados)} configuraciones probadas, el azar produce configuraciones
  en el percentil 99 de su propio tramo aproximadamente {len(marcados) * 0.01:.1f}
  veces por pura casualidad. Las que estén en el 99+ hay que contarlas contra
  ese número, no contra cero.
""")
    p99 = [x for x in marcados if x[0] >= 99]
    p95 = [x for x in marcados if x[0] >= 95]
    print(f"    en el percentil 99+ : {len(p99)}  (esperadas por azar: "
          f"{len(marcados) * 0.01:.1f})")
    print(f"    en el percentil 95+ : {len(p95)}  (esperadas por azar: "
          f"{len(marcados) * 0.05:.1f})")
    if base:
        mejor_c = max(r["cents"] for _, r in reales)
        print(f"\n    mejor de la grilla: {mejor_c:.0f}c   ·   "
              f"la base del proyecto: {base['cents']:.0f}c")

    ruta = config.data_dir() / "barrido_grande.json"
    ruta.write_text(json.dumps(
        [{"setup": l, "pctil": p, **{k: v for k, v in r.items()}}
         for p, l, r in marcados], ensure_ascii=False), encoding="utf-8")
    print(f"\n  resultado completo en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
