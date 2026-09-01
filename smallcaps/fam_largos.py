#!/usr/bin/env python3
"""La familia del LADO LARGO. Lo único de este proyecto que no paga locate.

**Por qué existe esta familia, y por qué la métrica cambia.** Todo el resto del
proyecto vende en corto, y el locate se cobra como fracción del NOMINAL, así que
`ret/nom` es el punto de muerte: si el locate se come el retorno sobre nominal,
la estrategia pierde por definición. **Un largo no paga locate.** Ahí el punto
de muerte no aplica y la unidad que manda vuelve a ser el PnL por sesión
(`bruto_R`). Un largo con `ret/nom` 12% puede ser mejor negocio que un corto con
30%, porque al corto todavía hay que restarle ~20 puntos y al largo no.

La tabla igual reporta `ret/nom` y `neto20` — para el largo `neto20` es una
columna SIN SENTIDO (le resta un costo que no existe) y está sólo para que la
comparación con las otras familias no obligue a cambiar de tabla.

------------------------------------------------------------------------------
VEREDICTO (2026-08-31): NO HAY LARGO OPERABLE EN ESTE CENSO. Y no es cerrado.
------------------------------------------------------------------------------

135 variantes medidas —7 mecanismos × 5 poblaciones, 26 controles de población,
y sobre los finalistas el barrido de stop, salida y objetivo—. El mejor número
de todos es **+0,017 R por sesión** con **t = 1,28** y 5,2 sesiones al mes
(+0,087 R al mes), contra **+1,88 R al mes** de la línea de base de cortos. No
es un edge chico: es cero con ruido alrededor.

**El número que cierra la discusión**: 56 variantes dan positivo en P1. De esas,
**55 dan vuelta el signo en P2** — el 98%. La única que sobrevive a los dos
períodos es la que tiene t = 1,28. Eso no es una familia con un ganador: es una
familia de ceros donde el ranking lo arma el ruido.

Ojo con la columna `replica` acá: el máximo de toda la familia es 14,3 puntos y
la mediana 3,0, o sea **ninguna variante llega al umbral de ruido de 15 puntos**.
No es una buena noticia — es que `replica` compara `ret/nom` entre períodos y en
esta familia `ret/nom` está pegado al cero en los dos, así que la brecha da chica
por una razón trivial. **Para el largo, el test de replicación que sirve es el
cambio de SIGNO del `bruto_R` entre P1 y P2**, no la brecha de `ret/nom`.

Los tres hallazgos que lo explican, en orden de importancia:

1. **El +5,4% del largo temprano era look-ahead puro.** Comprar a las 09:35 en
   días "reclaim" de expansión 0-100% da +5,97% de media. Confirmando el mismo
   reclaim **EN VIVO** a las 09:35 —cinco cierres sobre el máximo de
   pre-market— da **−1,13%**, peor que no filtrar nada (−0,04%). Los seis
   puntos de diferencia son exactamente el valor de saber a las 09:35 lo que
   `clasificar_apertura` recién decide a las 10:00. Ese número es el que hacía
   parecer viva a esta familia, y no existe.

2. **El censo es un estanque de cortos, por construcción.** `poblacion_obs`
   selecciona `gap_pct >= 25%`: papeles que YA saltaron un 25% de un día para
   el otro. El drift crudo de 10:01 al cierre es negativo en TODAS las bandas
   —mediana −0,89% en expansión 0-50 y −9,72% arriba de 150%, con menos del 45%
   de días positivos en cualquier banda—. Pedirle un largo a esta población es
   pedirle que compre agotamiento. Que el corto funcione y el largo no es **la
   misma observación vista dos veces**, no dos resultados.

3. **No es la fricción.** Con `COSTO_ACCION = 0` —contrafáctico, no operable—
   el mejor pasa de +0,011 a +0,021 R. La fricción se lleva entre 0,010 y 0,033
   R por sesión, real pero no decisiva: aun regalada, la señal es 1/16 del
   corto. Tampoco es el piso de liquidez (probado a $0, $250k y $1M por minuto:
   mismo resultado) ni el ancho del stop (10/15/20/30/45%: todos cero) ni la
   salida (cierre, 11:00, 12:00, 14:00, objetivo +20% y +40%: todos cero).

4. **Y el día 2 tampoco.** La única otra población alcanzable sin bajar datos
   nuevos —el día siguiente al evento, 1.765 días, ya descargados como vecinos—
   es una MONEDA: media entre −0,4% y +0,3% según la hora de entrada, mediana
   negativa siempre, 44-47% de días positivos. No hay largo, pero tampoco hay
   corto. El drift bajista del día del gap **no sobrevive a la noche**, y eso
   dice algo que vale para todo el proyecto: la única asimetría que hay en estos
   datos es el agotamiento del MISMO día del gap.

**Lo que NO dice este veredicto**: que no exista un largo en small caps. Dice
que no existe **en el censo que este proyecto bajó** ni en su día siguiente, y
ese censo tiene el gap del 25% metido en su definición. Un largo de verdad
necesitaría otra población —ruptura de rango de varios días, float bajo SIN gap
previo, continuación con volumen creciente día tras día— y eso es una descarga
de datos nueva, no otra señal sobre estos 1.927 días. Es la única línea de esta
familia que vale la pena seguir, y hay que decir por adelantado que **es cara**:
son horas de descarga para una hipótesis que todavía no tiene evidencia a favor.

**Efecto colateral que sí sirve**: los largos correlacionan **−0,13 a −0,40**
con la línea de base de cortos. La decorrelación existe y es fuerte. Pero
decorrelación con esperanza cero no es un hedge, es varianza gratis: no entra a
la cartera.

**El antecedente honesto.** Ya se midió antes (`test_gapandgo.py`,
`test_frontlong.py`) que el largo de reclaim daba ~0 y que arriba de 100% de
expansión pre-market se muere. Aquellas mediciones usaban PnL crudo sobre la
población elegida PARA CORTOS: expansión >100%, float chico, fade. Este archivo
parte de la sospecha opuesta —que el largo vive en otra población— y barre la
población de forma sistemática ANTES de mirar ningún mecanismo.

------------------------------------------------------------------------------
EL LOOK-AHEAD QUE TIENE EL FILTRO `apertura`, Y CÓMO SE RESUELVE
------------------------------------------------------------------------------

`motor.evaluar(apertura="reclaim")` llama a `clasificar_apertura`, que mira
barras **hasta las 10:00**. O sea: la etiqueta reclaim/fade NO se conoce a las
09:35. Cualquier señal que dispare antes de las 10:00 sobre una población
filtrada por `apertura` está usando información del futuro, y el número que sale
es mentira. Esto no es un detalle: en el reconocimiento previo, comprar a las
09:35 en días "reclaim" de expansión baja daba +5,4% de media — el número más
lindo de toda la familia, y es humo, porque a las 09:35 nadie sabe todavía que
el día va a ser reclaim.

Acá se respeta una regla dura, y por eso hay dos caminos:

  · **Camino A — filtro de población.** Si se usa `apertura="reclaim"`, la señal
    NO puede disparar antes de las 10:01. Todas las señales reciben `desde=` y
    las variantes con filtro de apertura lo llevan en `DESDE_ETIQUETA`.
  · **Camino B — detección en vivo.** La señal misma confirma el reclaim
    mirando sólo `bars[:i+1]` (`_reclaim_vivo`, `s_pmh_break`). Ahí se puede
    entrar a las 09:40 porque no se usó ninguna etiqueta posterior.

El camino B es el que vale para operar de verdad. El A está para poder contestar
la pregunta tal como la hizo el proyecto ("¿el rebote de VWAP en días reclaim?")
sin hacer trampa.

------------------------------------------------------------------------------
    python fam_largos.py                  # todo
    python fam_largos.py --etapa poblacion
    python fam_largos.py --etapa mecanismos
    python fam_largos.py --etapa stops
    python fam_largos.py --etapa friccion   # ¿señal o costo?
    python fam_largos.py --etapa anatomia   # t-stat, drift crudo, look-ahead
    python fam_largos.py --etapa dia2       # la otra población
"""

