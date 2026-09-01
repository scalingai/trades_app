#!/usr/bin/env python3
"""Tres meses: cuanto se invierte y cuanto sale. Con la distribucion, no la media.

Tres meses es CORTO para esto: la evaluacion sola se lleva el primer mes y la
firma no paga en el mismo mes en que fondeas. Asi que lo que se mide aca no es
tanto cuanta plata sale sino CUANTA PROBABILIDAD hay de que salga alguna.
"""
import statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import simulacion_2anios as S

S.DATA_MES = 0.0
rs = S.serie_filtrada(45.0, 50.0)
sm = max(4, round(len(rs)/22))
med = statistics.mean(x[0] for x in rs); nm = statistics.mean(x[1] for x in rs)
print(f"  stop 45% · filtro validado · {len(rs)} sesiones · {sm}/mes")
print(f"  bruto {med:+.3f} R · nominal {nm:.2f} R · punto de muerte {100*med/nm:.1f}%\n")

def corrida(n_cuentas, meses, locate, f=.28, N=4000):
    """Reimplementa el ciclo para n cuentas arbitrarias (el modulo asume 3)."""
    import random
    out=[]
    for s in range(N):
        rnd=random.Random(s); cam=[]
        while len(cam) < meses*sm+20:
            i=rnd.randrange(0,max(1,len(rs)-15)); cam+=rs[i:i+15]
        est=["eval"]*n_cuentas; eq=[0.0]*n_cuentas
        caja=-n_cuentas*S.EVAL_USD; evals=n_cuentas; k=0; cobros=0
        for mes in range(meses):
            nuevo=[False]*n_cuentas
            for _ in range(sm):
                x,nom=cam[k%len(cam)]; k+=1
                for c in range(n_cuentas):
                    if est[c]=="muerta": continue
                    eq[c]+= x*f - locate*nom*f
                    if eq[c]<=-1.0: est[c]="muerta"
                    elif est[c]=="eval" and eq[c]>=S.OBJ:
                        est[c]="fondeada"; eq[c]=0.0; nuevo[c]=True
            cob=0.0
            for c in range(n_cuentas):
                if est[c]=="fondeada" and not nuevo[c] and eq[c]>S.CUSHION:
                    cob+=(eq[c]-S.CUSHION)*S.TOPE_USD*S.SPLIT; eq[c]=S.CUSHION
            if cob>0: cobros+=1
            rec=sum(1 for c in range(n_cuentas) if est[c]=="muerta")
            caja+=cob-rec*S.EVAL_USD; evals+=rec
            for c in range(n_cuentas):
                if est[c]=="muerta": est[c]="eval"; eq[c]=0.0
        out.append((caja, evals, cobros, sum(1 for e in est if e=="fondeada")))
    return out

for loc,lab in ((.20,"locate 20% (el pesimista de Espes)"),(.10,"locate 10%")):
    print(f"  === {lab} ===\n")
    print(f"  {'cuentas':>8} {'invertis':>9} {'p10':>9} {'MEDIANA':>9} {'p75':>9} "
          f"{'p90':>9} {'cobro?':>8} {'fondead.':>9} {'en rojo':>8}")
    print("  "+"-"*84)
    for n in (1,2,3):
        r=corrida(n,3,loc); v=sorted(x[0] for x in r)
        q=lambda p: v[int(p*(len(v)-1))]
        print(f"  {n:>8} {('$'+format(n*97,',')):>9} {('$'+format(int(q(.10)),',')):>9} "
              f"{('$'+format(int(q(.50)),',')):>9} {('$'+format(int(q(.75)),',')):>9} "
              f"{('$'+format(int(q(.90)),',')):>9} "
              f"{100*sum(1 for x in r if x[2]>0)/len(r):>7.0f}% "
              f"{statistics.mean(x[3] for x in r):>9.2f} "
              f"{100*sum(1 for x in v if x<0)/len(v):>7.0f}%")
    print()

print("  Y SI ESPERAS UN POCO MAS — 3 cuentas, locate 20%\n")
print(f"  {'meses':>6} {'p10':>10} {'MEDIANA':>10} {'p90':>10} {'cobraste?':>11} {'en rojo':>8}")
print("  "+"-"*62)
for m in (2,3,4,6,9,12):
    r=corrida(3,m,.20); v=sorted(x[0] for x in r)
    q=lambda p: v[int(p*(len(v)-1))]
    print(f"  {m:>6} {('$'+format(int(q(.10)),',')):>10} {('$'+format(int(q(.50)),',')):>10} "
          f"{('$'+format(int(q(.90)),',')):>10} "
          f"{100*sum(1 for x in r if x[2]>0)/len(r):>10.0f}% "
          f"{100*sum(1 for x in v if x<0)/len(v):>7.0f}%")
print("""
  'cobro?' es la probabilidad de haber cobrado AL MENOS UNA VEZ. Es el numero
  que importa a 3 meses: no cuanto, sino si llego a salir algo.""")
