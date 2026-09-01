#!/usr/bin/env python3
"""Tres pruebas de dureza que NO hicimos, y que atacan lo que la amplitud no cubre.

Agus: "es interesante porque lo estamos probando sobre una capa grande de muchos
activos, no estamos ajustando por 1 activo puntual".

Es cierto y es una fortaleza real: no hay un AAPL cuyas manias particulares
estemos memorizando. Pero la amplitud protege contra UN tipo de sobreajuste y
deja tres puertas abiertas:

  1. CONCENTRACION. "Muchos activos" en la muestra no significa muchos activos
     en el RESULTADO. Si el 80% del PnL sale de cinco tickers, la muestra
     efectiva no son 75 jornadas sino cinco apuestas.
  2. UN SOLO DIA. Con 75 sesiones, una sola jornada excepcional puede sostener
     el promedio entero. Se saca y se mira.
  3. SELECCION ENTRE MUCHAS. Probamos ~450 variantes y elegimos la mejor. La
     mejor de 450 se ve bien AUNQUE NINGUNA sirva — es el problema de las
     comparaciones multiples, y es el que mas nos puede estar mintiendo.

Las tres se miden aca. Ninguna necesita datos nuevos.
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

def cosechar(ap, ex):
    dias = universo()
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    out = []
    for d in sorted(pob, key=lambda x: x.d):
        j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=10)
        if j:
            out.append({"d": d.d, "tk": d.ticker, "pnl": j["pnl"]/50.0,
                        "nom": j["nominal"]/50.0})
    return out

for lab, ap, ex in (("reclaim·exp100", "reclaim", 100), ("fade·exp150", "fade", 150)):
    S = cosechar(ap, ex)
    tot = sum(x["pnl"] for x in S)
    print(f"\n{'='*78}\n  {lab.upper()}  ·  {len(S)} jornadas  ·  total {tot:+.2f} R\n{'='*78}")

    # ---- 1) concentracion
    por_tk = {}
    for x in S:
        por_tk[x["tk"]] = por_tk.get(x["tk"], 0.0) + x["pnl"]
    ordenado = sorted(por_tk.items(), key=lambda kv: -kv[1])
    print(f"\n  1) CONCENTRACION — {len(por_tk)} tickers distintos\n")
    acum = 0.0
    for i, (tk, v) in enumerate(ordenado[:6], 1):
        acum += v
        print(f"     {i}. {tk:<7} {v:>+7.2f} R   acumulado {100*acum/tot:>5.0f}% del total")
    gan = [v for v in por_tk.values() if v > 0]
    print(f"\n     tickers con PnL positivo: {len(gan)} de {len(por_tk)}")
    print(f"     los 3 mejores explican el "
          f"{100*sum(v for _, v in ordenado[:3])/tot:.0f}% del total")

    # ---- 2) sacar el mejor dia / el mejor ticker
    print(f"\n  2) QUE PASA SI SACAMOS LO MEJOR\n")
    def met(sub):
        if not sub: return (0, 0, 0)
        m = statistics.mean(x["pnl"] for x in sub)
        n = statistics.mean(x["nom"] for x in sub)
        return (len(sub), m, 100*m/n if n else 0)
    base = met(S)
    print(f"     {'escenario':<34} {'n':>4} {'bruto R':>9} {'ret/nom':>9}")
    print("     " + "-"*60)
    print(f"     {'completo':<34} {base[0]:>4} {base[1]:>+9.3f} {base[2]:>8.1f}%")
    peor = sorted(S, key=lambda x: -x["pnl"])
    for k in (1, 2, 3, 5):
        r = met(peor[k:])
        print(f"     {f'sin las {k} mejores jornadas':<34} {r[0]:>4} {r[1]:>+9.3f} "
              f"{r[2]:>8.1f}%")
    for k in (1, 2, 3):
        malos = {tk for tk, _ in ordenado[:k]}
        r = met([x for x in S if x["tk"] not in malos])
        print(f"     {f'sin los {k} mejores tickers':<34} {r[0]:>4} {r[1]:>+9.3f} "
              f"{r[2]:>8.1f}%")

    # ---- 3) bootstrap por TICKER, no por sesion
    print(f"\n  3) BOOTSTRAP POR TICKER vs POR SESION\n")
    print("     Remuestrear sesiones supone que cada una es independiente. Si un")
    print("     ticker aporta varias, no lo son. Remuestrear TICKERS es honesto.\n")
    rnd = random.Random(11)
    tks = list(por_tk)
    ses_por_tk = {}
    for x in S:
        ses_por_tk.setdefault(x["tk"], []).append(x)
    for etiqueta, unidad in (("por sesion", None), ("por TICKER", tks)):
        medias = []
        for _ in range(4000):
            if unidad is None:
                m = [rnd.choice(S) for _ in range(len(S))]
            else:
                m = []
                while len(m) < len(S):
                    m += ses_por_tk[rnd.choice(unidad)]
                m = m[:len(S)]
            mm = statistics.mean(x["pnl"] for x in m)
            nn = statistics.mean(x["nom"] for x in m)
            medias.append(100*mm/nn if nn else 0)
        medias.sort()
        q = lambda p: medias[int(p*(len(medias)-1))]
        neg = 100*sum(1 for x in medias if x <= 0)/len(medias)
        print(f"     {etiqueta:>12}  p5 {q(.05):>6.1f}%  mediana {q(.50):>6.1f}%  "
              f"p95 {q(.95):>6.1f}%   ·  P(ret/nom<=0) = {neg:.1f}%")