from __future__ import annotations

import argparse
import sys

from motor import universo, evaluar, linea, encabezado
from dias import APERTURA_RTH, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# 10:01. Es el primer minuto en el que la etiqueta reclaim/fade ya está cerrada
# (`clasificar_apertura` mira hasta las 10:00 inclusive). Entrar a las 10:00 en
# punto sería quedarse justo sobre el borde: la barra que se usa para clasificar
# sería la misma en la que se compra.
DESDE_ETIQUETA = 10.0 + 1 / 60.0

# Piso de liquidez, en dólares por minuto medidos con los 10 minutos PREVIOS.
# Mismo criterio que la familia de cortos (`sesion.señales_swing`): un papel que
# operó $39M en el día puede estar moviendo $400 por minuto justo cuando toca
# entrar, y ahí no hay trade, hay un gráfico.
LIQ_MIN = 2.5e5

RES = []          # todos los resultados, para la tabla final ordenada


def correr(nombre, señal, **kw):
    """Envuelve `evaluar`, acumula y devuelve el resultado."""
    r = evaluar(nombre, señal, lado="long", familia="largo", **kw)
    RES.append(r)
    print(linea(r), flush=True)
    return r


def tabla(titulo, filas=None, orden="bruto_R"):
    filas = RES if filas is None else filas
    ok = [r for r in filas if "error" not in r]
    ok.sort(key=lambda r: -r[orden])
    print(f"\n  {titulo}  (n={len(ok)}; {len(filas) - len(ok)} con muestra corta)")
    print(encabezado())
    print("  " + "-" * 104)
    for r in ok:
        print(linea(r))


# ==========================================================================
# Utilidades que sólo miran el pasado
# ==========================================================================

def _liquido(dia, h, minimo=LIQ_MIN):
    if minimo <= 0:
        return True
    return (dia.liquidez_en(h) or 0) >= minimo


def _reclaim_vivo(dia, i, *, minutos=5):
    """¿A la barra `i` el día YA confirmó reclaim, mirando sólo hasta `i`?

    Confirmar = los últimos `minutos` cierres, todos por encima del máximo de
    pre-market. Es la versión observable en tiempo real de lo que
    `clasificar_apertura` decide recién a las 10:00. Se usa como PRECONDICIÓN de
    una entrada, no como filtro de población: por eso no hay look-ahead.
    """
    pmh = dia.pm_high
    if not pmh or i < minutos:
        return False
    return all(b[4] and b[4] > pmh for b in dia.bars[i - minutos + 1:i + 1])


def _min_corriente(dia):
    """Mínimo del día barra por barra, acumulativo hacia adelante.

    `Dia` expone `max_corriente` pero no el mínimo, y varias señales de esta
    familia lo necesitan. Se calcula acá y no en `dias.py` para no tocar un
    módulo que comparten todas las familias por una necesidad de una sola.
    """
    out, mn = [], float("inf")
    for b in dia.bars:
        if b[3] and b[3] < mn:
            mn = b[3]
        out.append(mn)
    return out


def _rango(dia, desde, hasta):
    """Índices de barras con `desde` <= hora <= `hasta`."""
    return [i for i, b in enumerate(dia.bars) if desde <= hora(b) <= hasta]


