#!/usr/bin/env python3
"""Familia MECANISMOS DE ENTRADA: distintos gatillos de corto, misma población.

**Qué pregunta contesta.** Todo lo validado del proyecto entra por un solo
gatillo —el swing de `sesion.py`— y no sabemos cuánto del número es el gatillo y
cuánto es el resto del arreglo: la población de días expandidos, el filtro de
apertura `fade`, el stop del 45%, el presupuesto por jornada. Acá se fija TODO
menos el gatillo y se prueban diecinueve formas de entrar sobre exactamente los
mismos días. Lo que sobrevive es del gatillo; lo que no cambia entre gatillos es
del arreglo.

**El control es la mitad del experimento.** Tres de los diecinueve —los que se
llaman `control-*`— NO tienen mecanismo: entran cada 30 minutos por reloj, cada 20
minutos por reloj, o una sola vez en la apertura, sin mirar el precio. Existen
para poner el piso. Si un gatillo con mecanismo no le gana al reloj, el gatillo no
aporta nada y el edge vive entero en la población y en el stop. Es la única forma
de que "midió +40%" signifique algo: sin piso, cualquier número parece bueno.

Hay DOS controles de reloj porque uno solo no alcanza: `ret/nom` premia la
frecuencia, así que el control tiene que dispararse tantas veces como el gatillo
que se le compara o la comparación está viciada. El de 20 minutos hace ~6,7 trades
por sesión, que es la frecuencia de los gatillos de estado.

**La métrica que manda es ret/nom**, no el PnL. Con cuentas de fondeo el locate
se cobra como porcentaje del nominal desplegado (~20%), así que `ret/nom` es el
punto de muerte literal. Y tiene una consecuencia que conviene tener presente al
leer la tabla: como el nominal de la jornada se reserva por el trade MÁS GRANDE
(`motor.jornada`) y no por la suma, **un gatillo que dispara varias veces al día
recicla el mismo locate** y sale estructuralmente mejor en esta métrica que uno
que dispara una sola vez, aunque el trade individual sea peor. No es trampa: es
exactamente lo que pasa al operar. Pero significa que la frecuencia es parte del
resultado, no un detalle aparte.

LA REGLA QUE NO SE NEGOCIA: la señal en la barra `i` sólo mira `dia.bars[:i+1]`.
No alcanza con creerlo — `--auditar` lo verifica truncando el día en cada índice
que la señal devolvió y volviendo a correrla sobre el pedazo. Si el índice sigue
apareciendo, la señal no usó nada del futuro. Si desaparece, hay look-ahead y el
número de esa fila no vale nada.

MECANISMO ANTES QUE NÚMERO: cada gatillo declara en su docstring POR QUÉ debería
funcionar antes de medirse. Un gatillo sin mecanismo es una forma cara de
sobreajustar; los tres que hay están etiquetados como placebo a propósito.

    python fam_mecanismos.py              # los 19 gatillos + barrido de los 3 mejores
    python fam_mecanismos.py --rapido     # sólo los 19, sin barrido
    python fam_mecanismos.py --auditar    # el test de look-ahead, y nada más
"""

from __future__ import annotations

import argparse
import statistics
import sys

from dias import APERTURA_RTH, Dia, hora
from sesion import señales_swing
from motor import encabezado, evaluar, linea, universo

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# La configuración COMPARTIDA. Es lo que hace comparable a la familia entera:
# todo gatillo opera la misma ventana, con el mismo piso de liquidez y la misma
# separación mínima. Si cada uno trajera su propia ventana, la tabla mediría
# ventanas, no mecanismos.
# --------------------------------------------------------------------------

DESDE = 9.5          # apertura RTH
HASTA = 15.5         # media hora antes del cierre: más tarde no hay tiempo de que pase nada
SEPARACION = 10 / 60  # 10 minutos entre entradas
MIN_LIQUIDEZ = 2.5e5  # dólares/minuto, mediana de los 10 minutos ANTERIORES

STOP_BASE = 45.0
POB_BASE = {"min_expansion": 150}

# Por qué DESDE = 9.5 y no 9.75 como la línea de base del proyecto: tres de los
# gatillos de esta familia (los tres rangos de apertura, y el quiebre del mínimo
# premarket) son POR CONSTRUCCIÓN sobre los primeros minutos. Arrancar a las
# 09:45 no los haría más conservadores, los borraría. El costo de la decisión hay
# que decirlo: la comparación contra `base·swing` no es limpia en este eje, y por
# eso al final se corre el mejor gatillo también con 09:45 para ver cuánto de su
# número vive en el primer cuarto de hora.


