"""El 100% era del bootstrap IID. Con bloques y con degradación, el número real."""
import random, statistics, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from estrategia_fondeo import serie_sesiones

rs = serie_sesiones()
n = len(rs)
med = statistics.mean(rs)
print(f'  {n} sesiones · media {med:+.3f} R · desvío {statistics.stdev(rs):.3f} R\n')

def corrida_bloques(rnd, largo, B=15):
    """Bootstrap por BLOQUES: preserva las rachas. Un bloque = 15 sesiones seguidas."""
    out = []
    while len(out) < largo:
        i = rnd.randrange(0, n - B)
        out += rs[i:i+B]
    return out[:largo]

def evaluar(seq, f, obj=1.2, tope=1.0, deg=1.0):
    eq = 0.0
    for k, x in enumerate(seq):
        eq += (x * deg if x > 0 else x) * f     # degradar SOLO las ganancias
        if eq <= -tope: return False, k+1, 'revienta'
        if eq >= obj:   return True,  k+1, 'pasa'
    return False, len(seq), 'no llega'

print('  A) BOOTSTRAP POR BLOQUES (rachas preservadas) vs IID\n')
print(f"  {'riesgo/tope':>12} {'IID':>8} {'bloques':>9} {'ses.med':>9} {'DD p99':>8}")
print('  '+'-'*50)
for f in (.06,.10,.145,.22,.35):
    rnd=random.Random(1); a=[evaluar(corrida_bloques(rnd,250),f) for _ in range(3000)]
    rnd=random.Random(1); b=[evaluar([rnd.choice(rs) for _ in range(250)],f) for _ in range(3000)]
    pa=100*sum(1 for r in a if r[0])/len(a); pb=100*sum(1 for r in b if r[0])/len(b)
    ses=sorted(r[1] for r in a if r[0])
    print(f"  {f:>12.3f} {pb:>7.0f}% {pa:>8.0f}% "
          f"{(f'{statistics.median(ses):.0f}' if ses else '—'):>9}")

print('\n  B) LA PRUEBA QUE IMPORTA: ¿cuánta degradación aguanta?')
print('     En vivo siempre se gana menos que en el backtest. Acá se recortan')
print('     SOLO las ganancias y se dejan las pérdidas enteras.\n')
print(f"  {'ganancias al':>13} {'media resultante':>17} " +
      ' '.join(f"{('f='+format(f,'.3f')):>9}" for f in (.06,.10,.145,.22)))
print('  '+'-'*72)
for deg in (1.0,.75,.60,.50,.40,.30):
    m = statistics.mean(x*deg if x>0 else x for x in rs)
    fila=[]
    for f in (.06,.10,.145,.22):
        rnd=random.Random(3)
        r=[evaluar(corrida_bloques(rnd,250),f,deg=deg) for _ in range(3000)]
        fila.append(f"{100*sum(1 for x in r if x[0])/len(r):>8.0f}%")
    print(f"  {deg*100:>12.0f}% {m:>+16.3f} R " + ' '.join(fila))

print('\n  C) LA SERIE REAL, sin remuestrear — todos los puntos de partida')
print(f"  {'riesgo/tope':>12} {'pasa':>7} {'revienta':>9} {'no llega':>9} {'ses.med':>9}")
print('  '+'-'*50)
for f in (.06,.10,.145,.22,.35):
    res=[evaluar(rs[i:],f) for i in range(0,n-30)]
    ok=[r for r in res if r[0]]
    rev=sum(1 for r in res if r[2]=='revienta')
    print(f"  {f:>12.3f} {100*len(ok)/len(res):>6.0f}% {100*rev/len(res):>8.0f}% "
          f"{100*sum(1 for r in res if r[2]=='no llega')/len(res):>8.0f}% "
          f"{(f'{statistics.median([r[1] for r in ok]):.0f}' if ok else '—'):>9}")