# ==========================================================================
# LOS MECANISMOS. El docstring declara el POR QUÉ antes de medir nada.
# ==========================================================================

def s_control(desde=DESDE_ETIQUETA):
    """CONTROL — comprar a una hora fija, sin condición. La hipótesis nula.

    Mecanismo: ninguno. Existe para tener contra qué comparar. Si un mecanismo
    elaborado no le gana a "comprar a las 10:01 y aguantar", el mecanismo no
    aporta nada y lo que se está midiendo es el DRIFT de la población, no la
    señal. Es el control que faltó en las mediciones viejas del gap and go.
    """
    def f(dia):
        i = dia.idx_en(desde)
        if i is None or not _liquido(dia, desde):
            return []
        return [i]
    return f


def s_pmh_break(desde=APERTURA_RTH, hasta=12.0, minutos=1, reentradas=1):
    """QUIEBRE DEL MÁXIMO DE PRE-MARKET.

    Mecanismo: el máximo de pre-market es EL nivel que mira todo el mundo en un
    small cap en movimiento. Abajo de él, el que compró en pre-market está en
    pérdida y vende en cada rebote; arriba, esa oferta desaparece de golpe y los
    que se pusieron cortos contra el gap quedan atrapados. El quiebre no predice
    nada por sí mismo: transfiere el control del libro del lado vendedor al
    comprador.

    Es la versión observable en tiempo real del "reclaim" — por eso esta señal
    puede disparar antes de las 10:00 sin hacer trampa. `minutos` es cuántos
    cierres seguidos arriba hacen falta para considerarlo confirmado: con 1 se
    compra el pinchazo, con 5 se compra la consolidación.
    """
    def f(dia):
        pmh = dia.pm_high
        if not pmh:
            return []
        out, seguidos = [], 0
        for i in _rango(dia, desde, hasta):
            b = dia.bars[i]
            seguidos = seguidos + 1 if (b[4] and b[4] > pmh) else 0
            if seguidos == minutos and _liquido(dia, hora(b)):
                out.append(i)
                if len(out) >= reentradas:
                    break
        return out
    return f


def s_orb(minutos_rango=5, desde=None, hasta=12.0, reentradas=1):
    """QUIEBRE DEL MÁXIMO DEL RANGO DE APERTURA (5 o 15 minutos).

    Mecanismo: los primeros minutos del RTH son la subasta donde se cruzan las
    órdenes acumuladas de la noche. El máximo de ese rango es el precio donde la
    oferta ganó. Romperlo hacia arriba significa que la oferta acumulada se
    consumió y lo que queda arriba es aire. Es el mismo mecanismo del PMH pero
    con un nivel que sólo existe DESPUÉS de abrir: filtra los días donde el gap
    ya venía roto de pre-market.

    Se exige cierre por encima, no mecha: la mecha es una ejecución, el cierre es
    un acuerdo.
    """
    fin_rango = APERTURA_RTH + minutos_rango / 60.0
    d0 = fin_rango if desde is None else max(fin_rango, desde)

    def f(dia):
        r = _rango(dia, APERTURA_RTH, fin_rango)
        altos = [dia.bars[i][2] for i in r if dia.bars[i][2]]
        if len(r) < max(3, minutos_rango - 1) or not altos:
            return []
        techo = max(altos)
        out = []
        for i in _rango(dia, d0, hasta):
            b = dia.bars[i]
            if b[4] and b[4] > techo and _liquido(dia, hora(b)):
                out.append(i)
                if len(out) >= reentradas:
                    break
        return out
    return f


def s_vwap_rebote(desde=DESDE_ETIQUETA, hasta=15.0, alejarse=3.0, tol=0.5,
                  exigir_reclaim=False, reentradas=3):
    """REBOTE EN EL VWAP: baja al VWAP y lo RESPETA.

    Mecanismo: el VWAP es el precio promedio pagado por todo el que operó hoy.
    El que compró más arriba lo usa como nivel de "todavía voy bien"; el que hace
    mercado lo usa como referencia de valor justo. Cuando el precio vuelve ahí y
    la barra CIERRA por encima, lo que se vio es que la oferta no alcanzó a
    quebrarlo: hay demanda identificada a un precio conocido, y eso deja el stop
    en un lugar barato (justo abajo).

    Lo que hace que no sea "comprar cualquier baja": hay que haberse ALEJADO
    primero (`alejarse`% por encima del VWAP) y volver. Sin esa condición, un
    papel que serrucha el VWAP todo el día dispara veinte veces y lo que se mide
    es el ruido de la banda, no un rebote.

    `exigir_reclaim` usa la detección EN VIVO, no la etiqueta: sirve para
    contestar la pregunta original ("rebote de VWAP en días reclaim") sin
    depender de una clasificación que recién existe a las 10:00.
    """
    def f(dia):
        out, armado = [], False
        for i in _rango(dia, APERTURA_RTH, hasta):
            b, v = dia.bars[i], dia.vwap[i]
            c, lo = b[4], b[3]
            if not c or not v or not lo:
                continue
            if (c / v - 1) * 100 >= alejarse:
                armado = True
                continue
            if not armado or hora(b) < desde:
                continue
            if lo <= v * (1 + tol / 100.0) and c > v:
                if exigir_reclaim and not _reclaim_vivo(dia, i):
                    continue
                if _liquido(dia, hora(b)):
                    out.append(i)
                    armado = False
                    if len(out) >= reentradas:
                        break
        return out
    return f


