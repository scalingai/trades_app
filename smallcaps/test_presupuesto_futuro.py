#!/usr/bin/env python3
"""Verificacion independiente del error #7: el presupuesto mira el futuro.

Franco reporta que en `motor.jornada` la linea

    if pnl - r_trade < -riesgo: break

usa `pnl`, que es la suma del PnL FINAL de los tramos anteriores. Como `_trade`
simula cada tramo hasta su cierre antes de pasar al siguiente, al decidir si
abre el tramo N el motor ya sabe como termina un tramo que a esa hora sigue
abierto.

No lo tomo de palabra. Esta es una implementacion INDEPENDIENTE, escrita desde
cero: en vez de recorrer los tramos en orden de indice, recorre el dia en orden
de TIEMPO y aplica la regla de presupuesto con lo que se sabe en ese minuto.
Si Franco tiene razon, las dos versiones tienen que diferir; si no, coinciden.

Tres reglas de presupuesto, todas honestas menos la primera:
  futuro   la de hoy: PnL final de los tramos anteriores        (look-ahead)
  cerrado  solo tramos que YA cerraron a esa hora
  mtm      cerrados + los vivos marcados a mercado en esa barra
  ninguna  sin limite diario
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, _trade, R_BASE
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

def jornada_regla(dia, señal, regla, *, stop=45.0, riesgo=R_BASE, max_trades=10):
    """Igual que motor.jornada pero el presupuesto usa `regla`."""
    idx = señal(dia)
    if not idx: return None
    r_trade = riesgo/3.0
    abiertos, cerrados, n = [], [], 0
    for i in idx:
        if n >= max_trades: break
        h = hora(dia.bars[i])
        if regla == "futuro":
            base = sum(t["pnl"] for t in abiertos + cerrados)
        elif regla == "cerrado":
            base = sum(t["pnl"] for t in cerrados + abiertos if t["h_sal"] <= h)
        elif regla == "mtm":
            # cerrados a valor final; vivos, marcados al cierre de ESTA barra
            base = 0.0
            for t in abiertos + cerrados:
                if t["h_sal"] <= h:
                    base += t["pnl"]
                else:
                    px = dia.bars[i][4]
                    base += t["acciones"]*(t["p_ent"] - px)   # short
        else:
            base = 0.0
        if regla != "ninguna" and base - r_trade < -riesgo:
            break
        r = _trade(dia, i, lado="short", stop_pct=stop, riesgo=r_trade)
        if not r: continue
        abiertos.append(r); n += 1
    if not n: return None
    det = abiertos
    return {"pnl": sum(t["pnl"] for t in det), "nominal": motor._nominal_pico(det),
            "trades": n}

dias = universo()
print("  VERIFICACION INDEPENDIENTE — implementacion escrita desde cero\n")
print(f"  {'poblacion':<18} {'regla':>10} {'ses':>5} {'tr/mes':>7} {'bruto R':>9} "
      f"{'nom R':>7} {'ret/nom':>9}")
print("  " + "-"*72)
guardado = {}
for lab, ap, ex in (("fade·exp150","fade",150), ("reclaim·exp100","reclaim",100)):
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    for regla in ("futuro", "mtm", "cerrado", "ninguna"):
        filas, tr = [], 0
        for d in pob:
            j = jornada_regla(d, vent(60), regla)
            if j:
                filas.append((j["pnl"]/R_BASE, j["nominal"]/R_BASE)); tr += j["trades"]
        if len(filas) < 20: continue
        m = statistics.mean(x[0] for x in filas); nn = statistics.mean(x[1] for x in filas)
        guardado[(lab, regla)] = (m, nn, len(filas), tr)
        print(f"  {lab:<18} {regla:>10} {len(filas):>5} {tr/22.9:>7.0f} "
              f"{m:>+9.3f} {nn:>7.2f} {100*m/nn:>8.1f}%")
    print()

print("  CONTROL: 'futuro' tiene que reproducir motor.jornada exactamente\n")
from motor import jornada as jornada_motor
for lab, ap, ex in (("fade·exp150","fade",150), ("reclaim·exp100","reclaim",100)):
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    dif = 0.0; n = 0
    for d in pob:
        a = jornada_regla(d, vent(60), "futuro")
        b = jornada_motor(d, vent(60), lado="short", stop_pct=45.0,
                          riesgo=R_BASE, max_trades=10)
        if a and b: dif = max(dif, abs(a["pnl"]-b["pnl"])); n += 1
    print(f"    {lab:<18} {n} sesiones · diferencia maxima ${dif:.10f}"
          + ("  IDENTICO" if dif < 1e-9 else "  <<< NO REPRODUCE"))
