"""La cartera de 3 cuentas contra la degradacion. Es lo que decide la agresividad."""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import cartera_fondeo as CF

rs, part = CF.series()

def con_deg(seq, deg):
    return [x * deg if x > 0 else x for x in seq]

def con_deg_p(seq, deg):
    return [[x * deg if x > 0 else x for x in fila] for fila in seq]

print("  3 CUENTAS · senales repartidas · cobrado 12m neto de evaluaciones")
print("  Se recortan SOLO las ganancias; las perdidas quedan enteras.\n")
cab = (.145, .22, .28, .35)
print(f"  {'ganancias al':>13} " + " ".join(f"{('f='+format(f,'.3f')):>22}" for f in cab))
print("  " + "-" * 105)
for deg in (1.0, .80, .70, .60, .50):
    d_rs, d_part = con_deg(rs, deg), con_deg_p(part, deg)
    fila = []
    for f in cab:
        r = [CF.simular(d_rs, d_part, "C", f, 3, 12, semilla=s) for s in range(2500)]
        cob = sorted(x[0] for x in r)
        cero = 100 * sum(1 for x in r if x[1] == 0) / len(r)
        fila.append(f"{('$'+format(int(statistics.mean(cob)),',')):>9}"
                    f"{('  p10 '+format(int(cob[int(.1*len(cob))]),',')):>13}")
    print(f"  {deg*100:>12.0f}% " + " ".join(fila))
print("""
  Cada celda: promedio y percentil 10. El p10 es el ano malo — si ahi
  todavia es positivo, la configuracion aguanta; si es negativo, la
  agresividad esta comprada con la cola.""")