def s_rojas(n=4, desde=DESDE_ETIQUETA, hasta=15.0, reentradas=3):
    """PRIMERA VELA VERDE TRAS N ROJAS — rebote de sobreventa.

    Mecanismo: una racha de minutos rojos seguidos en un small cap no es "el
    mercado bajando", es un vendedor grande ejecutando un programa. El programa
    termina cuando termina, y el primer minuto que cierra verde es la primera
    evidencia de que ya no está. Se compra la desaparición del vendedor, no una
    figura.

    El riesgo conocido: si el vendedor NO terminó, la vela verde es un respiro
    dentro de la ejecución y el largo compró un cuchillo. Por eso `n` importa —
    con `n` chico se compra cualquier pausa.
    """
    def f(dia):
        out, rojas = [], 0
        for i in _rango(dia, APERTURA_RTH, hasta):
            b = dia.bars[i]
            o, c = b[1], b[4]
            if not o or not c:
                continue
            if c < o:
                rojas += 1
                continue
            if rojas >= n and hora(b) >= desde and _liquido(dia, hora(b)):
                out.append(i)
                if len(out) >= reentradas:
                    break
            rojas = 0
        return out
    return f


def s_segunda_verde(desde=DESDE_ETIQUETA, hasta=15.0, reentradas=3):
    """SEGUNDA VELA VERDE CON VOLUMEN CRECIENTE TRAS UN MÍNIMO DEL DÍA.

    Mecanismo: el mínimo del día es donde la última oferta agresiva se ejecutó.
    Una sola vela verde después de eso puede ser el hueco que deja el vendedor al
    levantar la orden. DOS velas verdes seguidas Y con más volumen la segunda es
    otra cosa: alguien está pagando el offer con tamaño creciente. La condición
    de volumen es la que separa "dejó de vender" de "empezaron a comprar", que es
    lo que hace falta para que un largo pague.

    Se re-arma sólo con un mínimo NUEVO: sin eso, cualquier par de velas verdes a
    media tarde dispara sin que haya habido capitulación previa.
    """
    def f(dia):
        mins = _min_corriente(dia)
        out, armado, verdes = [], False, 0
        prev_min = None
        for i in _rango(dia, APERTURA_RTH, hasta):
            b = dia.bars[i]
            o, c, v = b[1], b[4], b[5] or 0
            if prev_min is not None and mins[i] < prev_min:
                armado, verdes = True, 0
            prev_min = mins[i]
            if not o or not c:
                continue
            if c > o:
                verdes += 1
            else:
                verdes = 0
                continue
            vprev = (dia.bars[i - 1][5] or 0) if i else 0
            if (armado and verdes >= 2 and v > vprev
                    and hora(b) >= desde and _liquido(dia, hora(b))):
                out.append(i)
                armado = False
                if len(out) >= reentradas:
                    break
        return out
    return f


def s_dip(caida=15.0, desde=DESDE_ETIQUETA, hasta=15.0, reentradas=3):
    """COMPRA DE LA CAÍDA: cayó `caida`% desde el máximo del día y hace un mínimo
    MÁS ALTO.

    Mecanismo: en un small cap que corrió, la caída desde el máximo es una toma
    de ganancias, no un cambio de tendencia — hasta que lo es. Lo que separa una
    cosa de la otra es si el próximo intento de bajar falla. El mínimo más alto
    ES ese fallo: la oferta ya no consigue precios peores. Se compra el fallo del
    vendedor, con el mínimo anterior como invalidación evidente.

    Es la única señal de la familia que compra DEBILIDAD. Por eso el mecanismo
    tiene que estar explícito: sin la condición de mínimo más alto, esto es
    "comprar porque bajó", que es la forma más cara de perder plata que existe.
    """
    def f(dia):
        out, armado, piso = [], False, None
        prev = None
        for i in _rango(dia, APERTURA_RTH, hasta):
            b = dia.bars[i]
            c, lo, mx = b[4], b[3], dia.max_corriente[i]
            if not c or not lo or mx in (None, float("-inf")):
                prev = b
                continue
            if c <= mx * (1 - caida / 100.0):
                piso = lo if not armado else min(piso, lo)
                armado = True
            if armado and piso and prev is not None and prev[3] and prev[4]:
                if lo > prev[3] and lo > piso and c > prev[4] and hora(b) >= desde:
                    if _liquido(dia, hora(b)):
                        out.append(i)
                        armado, piso = False, None
                        if len(out) >= reentradas:
                            break
            prev = b
        return out
    return f


def s_continuacion(h=10.5):
    """CONTINUACIÓN: el precio está SOBRE el VWAP a las 10:30.

    Mecanismo: la primera hora es donde se descarga el papel que entró en
    pre-market. Un papel que a las 10:30 sigue arriba del VWAP absorbió esa
    descarga: la oferta del día ya salió y no alcanzó. Lo que queda para la tarde
    es un libro sin vendedor forzado.

    Es la señal más barata de operar de todas —una condición, un horario— y por
    eso vale medirla aunque parezca ingenua: si el edge del largo es puro DRIFT
    de una población, ésta lo captura sin ningún artificio y deja en evidencia a
    los mecanismos que no agregan nada.
    """
    def f(dia):
        if dia.estado_en(h) != "front":
            return []
        i = dia.idx_en(h)
        if i is None or not _liquido(dia, h):
            return []
        return [i]
    return f


# ==========================================================================
# Poblaciones
# ==========================================================================

# Sin filtro ninguno. Todo lo demás se construye encima de esto para que quede
# claro qué agrega cada filtro, en vez de heredar en silencio los defaults de
# `poblacion()`, que están calibrados PARA CORTOS (exp>=100, float<47M,
# $137M/día) y matarían al largo antes de empezar.
LIBRE = {"min_ratio_vol": 0, "min_expansion": 0, "min_dolar": 0, "max_float": None}


def pob(**kw):
    return {**LIBRE, **kw}