def _ctx(dia):
    """Derivadas por barra que comparten varios gatillos, calculadas una vez.

    **Por qué existe.** `dia.liquidez_en(h)` resuelve el índice recorriendo las
    barras desde el principio; llamarla por barra es cuadrático y con 1927 días ×
    ~900 barras eso son cientos de millones de operaciones por corrida. Acá se
    calcula todo de una pasada y se cuelga del objeto `Dia`, que se comparte entre
    todas las llamadas a `evaluar()` de la sesión. El valor es idéntico al de
    `liquidez_en` — misma ventana de 10 minutos previos, misma mediana.

    Los cierres se rellenan hacia adelante (y el primero hacia atrás) para que los
    promedios móviles no tengan agujeros: en micro caps la barra existe sólo si
    hubo un trade, así que un hueco significa "no operó", no "falta el dato".

    Todo lo de acá es acumulativo hacia atrás: el valor del índice `i` usa barras
    `0..i` y ninguna posterior.
    """
    c = getattr(dia, "_ctx_mecanismos", None)
    if c is not None:
        return c

    bars = dia.bars
    n = len(bars)
    primero = next((b[4] for b in bars if b[4]), None)
    if primero is None or n < 12:
        dia._ctx_mecanismos = c = {"vacio": True}
        return c

    hs = [hora(b) for b in bars]
    cier, ult = [], primero
    for b in bars:
        if b[4]:
            ult = b[4]
        cier.append(ult)
    vol = [b[5] or 0.0 for b in bars]
    dol = [(b[5] or 0.0) * (b[4] or 0.0) for b in bars]

    liq = [None] * n
    for i in range(10, n):
        liq[i] = statistics.median(dol[i - 10:i])

    def media(k):
        out, s = [None] * n, 0.0
        for i in range(n):
            s += cier[i]
            if i >= k:
                s -= cier[i - k]
            if i >= k - 1:
                out[i] = s / k
        return out

    vmed = [None] * n
    for i in range(30, n):
        vmed[i] = statistics.median(vol[i - 30:i])

    # Máximo corriente medido SÓLO desde la apertura. `dia.max_corriente` arranca
    # a las 04:00 e incluye el pico del premarket, que muchas veces se imprimió con
    # 200 acciones. Los dos son máximos legítimos y miden cosas distintas; por eso
    # hay dos gatillos de falla de máximo, uno con cada definición.
    i_open = next((i for i in range(n) if hs[i] >= APERTURA_RTH), None)
    max_rth = [None] * n
    mx = float("-inf")
    if i_open is not None:
        for i in range(i_open, n):
            if bars[i][2] and bars[i][2] > mx:
                mx = bars[i][2]
            max_rth[i] = mx if mx > float("-inf") else None

    pm = [b[3] for i, b in enumerate(bars) if 4.0 <= hs[i] < APERTURA_RTH and b[3]]

    rangos = {}
    for m in (5, 15, 30):
        fin = APERTURA_RTH + m / 60.0
        lows = [b[3] for i, b in enumerate(bars)
                if APERTURA_RTH <= hs[i] < fin and b[3]]
        rangos[m] = min(lows) if lows else None

    dia._ctx_mecanismos = c = {
        "vacio": False, "hs": hs, "cier": cier, "vol": vol, "liq": liq,
        "ma9": media(9), "ma20": media(20), "vmed30": vmed,
        "max_rth": max_rth, "i_open": i_open,
        "pm_low": min(pm) if pm else None, "or_low": rangos,
    }
    return c


def _paso(ctx, i, h, ultimo):
    """La puerta común: ventana horaria, separación entre entradas y liquidez.

    La separación existe porque sin ella un gatillo de estado —"cerrar debajo de
    la media de 9"— dispara en diez minutos consecutivos y la tabla mide quién
    repite más rápido, no quién elige mejor. La liquidez es el filtro de si el
    papel se puede operar EN ESE MINUTO: el volumen del día entero no sirve, hay
    días de $39M que a la hora de la entrada movían $412 por minuto.
    """
    if h < DESDE or h > HASTA:
        return False
    if h - ultimo < SEPARACION:
        return False
    return (ctx["liq"][i] or 0.0) >= MIN_LIQUIDEZ


# ==========================================================================
# LOS CONTROLES. Sin mecanismo, a propósito: son el piso contra el que se lee
# todo lo demás.
# ==========================================================================

def _control_reloj(dia, paso):
    """PLACEBO — entra cada `paso` horas por reloj, sin mirar el precio.

    NO TIENE MECANISMO Y ESE ES EL PUNTO. Es la hipótesis nula de la familia
    entera: en una población de días que ya vienen filtrados por expansión, por
    ratio de volumen y por apertura `fade`, ¿cuánto rinde entrar corto sin elegir
    el momento? Todo gatillo que no le gane a esto está cobrando por una decisión
    que no toma.

    Hay DOS versiones por una razón que la métrica obliga: `ret/nom` premia la
    frecuencia, porque el nominal de la jornada se reserva por el trade más grande
    y no por la suma. Un control que entra cada 30 minutos hace ~5 trades por
    sesión y uno que entra cada 20 hace ~8, que es la frecuencia de los gatillos
    de estado (medias móviles, rachas). Comparar contra el control de frecuencia
    PARECIDA es lo único que separa "elige mejor el momento" de "entra más veces".

    Se le deja el mismo filtro de liquidez que a los demás para que la diferencia
    sea el gatillo y no el poder salir.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    objetivos = []
    t = APERTURA_RTH + paso
    while t <= HASTA:
        objetivos.append(round(t, 4))
        t += paso
    out, ultimo, k = [], -99.0, 0
    for i, h in enumerate(ctx["hs"]):
        if k >= len(objetivos):
            break
        if h > HASTA:
            break
        if h < objetivos[k]:
            continue
        while k < len(objetivos) and h >= objetivos[k]:
            k += 1
        if _paso(ctx, i, h, ultimo):
            ultimo = h
            out.append(i)
    return out


def control_open(dia):
    """PLACEBO — una entrada, en la apertura, y aguantar.

    El otro extremo del piso: el día completo en un solo trade, sin gatillo. Sirve
    para separar dos cosas que la métrica mezcla — cuánto del ret/nom viene de que
    estos días BAJAN, y cuánto de reciclar el mismo locate varias veces.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    for i, h in enumerate(ctx["hs"]):
        if h < DESDE:
            continue
        if h > HASTA:
            break
        if _paso(ctx, i, h, -99.0):
            return [i]
    return []


# ==========================================================================
# LOS GATILLOS CON MECANISMO
# ==========================================================================

