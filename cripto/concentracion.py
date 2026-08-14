#!/usr/bin/env python3
"""Etapa 5.d — ¿quién carga el resultado, y se lo puede identificar de antemano?

Nace de corregir un error propio. `spread.py` declaraba que el efecto no
generalizaba entre símbolos, basándose en UN sorteo aleatorio de la mitad del
universo. Repitiendo el sorteo 200 veces, **el 72% da las dos mitades
positivas**: aquel sorteo cayó en el 28% desafortunado y no era evidencia de
nada. Una partición sola, con esta varianza, no decide.

Pero la pregunta de fondo seguía abierta, y la respuesta correcta es peor que
la equivocada.

**La concentración es extrema.** Sobre la pata corta —460 eventos en 85
símbolos— el aporte se reparte así:

    top  1 símbolo   17% del total
    top  3           48%
    top  5           63%
    top 10           96%
    top 20          145%   ← del 20 en adelante, el resto pierde

Tres tokens explican la mitad. Diez explican todo. Y eso explica el 28% de
sorteos fallidos: depende de si `TAKEUSDT` y `TACUSDT` caen en la misma mitad.

**Y no son identificables de antemano.** Comparando los 10 que más aportan
contra los otros 75, en características observables ANTES del evento:

    característica          top 10    resto
    dilución 90d previa      39,3%     29,3%
    market cap (M USD)        31,8      37,3
    volumen del evento (M)    47,4      52,2
    RVOL                      12,9      11,0
    rango del día             27,1%     23,5%
    días desde listado         223       240

Ninguna separa. La única diferencia grande —9 eventos por símbolo contra 3— es
**casi tautológica**: un símbolo con más eventos acumula más aporte TOTAL por
construcción. Medido por evento, que es lo correcto, no ordena.

**Y la hipótesis del "explotador serial" tampoco.** Era la candidata natural,
por analogía con el diluidor serial que sí discriminaba en acciones. El aporte
por evento según cuántas veces ya explotó el token: 1,70% → 2,75% → 1,65% →
0,85% → 0,97%. No es monótono. Peor: el mismo patrón descendente aparece en el
balde de dilución BAJA, o sea que no es propio del efecto que se estudia.

**Conclusión.** El resultado lo cargan unos pocos tokens que se derrumbaron, y
nada observable de antemano dice cuáles van a ser. Con 10 símbolos en el grupo
de arriba, además, cualquier comparación de características está mal potenciada
y hay que leerla con eso puesto.

    python concentracion.py
    python concentracion.py --sorteos 200
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import statistics as st
import sys
from collections import defaultdict
from datetime import date

import config
from spread import DECIL_10, cargar_con_funding, serie_diaria

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def robustez_particion(filas, slip: float, sorteos: int, semilla: int) -> None:
    """Repite el corte por símbolos muchas veces en vez de fiarse de uno."""
    print("\n\n¿EL EFECTO GENERALIZA ENTRE SÍMBOLOS?")
    print(f"({sorteos} sorteos aleatorios de mitad del universo)\n")
    random.seed(semilla)
    simbolos = sorted({x["simbolo"] for x in filas})
    ambas, peores = 0, []
    for _ in range(sorteos):
        random.shuffle(simbolos)
        mitad = set(simbolos[:len(simbolos) // 2])
        a = [r for _, r in serie_diaria(
            [x for x in filas if x["simbolo"] in mitad], DECIL_10, 0.0, slip)]
        b = [r for _, r in serie_diaria(
            [x for x in filas if x["simbolo"] not in mitad], DECIL_10, 0.0, slip)]
        if len(a) < 40 or len(b) < 40:
            continue
        ma, mb = st.fmean(a), st.fmean(b)
        ambas += (ma > 0 and mb > 0)
        peores.append(min(ma, mb))
    n = len(peores) or 1
    peores.sort()
    print(f"  las dos mitades positivas : {ambas}/{n}  ({100*ambas/n:.0f}%)")
    print(f"  al menos una negativa     : {n-ambas}/{n}  ({100*(n-ambas)/n:.0f}%)")
    print(f"  peor mitad: mediana {st.median(peores)*100:+.3f}%/día   "
          f"p10 {peores[int(.1*n)]*100:+.3f}%   p90 {peores[int(.9*n)]*100:+.3f}%")
    print("\n  Una sola partición NO decide nada con esta varianza.")


def concentracion(filas) -> tuple[dict, dict]:
    alto = [x for x in filas if x["crec"] >= DECIL_10]
    aporte: dict[str, float] = defaultdict(float)
    eventos: dict[str, list] = defaultdict(list)
    for x in alto:
        aporte[x["simbolo"]] += -x["raw"] + x["fnd"]
        eventos[x["simbolo"]].append(x)
    orden = sorted(aporte.items(), key=lambda kv: -kv[1])
    total = sum(aporte.values()) or 1e-9

    print("\n\n¿QUIÉN CARGA EL RESULTADO?")
    print(f"(pata corta: {len(alto)} eventos sobre {len(aporte)} símbolos)\n")
    for k in (1, 3, 5, 10, 20):
        acum = sum(v for _, v in orden[:k])
        print(f"  top {k:>2} símbolos aportan {100*acum/total:>5.0f}% del total")
    positivos = sum(1 for _, v in orden if v > 0)
    print(f"\n  símbolos con aporte positivo: {positivos}/{len(aporte)} "
          f"({100*positivos/len(aporte):.0f}%)")
    print("  → del 20 en adelante el resto PIERDE: la cola no es un extra,")
    print("    es todo el resultado.")
    return aporte, eventos


def caracteristicas(aporte, eventos) -> None:
    """¿Los que aportan se distinguen ANTES del evento?"""
    orden = sorted(aporte.items(), key=lambda kv: -kv[1])
    top = {s for s, _ in orden[:10]}
    resto = set(aporte) - top

    print("\n\n¿SE LOS PUEDE IDENTIFICAR DE ANTEMANO?")
    print(f"(top 10 aportantes contra los otros {len(resto)})\n")
    print(f"  {'característica':<26}{'top 10':>12}{'resto':>12}")

    def comparar(nombre, fn):
        a = [v for s in top for x in eventos[s] if (v := fn(x)) is not None]
        b = [v for s in resto for x in eventos[s] if (v := fn(x)) is not None]
        if a and b:
            print(f"  {nombre:<26}{st.median(a):>12,.1f}{st.median(b):>12,.1f}")

    comparar("dilución 90d previa (%)", lambda x: x["crec"])
    comparar("market cap (M USD)",
             lambda x: x["mcap"] / 1e6 if x["mcap"] else None)
    comparar("volumen del evento (M)", lambda x: x["vol"] / 1e6)
    comparar("RVOL", lambda x: x["rvol"])
    comparar("rango del día (%)", lambda x: x["rango"])
    comparar("días desde listado",
             lambda x: (date.fromisoformat(x["d"])
                        - date.fromisoformat(x["primer"])).days
             if x["primer"] else None)
    print("\n  Ninguna separa. Y con 10 símbolos arriba, cualquier comparación")
    print("  de características está mal potenciada: leerla con eso puesto.")


def explotador_serial(filas) -> None:
    """La candidata natural, por analogía con el diluidor serial de acciones."""
    print("\n\n¿SIRVE 'CUÁNTAS VECES YA EXPLOTÓ'? (point-in-time)")
    print("(el conteo solo mira hacia atrás, nunca al futuro)\n")
    ordenados = sorted(filas, key=lambda x: x["d"])
    vistos: dict[str, int] = defaultdict(int)
    for x in ordenados:
        x["previos"] = vistos[x["simbolo"]]
        vistos[x["simbolo"]] += 1

    tramos = [("0 (primera vez)", 0, 1), ("1-2", 1, 3), ("3-5", 3, 6),
              ("6-10", 6, 11), ("11+", 11, 10 ** 9)]
    for titulo, sel in (("dilución ALTA (el efecto)",
                         lambda x: x["crec"] >= DECIL_10),
                        ("dilución BAJA (control)", lambda x: x["crec"] <= 0.0)):
        print(f"  {titulo}")
        print(f"    {'eventos previos':<18}{'n':>6}{'media':>10}{'mediana':>10}")
        for etq, lo, hi in tramos:
            g = [-x["raw"] + x["fnd"] for x in filas
                 if sel(x) and lo <= x["previos"] < hi]
            if len(g) < 25:
                continue
            print(f"    {etq:<18}{len(g):>6}{st.fmean(g)*100:>9.2f}%"
                  f"{st.median(g)*100:>9.2f}%")
        print()
    print("  No es monótono en el grupo del efecto, y el mismo patrón")
    print("  descendente aparece en el control: no es propio de la dilución.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--slip", type=float, default=0.001)
    p.add_argument("--sorteos", type=int, default=200)
    p.add_argument("--semilla", type=int, default=101)
    args = p.parse_args()

    con = sqlite3.connect(config.db_path(), timeout=60)
    filas = cargar_con_funding(con)
    print("=" * 74)
    print("  CONCENTRACIÓN — ¿quién carga el spread y se lo ve venir?")
    print("=" * 74)
    robustez_particion(filas, args.slip, args.sorteos, args.semilla)
    aporte, eventos = concentracion(filas)
    caracteristicas(aporte, eventos)
    explotador_serial(filas)
    print("\n" + "=" * 74)
    print("  El resultado lo cargan unos pocos tokens que se derrumbaron, y")
    print("  nada observable de antemano dice cuáles van a ser.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
