#!/usr/bin/env python3
"""La matriz de correlacion, rehecha con TODAS las correcciones adentro.

Las matrices anteriores usaban estrategias medidas con dos fugas de look-ahead
y con el nominal mal calculado (el trade mas grande en vez de la exposicion
simultanea). No sirven. Esta parte de cero.

Y hay una distincion que el analisis anterior no hacia y decide todo:

  · La correlacion NO mejora el punto de muerte. El ret/nom de una cartera es
    un promedio ponderado de los ret/nom de sus patas: si ninguna pata supera
    el locate, ninguna combinacion lo va a superar. Decorrelacionar cosas que
    pierden da una perdida mas suave, no una ganancia.
  · La correlacion SI mejora la supervivencia. En una cuenta de fondeo lo que
    te saca no es la media sino el drawdown, y ahi juntar series que no caen
    juntas vale de verdad.

O sea que hay que medir las dos cosas por separado, porque contestan preguntas
distintas: "es negocio?" y "sobrevive la evaluacion?".

    SMALLCAPS_CENSO=1 python test_correlacion_limpia.py
"""
import itertools, math, statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
LOC = 0.20
TOPE, OBJ, F = 1000.0, 1.2, 0.40

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

CONF = [("reclaim·exp100",  "reclaim", 100),
        ("reclaim·exp150",  "reclaim", 150),
        ("reclaim·todo",    "reclaim", 0),
        ("fade·exp150",     "fade",    150),
        ("fade·exp100",     "fade",    100),
        ("sin-apertura",    None,      150)]

dias = universo()
S = {}
print("  LAS PATAS, con todas las correcciones\n")
print(f"  {'estrategia':<18} {'ses/m':>6} {'bruto R':>9} {'nom R':>7} {'ret/nom':>9} "
      f"{'neto@20%':>10} {'peor dia':>9}")
print("  " + "-"*74)
for lab, ap, ex in CONF:
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    serie = {}
    for d in pob:
        j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=10)
        if j:
            pR, nR = j["pnl"]/50.0, j["nominal"]/50.0
            a, b = serie.get(d.d, (0.0, 0.0))
            serie[d.d] = (a + pR, b + nR)
    if len(serie) < 20: continue
    S[lab] = serie
    m = statistics.mean(v[0] for v in serie.values())
    nn = statistics.mean(v[1] for v in serie.values())
    peor = min(v[0] for v in serie.values())
    print(f"  {lab:<18} {len(serie)/22.9:>6.1f} {m:>+9.3f} {nn:>7.2f} "
          f"{100*m/nn:>8.1f}% {m-LOC*nn:>+10.3f} {peor:>+9.2f}")

def corr(a, b):
    com = sorted(set(a) & set(b))
    if len(com) < 20: return None
    x = [a[d][0] for d in com]; y = [b[d][0] for d in com]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((v-mx)**2 for v in x)); sy = math.sqrt(sum((v-my)**2 for v in y))
    if not sx or not sy: return None
    return sum((x[i]-mx)*(y[i]-my) for i in range(len(x)))/(sx*sy)

ns = list(S)
print(f"\n  MATRIZ DE CORRELACION  (abajo: % de fechas compartidas)\n")
print("       " + " ".join(f"{n[:14]:>15}" for n in ns))
for a in ns:
    fila = []
    for b in ns:
        if a == b: fila.append(f"{'—':>15}"); continue
        c = corr(S[a], S[b])
        sol = 100*len(set(S[a]) & set(S[b]))/len(set(S[a]) | set(S[b]))
        fila.append(f"{(f'{c:+.2f}' if c is not None else 'poco solape'):>9}{sol:>5.0f}%" if c is not None
                    else f"{'sin solape':>15}")
    print(f"  {a[:5]:>5} " + " ".join(fila))

print(f"\n  1) LA CORRELACION NO MUEVE EL PUNTO DE MUERTE\n")
print(f"  {'cartera':>40} {'ret/nom':>9} {'neto@20%':>10}")
print("  " + "-"*62)
for k in (1, 2, 3):
    mejor = None
    for combo in itertools.combinations(ns, k):
        fechas = set().union(*[set(S[n]) for n in combo])
        pnl = sum(sum(S[n].get(d, (0,0))[0] for n in combo) for d in fechas)/len(fechas)
        nom = sum(sum(S[n].get(d, (0,0))[1] for n in combo) for d in fechas)/len(fechas)
        v = pnl - LOC*nom
        if mejor is None or v > mejor[0]: mejor = (v, combo, 100*pnl/nom)
    v, combo, rn = mejor
    print(f"  {' + '.join(x[:12] for x in combo):>40} {rn:>8.1f}% {v:>+10.3f}")

print(f"\n  2) LA CORRELACION SI MEJORA LA SUPERVIVENCIA\n")
print("  Peor jornada conjunta y dias en que TODAS las patas pierden a la vez.\n")
print(f"  {'cartera':>40} {'peor dia':>9} {'todas rojo':>11} {'de':>5}")
print("  " + "-"*70)
for k in (1, 2, 3):
    for combo in itertools.combinations(ns, k):
        if k > 1 and "reclaim·exp100" not in combo: continue
        fechas = sorted(set().union(*[set(S[n]) for n in combo]))
        dia = [sum(S[n].get(d, (0,0))[0] for n in combo) for d in fechas]
        juntos = sum(1 for d in fechas
                     if all(S[n].get(d, (0,0))[0] < 0 for n in combo if d in S[n])
                     and sum(1 for n in combo if d in S[n]) == len(combo))
        comp = sum(1 for d in fechas if sum(1 for n in combo if d in S[n]) == len(combo))
        print(f"  {' + '.join(x[:12] for x in combo):>40} {min(dia):>+9.2f} "
              f"{juntos:>11} {comp:>5}")