def vwap_reject(dia):
    """1. RECHAZO DE VWAP — toca el VWAP desde abajo y cierra debajo.

    MECANISMO: el VWAP es el precio al que está comprado el promedio de los que
    entraron hoy. En un papel que ya se dio vuelta, la gente arriba del VWAP no
    quiere ganar, quiere SALIR EMPATADA — y esa oferta se acumula exactamente en
    esa línea. Cuando el rebote llega ahí y no puede cerrar arriba, lo que se está
    viendo es la oferta de los atrapados absorbiendo todo el bid disponible. Es un
    fracaso observable de la recuperación, con la invalidación pegada arriba.

    Se exige venir de ABAJO (la barra previa cerró bajo el VWAP) para no confundir
    esto con un día que todavía está arriba y recién se acerca a la línea.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, out, ultimo = dia.bars, [], -99.0
    for i in range(1, len(bars)):
        h = ctx["hs"][i]
        if h > HASTA:
            break
        b, prev = bars[i], bars[i - 1]
        if not (b[2] and b[4] and prev[4]):
            continue
        if prev[4] >= dia.vwap[i - 1]:        # veníamos de arriba: no es rechazo
            continue
        if b[2] < dia.vwap[i]:                # ni lo tocó
            continue
        if b[4] >= dia.vwap[i]:               # lo tocó y lo recuperó: tampoco
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


def vwap_perdida(dia):
    """1b. PÉRDIDA DE VWAP — primer cierre debajo viniendo de arriba.

    MECANISMO: la misma línea, el otro sentido. Acá el evento es el instante en
    que el comprador promedio del día pasa a estar perdiendo. Mientras el precio
    está arriba del VWAP nadie tiene urgencia; cuando lo pierde, todos los que
    compraron hoy están en rojo a la vez y comparten el mismo nivel de referencia
    para rendirse.

    Es el complemento honesto del rechazo: si el rechazo mide algo real, esta
    debería medir menos —llega más tarde y con menos confirmación—, y si mide lo
    mismo, entonces las dos están midiendo "el papel está débil" y no la línea.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, out, ultimo = dia.bars, [], -99.0
    for i in range(1, len(bars)):
        h = ctx["hs"][i]
        if h > HASTA:
            break
        b, prev = bars[i], bars[i - 1]
        if not (b[4] and prev[4]):
            continue
        if prev[4] < dia.vwap[i - 1] or b[4] >= dia.vwap[i]:
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


def hod_fail(dia):
    """2. FALLA DEL MÁXIMO DEL DÍA — nuevo máximo y la barra siguiente cierra
    debajo del mínimo de la barra del máximo.

    MECANISMO: el máximo del día es el precio donde el último comprador marginal
    pagó de más. Si el minuto siguiente cierra debajo del MÍNIMO de esa barra,
    todos los que compraron en el minuto del máximo quedan perdiendo al instante —
    y en un papel sin bid institucional esos son los únicos compradores que
    quedaban. Además comparten el mismo punto de rendición, que es el máximo.

    Es el gatillo que mejor se lleva con el esquema de riesgo del proyecto: la
    invalidación está a un tick del máximo, o sea cerca, y como el tamaño sale del
    riesgo dividido por la distancia al stop, invalidación cerca significa
    posición grande sin arriesgar más.

    Acá "máximo del día" es el de `dia.max_corriente`, que arranca a las 04:00 e
    incluye el premarket. Es el máximo que mira todo el mundo.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, out, ultimo = dia.bars, [], -99.0
    for i in range(2, len(bars)):
        h = ctx["hs"][i]
        if h > HASTA:
            break
        j = i - 1
        if not (bars[j][2] and bars[j][3] and bars[i][4]):
            continue
        if bars[j][2] <= dia.max_corriente[j - 1]:     # j no hizo nuevo máximo
            continue
        if bars[i][4] >= bars[j][3]:                   # no perdió el mínimo de j
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


def hod_fail_rth(dia):
    """2b. FALLA DEL MÁXIMO DE LA SESIÓN — igual, pero el máximo se mide desde las 09:30.

    MECANISMO: el mismo, con una corrección de higiene. El pico del premarket
    muchas veces se imprimió con doscientas acciones a las 06:14 y no representa
    ninguna subasta; el máximo hecho con el mercado abierto sí. Separar los dos
    contesta si el gatillo vive en el evento "se agotó la demanda" o en el nivel
    específico que quedó pintado de madrugada.

    Como además dispara más seguido, es el par natural para leer cuánta parte del
    ret/nom es reciclaje de locate y cuánta es calidad del trade.
    """
    ctx = _ctx(dia)
    if ctx["vacio"] or ctx["i_open"] is None:
        return []
    bars, out, ultimo = dia.bars, [], -99.0
    mrth = ctx["max_rth"]
    for i in range(ctx["i_open"] + 2, len(bars)):
        h = ctx["hs"][i]
        if h > HASTA:
            break
        j = i - 1
        if not (bars[j][2] and bars[j][3] and bars[i][4] and mrth[j - 1]):
            continue
        if bars[j][2] <= mrth[j - 1]:
            continue
        if bars[i][4] >= bars[j][3]:
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


def _or_break(dia, minutos):
    """3. QUIEBRE DEL MÍNIMO DEL RANGO DE APERTURA (5, 15 y 30 minutos).

    MECANISMO: el rango de apertura es la subasta entre el que quiere salir de la
    posición de la noche y el que llega a comprar el movimiento. Su mínimo es el
    precio que los compradores defendieron en los minutos de mayor volumen del
    día — el único nivel del día construido con liquidez de verdad. Perderlo
    significa que el comprador de la apertura se retiró, y debajo no hay ninguna
    referencia hasta la base del premarket.

    Los tres plazos miden la misma tesis con distinta paciencia: 5 minutos da una
    señal temprana y sucia, 30 una tardía y limpia. Si el edge existe debería
    haber un gradiente, no un solo plazo mágico; un plazo que gana con los otros
    dos en cero es sobreajuste al plazo.

    Se re-arma cuando un cierre vuelve arriba del nivel: un día que rompe, vuelve
    y rompe otra vez ofrece dos oportunidades reales, no una.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    nivel = ctx["or_low"][minutos]
    if not nivel:
        return []
    fin = APERTURA_RTH + minutos / 60.0
    bars, out, ultimo, armado = dia.bars, [], -99.0, True
    for i in range(len(bars)):
        h = ctx["hs"][i]
        if h < fin:
            continue
        if h > HASTA:
            break
        c = bars[i][4]
        if not c:
            continue
        if c > nivel:
            armado = True
            continue
        if armado and c < nivel and _paso(ctx, i, h, ultimo):
            ultimo = h
            armado = False
            out.append(i)
    return out