BANDAS_EXP = [
    ("exp0-50", pob(min_expansion=0, max_expansion=50)),
    ("exp50-100", pob(min_expansion=50, max_expansion=100)),
    ("exp100-150", pob(min_expansion=100, max_expansion=150)),
    ("exp150+", pob(min_expansion=150)),
]


def por_float(dias, minimo=None, maximo=None):
    """Sub-universo por float. `poblacion()` sólo tiene `max_float`.

    Los días sin float conocido se DESCARTAN cuando se filtra por float: son 634
    de 1927 y meterlos en cualquiera de las dos bandas sesgaría la comparación.
    Que la muestra baje es el precio de que la banda signifique algo.
    """
    out = []
    for d in dias:
        f = d.float_acciones
        if f is None:
            continue
        if minimo is not None and f < minimo:
            continue
        if maximo is not None and f > maximo:
            continue
        out.append(d)
    return out


# ==========================================================================
# Etapas
# ==========================================================================

def etapa_poblacion(dias):
    """Dónde vive el largo. Se barre con el CONTROL, no con un mecanismo.

    A propósito: si se barriera la población con una señal elaborada no se
    sabría si lo que aparece es la población o la señal. El control a las 10:01
    aísla el drift, que es lo que define a la población.
    """
    print("\n\n=== ETAPA 1 · POBLACIÓN ===")
    print("  Control: comprar a las 10:01 y aguantar al cierre, stop 20%.")
    print("  Lo que se mide acá es el DRIFT de cada población, no una señal.\n")
    print(encabezado())
    print("  " + "-" * 104)
    local = []

    for ap in (None, "fade", "reclaim"):
        et = ap or "sinf"
        for nom, p in BANDAS_EXP:
            local.append(correr(f"largo·ctrl·{et}·{nom}", s_control(),
                                dias=dias, stop=20.0, apertura=ap, pob=p,
                                notas="control 10:01, barrido de expansión"))
        local.append(correr(f"largo·ctrl·{et}·todo", s_control(),
                            dias=dias, stop=20.0, apertura=ap, pob=pob(),
                            notas="control 10:01, sin filtro de expansión"))

    print("\n  -- bandas de float (sólo días con float conocido) --")
    for et, ap in (("sinf", None), ("reclaim", "reclaim")):
        for lab, mn, mx in (("f<10M", None, 10e6), ("f10-47M", 10e6, 47e6),
                            ("f>47M", 47e6, None)):
            local.append(correr(f"largo·ctrl·{et}·{lab}", s_control(),
                                dias=por_float(dias, mn, mx), stop=20.0,
                                apertura=ap, pob=pob(),
                                notas=f"control 10:01, float {lab}"))

    print("\n  -- otros ejes: liquidez, precio, ratio de volumen --")
    local.append(correr("largo·ctrl·pobcorto", s_control(), dias=dias, stop=20.0,
                        apertura="fade", pob=None,
                        notas="la población exacta de los cortos, operada al revés"))
    local.append(correr("largo·ctrl·dolar137", s_control(), dias=dias, stop=20.0,
                        apertura=None, pob=pob(min_dolar=137e6),
                        notas="control 10:01, sólo días de >$137M"))
    local.append(correr("largo·ctrl·rvol3", s_control(), dias=dias, stop=20.0,
                        apertura=None, pob=pob(min_ratio_vol=3.0),
                        notas="control 10:01, ratio de volumen >=3"))
    local.append(correr("largo·ctrl·p1a10", s_control(), dias=dias, stop=20.0,
                        apertura=None, pob=pob(min_precio=1.0, max_precio=10.0),
                        notas="control 10:01, precio entre $1 y $10"))
    local.append(correr("largo·ctrl·p10+", s_control(), dias=dias, stop=20.0,
                        apertura=None, pob=pob(min_precio=10.0),
                        notas="control 10:01, precio > $10"))
    tabla("ETAPA 1 · población, ordenada por bruto_R", local)
    return local


def etapa_mecanismos(dias, poblaciones):
    """Los siete mecanismos, cada uno sobre CADA población candidata.

    Correr todo contra todo y no el mecanismo lindo contra la población linda:
    elegir la población mirando un mecanismo y después el mecanismo mirando esa
    población es la receta clásica para encontrar un fantasma.
    """
    print("\n\n=== ETAPA 2 · MECANISMOS ===\n")
    print(encabezado())
    print("  " + "-" * 104)
    local = []

    for lab, ap, p in poblaciones:
        temprano = ap is None      # sin etiqueta => se puede disparar antes de las 10
        d0 = APERTURA_RTH if temprano else DESDE_ETIQUETA

        pruebas = [
            (f"pmh1·{lab}", s_pmh_break(desde=d0, minutos=1),
             "quiebre del máximo de pre-market, 1 cierre"),
            (f"pmh5·{lab}", s_pmh_break(desde=d0, minutos=5),
             "quiebre del PMH sostenido 5 cierres"),
            (f"orb5·{lab}", s_orb(5, desde=d0),
             "quiebre del rango de apertura de 5 minutos"),
            (f"orb15·{lab}", s_orb(15, desde=d0),
             "quiebre del rango de apertura de 15 minutos"),
            (f"vwap·{lab}", s_vwap_rebote(desde=d0),
             "rebote en VWAP tras alejarse 3%"),
            (f"vwapRC·{lab}", s_vwap_rebote(desde=d0, exigir_reclaim=True),
             "rebote en VWAP con reclaim confirmado EN VIVO"),
            (f"rojas4·{lab}", s_rojas(4, desde=d0), "primera verde tras 4 rojas"),
            (f"rojas7·{lab}", s_rojas(7, desde=d0), "primera verde tras 7 rojas"),
            (f"2verde·{lab}", s_segunda_verde(desde=d0),
             "2da verde con volumen creciente tras mínimo nuevo"),
            (f"dip15·{lab}", s_dip(15.0, desde=d0),
             "-15% desde el máximo del día + mínimo más alto"),
            (f"dip25·{lab}", s_dip(25.0, desde=d0),
             "-25% desde el máximo del día + mínimo más alto"),
            (f"cont1030·{lab}", s_continuacion(), "sobre el VWAP a las 10:30"),
        ]
        for nom, señal, nota in pruebas:
            local.append(correr(f"largo·{nom}", señal, dias=dias, stop=20.0,
                                apertura=ap, pob=p, notas=nota))
        print("  " + "-" * 104)
    tabla("ETAPA 2 · mecanismos, ordenada por bruto_R", local)
    return local


