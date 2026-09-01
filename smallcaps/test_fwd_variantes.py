"""Todas las variantes sobre los 51 dias nuevos, para exprimir la ventana fresca."""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import motor
from motor import universo, poblacion, jornada
from sesion import señales_swing
from chavineta import clasificar_apertura as _cl
from dias import hora

motor.clasificar_apertura = lambda d, **k: _cl(d, hasta=10.0)
CORTE = "2026-08-12"
dias = universo()
nuevos = [d for d in dias if d.d > CORTE]
viejos = [d for d in dias if d.d <= CORTE]
print(f"  {len(nuevos)} dias nuevos ({min(d.d for d in nuevos)} -> {max(d.d for d in nuevos)})")
print(f"  ~13 ruedas · el sistema nunca los vio\n")

def vent(m):
    def f(d):
        idx = señales_swing(d, desde=10.0)
        if not idx: return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= m/60.0]
    return f

def correr(pool, ap, ex, etiqueta):
    pob = poblacion(pool, min_ratio_vol=0.0, min_expansion=ex, min_dolar=0.0,
                    max_float=47e6)
    if ap: pob = [d for d in pob if _cl(d, hasta=10.0) == ap]
    filas = []
    for d in pob:
        j = jornada(d, vent(60), lado="short", stop_pct=45.0, riesgo=50.0,
                    max_trades=10)
        if j: filas.append((d.d, j["pnl"]/50.0, j["nominal"]/50.0))
    if not filas: return None
    m = statistics.mean(x[1] for x in filas); nn = statistics.mean(x[2] for x in filas)
    return (len(filas), m, nn, 100*m/nn if nn else 0,
            100*sum(1 for x in filas if x[1] > 0)/len(filas))

print(f"  {'variante':<22} {'':>4} {'n':>4} {'bruto R':>9} {'nom R':>7} {'ret/nom':>9} {'pos':>6}")
print("  " + "-"*68)
for lab, ap, ex in (("fade·exp150","fade",150), ("fade·exp100","fade",100),
                    ("reclaim·exp100","reclaim",100), ("reclaim·todo","reclaim",0),
                    ("sin-apertura",None,150), ("sin-apertura·exp100",None,100)):
    for pool, tag in ((viejos, "visto"), (nuevos, "NUEVO")):
        r = correr(pool, ap, ex, lab)
        if not r:
            print(f"  {lab:<22} {tag:>5} {'—':>4}   (sin jornadas)"); continue
        n, m, nn, rn, pos = r
        print(f"  {lab:<22} {tag:>5} {n:>4} {m:>+9.3f} {nn:>7.2f} {rn:>8.1f}% {pos:>5.0f}%")
    print()