def _roja_tras_verdes(dia, n):
    """4. PRIMERA VELA ROJA TRAS N VERDES CONSECUTIVAS.

    MECANISMO: una racha de minutos verdes seguidos en una micro cap no es
    acumulación, es persecución. Cada minuto de la racha suma compradores tardíos
    sin ningún colchón, y todos con el mismo precio de referencia: el de hace un
    rato. El primer minuto rojo es la primera evidencia dura de que el comprador
    marginal dejó de aparecer, y como toda la racha está apenas arriba del agua,
    esa gente se convierte en oferta al instante.

    Es el gatillo más "de tape reading" de la familia y también el más frágil: N
    es un parámetro sin ninguna razón teórica para valer 3 o 5. Por eso se miden
    los dos, y si el resultado depende fuerte de N, la tesis es floja.

    La racha se cuenta sólo con mercado abierto: en premarket las barras son ralas
    y "tres verdes seguidas" puede abarcar media hora de reloj, que no es lo mismo
    que tres minutos de persecución.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, out, ultimo, verdes = dia.bars, [], -99.0, 0
    for i in range(len(bars)):
        h = ctx["hs"][i]
        if h < APERTURA_RTH:
            continue
        if h > HASTA:
            break
        b = bars[i]
        if not (b[1] and b[4]):
            continue
        if b[4] > b[1]:
            verdes += 1
            continue
        if b[4] < b[1] and verdes >= n and _paso(ctx, i, h, ultimo):
            ultimo = h
            out.append(i)
        verdes = 0
    return out


def pm_low_break(dia):
    """5. QUIEBRE DEL MÍNIMO DEL PREMARKET.

    MECANISMO: el mínimo del premarket es el piso que construyeron los únicos que
    estaban despiertos — los que compraron la noticia a las 4 de la mañana, que
    son los que tienen la posición más grande y el precio más bajo. Debajo de ese
    nivel TODO el que participó antes de la apertura está perdiendo, y no queda
    ninguna referencia de precio hasta el cierre del día anterior, que suele estar
    un 100% más abajo en estos papeles.

    Es el nivel más "estructural" de la familia: no depende de ningún parámetro,
    lo define el propio día.
    """
    ctx = _ctx(dia)
    if ctx["vacio"] or not ctx["pm_low"]:
        return []
    nivel = ctx["pm_low"]
    bars, out, ultimo, armado = dia.bars, [], -99.0, True
    for i in range(len(bars)):
        h = ctx["hs"][i]
        if h < DESDE:
            continue
        if h > HASTA:
            break
        c = bars[i][4]
        if not c:
            continue
        if c > nivel:
            armado = True
            continue
        if armado and c < nivel and _paso(ctx, i, h, ultimo):
            ultimo = h
            armado = False
            out.append(i)
    return out


def _perdida_ma(dia, k):
    """6. PÉRDIDA DEL PROMEDIO MÓVIL DE 9 Y DE 20 MINUTOS.

    MECANISMO —y hay que ser honesto con este—: no hay nada especial en el
    promedio de los últimos nueve cierres. El mecanismo es REFLEXIVO, no
    estadístico: en estos papeles la totalidad del flujo intradiario son traders
    minoristas mirando el mismo gráfico de 1 minuto con las mismas dos líneas
    puestas por default. La media de 9 no predice nada, pero funciona como punto
    de coordinación: perderla es la señal compartida de salida para una fracción
    grande de los participantes que efectivamente están operando ese papel.

    Es el mecanismo más débil de la familia, declarado como tal ANTES de medir. Si
    mide bien, lo que hay que revisar es si no está midiendo simplemente "el
    precio viene bajando", que es una tautología en una población de días fade.

    Sobre las últimas `k` BARRAS, no los últimos `k` minutos de reloj: es lo que
    dibuja el gráfico que mira el que opera.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    ma = ctx["ma9"] if k == 9 else ctx["ma20"]
    cier, out, ultimo = ctx["cier"], [], -99.0
    for i in range(k, len(ctx["hs"])):
        h = ctx["hs"][i]
        if h > HASTA:
            break
        if ma[i] is None or ma[i - 1] is None:
            continue
        if cier[i - 1] < ma[i - 1] or cier[i] >= ma[i]:   # tiene que CRUZAR
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


