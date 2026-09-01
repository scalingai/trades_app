import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import test_locate_nominal as T

print("  ABRIR MAS EL STOP: si el locate es % del nominal, el stop ancho es DEFENSA")
print(f"\n  {'stop':>16} {'bruto/ses':>11} {'nominal':>9} {'muerte':>8} "
      f"{'neto @15%':>11} {'neto @20%':>11}")
print("  " + "-" * 70)
for sp, tope in ((25, 30), (None, 30), (None, 40), (None, 50), (None, 60), (35, 40), (45, 50)):
    f = T.correr(sp, tope_stop=tope)
    if len(f) < 50: continue
    m = statistics.mean(x[0] for x in f); n = statistics.mean(x[1] for x in f)
    lab = (f"{sp}% fijo" if sp else f"estruct. tope {tope:.0f}%")
    print(f"  {lab:>16} {m:>+10.2f} {('$'+format(int(n),',')):>9} "
          f"{100*m/n:>7.1f}% {m-.15*n:>+10.2f} {m-.20*n:>+10.2f}")

print("\n  LA CUENTA FINAL, con los costos que las fuentes agregaron")
print("  ($200/mes de data segun Espes; el locate escala con el riesgo,")
print("   asi que sumar tamano NO lo amortiza)\n")
f = T.correr(None, tope_stop=40)
m = statistics.mean(x[0] for x in f); n = statistics.mean(x[1] for x in f)
print(f"  {'locate':>8} {'neto/ses R=$50':>15} {'R=$280 (f=.28)':>16} "
      f"{'x10 ses/mes':>12} {'-$200 data':>12} {'x3 cuentas':>12}")
print("  " + "-" * 80)
for loc in (0.0, .02, .05, .10, .15, .175, .20):
    base = m - loc * n
    esc = base * 5.6
    mes = esc * 10
    print(f"  {100*loc:>7.1f}% {base:>+14.2f} {esc:>+15.2f} "
          f"{('$'+format(int(mes),',')):>12} {('$'+format(int(mes-200),',')):>12} "
          f"{('$'+format(int(mes*3-200),',')):>12}")
print("""
  El costo de data es UNO solo aunque tengas tres cuentas: por eso la ultima
  columna es la que decide, y por eso una sola cuenta no cierra ni con locate
  barato.""")
