#!/usr/bin/env python3
"""Trailing stop, medido con el nominal = exposicion SIMULTANEA.

Idea de Agus, y ataca lo correcto: se devuelve el 44% del maximo a favor, pero
un objetivo fijo no sirve porque corta la cola derecha que paga todo. El trailing
promete lo mejor de los dos: sigue al precio y no tiene techo.

Y ahora tiene una segunda palanca que el estudio de ayer no podia ver: al cerrar
antes, los tramos se solapan menos y el PICO de exposicion baja. Menos locate.

Dos formas, las dos sin mirar el futuro (el nivel se fija con barras cerradas):
  · DEVUELVE x%  cierra si se devuelve esa fraccion del maximo a favor
  · ANCHO x%     el stop sigue al extremo a favor a esa distancia
`arma` = a partir de que ganancia se activa. Antes de eso rige el stop original.

    SMALLCAPS_CENSO=1 python test_trailing.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, evaluar
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
dias = universo()
L = {"min_ratio_vol": 0.0, "min_dolar": 0.0}


def ventana(mins):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx:
            return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= mins / 60.0]
    return f


CASOS = [("reclaim·exp100", "reclaim", 100, 60), ("fade·exp150", "fade", 150, 60)]

for lab, ap, ex, vent in CASOS:
    sig = ventana(vent)
    base = evaluar(f"tr·base·{lab}", sig, dias=dias, familia="trailing", stop=45.0,
                   pob={"min_expansion": ex, **L}, apertura=ap, guardar=False)
    print(f"\n  {lab.upper()}  ·  agrega hasta {vent} min  ·  "
          f"base sin trailing: ret/nom {base['ret_nom']:.1f}%  "
          f"(bruto {base['bruto_R']:+.3f} · nom {base['nom_R']:.2f})\n")
    tabla = {("base", "-"): (base["bruto_R"], base["nom_R"], base["replica"])}

    print(f"  {'variante':>22} {'ses/m':>6} {'tr/m':>5} {'bruto':>8} {'nom':>6} "
          f"{'ret/nom':>8} {'P1':>7} {'P2':>7} {'brecha':>7}")
    print("  " + "-"*84)
    for arma in (0.0, 10.0, 20.0):
        for dev in (25, 33, 50, 66):
            nm = f"dev{dev}·arma{int(arma)}"
            r = evaluar(f"tr·{nm}·{lab}", sig, dias=dias, familia="trailing",
                        stop=45.0, pob={"min_expansion": ex, **L}, apertura=ap,
                        trail_devuelve=dev, trail_arma=arma, guardar=False)
            if "error" in r: continue
            tabla[(nm, dev)] = (r["bruto_R"], r["nom_R"], r["replica"])
            print(f"  {nm:>22} {r['ses_mes']:>6.1f} {r['trades_mes']:>5} "
                  f"{r['bruto_R']:>+8.3f} {r['nom_R']:>6.2f} {r['ret_nom']:>7.1f}% "
                  f"{(r['P1'] or {}).get('ret_nom',0):>6.1f}% "
                  f"{(r['P2'] or {}).get('ret_nom',0):>6.1f}% {(r['replica'] or 0):>6.1f}p")
        for anc in (10, 15, 20, 30):
            nm = f"anc{anc}·arma{int(arma)}"
            r = evaluar(f"tr·{nm}·{lab}", sig, dias=dias, familia="trailing",
                        stop=45.0, pob={"min_expansion": ex, **L}, apertura=ap,
                        trail_ancho=anc, trail_arma=arma, guardar=False)
            if "error" in r: continue
            tabla[(nm, anc)] = (r["bruto_R"], r["nom_R"], r["replica"])
            print(f"  {nm:>22} {r['ses_mes']:>6.1f} {r['trades_mes']:>5} "
                  f"{r['bruto_R']:>+8.3f} {r['nom_R']:>6.2f} {r['ret_nom']:>7.1f}% "
                  f"{(r['P1'] or {}).get('ret_nom',0):>6.1f}% "
                  f"{(r['P2'] or {}).get('ret_nom',0):>6.1f}% {(r['replica'] or 0):>6.1f}p")
        print()

    print(f"  {lab.upper()}  ·  MEJOR VARIANTE SEGUN EL LOCATE\n")
    print(f"  {'locate':>8} {'mejor':>22} {'neto R':>9} {'vs base':>9} {'brecha':>7}")
    print("  " + "-"*60)
    for loc in (.05, .10, .15, .175, .20, .25):
        nb = tabla[("base", "-")][0] - loc*tabla[("base", "-")][1]
        mejor = max(tabla.items(), key=lambda kv: kv[1][0] - loc*kv[1][1])
        v = mejor[1][0] - loc*mejor[1][1]
        print(f"  {loc:>7.1%} {mejor[0][0]:>22} {v:>+9.3f} {v-nb:>+9.3f} "
              f"{(mejor[1][2] or 0):>6.1f}p" + ("   NEGOCIO" if v > 0 else ""))
