#!/usr/bin/env python3
"""Familia POBLACIONES: los días que hoy tiramos, y si alguno tiene edge propio.

**Por qué esta familia y no otra.** Vamos a correr tres cuentas de fondeo en
paralelo y está medido que con la misma señal las tres revientan el mismo día.
La correlación entre dos estrategias que operan los MISMOS días nunca baja de
algo, por distinta que sea la regla de entrada: comparten el shock. En cambio
dos estrategias que operan días distintos tienen correlación **cero por
construcción**, no por suerte y no por diversificación estadística. Es la fuente
de decorrelación más limpia que existe, y la única que no se rompe cuando cambia
el régimen.

La configuración actual descarta muchísimo. De 1.927 días del censo el embudo
deja 163:

    1927 → ratio de volumen ≥3 (1541) → expansión premarket ≥150% (285)
         → volumen del día >$137M (242) → float <47M (204) → apertura fade (163)

Cada uno de esos cortes es una hipótesis sobre dónde vive el edge, y cada uno
tira días que podrían ser operables con OTRA regla. Este archivo mide qué hay
del otro lado de cada corte.

**El gatillo se congela.** Todo se mide con `señales_swing` y stop 45% fijo, que
es la línea de base validada del proyecto. No es que sea el mejor gatillo para
cada población — casi seguro no lo es. Es que si cambio gatillo Y población a la
vez no puedo atribuir la diferencia a ninguno de los dos. Acá se mide POBLACIÓN;
optimizar el gatillo adentro de la que sobreviva es el paso siguiente, no este.

**La métrica que manda es ret/nom.** Con cuentas de fondeo el locate se cobra
como fracción del nominal desplegado (~20% anualizado en el papel difícil), así
que `ret/nom` ES el punto de muerte. Y acá aparece el detalle que hace
interesante a media familia: el locate NO es 20% en todas las poblaciones. En
float alto y volumen alto el papel es fácil de prestar y el locate baja a un
dígito. Una población con ret/nom de 25% y locate del 5% deja más que una con
45% y locate del 20%. Por eso las poblaciones "peores" no están descartadas de
entrada.

**Qué NO mide este archivo.** El costo real de locate por población — no tenemos
esa serie. Se declara el mecanismo (float alto ⇒ locate barato) y se deja
anotado; cuando haya datos de borrow se vuelve acá.

**DOS FUGAS DEL BANCO, encontradas midiendo esta familia.** No las introduje yo y
le pegan a la línea de base igual que a todo lo demás, así que las comparaciones
entre celdas siguen valiendo; los NIVELES absolutos de todo el proyecto, no.

  1. `clasificar_apertura` mira barras hasta las **10:00**, pero `señales_swing`
     puede entrar desde las **09:45**. O sea: se filtra el día con una etiqueta
     que a la hora de entrar todavía no existe. Son el 22-27% de los trades.
  2. `ratio_volumen` divide el volumen del **día completo** por el del día
     previo, y `dolar_dia` es también del día completo. Ninguno de los dos se
     conoce a las 09:30. El docstring de `motor.poblacion` avisa por `min_dolar`
     pero no por `min_ratio_vol`, que tiene exactamente el mismo problema.

El bloque 11 vuelve a medir lo importante con las dos fugas tapadas —entradas
desde las 10:00 y sin ningún filtro que use datos del día— y ahí se ve cuánto de
cada número era señal y cuánto era el futuro. Spoiler: a la base le saca 12
puntos y al hallazgo del reclaim no le saca nada.

    python fam_poblaciones.py
    python fam_poblaciones.py --refrescar     # rearma el caché de post-evento
"""

from __future__ import annotations

import argparse
import math
import pickle
import sqlite3
import statistics
import sys
import textwrap
from collections import Counter, defaultdict
from pathlib import Path

import config
from chavineta import clasificar_apertura
from dias import cargar, dias_con_barras, dias_de_poblacion
from massive.minutes import MinuteStore
from motor import correlacion, encabezado, evaluar, linea, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CACHE_POST = Path(config.data_dir()) / "universo_post.pkl"

# El embudo vigente, escrito una sola vez. Todo lo demás es este dict con una
# pieza cambiada, así que si mañana se mueve un umbral se mueve acá.
BASE = dict(min_ratio_vol=3.0, min_expansion=150.0, min_dolar=137e6,
            max_float=47e6)
# Y su opuesto: ningún corte. Sirve para las poblaciones donde el filtro que
# quiero probar ya es bastante restrictivo por sí solo.
ABIERTA = dict(min_ratio_vol=0, min_expansion=0, min_dolar=0, max_float=None)