def etapa_stops(dias, candidatos):
    """Stop, salida y objetivo sobre los sobrevivientes.

    Para un largo el stop corto NO es gratis por la vía que uno esperaría: el
    nominal sale de `riesgo ÷ ancho del stop`, así que a stop más chico, más
    acciones — y el costo por acción ($0,04) se multiplica. En un papel de $2 un
    stop del 10% pone el costo arriba del 10% del riesgo. El barrido tiene que
    mostrar ESE trade-off, no sólo la tasa de stops.
    """
    print("\n\n=== ETAPA 3 · STOPS Y SALIDAS ===\n")
    print(encabezado())
    print("  " + "-" * 104)
    local = []
    for lab, señal, ap, p, nota in candidatos:
        for st in (10.0, 15.0, 20.0, 30.0, 45.0):
            local.append(correr(f"largo·{lab}·st{int(st)}", señal, dias=dias,
                                stop=st, apertura=ap, pob=p,
                                notas=f"{nota} · stop {st}%"))
        for h in (11.0, 12.0, 14.0):
            local.append(correr(f"largo·{lab}·sal{int(h)}", señal, dias=dias,
                                stop=20.0, apertura=ap, pob=p, salida_h=h,
                                notas=f"{nota} · salida forzada {h}:00"))
        for obj in (20.0, 40.0):
            local.append(correr(f"largo·{lab}·obj{int(obj)}", señal, dias=dias,
                                stop=20.0, apertura=ap, pob=p, objetivo_pct=obj,
                                notas=f"{nota} · objetivo +{obj}%"))
        print("  " + "-" * 104)
    tabla("ETAPA 3 · stops y salidas, ordenada por bruto_R", local)
    return local


# Las poblaciones que entran a la etapa 2 se fijan a mano, después de leer la
# etapa 1. Están escritas y no calculadas a propósito: que el criterio de
# selección quede en el archivo y no en la cabeza de nadie.
CANDIDATAS = [
    ("libre", None, pob()),
    ("exp0-50", None, pob(min_expansion=0, max_expansion=50)),
    ("exp50-100", None, pob(min_expansion=50, max_expansion=100)),
    ("exp100+", None, pob(min_expansion=100)),
    ("RCexp0-100", "reclaim", pob(min_expansion=0, max_expansion=100)),
]

# Los finalistas de la etapa 3 se eligen **por P1 solo**, nunca por la muestra
# completa: elegir con el total y después "validar" con P2 es mirarse la mano.
# Estos cinco son los cinco mejores por `bruto_R` de P1 de la etapa 2 (ver la
# nota del veredicto al pie del archivo). Que TODOS den vuelta el signo en P2 es
# el resultado, no un accidente del corte.
FINALISTAS = [
    ("cont1030·libre", s_continuacion(), None, pob(), "sobre el VWAP a las 10:30"),
    ("orb15·libre", s_orb(15, desde=APERTURA_RTH), None, pob(),
     "quiebre del rango de apertura de 15'"),
    ("rojas4·exp0-50", s_rojas(4, desde=APERTURA_RTH), None,
     pob(min_expansion=0, max_expansion=50), "primera verde tras 4 rojas"),
    ("cont1030·exp0-50", s_continuacion(), None,
     pob(min_expansion=0, max_expansion=50), "sobre el VWAP a las 10:30"),
    ("pmh1·exp0-50", s_pmh_break(desde=APERTURA_RTH, minutos=1), None,
     pob(min_expansion=0, max_expansion=50), "quiebre del máximo de pre-market"),
]


def etapa_friccion(dias, candidatos):
    """¿El largo pierde porque el movimiento es malo, o porque la fricción se lo
    come?

    Es la pregunta que decide el veredicto, y no se contesta con la tabla: dos
    estrategias con el mismo `bruto_R` negativo pueden estar en situaciones
    opuestas. Acá se vuelve a correr cada finalista con `COSTO_ACCION = 0`, que
    NO es una estrategia operable —es un contrafáctico— y se compara.

    **Por qué la fricción pega tanto más fuerte en el largo que en el corto**:
    el tamaño sale de `riesgo ÷ (precio × ancho del stop)`, así que las acciones
    son `riesgo × 100 ÷ (precio × stop)` y el costo en R es `0,04 × 100 ÷
    (precio × stop)`. Con stop del 20% y un papel de $2, eso da **0,10 R por
    trade**: el 10% del riesgo se va en comisión y spread antes de que el precio
    se mueva. El corto vive del mismo problema pero cobra una caída del 10-30%
    cuando acierta; el largo de esta población cobra mucho menos.
    """
    import motor
    print("\n\n=== ETAPA 4 · ¿SEÑAL O FRICCIÓN? ===")
    print("  La columna 'sincosto' NO es operable: es el contrafáctico de "
          "$0,00 por acción.\n")
    print(f"  {'estrategia':<34} {'con costo':>10} {'sin costo':>10} "
          f"{'fricción':>10} {'ses/m':>7}")
    print("  " + "-" * 76)
    guardado = motor.COSTO_ACCION
    for lab, señal, ap, p, _ in candidatos:
        con = evaluar(f"largo·{lab}", señal, lado="long", familia="largo",
                      dias=dias, stop=20.0, apertura=ap, pob=p, guardar=False)
        motor.COSTO_ACCION = 0.0
        try:
            sin = evaluar(f"largo·{lab}·sincosto", señal, lado="long",
                          familia="largo", dias=dias, stop=20.0, apertura=ap,
                          pob=p, guardar=False)
        finally:
            motor.COSTO_ACCION = guardado
        if "error" in con or "error" in sin:
            continue
        print(f"  {lab:<34} {con['bruto_R']:>+10.3f} {sin['bruto_R']:>+10.3f} "
              f"{con['bruto_R'] - sin['bruto_R']:>+10.3f} {con['ses_mes']:>7.1f}")