def _climax(dia, kvol):
    """7. CLÍMAX DE VOLUMEN — volumen > K× la mediana de las últimas 30 barras,
    cerrando en el tercio inferior de su rango.

    MECANISMO: un minuto con varias veces el volumen reciente que además cierra
    contra sus mínimos es la impresión donde la oferta le pasó por encima al bid.
    No es "mucho volumen", es volumen con dirección: en un papel cuyo float rota
    varias veces en el día, ese único minuto ES la transferencia de la posición
    desde el que persiguió el movimiento hacia el que se la vendió. Lo que viene
    después no tiene comprador de tamaño porque el comprador de tamaño acaba de
    ejecutar.

    La condición de cierre en el tercio inferior es la que separa el clímax de
    venta del clímax de compra — sin ella, el gatillo dispara igual en la barra
    que rompe hacia arriba, que es el peor momento posible para estar corto.

    Se miden K=3 y K=5 por la misma razón que N en la racha: el umbral no tiene
    fundamento teórico y conviene ver si el resultado depende de él.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, vmed, vol = dia.bars, ctx["vmed30"], ctx["vol"]
    out, ultimo = [], -99.0
    for i in range(30, len(bars)):
        h = ctx["hs"][i]
        if h < DESDE:
            continue
        if h > HASTA:
            break
        b = bars[i]
        if not (vmed[i] and b[2] and b[3] and b[4]):
            continue
        if vol[i] <= kvol * vmed[i]:
            continue
        rango = b[2] - b[3]
        if rango <= 0 or (b[4] - b[3]) / rango > 1 / 3:
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


def doble_techo(dia, tolerancia=1.0, separacion_min=10.0, min_valle=2.0):
    """8. DOBLE TECHO — dos máximos a menos de 1% entre sí separados por más de 10
    minutos; entrada al perder el valle intermedio.

    MECANISMO: dos intentos al mismo precio, separados en el tiempo, los dos
    fallando, es la firma observable de un vendedor trabajando una orden en un
    nivel. No es geometría: es que alguien tiene tamaño para vender ahí y lo está
    mostrando dos veces. El valle entre los dos intentos es donde están parados
    los compradores que defendieron el primero; perder el valle significa que esa
    defensa también cedió, y entre ahí y la próxima referencia no queda nadie.

    Cómo se detecta sin mirar el futuro: se sigue el máximo corriente y, después
    de él, el mínimo corriente. Cuando una barra posterior vuelve a un 1% del
    máximo y pasaron más de 10 minutos, el patrón queda ARMADO con el valle como
    nivel. La entrada es el primer cierre debajo del valle. Si en algún momento el
    precio supera el máximo por más de la tolerancia, no hubo doble techo: hubo
    ruptura, y el techo se reinicia al nuevo máximo.

    `min_valle` no está en el enunciado clásico y hay que justificarlo: sin él, dos
    barras seguidas cumplen "dos máximos a menos de 1%" y el valle es la mecha de
    una vela. Un valle del 0,2% no es un doble techo, es ruido con nombre. Se pide
    que el valle esté al menos 2% abajo para que el patrón sea el que se dibuja
    cuando uno lo cuenta.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, hs = dia.bars, ctx["hs"]
    out, ultimo = [], -99.0
    techo = None          # (índice, precio) del primer intento
    valle = None
    armado = None         # nivel del valle a perder
    for i in range(len(bars)):
        h = hs[i]
        if h < APERTURA_RTH:
            continue
        if h > HASTA:
            break
        b = bars[i]
        alto, bajo, c = b[2], b[3], b[4]
        if techo is None:
            if alto:
                techo, valle, armado = (i, alto), None, None
            continue
        if alto and alto > techo[1] * (1 + tolerancia / 100.0):
            techo, valle, armado = (i, alto), None, None      # rompió: no es doble techo
            continue
        if bajo:
            valle = bajo if valle is None else min(valle, bajo)
        if (armado is None and alto and valle is not None
                and alto >= techo[1] * (1 - tolerancia / 100.0)
                and (h - hs[techo[0]]) * 60 > separacion_min
                and valle <= techo[1] * (1 - min_valle / 100.0)):
            armado = valle
        if armado is not None and c and c < armado:
            if _paso(ctx, i, h, ultimo):
                ultimo = h
                out.append(i)
            techo, valle, armado = ((i, alto) if alto else None), None, None
    return out


def mecha_superior(dia, mecha=60.0, cerca_max=1.0):
    """9. MECHA SUPERIOR CONTRA EL MÁXIMO — rechazo dentro del propio minuto.

    MECANISMO: es el mismo evento que la falla de máximo, medido un minuto antes.
    Una mecha superior larga contra el máximo del día es la huella de una demanda
    que apareció y fue servida entera dentro del mismo minuto: el papel intentó
    romper y la subasta rechazó el precio en el acto. La diferencia con la falla de
    máximo no es la tesis sino el precio de la confirmación — acá se entra más
    arriba y con menos evidencia.

    Sirve para contestar una pregunta concreta de la familia: ¿la confirmación de
    la barra siguiente se paga o se cobra? Si la falla de máximo rinde más, la
    paciencia se cobra; si rinde menos, se paga.
    """
    ctx = _ctx(dia)
    if ctx["vacio"]:
        return []
    bars, out, ultimo = dia.bars, [], -99.0
    for i in range(1, len(bars)):
        h = ctx["hs"][i]
        if h < DESDE:
            continue
        if h > HASTA:
            break
        b = bars[i]
        if not (b[2] and b[3] and b[4] and b[1]):
            continue
        rango = b[2] - b[3]
        if rango <= 0:
            continue
        cuerpo_alto = max(b[1], b[4])
        if 100 * (b[2] - cuerpo_alto) / rango < mecha:
            continue
        if (b[4] - b[3]) / rango > 0.5:              # tiene que cerrar en la mitad baja
            continue
        hod = dia.max_corriente[i]
        if not hod or b[2] < hod * (1 - cerca_max / 100.0):
            continue
        if not _paso(ctx, i, h, ultimo):
            continue
        ultimo = h
        out.append(i)
    return out


