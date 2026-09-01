import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from test_ret_nominal_valida import cargar_filas, rn, CORTE
filas = cargar_filas()
p1=[f for f in filas if f["d"]<CORTE]; p2=[f for f in filas if f["d"]>=CORTE]
tot=sum(f["pnl"] for f in filas)

C=[("sin filtro", lambda f: True),
   ("volumen > $137M", lambda f: f["dolar"] and f["dolar"]>137e6),
   ("float < 47M (donde hay dato)", lambda f: f["float"] is None or f["float"]<=47e6),
   ("VALIDADO: vol>$137M + float<47M",
    lambda f: f["dolar"] and f["dolar"]>137e6 and (f["float"] is None or f["float"]<=47e6)),
   ("  + techo de volumen $470M",
    lambda f: f["dolar"] and 137e6<f["dolar"]<=470e6 and (f["float"] is None or f["float"]<=47e6))]

print(f"  {'filtro':>34} {'n':>5} {'ret/nom':>9} {'P1':>8} {'P2':>8} {'brecha':>8} "
      f"{'%PnL':>7} {'neto@20%':>9}")
print("  "+"-"*94)
for lab,p in C:
    g=[f for f in filas if p(f)]; r=rn(g)
    a=rn([f for f in p1 if p(f)]); b=rn([f for f in p2 if p(f)])
    m=statistics.mean(x["pnl"] for x in g); n=statistics.mean(x["nom"] for x in g)
    print(f"  {lab:>34} {r[0]:>5} {r[2]:>8.1f}% {a[2]:>7.1f}% {b[2]:>7.1f}% "
          f"{abs(a[2]-b[2]):>7.1f}p {100*sum(x['pnl'] for x in g)/tot:>6.1f}% {m-.20*n:>+8.2f}")

print("\n  EL FILTRO VALIDADO, contra el locate\n")
g=[f for f in filas if f["dolar"] and f["dolar"]>137e6 and (f["float"] is None or f["float"]<=47e6)]
m=statistics.mean(x["pnl"] for x in g); n=statistics.mean(x["nom"] for x in g)
print(f"  {'locate':>8} {'neto/sesion':>12} {'x5.6 (f=.28)':>14} {'x10 ses/mes':>12} "
      f"{'x3 cuentas -$200':>18}")
print("  "+"-"*70)
for loc in (0,.05,.10,.15,.20,.25,.269):
    b=m-loc*n; mes=b*5.6*10
    print(f"  {100*loc:>7.1f}% {b:>+11.2f} {b*5.6:>+13.2f} {('$'+format(int(mes),',')):>12} "
          f"{('$'+format(int(mes*3-200),',')):>18}")
