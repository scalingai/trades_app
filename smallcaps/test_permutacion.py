#!/usr/bin/env python3
"""La prueba que falta: la etiqueta "reclaim" lleva informacion, o cualquier
particion al azar de los dias daria lo mismo?

Es la unica de las tres puertas que la amplitud NO cierra. Muchos activos
protegen contra memorizar las manias de uno; no protegen contra haber elegido
UNA de 450 variantes despues de mirarlas todas. La mejor de 450 se ve bien
aunque ninguna sirva.

EL TEST. Se conserva todo —los mismos dias, las mismas senales, el mismo motor—
y se cambia UNA cosa: que dias se llaman "reclaim". Se sortea al azar una
particion del mismo tamano, se mide, y se repite 3000 veces. Eso construye la
distribucion de lo que daria una etiqueta SIN informacion.

Si el 11,5% real cae adentro de esa nube, la etiqueta no dice nada y lo que
tenemos es el resultado de haber mirado muchas particiones. Si cae afuera, la
etiqueta lleva senal de verdad.

Es el mismo razonamiento del placebo del reloj que ya nos salvo una vez, pero
aplicado a la SELECCION DE DIAS en vez de al gatillo de entrada.
"""
import random, statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

dias = universo()
# Universo comun: todos los dias con expansion >=100 que dan senal, SIN mirar
# la apertura. De aca sale tanto el grupo real como los sorteados.
pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=100.0, min_dolar=0.0,
                max_float=47e6)
todos = []
for d in pob:
    j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0, max_trades=10)
    if j:
        todos.append({"pnl": j["pnl"]/50.0, "nom": j["nominal"]/50.0,
                      "ap": _cl(d, hasta=10.0)})
reales = [x for x in todos if x["ap"] == "reclaim"]
resto = [x for x in todos if x["ap"] != "reclaim"]

def rn(g):
    m = statistics.mean(x["pnl"] for x in g)
    n = statistics.mean(x["nom"] for x in g)
    return 100*m/n if n else 0.0

real = rn(reales)
print(f"  universo comun: {len(todos)} jornadas (expansion>=100, sin filtrar apertura)")
print(f"  el grupo 'reclaim' real: {len(reales)} jornadas · ret/nom {real:.1f}%")
print(f"  el resto:               {len(resto)} jornadas · ret/nom {rn(resto):.1f}%\n")

print("  PERMUTACION — 3000 particiones al azar del MISMO tamano\n")
rnd = random.Random(2026)
nulos = []
for _ in range(3000):
    m = rnd.sample(todos, len(reales))
    nulos.append(rn(m))
nulos.sort()
q = lambda p: nulos[int(p*(len(nulos)-1))]
mejor_que = 100*sum(1 for x in nulos if x < real)/len(nulos)
print(f"    {'la nube del azar':>22}  p5 {q(.05):>6.1f}%   mediana {q(.50):>6.1f}%   "
      f"p95 {q(.95):>6.1f}%   max {nulos[-1]:>6.1f}%")
print(f"    {'el reclaim real':>22}     {real:>6.1f}%")
print(f"\n    supera al {mejor_que:.1f}% de las particiones al azar")
print(f"    p-valor (una cola): {100-mejor_que:.2f}%")

print(f"""
  COMO LEERLO. Un p-valor del 5% quiere decir que una etiqueta sin informacion
  produciria este resultado una vez cada veinte. Pero nosotros no probamos una
  etiqueta: probamos ~450 variantes. Con 450 intentos, algo con p=5% aparece
  ~22 veces por puro azar.

  El ajuste crudo (Bonferroni) pide que el p-valor sea menor a 0,05/450 =
  0,011% para que sobreviva a haber mirado tantas. Es una vara conservadora
  —las 450 no son independientes entre si— pero da el orden de magnitud.
""")
umbral = 0.05/450*100
print(f"    vara ingenua ......... p < 5%      ->  "
      f"{'PASA' if (100-mejor_que) < 5 else 'no pasa'}")
print(f"    vara por 450 pruebas . p < {umbral:.3f}%  ->  "
      f"{'PASA' if (100-mejor_que) < umbral else 'NO PASA'}")