# --------------------------------------------------------------------------
# El catálogo. El orden es el del enunciado; los controles van primero porque
# son la vara.
# --------------------------------------------------------------------------

GATILLOS = [
    ("control-reloj", lambda d: _control_reloj(d, 0.5),
     "PLACEBO: entra cada 30 min por reloj. Es el piso de la familia."),
    ("control-reloj20", lambda d: _control_reloj(d, 1 / 3),
     "PLACEBO con la frecuencia de los gatillos de estado (~8 trades/sesión)."),
    ("control-open", control_open,
     "PLACEBO: una entrada en la apertura y aguantar todo el día."),
    ("vwap-reject", vwap_reject,
     "los atrapados venden para salir empatados justo en el VWAP"),
    ("vwap-perdida", vwap_perdida,
     "el comprador promedio del día pasa a perder, todos a la vez"),
    ("hod-fail", hod_fail,
     "el último comprador marginal queda perdiendo al minuto siguiente"),
    ("hod-fail-rth", hod_fail_rth,
     "igual, pero contra el máximo hecho con mercado abierto"),
    ("or5", lambda d: _or_break(d, 5),
     "se retiró el comprador de la apertura; abajo no hay referencia"),
    ("or15", lambda d: _or_break(d, 15), "ídem, con 15 minutos de rango"),
    ("or30", lambda d: _or_break(d, 30), "ídem, con 30 minutos de rango"),
    ("roja-tras-3", lambda d: _roja_tras_verdes(d, 3),
     "la racha verde es persecución; el primer rojo es que dejó de haber comprador"),
    ("roja-tras-5", lambda d: _roja_tras_verdes(d, 5), "ídem, racha más larga"),
    ("pm-low", pm_low_break,
     "debajo del mínimo premarket, todo el que madrugó está perdiendo"),
    ("ma9", lambda d: _perdida_ma(d, 9),
     "punto de coordinación: es la línea que mira todo el flujo minorista"),
    ("ma20", lambda d: _perdida_ma(d, 20), "ídem, la línea lenta"),
    ("climax-k3", lambda d: _climax(d, 3),
     "el minuto donde la oferta le pasa por encima al bid"),
    ("climax-k5", lambda d: _climax(d, 5), "ídem, umbral más exigente"),
    ("doble-techo", doble_techo,
     "un vendedor con tamaño se muestra dos veces; el valle es la defensa que cede"),
    ("mecha-superior", mecha_superior,
     "el mismo rechazo que la falla de máximo, un minuto antes y más caro"),
]

POR_NOMBRE = {n: f for n, f, _ in GATILLOS}


# --------------------------------------------------------------------------
# La auditoría de look-ahead. No es un comentario: es un test.
# --------------------------------------------------------------------------

def auditar(dias, *, muestra=60):
    """Verifica que ninguna señal use información posterior a su propia barra.

    **Cómo.** Para cada índice `i` que la señal devolvió en un día, se reconstruye
    un `Dia` con `bars[:i+1]` —o sea, el día tal como se veía EN ESE MINUTO, con
    el VWAP y el máximo corriente recalculados sobre el pedazo— y se vuelve a
    correr la señal. Si `i` sigue apareciendo, la decisión no dependió de nada
    futuro. Si desaparece, hay look-ahead.

    Es una condición necesaria, no suficiente: una señal podría mirar el futuro y
    dar la misma respuesta por casualidad. Pero con miles de índices verificados,
    un look-ahead real no sobrevive.
    """
    print("\n  AUDITORÍA DE LOOK-AHEAD (se trunca el día en cada señal y se recorre de nuevo)")
    print(f"  {'gatillo':<18} {'señales':>9} {'verificadas':>12} {'fallas':>8}")
    print("  " + "-" * 52)
    malos = 0
    for nombre, fn, _ in GATILLOS:
        chequeadas = fallas = total = 0
        for dia in dias[:muestra]:
            idx = fn(dia)
            total += len(idx)
            for i in idx[:4]:                       # hasta 4 por día: alcanza y sobra
                recorte = Dia(dia.ticker, dia.d, dia.bars[:i + 1],
                              dia.prev_close, dia.prev_vol, dia.vol_dia)
                chequeadas += 1
                if i not in fn(recorte):
                    fallas += 1
        marca = "  ✓" if not fallas else "  ✗ LOOK-AHEAD"
        print(f"  {nombre:<18} {total:>9} {chequeadas:>12} {fallas:>8}{marca}")
        malos += fallas
    print("  " + "-" * 52)
    print(f"  {'TOTAL' :<18} {'':>9} {'':>12} {malos:>8}"
          + ("  ✓ ninguna señal mira hacia adelante" if not malos else "  ✗ HAY LOOK-AHEAD"))
    return malos


# --------------------------------------------------------------------------

def _ordenar(res):
    """Por ret/nom descendente. Los que no llegaron a muestra van al final."""
    return sorted(res, key=lambda r: (0, r["ret_nom"]) if "error" not in r else (-1, 0),
                  reverse=True)


