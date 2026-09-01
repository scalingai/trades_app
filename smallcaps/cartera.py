#!/usr/bin/env python3
"""La cartera: qué estrategias poner en cada cuenta para llegar a $20.000.

**El problema, planteado bien.** No estamos buscando la mejor estrategia. Estamos
buscando el mejor CONJUNTO de estrategias para repartir entre 3 cuentas de
fondeo. Y son dos problemas distintos, porque la simulación de 24 meses mostró
el mes 13: con la misma señal en las tres cuentas, **las tres revientan el mismo
día** y se pierden tres meses reconstruyendo.

Una cuenta reventada no es una pérdida de dinero (el piso son los $97 de la
evaluación) — es una pérdida de TIEMPO, que es el recurso escaso: hay entre 3 y
10 sesiones operables por mes según la estrategia. Por eso la correlación entre
estrategias importa más que el rendimiento de cada una.

CÓMO SE MIDE ACÁ, y por qué así:

  · Cada cuenta corre UNA estrategia. En una fecha donde esa estrategia no opera,
    la cuenta no hace nada — y ahí está la decorrelación real: no es que los
    retornos estén poco correlacionados, es que **ni siquiera operan los mismos
    días**.
  · El locate se cobra sobre el NOMINAL de cada estrategia, que cada una reporta
    por separado. Una estrategia de nominal chico paga menos locate y por eso
    puede ser mejor socia aunque su PnL sea menor.
  · Los cortos pagan locate; los largos NO. Se distingue por el campo `lado`.
  · El objetivo NO es el retorno esperado sino **P(llegar a $20.000)** y el
    tiempo mediano en lograrlo. Son problemas de primer paso, y ahí una cartera
    con menos media pero menos varianza puede ganarle a una más rentable.

    python cartera.py                    # el ranking de combinaciones
    python cartera.py --locate 0.10
    python cartera.py --meta 20000 --cuentas 3
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import sqlite3
import statistics
import sys
from pathlib import Path

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TOPE_USD = 1000.0      # tope de drawdown de la cuenta de $20.000 (5%)
OBJ = 1.2              # objetivo de la evaluación: +6% contra -5%
EVAL_USD = 97.0
SPLIT = 0.70
CUSHION = 0.25
F = 0.28               # riesgo por sesión como fracción del tope


def cargar(min_ses_mes=1.5, max_brecha=15.0, min_n=30):
    """Estrategias con su serie. Se descartan las que no replican.

    El filtro de replicación es el que hace que esto no sea un ejercicio de
    sobreajuste: una estrategia cuya brecha entre P1 y P2 supera 15 puntos
    encontró ruido, y meterla en una cartera es propagar ese ruido.
    """
    c = sqlite3.connect(config.data_dir() / "trades.sqlite")
    c.row_factory = sqlite3.Row
    out = {}
    for r in c.execute("SELECT * FROM estrategia"):
        if r["n"] is None or r["n"] < min_n:
            continue
        if (r["ses_mes"] or 0) < min_ses_mes:
            continue
        if r["replica"] is not None and r["replica"] > max_brecha:
            continue
        serie = {d: (p, n) for d, p, n in c.execute(
            "SELECT d,pnl_R,nominal_R FROM sesion WHERE estrategia=?",
            (r["nombre"],))}
        if not serie:
            continue
        out[r["nombre"]] = {
            "nombre": r["nombre"], "familia": r["familia"], "lado": r["lado"],
            "ses_mes": r["ses_mes"], "ret_nom": r["ret_nom"],
            "bruto_R": r["bruto_R"], "nom_R": r["nom_R"],
            "replica": r["replica"], "serie": serie,
        }
    c.close()
    return out


def correlacion(a, b):
    """Correlación sobre las fechas COMPARTIDAS. None si casi no se solapan.

    Que devuelva None no es un fallo: significa que las dos estrategias operan
    días distintos, o sea decorrelación por construcción, que es mejor que una
    correlación baja medida sobre retornos.
    """
    comunes = sorted(set(a) & set(b))
    if len(comunes) < 20:
        return None
    x = [a[d][0] for d in comunes]
    y = [b[d][0] for d in comunes]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if not sx or not sy:
        return None
    return sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / (sx * sy)


def calendario_real():
    """Todos los días hábiles del censo, no sólo los que alguna estrategia opera.

    **Este es el arreglo de un error que inflaba todo por 2,7x.** Antes el
    calendario se armaba con la unión de las fechas operadas, y como el
    simulador cuenta 21 días por mes, una estrategia que opera 6 veces al mes
    recibía 21 oportunidades mensuales. El resultado salía casi tres veces más
    rápido de lo posible.

    El calendario tiene que ser el del MERCADO; que una estrategia no opere un
    día es justamente su tasa de oportunidad, y es lo que limita cuán rápido se
    puede llegar a una meta.
    """
    import pickle
    ruta = Path(config.data_dir()) / "universo.pkl"
    if ruta.exists():
        with open(ruta, "rb") as fh:            # caché escrito por motor.py
            return sorted({d.d for d in pickle.load(fh)})
    c = sqlite3.connect(config.data_dir() / "trades.sqlite")
    out = sorted({r[0] for r in c.execute("SELECT DISTINCT d FROM sesion")})
    c.close()
    return out


def solape(a, b):
    """Fracción de fechas compartidas sobre la unión. 0 = poblaciones disjuntas."""
    u = len(set(a) | set(b))
    return len(set(a) & set(b)) / u if u else 0.0


def simular(combo, calendario, locate, meta, max_meses=48, semilla=0, f=F,
            tope=TOPE_USD, eval_usd=EVAL_USD, split=SPLIT):
    """Una corrida. Cada cuenta corre UNA estrategia. Devuelve (meses, caja).

    `meses` es None si no llegó a la meta dentro del horizonte.
    """
    rnd = random.Random(semilla)
    n_cta = len(combo)
    # Camino común de fechas, por bloques de 15 días hábiles para preservar
    # las rachas: si se remuestrea día por día se destruye el agrupamiento de
    # los días malos y el drawdown sale artificialmente bajo.
    largo = max_meses * 21
    camino = []
    while len(camino) < largo:
        i = rnd.randrange(0, max(1, len(calendario) - 15))
        camino += calendario[i:i + 15]
    camino = camino[:largo]

    estado = ["eval"] * n_cta
    eq = [0.0] * n_cta
    caja = -n_cta * eval_usd
    dia_del_mes = 0
    nuevo = [False] * n_cta

    for k, fecha in enumerate(camino):
        for c, est in enumerate(combo):
            if estado[c] == "muerta":
                continue
            s = est["serie"].get(fecha)
            if not s:
                continue                      # esa estrategia no opera ese día
            pnl_R, nom_R = s
            costo = locate * nom_R if est["lado"] == "short" else 0.0
            eq[c] += (pnl_R - costo) * f
            if eq[c] <= -1.0:
                estado[c] = "muerta"
            elif estado[c] == "eval" and eq[c] >= OBJ:
                estado[c] = "fondeada"
                eq[c] = 0.0
                nuevo[c] = True

        dia_del_mes += 1
        if dia_del_mes >= 21:                 # cierre de mes: cobro y recompras
            dia_del_mes = 0
            for c in range(n_cta):
                if estado[c] == "fondeada" and not nuevo[c] and eq[c] > CUSHION:
                    caja += (eq[c] - CUSHION) * tope * split
                    eq[c] = CUSHION
            nuevo = [False] * n_cta
            for c in range(n_cta):
                if estado[c] == "muerta":
                    caja -= eval_usd
                    estado[c] = "eval"
                    eq[c] = 0.0
            if caja >= meta:
                return (k + 1) / 21.0, caja
    return None, caja


def evaluar_combo(combo, calendario, locate, meta, corridas, max_meses, f=F):
    res = [simular(combo, calendario, locate, meta, max_meses, s, f)
           for s in range(corridas)]
    llego = [r[0] for r in res if r[0] is not None]
    cajas = sorted(r[1] for r in res)
    return {
        "p_llega": 100 * len(llego) / len(res),
        "meses_med": statistics.median(llego) if llego else None,
        "meses_p90": (sorted(llego)[int(.9 * len(llego))] if llego else None),
        "caja_med": cajas[len(cajas) // 2],
        "caja_p10": cajas[int(.1 * len(cajas))],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cartera de estrategias por cuenta")
    ap.add_argument("--locate", type=float, default=0.20)
    ap.add_argument("--meta", type=float, default=20000.0)
    ap.add_argument("--cuentas", type=int, default=3)
    ap.add_argument("--corridas", type=int, default=400)
    ap.add_argument("--max-meses", type=int, default=48)
    ap.add_argument("--f", type=float, default=F)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)

    ests = cargar()
    if len(ests) < args.cuentas:
        print(f"  Sólo hay {len(ests)} estrategias que replican. "
              "Corré primero las familias (fam_*.py, salidas.py).")
        return 1

    print("=" * 100)
    print(f"  CARTERA — meta ${args.meta:,.0f} · {args.cuentas} cuentas · "
          f"locate {args.locate:.0%} · f={args.f}")
    print(f"  {len(ests)} estrategias que replican (brecha P1-P2 < 15 puntos)")
    print("=" * 100)

    # Sólo las que sobreviven al locate por sí solas entran a las combinaciones:
    # una estrategia con neto negativo sólo puede aportar decorrelación, y no
    # compensa quemar una cuenta entera en ella.
    viables = {k: v for k, v in ests.items()
               if v["bruto_R"] - (args.locate * v["nom_R"]
                                  if v["lado"] == "short" else 0) > 0}
    print(f"\n  {len(viables)} sobreviven el locate del {args.locate:.0%}\n")
    print(f"  {'estrategia':<38} {'lado':>5} {'ses/m':>6} {'ret/nom':>8} "
          f"{'neto R':>8} {'brecha':>7}")
    print("  " + "-" * 78)
    for v in sorted(viables.values(), key=lambda x: -x["bruto_R"]):
        neto = v["bruto_R"] - (args.locate * v["nom_R"] if v["lado"] == "short" else 0)
        print(f"  {v['nombre']:<38} {v['lado']:>5} {v['ses_mes']:>6.1f} "
              f"{v['ret_nom']:>7.1f}% {neto:>+8.3f} "
              f"{(v['replica'] if v['replica'] is not None else 0):>6.1f}p")

    calendario = sorted({d for v in ests.values() for d in v["serie"]})
    nombres = list(viables)

    print(f"\n  COMBINACIONES DE {args.cuentas} — ordenadas por tiempo hasta "
          f"${args.meta:,.0f}\n")
    filas = []
    for combo_n in itertools.combinations(nombres, args.cuentas):
        combo = [viables[n] for n in combo_n]
        m = evaluar_combo(combo, calendario, args.locate, args.meta,
                          args.corridas, args.max_meses, args.f)
        cors = [correlacion(a["serie"], b["serie"])
                for a, b in itertools.combinations(combo, 2)]
        sol = [solape(a["serie"], b["serie"])
               for a, b in itertools.combinations(combo, 2)]
        filas.append({**m, "combo": combo_n,
                      "cor": statistics.mean([c for c in cors if c is not None])
                      if any(c is not None for c in cors) else None,
                      "solape": statistics.mean(sol)})
    filas.sort(key=lambda x: (x["meses_med"] is None, x["meses_med"] or 999))

    print(f"  {'#':>3} {'meses':>7} {'p90':>6} {'llega':>7} {'caja 48m':>10} "
          f"{'corr':>6} {'solape':>7}  estrategias")
    print("  " + "-" * 96)
    for i, r in enumerate(filas[:args.top], 1):
        mm = f"{r['meses_med']:.1f}" if r["meses_med"] else "—"
        p9 = f"{r['meses_p90']:.0f}" if r["meses_p90"] else "—"
        co = f"{r['cor']:+.2f}" if r["cor"] is not None else "  —"
        print(f"  {i:>3} {mm:>7} {p9:>6} {r['p_llega']:>6.0f}% "
              f"{('$' + format(int(r['caja_med']), ',')):>10} {co:>6} "
              f"{r['solape']:>6.0%}  " + " + ".join(
                  n.replace('·', '.')[:22] for n in r["combo"]))

    if filas and filas[0]["meses_med"]:
        mejor = filas[0]
        print(f"\n  LA MEJOR: ${args.meta:,.0f} en {mejor['meses_med']:.1f} meses "
              f"(mediana), {mejor['meses_p90']:.0f} en el escenario malo, "
              f"{mejor['p_llega']:.0f}% de llegar en {args.max_meses} meses")

    print("""
  'solape' es la fracción de fechas que comparten las estrategias de la
  combinación. Un solape bajo es mejor que una correlación baja: significa que
  ni siquiera operan los mismos días, así que no pueden reventar juntas.
""")
    salida = Path(config.data_dir()) / "cartera.json"
    salida.write_text(json.dumps(
        [{k: v for k, v in f.items() if k != "combo"} | {"combo": list(f["combo"])}
         for f in filas], ensure_ascii=False), encoding="utf-8")
    print(f"  ranking completo en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