def etapa_anatomia(dias):
    """Por qué NO hay largo. Tres mediciones que explican el resultado.

    Una tabla llena de ceros no es una explicación: hay que mostrar el
    mecanismo. Acá se contestan las tres preguntas que quedan abiertas cuando
    todo da cero.
    """
    import math
    import statistics as st
    from chavineta import clasificar_apertura

    print("\n\n=== ETAPA 5 · ANATOMÍA DEL CERO ===")

    # ---- (1) ¿+0,017 R es distinto de cero? -----------------------------
    #
    # La tabla ordena por media y la media de una muestra chica ordena por
    # ruido. Sin el error estándar, el primer puesto de la tabla no significa
    # nada. `t` es la media dividida por su error estándar: abajo de 2 no hay
    # con qué distinguirlo del cero.
    print("\n  (1) ¿El mejor número es distinto de CERO?")
    print(f"  {'estrategia':<30} {'n':>4} {'media R':>9} {'desvío':>8} "
          f"{'err.est':>8} {'t':>6} {'R/mes':>7}")
    print("  " + "-" * 78)
    pruebas = [(lab, s, ap, p, n) for lab, s, ap, p, n in FINALISTAS]
    pruebas.append(("cont1030·exp0-50·obj40", s_continuacion(), None,
                    pob(min_expansion=0, max_expansion=50), "objetivo +40%"))
    for lab, señal, ap, p, _ in pruebas:
        kw = {"objetivo_pct": 40.0} if lab.endswith("obj40") else {}
        r = evaluar(f"largo·{lab}", señal, lado="long", familia="largo",
                    dias=dias, stop=20.0, apertura=ap, pob=p, guardar=False, **kw)
        if "error" in r:
            continue
        v = list(r["serie"].values())
        m, sd = st.mean(v), st.pstdev(v)
        ee = sd / math.sqrt(len(v)) if v else 0
        print(f"  {lab:<30} {len(v):>4} {m:>+9.3f} {sd:>8.3f} {ee:>8.3f} "
              f"{(m / ee if ee else 0):>6.2f} {m * r['ses_mes']:>+7.3f}")

    # ---- (2) el drift crudo de la población ------------------------------
    #
    # Sin stop, sin costos, sin señal: cuánto se mueve el papel desde las 10:01
    # hasta el cierre. Es el techo teórico de cualquier largo que aguante la
    # sesión. Si acá no hay nada, ninguna gestión de salida lo va a inventar.
    print("\n  (2) Drift crudo 10:01 → cierre, sin stop ni costos (%)")
    print(f"  {'población':<22} {'n':>5} {'media':>8} {'mediana':>8} "
          f"{'>0':>6} {'p10':>8} {'p90':>8}")
    print("  " + "-" * 70)

    def crudo(sel):
        out = []
        for d in sel:
            i = d.idx_en(DESDE_ETIQUETA)
            c = d.rth_close
            if i is None or not c or not d.bars[i][4]:
                continue
            out.append(100 * (c / d.bars[i][4] - 1))
        return out

    def _q(v, q):
        s = sorted(v)
        return s[min(len(s) - 1, int(q * len(s)))]

    for lab, lo, hi in (("exp 0-50", 0, 50), ("exp 50-100", 50, 100),
                        ("exp 100-150", 100, 150), ("exp >150", 150, 1e9),
                        ("todo", 0, 1e9)):
        sel = [d for d in dias if lo <= (d.expansion_pct or 0) < hi]
        v = crudo(sel)
        if len(v) < 20:
            continue
        print(f"  {lab:<22} {len(v):>5} {st.mean(v):>+8.2f} "
              f"{st.median(v):>+8.2f} {100 * sum(1 for x in v if x > 0) / len(v):>5.0f}% "
              f"{_q(v, .10):>+8.2f} {_q(v, .90):>+8.2f}")

    # ---- (3) cuánto de lo lindo era look-ahead ---------------------------
    #
    # La medición que hacía parecer vivo al largo: comprar a las 09:35 en días
    # "reclaim" de expansión baja daba +5,4% de media. Acá se compara contra la
    # MISMA entrada pero con el reclaim confirmado EN VIVO (5 cierres sobre el
    # máximo de pre-market antes de las 09:35). La diferencia entre las dos
    # columnas es exactamente el valor de saber el futuro.
    print("\n  (3) El precio de la etiqueta: 09:35, expansión 0-100%")
    print(f"  {'variante':<44} {'n':>5} {'media':>8} {'mediana':>8} {'>0':>6}")
    print("  " + "-" * 76)
    h = APERTURA_RTH + 5 / 60.0
    base = [d for d in dias if 0 <= (d.expansion_pct or 0) < 100]

    def mueve(sel):
        v = []
        for d in sel:
            i = d.idx_en(h)
            c = d.rth_close
            if i is None or not c or not d.bars[i][4]:
                continue
            v.append(100 * (c / d.bars[i][4] - 1))
        return v

    for lab, sel in (
            ("etiqueta reclaim (mira hasta las 10:00) — HUMO",
             [d for d in base if clasificar_apertura(d) == "reclaim"]),
            ("reclaim confirmado EN VIVO a las 09:35 — operable",
             [d for d in base
              if (i := d.idx_en(h)) is not None and _reclaim_vivo(d, i)]),
            ("toda la banda, sin condición",
             base)):
        v = mueve(sel)
        if len(v) < 20:
            print(f"  {lab:<44} {len(v):>5}   (muestra corta)")
            continue
        print(f"  {lab:<44} {len(v):>5} {st.mean(v):>+8.2f} "
              f"{st.median(v):>+8.2f} "
              f"{100 * sum(1 for x in v if x > 0) / len(v):>5.0f}%")