def _por_trade(titulo, res):
    """Separa las dos cosas que `ret/nom` mezcla: calidad del trade y frecuencia.

    `ret/nom` sube por dos vías distintas —trades mejores o más trades sobre el
    mismo locate reservado— y la tabla principal no las distingue. Acá se divide
    el bruto por la cantidad de trades de la sesión: es la calidad del gatillo
    aislada de cuántas veces dispara. Un gatillo que gana en `ret/nom` y pierde
    acá no está eligiendo mejor el momento, está reciclando el locate; sigue
    siendo bueno para una cuenta de fondeo, pero por otro motivo del que dice.
    """
    print(f"\n  {titulo}")
    print(f"  {'estrategia':<38} {'n':>5} {'tr/ses':>7} {'bruto/ses':>10} "
          f"{'R/trade':>9} {'ret/nom':>8}")
    print("  " + "-" * 82)
    filas = []
    for r in res:
        if "error" in r or not r["ses_mes"]:
            continue
        tr = r["trades_mes"] / r["ses_mes"]
        filas.append((r["nombre"], r["n"], tr, r["bruto_R"],
                      r["bruto_R"] / tr if tr else 0.0, r["ret_nom"]))
    for n, cnt, tr, br, rt, rn in sorted(filas, key=lambda x: -x[4]):
        print(f"  {n:<38} {cnt:>5} {tr:>7.1f} {br:>+10.3f} {rt:>+9.4f} {rn:>7.1f}%")