def _con(base, **cambios):
    return dict(base, **cambios)


# --------------------------------------------------------------------------
# El post-evento: los días 2, 3 y 4 de un movimiento.
# --------------------------------------------------------------------------

def universo_post(refrescar: bool = False):
    """Los días SIGUIENTES a un evento del censo, que el censo no incluye.

    Es la población virgen de verdad. Cada descarga de minutos trajo el día del
    evento **más los ~4 siguientes**, y esos días de después nunca se midieron:
    no los sorteó nadie, así que quedaron afuera del censo y de todo el
    análisis. Son 4.155 jornadas con barras completas, más del doble que el
    censo entero.

    **Por qué no es look-ahead operarlos.** Un día post-evento se define por lo
    que pasó AYER: ayer el papel gapeó, ayer operó volumen. A las 09:30 de hoy
    eso ya es historia y está en la pantalla. La condición de entrada al
    universo es puramente retrospectiva, que es exactamente lo que el censo
    observable exige. (Distinto sería filtrar por el rango de HOY, que es el
    sesgo que invalidó la muestra vieja de 1.500 días.)

    Se marca `dia.post_k` = cuántas ruedas pasaron desde el evento. Si el papel
    vuelve a calificar como evento, la cadena se corta ahí: ese día ya lo opera
    la población actual y no es virgen.

    El float sale de `event_structure` con la fila más reciente **anterior o
    igual** a la fecha. Point-in-time: nunca la de después.
    """
    # Caché en pickle por el mismo motivo que `motor.universo()`: guarda objetos
    # `Dia` ya armados y rearmarlos cuesta 20s por corrida. Lo escribe ESTE módulo
    # en el directorio de datos local; nunca se carga un pickle de otra procedencia.
    if CACHE_POST.exists() and not refrescar:
        with open(CACHE_POST, "rb") as fh:
            return pickle.load(fh)

    store = MinuteStore()
    filas = dias_con_barras(store.conn)
    store.close()
    pob = dias_de_poblacion()

    db = sqlite3.connect(config.bars_db_path())
    cal = sorted({d for (d,) in db.execute("SELECT DISTINCT d FROM bars_daily")})
    est = defaultdict(list)
    for t, d, so in db.execute(
            "SELECT ticker,d,shares_outstanding FROM event_structure ORDER BY d"):
        if so:
            est[t].append((d, so))
    db.close()

    idx = {d: i for i, d in enumerate(cal)}
    con_barras = defaultdict(set)
    for t, d, _ in filas:
        con_barras[t].add(d)

    orden = {}
    for t, d in sorted(pob):
        i = idx.get(d)
        if i is None:
            continue
        for k in (1, 2, 3, 4):
            if i + k >= len(cal):
                break
            dd = cal[i + k]
            if (t, dd) in pob:      # volvió a ser evento: deja de ser virgen
                break
            if dd in con_barras[t]:
                orden.setdefault((t, dd), k)

    out = []
    for dia in cargar(solo=set(orden)):
        dia.dolar_dia = sum((b[5] or 0) * (b[4] or 0) for b in dia.bars)
        dia.post_k = orden[(dia.ticker, dia.d)]
        fl = None
        for d0, so in est.get(dia.ticker, []):
            if d0 <= dia.d:
                fl = so
        dia.float_acciones = fl
        out.append(dia)
    with open(CACHE_POST, "wb") as fh:
        pickle.dump(out, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return out


def censo_por_orden(dias, *, ventana_dias: int = 5):
    """Marca cada día del censo con su ORDEN dentro de una racha del ticker.

    Lo que pidió Agus: agrupar el censo por ticker, ordenar por fecha, y separar
    la primera aparición de la segunda y la tercera. Un ticker que vuelve a
    calificar como evento dentro de `ventana_dias` está en la misma racha.

    Ojo con la diferencia respecto de `universo_post`: acá el día 2 **también
    califica como evento** (volvió a gapear ≥25% con liquidez), o sea es la
    segunda pierna de una parabólica. En `universo_post` el día 2 es cualquier
    día siguiente, califique o no. Son dos poblaciones distintas y la del censo
    es mucho más chica.
    """
    from datetime import date
    por_tk = defaultdict(list)
    for d in dias:
        por_tk[d.ticker].append(d)
    for tk, v in por_tk.items():
        v.sort(key=lambda x: x.d)
        prev, k = None, 1
        for d in v:
            if prev is not None:
                salto = (date.fromisoformat(d.d) - date.fromisoformat(prev)).days
                k = k + 1 if salto <= ventana_dias else 1
            d.orden_racha = k
            prev = d.d
    return dias


# --------------------------------------------------------------------------
# El banco de medición
# --------------------------------------------------------------------------

RES = []          # (resultado, n_candidatos, hipotesis)


def medir(nombre, hipotesis, *, dias, pob, apertura="fade", notas=""):
    """Declara la hipótesis, mide, y guarda el resultado para la tabla final.

    El orden importa y no es decorativo: la hipótesis se imprime ANTES del
    número. Si se escribe después, deja de ser una hipótesis y pasa a ser una
    explicación de lo que salió, que es como se fabrica un edge que no existe.
    """
    cand = poblacion(dias, **pob)
    if apertura:
        cand = [d for d in cand if clasificar_apertura(d) == apertura]
    print(f"\n  ── {nombre}")
    print(textwrap.fill(hipotesis, 94, initial_indent="     ",
                        subsequent_indent="     "))
    print(f"     [{len(cand)} días candidatos · "
          f"{len({d.d for d in cand})} fechas distintas]")
    r = evaluar(nombre, lambda d: señales_swing(d), dias=dias, familia="poblacion",
                lado="short", stop=45.0, apertura=apertura, pob=pob, notas=notas)
    RES.append((r, len(cand), hipotesis))
    print(linea(r))
    return r


def corr_cartera(a, b):
    """Correlación sobre la UNIÓN de fechas, rellenando con cero lo no operado.

    **Es la que importa para tres cuentas de fondeo, y no la de `motor`.** La del
    motor mide sobre las fechas COMPARTIDAS, que contesta "cuando las dos operan,
    ¿se mueven juntas?". Pero una cuenta que no operó ese día no perdió plata:
    aportó cero. Lo que hunde a tres cuentas a la vez es el PnL conjunto del
    calendario completo, y ahí un día sin operar es un cero, no un dato faltante.

    La consecuencia práctica: dos estrategias que casi no comparten fechas dan
    correlación de cartera cerca de cero **aunque adentro de las pocas fechas
    comunes estén clavadas**. Eso es exactamente la decorrelación por
    construcción que estamos buscando, y la métrica del motor no la ve.
    """
    fechas = sorted(set(a) | set(b))
    if len(fechas) < 20:
        return None
    x = [a.get(d, 0.0) for d in fechas]
    y = [b.get(d, 0.0) for d in fechas]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if not sx or not sy:
        return None
    return sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / (sx * sy)


def veredicto(r, base_fechas):
    """Traduce el resultado a una etiqueta corta, con los gates del protocolo."""
    if "error" in r:
        return "muestra corta"
    marcas = []
    if r["n"] < 40:
        marcas.append(f"n={r['n']}<40")
    # `linea()` imprime 0.0% cuando un período no llegó a 20 sesiones, y eso se
    # lee como "dio cero" cuando en realidad es "no hay dato". Sin este chequeo,
    # una población que sólo existe en un período pasa por validada.
    if r["P1"] is None or r["P2"] is None:
        marcas.append("un solo período")
    elif r["replica"] > 15:
        marcas.append(f"no replica ({r['replica']:.0f}p)")
    if r["ret_nom"] < 20:
        marcas.append("muere al 20%")
    elif r["ret_nom"] < 30:
        marcas.append("justo")
    return " · ".join(marcas) if marcas else "SIRVE"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Familia poblaciones")
    ap.add_argument("--refrescar", action="store_true",
                    help="rearma el caché de días post-evento (~20s)")
    args = ap.parse_args(argv)

    censo = censo_por_orden(universo())
    post = universo_post(refrescar=args.refrescar)
    print(f"  censo: {len(censo)} días · post-evento (virgen): {len(post)} días")
    print(f"  post por rueda: "
          f"{dict(sorted(Counter(d.post_k for d in post).items()))}")

    print("\n" + "=" * 112)
    print("  LA REFERENCIA — la población que ya operamos")
    print("=" * 112)
    print(encabezado())
    base = medir(
        "poblacion·BASE-actual",
        "El embudo vigente, medido acá para que todo lo demás se compare contra "
        "el mismo número y no contra un recuerdo. rvol≥3, expansión≥150%, "
        "volumen>$137M, float<47M, apertura fade.",
        dias=censo, pob=dict(BASE), notas="referencia del embudo actual")
    base_fechas = set(base["serie"])

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  1. EXPANSIÓN PREMARKET — hoy exigimos ≥150%; la mediana del censo es 72%")
    print("=" * 112)
    print(encabezado())

    medir("poblacion·exp-0-50",
          "HIPÓTESIS: no debería haber nada. La expansión premarket es la variable "
          "que el proyecto tiene medida como la que decide la DIRECCIÓN, con "
          "gradiente monotónico en cinco baldes. Un papel que expandió 30% no tuvo "
          "carácter parabólico: no hay multitud comprada arriba ni urgencia de la "
          "empresa por emitir contra la suba. Sin exageración no hay reversión que "
          "capturar y el gatillo de swing va a entrar contra un movimiento normal.",
          dias=censo, pob=_con(BASE, min_expansion=0, max_expansion=50))

    medir("poblacion·exp-50-100",
          "HIPÓTESIS: edge menor pero del mismo signo. Es el corazón de la "
          "distribución —la mediana del censo cae acá— y por lo tanto la población "
          "más grande de todas. Si el gradiente de expansión es real y continuo, "
          "acá tiene que haber algo, más chico. Es la que más frecuencia agrega si "
          "sobrevive.",
          dias=censo, pob=_con(BASE, min_expansion=50, max_expansion=100))

    medir("poblacion·exp-100-150",
          "HIPÓTESIS: casi lo mismo que la base. Está pegada al corte. Si el 150 "
          "fuera un descubrimiento y no un umbral arbitrario sobre un continuo, "
          "acá el edge tendría que caerse de golpe. Si en cambio da parecido, el "
          "corte está de más y estamos regalando frecuencia. Este es el test que "
          "distingue 'umbral con mecanismo' de 'umbral heredado'.",
          dias=censo, pob=_con(BASE, min_expansion=100, max_expansion=150))

    medir("poblacion·exp-50-150·ancha",
          "HIPÓTESIS: la versión operable de las dos anteriores. Mismo rango de "
          "expansión pero sin los cortes de volumen ni de float, que son cortes de "
          "ESCALA (cuánto nominal entra) y no de dirección. Para una cuenta de "
          "fondeo chica la escala no ata. Espero ret/nom parecido al de exp-50-150 "
          "puro y bastante más frecuencia.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, min_expansion=50,
                               max_expansion=150))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  2. APERTURA RECLAIM — hoy se descarta el día entero (474 de 1927)")
    print("=" * 112)
    print(encabezado())

    medir("poblacion·reclaim·exp150",
          "HIPÓTESIS: debería perder. Reclaim es, por definición, donde los cortos "
          "quedan atrapados: rompió el máximo de premarket, cerró arriba cinco "
          "minutos seguidos y volvió a hacer máximo. Ese es el mecanismo del "
          "squeeze y shortear ahí es ponerse del lado equivocado. PERO el gatillo "
          "de swing no entra en la ruptura: pide un rebote de 8% y una barra que "
          "cierra por debajo del mínimo anterior, o sea entra cuando el reclaim ya "
          "se dio vuelta. La pregunta real es si el filtro de apertura sigue "
          "haciendo falta cuando el gatillo ya exige confirmación.",
          dias=censo, pob=dict(BASE), apertura="reclaim")

    medir("poblacion·reclaim·todo",
          "HIPÓTESIS: la versión con frecuencia. Todos los reclaims con rvol≥3, sin "
          "importar la expansión ni el volumen ni el float. Si el reclaim con "
          "expansión alta pierde por el squeeze, el reclaim de un papel que "
          "expandió 40% debería perder menos: no hay suficiente gente atrapada "
          "para el squeeze. Espero un número mejor que el de arriba, lo cual sería "
          "raro y por eso vale medirlo.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0), apertura="reclaim")

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  3. FLOAT ALTO — hoy exigimos <47M acciones")
    print("=" * 112)
    print(encabezado())

    alto = [d for d in censo if d.float_acciones and d.float_acciones > 47e6]
    gigante = [d for d in censo if d.float_acciones and d.float_acciones > 200e6]

    medir("poblacion·float-alto",
          "HIPÓTESIS: menos edge por trade, pero puede ser la mejor población del "
          "archivo igual. Con float grande no hay mecanismo de squeeze —hay papel "
          "para prestar, el spread no se abre, la parabólica no puede pasar— así "
          "que los movimientos son más chatos. Lo que compensa: EL LOCATE ES "
          "BARATO. Como el punto de muerte es el locate sobre el nominal, una "
          "población con locate del 5% sobrevive con un tercio del ret/nom que "
          "necesita la base. Un 20% acá vale más que un 45% en papel abarrotado.",
          dias=alto, pob=_con(BASE, max_float=None, min_expansion=100),
          notas="float>47M · locate barato: el punto de muerte baja")

    medir("poblacion·float-gigante",
          "HIPÓTESIS: casi seguro muestra corta, y si alcanza va a dar cerca de "
          "cero. Con más de 200M de acciones el papel deja de ser una small cap "
          "estructuralmente: el gap es noticia real, no desequilibrio de oferta. "
          "Se mide para cerrar la puerta con un número, no porque espere algo.",
          dias=gigante, pob=_con(ABIERTA, min_ratio_vol=3.0))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  4. VOLUMEN DEL DÍA BAJO — hoy exigimos >$137M")
    print("=" * 112)
    print(encabezado())

    medir("poblacion·dolar-bajo",
          "HIPÓTESIS: el edge debería estar igual o MEJOR. El corte de $137M no es "
          "un corte de dirección sino de escala: existe para que el nominal entre "
          "sin mover el precio. Con $50 de riesgo diario el nominal es de ~$110 y "
          "el impacto de mercado es una anécdota. Y hay un argumento a favor: "
          "menos volumen es menos ojos, menos algos y menos eficiencia. El piso de "
          "operabilidad ya está adentro del gatillo, que exige $250k/min de "
          "liquidez en los diez minutos previos.",
          dias=censo, pob=_con(BASE, min_dolar=0, max_dolar=137e6,
                               min_expansion=100))

    medir("poblacion·dolar-bajo·ancha",
          "HIPÓTESIS: la misma idea sin el corte de expansión. Es la población más "
          "grande que queda del otro lado del embudo (430 días candidatos). Si "
          "acá hay algo, el corte de volumen es el más caro de los cinco.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, max_dolar=137e6))

    medir("poblacion·dolar-muy-bajo",
          "HIPÓTESIS: acá espero que el filtro de liquidez del gatillo mate casi "
          "todo. Un papel que opera menos de $50M en el día rara vez sostiene "
          "$250k por minuto en el momento de entrar. Si igual quedan sesiones, es "
          "la población más barata de locate por unidad de riesgo, pero también la "
          "que menos escala.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, max_dolar=50e6))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  5. PRECIO — hoy no se filtra, así que esto PARTE la población actual")
    print("=" * 112)
    print(encabezado())

    for lo, hi, etiq, hip in (
        (0.20, 1.0, "sub-dolar",
         "HIPÓTESIS: bruto positivo, neto muerto. Es el hallazgo más duro del "
         "proyecto: debajo de $1 el costo fijo por acción se come más de un cuarto "
         "del riesgo en el 79% de los momentos. Con $0.04/acción de ida y vuelta "
         "sobre un papel de $0.50 son ocho puntos porcentuales antes de que el "
         "precio se mueva. Y el locate del sub-dólar es el más caro que existe."),
        (1.0, 5.0, "1-5",
         "HIPÓTESIS: la banda donde vive la mayor parte del censo. Debería parecerse "
         "al promedio. Se mide para tener el punto de comparación de las otras dos, "
         "no porque espere una sorpresa."),
        (5.0, 20.0, "5-20",
         "HIPÓTESIS: la mejor de las tres. El proyecto ya midió que la banda de $10+ "
         "fue la única con esperanza neta positiva por sí sola: el costo por acción "
         "pesa cinco veces menos y el papel es más fácil de prestar. Si esto "
         "confirma, el precio es un filtro de tamaño, no de descarte."),
    ):
        medir(f"poblacion·precio·{etiq}", hip, dias=censo,
              pob=_con(BASE, min_expansion=100, min_precio=lo, max_precio=hi))

    medir("poblacion·precio·5-20·ancha",
          "HIPÓTESIS: si la banda cara funciona, sacarle los cortes de volumen y "
          "float debería mantener el número y multiplicar la frecuencia — porque un "
          "papel de $8 con float alto y volumen moderado es justamente el que el "
          "embudo actual descarta tres veces seguidas.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, min_precio=5.0,
                               max_precio=20.0))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  6. RATIO DE VOLUMEN 1-3 — hoy exigimos ≥3")
    print("=" * 112)
    print(encabezado())

    tibio = [d for d in censo if 1.0 <= (d.ratio_volumen or 0) < 3.0]
    medir("poblacion·rvol-1-3",
          "HIPÓTESIS: nada. El ratio de volumen contra el día previo es lo que dice "
          "'hoy pasó algo'. Debajo de 3 el papel se movió sin que llegara volumen "
          "nuevo: es un gap por falta de oferta, no por noticia. Sin combustible no "
          "hay parabólica, y sin papel nuevo no hay reversión. Además el ratio bajo "
          "puede ser un artefacto —un reverse split deja el ratio en <1 sin que "
          "haya pasado nada.",
          dias=tibio, pob=_con(ABIERTA, min_ratio_vol=0))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  7. EL POST-EVENTO — días 2, 3 y 4. Población que el censo NO CONTIENE")
    print("=" * 112)
    print(encabezado())

    p1 = [d for d in post if d.post_k == 1]
    p2 = [d for d in post if d.post_k == 2]
    p34 = [d for d in post if d.post_k in (3, 4)]

    medir("poblacion·post-1",
          "HIPÓTESIS: la más importante del archivo, y no por su número sino porque "
          "NO SE SOLAPA con la base por construcción —el censo excluye estos días "
          "explícitamente. Mecanismo: el día del evento la empresa ve la ventana y "
          "emite, y el papel nuevo aterriza en T+1/T+2; encima los que compraron la "
          "parabólica están todos arriba del precio y el primer rebote es su "
          "salida. Predicción: mismo signo, edge más chico —el movimiento ya no es "
          "parabólico— y con el riesgo grande de que la liquidez se derrumbe y el "
          "filtro de $250k/min deje sin sesiones.",
          dias=p1, pob=dict(ABIERTA))

    medir("poblacion·post-2",
          "HIPÓTESIS: si el mecanismo es la EMISIÓN, el efecto tiene que durar días "
          "y post-2 debería parecerse a post-1. Si el mecanismo es el ATRAPAMIENTO "
          "intradía, se apaga en 24 horas y post-2 da cero. Este par de mediciones "
          "separa las dos explicaciones, que es más valioso que el edge en sí.",
          dias=p2, pob=dict(ABIERTA))

    medir("poblacion·post-3-4",
          "HIPÓTESIS: cerca de cero. A tres o cuatro ruedas el papel ya encontró su "
          "nivel y lo que queda es deriva. Se mide para ver dónde se apaga la "
          "curva, no porque espere operarlo.",
          dias=p34, pob=dict(ABIERTA))

    regap = [d for d in p1 if (d.expansion_pct or 0) >= 15]
    singap = [d for d in p1 if (d.expansion_pct or 0) < 15]

    medir("poblacion·post-1·regap",
          "HIPÓTESIS: el mejor de los post. Es el día 2 clásico de una parabólica: "
          "el papel vuelve a expandir ≥15% en premarket sobre el cierre del evento. "
          "Hay multitud NUEVA comprando arriba y la anterior sigue atrapada, o sea "
          "las dos condiciones del fade juntas. Es la única sub-población post donde "
          "espero un número comparable al de la base.",
          dias=regap, pob=dict(ABIERTA))

    medir("poblacion·post-1·sin-gap",
          "HIPÓTESIS: el complemento del anterior. Sin gap nuevo no hay disparador "
          "y lo que queda es un papel resacoso. Si esto da parecido al regap, "
          "entonces el edge del post-1 no viene del gap sino de la emisión, que es "
          "el resultado más interesante posible acá.",
          dias=singap, pob=dict(ABIERTA))

    medir("poblacion·post-1·reclaim",
          "HIPÓTESIS: el peor de todos. Un papel que al día siguiente del evento "
          "recupera el máximo de premarket y lo sostiene es el que tiene continuación "
          "real. Debería perder plata y sirve como control negativo: si TODO da "
          "positivo en esta familia, la que está mal es la medición.",
          dias=p1, pob=dict(ABIERTA), apertura="reclaim")

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  8. DÍA 2 DEL CENSO — el ticker vuelve a calificar dentro de 5 ruedas")
    print("=" * 112)
    print(encabezado())

    racha2 = [d for d in censo if getattr(d, "orden_racha", 1) >= 2]
    medir("poblacion·censo-dia2",
          "HIPÓTESIS: distinta del post-1 y probablemente mejor. Acá el día 2 "
          "TAMBIÉN calificó como evento —volvió a gapear con liquidez— así que es "
          "la segunda pierna de una parabólica de verdad, no la resaca. Contra: la "
          "muestra es chica (130 días antes de cualquier filtro) y no voy a poder "
          "sacar conclusiones fuertes. A favor: se solapa poco con la base, porque "
          "casi ninguno de estos días pasa el embudo completo.",
          dias=racha2, pob=_con(ABIERTA, min_ratio_vol=0))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  9. COMBINACIONES CON MECANISMO")
    print("=" * 112)
    print(encabezado())

    medir("poblacion·reclaim·float-alto",
          "HIPÓTESIS: el test más limpio del mecanismo de toda la familia. Si el "
          "reclaim es malo PORQUE hay squeeze, entonces con float alto —donde el "
          "squeeze no puede ocurrir, hay papel de sobra— el reclaim tendría que "
          "dejar de ser malo. Si sigue igual de malo, entonces el reclaim no es un "
          "squeeze: es simplemente un papel que sube, y el filtro de apertura está "
          "midiendo otra cosa que la que dice medir.",
          dias=[d for d in censo if d.float_acciones and d.float_acciones > 47e6],
          pob=_con(ABIERTA, min_ratio_vol=3.0), apertura="reclaim")

    medir("poblacion·gapper-aburrido",
          "HIPÓTESIS: la población descartada más grande que existe — expansión "
          "menor a 100% Y volumen menor a $137M. La cruza de los dos cortes que más "
          "días tiran. Sin exageración y sin volumen no debería haber nada; si lo "
          "hay, el edge del proyecto no es de las parabólicas sino de los gaps en "
          "general, que sería el hallazgo que más cambia el sistema.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, max_expansion=100,
                               max_dolar=137e6))

    medir("poblacion·todo-fade",
          "HIPÓTESIS: el límite superior de frecuencia. Cualquier día del censo con "
          "rvol≥3 y apertura fade, sin ningún otro corte. Es la referencia contra la "
          "que hay que leer TODAS las de arriba: si esta da parecido a la base, los "
          "cuatro filtros restantes no están seleccionando nada y el sistema está "
          "renunciando a tres cuartas partes de su frecuencia a cambio de ruido.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  10. EL RECLAIM, APRETADO — sondeo POST-HOC, disparado por el bloque 2")
    print("     Estas cuatro NO son hipótesis previas: salieron de mirar el resultado")
    print("     del bloque 2, que fue al revés de lo que yo predije. Van marcadas como")
    print("     lo que son —un sondeo— y no cuentan como confirmación independiente.")
    print("=" * 112)
    print(encabezado())

    medir("poblacion·reclaim·exp-0-100",
          "SONDEO: si el reclaim rinde porque NO hay squeeze (poca gente atrapada), "
          "entonces el reclaim de expansión baja tendría que ser el mejor de los "
          "reclaims. Es el corte que separa 'el reclaim funciona' de 'el reclaim "
          "funciona donde no hay multitud'.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, max_expansion=100),
          apertura="reclaim", notas="post-hoc")

    medir("poblacion·reclaim·exp-100+",
          "SONDEO: el complemento. Reclaim con expansión ≥100%, o sea con multitud "
          "de verdad arriba. Si acá también rinde, el squeeze no es el mecanismo "
          "dominante y el filtro de apertura está tirando días buenos por una "
          "teoría y no por una medición.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, min_expansion=100),
          apertura="reclaim", notas="post-hoc")

    medir("poblacion·reclaim·liquido",
          "SONDEO: ¿el reclaim rinde en la parte líquida, que es la única que "
          "escala? Reclaim con volumen del día >$137M. Si el edge del reclaim vive "
          "sólo en lo ilíquido, no sirve para una segunda cuenta de fondeo.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0, min_dolar=137e6),
          apertura="reclaim", notas="post-hoc")

    medir("poblacion·sin-filtro-apertura",
          "SONDEO: fade Y reclaim juntos, sin ningún otro corte más que rvol≥3. Si "
          "esto queda entre los dos, el filtro de apertura está partiendo la "
          "población en dos mitades operables y no separando buena de mala. Es el "
          "número que decide si el filtro de las 10:00 se saca del sistema.",
          dias=censo, pob=_con(ABIERTA, min_ratio_vol=3.0), apertura=None,
          notas="post-hoc")

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  11. CONTROL DE FUGA — lo mismo, pero sin mirar el futuro")
    print("     Entradas desde las 10:00 (después de que la etiqueta de apertura")
    print("     exista) y sin `min_ratio_vol` ni cortes de dólar, que son cantidades")
    print("     del día completo. Es la versión que se podría haber operado de verdad.")
    print("=" * 112)
    print(encabezado())

    tarde = lambda d: señales_swing(d, desde=10.0)
    limpio = dict(min_ratio_vol=0, min_expansion=0, min_dolar=0, max_float=None)
    for nombre, ap, pb in (
        ("poblacion·LIMPIO·base", "fade",
         _con(limpio, min_expansion=150.0, max_float=47e6)),
        ("poblacion·LIMPIO·reclaim-100", "reclaim", _con(limpio, min_expansion=100.0)),
        ("poblacion·LIMPIO·reclaim-todo", "reclaim", dict(limpio)),
        ("poblacion·LIMPIO·todo-fade", "fade", dict(limpio)),
    ):
        r = evaluar(nombre, tarde, dias=censo, familia="poblacion", lado="short",
                    stop=45.0, apertura=ap, pob=pb,
                    notas="sin fuga: entrada >=10:00 y sin filtros del dia completo")
        RES.append((r, 0, "control de fuga"))
        print(linea(r))

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  TABLA COMPLETA — ordenada por ret/nom")
    print("=" * 112)
    print(encabezado() + "   solapa  veredicto")
    print("  " + "-" * 130)
    ok = [(r, c) for r, c, _ in RES if "error" not in r]
    malos = [(r, c) for r, c, _ in RES if "error" in r]
    for r, c in sorted(ok, key=lambda x: -x[0]["ret_nom"]):
        s = len(set(r["serie"]) & base_fechas) / max(1, len(r["serie"]))
        print(linea(r) + f"  {100*s:>5.0f}%  {veredicto(r, base_fechas)}")
    for r, c in malos:
        print(f"  {r['nombre']:<38} {r['error']}  ({c} días candidatos)")

    # ------------------------------------------------------------------
    print("\n" + "=" * 112)
    print("  DECORRELACIÓN CONTRA LA BASE")
    print("  'sin dato' en la correlación = comparten menos de 20 fechas = ya están")
    print("  decorrelacionadas por construcción, que es exactamente lo que buscamos.")
    print("=" * 112)
    print(f"  {'poblacion':<38} {'fechas':>7} {'propias':>8} {'comun':>6} "
          f"{'corr-com':>9} {'corr-cart':>10} {'ambas-':>7} {'peor-jun':>9}")
    print("  " + "-" * 104)
    peor_base = min(base["serie"], key=lambda d: base["serie"][d])
    for r, _ in sorted(ok, key=lambda x: -x[0]["ret_nom"]):
        if r["nombre"] == base["nombre"]:
            continue
        comunes = set(r["serie"]) & base_fechas
        c = correlacion(r["serie"], base["serie"])
        cc = corr_cartera(r["serie"], base["serie"])
        ambas = sum(1 for d in comunes
                    if r["serie"][d] < 0 and base["serie"][d] < 0)
        union = sorted(set(r["serie"]) | base_fechas)
        peor = min(r["serie"].get(d, 0.0) + base["serie"].get(d, 0.0)
                   for d in union)
        print(f"  {r['nombre']:<38} {len(r['serie']):>7} "
              f"{len(set(r['serie']) - base_fechas):>8} {len(comunes):>6} "
              f"{(f'{c:+.2f}' if c is not None else '-'):>9} "
              f"{(f'{cc:+.2f}' if cc is not None else '-'):>10} "
              f"{ambas:>7} {peor:>+9.2f}")
    peores = sorted(base["serie"].values())
    print(f"\n  peor jornada de la BASE sola: {peor_base} "
          f"{base['serie'][peor_base]:+.2f}R  ·  sus dos peores suman "
          f"{sum(peores[:2]):+.2f}R  ·  jornadas negativas: "
          f"{sum(1 for v in base['serie'].values() if v < 0)} de {len(peores)}")
    print(textwrap.fill(
        "CÓMO LEER ESTA TABLA. 'propias' son fechas que la base NO opera: es la "
        "frecuencia que suma una segunda cuenta sin pisar a la primera. "
        "'corr-com' es la del motor, sobre fechas compartidas; 'corr-cart' es la "
        "que decide, sobre la unión con cero donde no se operó — es la que "
        "contesta si las tres cuentas revientan el mismo día. 'ambas-' cuenta los "
        "días en que las dos perdieron a la vez, que es el evento que rompe una "
        "evaluación de fondeo. 'peor-jun' es la peor jornada de la SUMA de las "
        "dos, en R, y hay que leerla contra la peor de la base sola: si no "
        "empeora, la segunda cuenta sale gratis en drawdown.",
        94, initial_indent="  ", subsequent_indent="  "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