def etapa_dia2():
    """EL DÍA 2: la única otra población que los datos YA bajados permiten.

    El censo son días con `gap_pct >= 25%` — por construcción, papeles que ya
    saltaron. Si el largo no vive ahí, la pregunta obvia es dónde sí, y la única
    otra población alcanzable sin bajar datos nuevos es el día SIGUIENTE al
    evento: la descarga trae 4 días extra por llamada, así que ya están.

    Y es una población legítima, no un resto: al cierre del día 1 ya sabés que
    mañana es el día 2 de un runner. No hay nada del futuro en esa selección.

    Se excluyen los días que a su vez son evento del censo, para no medir dos
    veces lo mismo con otro nombre.

    Esto NO usa `universo()`: ese caché está restringido al censo. Carga a mano y
    tarda unos segundos.
    """
    import statistics as st
    from collections import defaultdict
    from dias import cargar, dias_con_barras, dias_de_poblacion
    from massive.minutes import MinuteStore

    print("\n\n=== ETAPA 6 · ¿Y EN EL DÍA 2? ===")
    censo = dias_de_poblacion()
    store = MinuteStore()
    try:
        todos = dias_con_barras(store.conn)
    finally:
        store.close()
    por_tk = defaultdict(list)
    for t, d, _ in todos:
        por_tk[t].append(d)
    for t in por_tk:
        por_tk[t].sort()

    siguiente = set()
    for t, d in censo:
        post = [x for x in por_tk.get(t, []) if x > d]
        if post:
            siguiente.add((t, post[0]))
    siguiente -= censo
    dias2 = list(cargar(solo=siguiente))
    print(f"  día+1 del censo, con barras y que no son evento: {len(dias2)}")

    def mueve(sel, h):
        v = []
        for d in sel:
            i = d.idx_en(h)
            c = d.rth_close
            if i is None or not c or not d.bars[i][4]:
                continue
            v.append(100 * (c / d.bars[i][4] - 1))
        return v

    def _q(v, q):
        s = sorted(v)
        return s[min(len(s) - 1, int(q * len(s)))]

    print(f"\n  {'entrada':<10} {'n':>5} {'media':>8} {'mediana':>8} {'>0':>6} "
          f"{'p10':>8} {'p90':>8}")
    print("  " + "-" * 58)
    for h, lab in ((APERTURA_RTH + 5 / 60, "09:35"), (DESDE_ETIQUETA, "10:01"),
                   (10.5, "10:30"), (11.5, "11:30")):
        v = mueve(dias2, h)
        if len(v) < 20:
            continue
        print(f"  {lab:<10} {len(v):>5} {st.mean(v):>+8.2f} {st.median(v):>+8.2f} "
              f"{100 * sum(1 for x in v if x > 0) / len(v):>5.0f}% "
              f"{_q(v, .10):>+8.2f} {_q(v, .90):>+8.2f}")
    for est in ("front", "back"):
        sel = [d for d in dias2 if d.estado_en(10.5) == est]
        v = mueve(sel, 10.5)
        if len(v) < 20:
            continue
        print(f"  10:30 {est:<4} {len(v):>5} {st.mean(v):>+8.2f} "
              f"{st.median(v):>+8.2f} "
              f"{100 * sum(1 for x in v if x > 0) / len(v):>5.0f}% "
              f"{_q(v, .10):>+8.2f} {_q(v, .90):>+8.2f}")
    print("\n  Lectura: el día 2 es una MONEDA (media ±0,3%, mediana negativa,"
          "\n  45-47% de días positivos). No hay largo pero tampoco hay corto: el"
          "\n  drift bajista del día 1 no sobrevive a la noche. Confirma que lo que"
          "\n  hace ganar al corto es el agotamiento del MISMO día del gap, y que"
          "\n  esa es la única asimetría que hay en estos datos.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--etapa", default="todo",
                    choices=("todo", "poblacion", "mecanismos", "stops",
                             "friccion", "anatomia", "dia2"))
    a = ap.parse_args()

    dias = universo()
    print(f"  universo: {len(dias)} días en caché")

    if a.etapa in ("todo", "poblacion"):
        etapa_poblacion(dias)
    if a.etapa in ("todo", "mecanismos"):
        etapa_mecanismos(dias, CANDIDATAS)
    if a.etapa in ("todo", "stops"):
        etapa_stops(dias, FINALISTAS)
    if a.etapa in ("todo", "friccion"):
        etapa_friccion(dias, FINALISTAS)
    if a.etapa in ("todo", "anatomia"):
        etapa_anatomia(dias)
    if a.etapa in ("todo", "dia2"):
        etapa_dia2()

    if RES:
        tabla("TODO LO CORRIDO, ordenado por bruto_R")


if __name__ == "__main__":
    main()