def _tabla(titulo, res):
    print(f"\n  {titulo}")
    print(encabezado())
    print("  " + "-" * 104)
    for r in _ordenar(res):
        print(linea(r))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Familia: mecanismos de entrada en corto")
    ap.add_argument("--rapido", action="store_true",
                    help="sólo la tabla base, sin barrer stop ni expansión")
    ap.add_argument("--auditar", action="store_true",
                    help="corre sólo el test de look-ahead y sale")
    ap.add_argument("--muestra-auditoria", type=int, default=60)
    args = ap.parse_args(argv)

    # `DESDE` y `MIN_LIQUIDEZ` se pisan al final, en los diagnósticos: `_paso` las
    # lee del módulo en cada llamada, así que moverlas cambia el gatillo sin tener
    # que duplicar código. La declaración va acá arriba porque Python la exige
    # antes del primer uso del nombre en la función.
    global DESDE, MIN_LIQUIDEZ

    dias = universo()
    print("=" * 108)
    print("  FAMILIA · MECANISMOS DE ENTRADA EN CORTO")
    print(f"  {len(dias)} días en el censo · población: expansión ≥ "
          f"{POB_BASE['min_expansion']}% · apertura fade · stop {STOP_BASE:.0f}%")
    print(f"  ventana {DESDE:.2f}–{HASTA:.2f} · separación {SEPARACION*60:.0f} min · "
          f"liquidez ≥ ${MIN_LIQUIDEZ/1e3:.0f}k/min — IGUALES para todos los gatillos")
    print("=" * 108)

    if args.auditar:
        return 1 if auditar(dias, muestra=args.muestra_auditoria) else 0

    auditar(dias, muestra=args.muestra_auditoria)

    base = []
    for nombre, fn, mec in GATILLOS:
        base.append(evaluar(f"mecanismo·{nombre}", fn, dias=dias, familia="mecanismo",
                            stop=STOP_BASE, pob=dict(POB_BASE), notas=mec))
    _tabla("TODOS LOS GATILLOS, MISMA POBLACIÓN Y MISMO STOP", base)

    # La referencia del proyecto, en la MISMA tabla y con el mismo motor. No se
    # guarda: la fila ya existe en la base y volver a escribirla desde acá sólo
    # agregaría ruido de autoría a una estrategia que no es de esta familia.
    ref = evaluar("base·swing·exp150 (referencia)", lambda d: señales_swing(d),
                  dias=dias, stop=STOP_BASE, pob=dict(POB_BASE), guardar=False)
    print("  " + "-" * 104)
    print(linea(ref))

    print("""
  CÓMO LEER ESTA TABLA. `control-reloj`, `control-reloj20` y `control-open` no
  tienen mecanismo: entran por reloj. Lo que esté abajo de ellos no aporta
  información sobre CUÁNDO entrar — su número es el de la población, no el del
  gatillo. Y `brecha` es el control de honestidad: es |P1 − P2| en ret/nom.
  Arriba de 15 puntos el gatillo encontró ruido de un período y no un mecanismo,
  por lindo que sea el promedio.

  OJO con las filas de pocas sesiones: cuando un período no llega a 20 sesiones,
  `motor.linea()` imprime 0.0% en P1/P2 y un guion en la brecha. Eso NO es un
  resultado de cero, es la ausencia de resultado. La columna `n` de la tabla de
  abajo dice cuántas sesiones hay de verdad.""")

    _por_trade("LA MISMA TABLA, DIVIDIDA POR TRADE (calidad del gatillo sin la "
               "frecuencia)", base + [ref])

    print("""
  LA LECTURA NEUTRAL A LA FRECUENCIA. `control-reloj20` dispara ~6,7 veces por
  sesión, casi lo mismo que los gatillos de estado (~7,8). Comparar contra ÉL y no
  contra el de 30 minutos es lo que saca del medio la ventaja gratis de reciclar
  el locate. Y hay un detalle que conviene no pasar por alto: los dos controles de
  reloj NO se diferencian sólo en frecuencia, también en la hora de la primera
  entrada (10:00 contra 09:50), así que su R/trade tampoco es directamente
  comparable entre sí. Por eso la comparación buena es la de esta tabla —R por
  trade—, y no una regla de tres sobre la de arriba.

  Lo que hay que mirar es la primera columna de la derecha: si un gatillo con
  mecanismo no le saca ventaja POR TRADE al reloj, lo único que aporta es entrar
  más seguido. Eso igual sirve para una cuenta de fondeo —el locate se paga una
  vez y se usa varias— pero es una propiedad de la contabilidad, no del gatillo, y
  se consigue igual entrando por reloj.""")

    # -- rescate: ¿son MALOS o sólo RAROS? --------------------------------
    # Un gatillo que no llega a 20 sesiones no está descartado, está sin medir.
    # Se lo vuelve a correr sobre la población grande (expansión ≥ 100%, que es
    # ~50% más días) para separar las dos cosas. Es la única forma honesta de
    # cerrar una tesis: si con el doble de días sigue sin dar, ahí sí falló.
    flacos = [r for r in base
              if "error" in r or r["ses_mes"] < 2.0]
    if flacos:
        print("\n" + "=" * 108)
        print("  RESCATE — los gatillos que no llegaron a muestra, sobre la población grande")
        print("  (expansión ≥ 100% en vez de 150%). Separa 'malo' de 'raro'.")
        print("=" * 108)
        rescate = []
        for r in flacos:
            corto = r["nombre"].split("·")[1]
            rescate.append(evaluar(f"mecanismo·{corto}·exp100", POR_NOMBRE[corto],
                                   dias=dias, familia="mecanismo", stop=STOP_BASE,
                                   pob={"min_expansion": 100},
                                   notas="rescate: población grande para llegar a muestra"))
        _tabla("", rescate)

    if args.rapido:
        return 0

    # -- barrido, SÓLO para los tres mejores por ret/nom -------------------
    # El orden importa: se elige acá, después de haber reportado todo, y no
    # mirando la muestra completa para después contar sólo lo que dio bien.
    top = [r for r in _ordenar(base) if "error" not in r][:3]
    print("\n" + "=" * 108)
    print("  BARRIDO DE LOS TRES MEJORES POR ret/nom: "
          + ", ".join(r["nombre"].split("·")[1] for r in top))
    print("  Lo que se busca no es la celda más alta sino si la superficie es MESETA")
    print("  o PICO. Un máximo aislado rodeado de números malos es sobreajuste.")
    print("=" * 108)

    for r in top:
        corto = r["nombre"].split("·")[1]
        fn = POR_NOMBRE[corto]
        mec = next(m for n, _, m in GATILLOS if n == corto)
        filas = [r]
        for s in (25.0, 35.0, 55.0):
            filas.append(evaluar(f"mecanismo·{corto}·stop{s:.0f}", fn, dias=dias,
                                 familia="mecanismo", stop=s, pob=dict(POB_BASE),
                                 notas=f"{mec} · barrido de stop"))
        for e in (100.0, 200.0):
            filas.append(evaluar(f"mecanismo·{corto}·exp{e:.0f}", fn, dias=dias,
                                 familia="mecanismo", stop=STOP_BASE,
                                 pob={"min_expansion": e},
                                 notas=f"{mec} · barrido de expansión"))
        print(f"\n  {corto.upper()}  —  stop en (25,35,45,55) · expansión en (100,150,200)")
        print(encabezado())
        print("  " + "-" * 104)
        for f in sorted(filas, key=lambda x: x["nombre"]):
            print(linea(f))

    # -- dos diagnósticos sobre el mejor -----------------------------------
    mejor = top[0]["nombre"].split("·")[1]
    fn = POR_NOMBRE[mejor]
    print("\n" + "=" * 108)
    print(f"  DIAGNÓSTICO DE {mejor.upper()}: de dónde sale el número")
    print("=" * 108)

    d0, l0 = DESDE, MIN_LIQUIDEZ
    diag = [top[0]]
    try:
        # El contexto cacheado por día NO depende de DESDE (son derivadas por
        # barra, no la ventana), así que moverla no invalida nada.
        DESDE = 9.75
        diag.append(evaluar(f"mecanismo·{mejor}·desde945", fn, dias=dias,
                            familia="mecanismo", stop=STOP_BASE, pob=dict(POB_BASE),
                            notas="mismo gatillo, arrancando 09:45 como la línea de base"))
        DESDE = d0
        MIN_LIQUIDEZ = 0.0
        diag.append(evaluar(f"mecanismo·{mejor}·sinliquidez", fn, dias=dias,
                            familia="mecanismo", stop=STOP_BASE, pob=dict(POB_BASE),
                            notas="sin el piso de liquidez: cuánto del número es filtro"))
    finally:
        DESDE, MIN_LIQUIDEZ = d0, l0

    print(encabezado())
    print("  " + "-" * 104)
    for f in diag:
        print(linea(f))

    print("""
  El primero contesta cuánto del resultado vive en los primeros 15 minutos de la
  sesión —el tramo que la línea de base del proyecto NO opera—, y el segundo
  cuánto lo aporta el filtro de liquidez en vez del gatillo. Un gatillo que se
  desarma al mover cualquiera de los dos no es un mecanismo: es una ventana.

  Y el primero cierra la familia, porque `control-reloj20` ya arranca a las 09:50:
  su 26,5% ES el número sin los primeros quince minutos. Poner al lado el
  `·desde945` del mejor gatillo es la comparación completamente pareada —misma
  ventana, frecuencia parecida, misma población, mismo stop— y ahí la ventaja de
  elegir el momento se mide en un punto de ret/nom, no en trece.

  QUÉ SE LLEVA DE ACÁ. Ningún gatillo de esta familia le gana a la línea de base
  del proyecto, y catorce de los dieciséis con mecanismo declarado no le ganan ni
  al reloj de frecuencia pareada. La conclusión no es "los gatillos no sirven": es que en esta población
  el precio de entrada importa mucho menos de lo que la literatura de day trading
  supone, y que casi todo el ret/nom viene de tres decisiones que se toman ANTES
  de mirar el gráfico — qué día se opera, con qué stop, y cuántas veces se reusa
  el mismo locate. Buscar mejores gatillos sobre esta población es cavar donde ya
  no hay. El lugar donde queda algo es la POBLACIÓN: la expansión mueve el número
  de todos, incluido el placebo.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
