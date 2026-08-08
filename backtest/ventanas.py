"""
Ventanas horarias de minuto exacto.

Los indicadores de tipo ICT/SMC marcan tramos del día muy estrechos —diez
minutos— y afirman que ahí ocurre algo distinto. Es una hipótesis limpia y,
a diferencia de casi todo lo demás en ese mundo, contrastable: o esos minutos
se comportan distinto del resto del día o no.

Este módulo da las tres piezas que hacen falta para contrastarla.

**Hora local, no UTC.** Todos los análisis anteriores del proyecto agrupan por
hora UTC, y con eso una ventana de diez minutos definida en hora de Nueva York
es invisible. Además hay dos lecturas posibles de "GMT-4", y no son la misma:
el desfase fijo que dibuja el indicador todo el año, y la hora local de Nueva
York, que en invierno se separa una hora. Se pueden medir las dos.

**El día entero como referencia.** Preguntar "¿la ventana 09:55-10:05 es
buena?" no tiene respuesta útil aislada: siempre sale un número. La pregunta
con respuesta es "¿qué puesto ocupa entre los 144 tramos de diez minutos que
tiene el día?". Si es el primero, hay algo; si es el sexagésimo, no. Por eso
`perfil` devuelve la tabla completa y no sólo las ventanas señaladas.

**Barrido y reversión.** Una ventana horaria por sí sola no dice hacia dónde
operar, así que no puede tener ventaja en un bracket simétrico. Lo que sí
tiene dirección es el modelo que la acompaña: dentro de la ventana el precio
perfora un extremo previo, barre las órdenes acumuladas ahí y se da la vuelta.
Eso es una regla, y se puede medir.
"""

from datetime import time

import numpy as np
import pandas as pd

from backtest import barreras, patrones

# El indicador escribe "GMT-4" fijo. Eso coincide con Nueva York sólo de marzo
# a noviembre; el resto del año la ciudad está en GMT-5 y las ventanas se
# desplazan una hora respecto al evento que pretenden marcar. Se guardan las
# dos lecturas porque la diferencia entre ellas es, en sí misma, una prueba:
# si el efecto es de mercado seguirá a Nueva York, y si es un artefacto del
# reloj seguirá al desfase fijo.
ZONAS = {"fija": "Etc/GMT+4", "nueva-york": "America/New_York"}


def hora_local(indice, zona="fija"):
    """Reexpresa un índice UTC en la zona pedida."""
    return indice.tz_convert(ZONAS.get(zona, zona))


def _minuto_del_dia(indice, zona):
    local = hora_local(indice, zona)
    return (local.hour * 60 + local.minute).to_numpy()


def mascara_ventana(indice, inicio, fin, zona="fija"):
    """
    Marca las velas cuya hora local cae en [inicio, fin).

    El intervalo es semiabierto: 09:55-10:05 incluye 09:55:00 y excluye
    10:05:00, que es cómo se dibuja la caja en el gráfico. Si `fin` es anterior
    a `inicio` se entiende que la ventana cruza la medianoche.
    """
    minutos = _minuto_del_dia(indice, zona)
    a = inicio.hour * 60 + inicio.minute
    b = fin.hour * 60 + fin.minute
    if a <= b:
        return (minutos >= a) & (minutos < b)
    return (minutos >= a) | (minutos < b)


def _huecos(marcas):
    """
    Dónde la serie se interrumpe: pasos mucho mayores que el habitual.

    Importa porque sin esto un día que falte en el histórico pegaría la ventana
    de un día con la del siguiente y las mediría como una sola aparición de
    veinticuatro horas.
    """
    if marcas is None:
        return None
    t = pd.DatetimeIndex(marcas).asi8
    if len(t) < 3:
        return np.zeros(max(len(t) - 1, 0), dtype=bool)
    paso = np.diff(t)
    return paso > 2 * np.median(paso)


def ocurrencias(mascara, cual="primera", marcas=None):
    """
    Posición de la primera (o última) vela de cada aparición de la ventana.

    Cada aparición es normalmente una por día. Se cuentan así y no por número
    de velas porque las velas de dentro de una misma ventana no son
    observaciones independientes.
    """
    if cual not in ("primera", "ultima"):
        raise ValueError(f"cual debe ser 'primera' o 'ultima', no {cual!r}")
    m = np.asarray(mascara, dtype=bool)
    if not m.any():
        return np.array([], dtype=int)

    hueco = _huecos(marcas)
    entra = m[1:] & ~m[:-1]
    sale = ~m[1:] & m[:-1]
    if hueco is not None:
        entra = entra | (m[1:] & hueco)
        sale = sale | (m[:-1] & hueco)

    inicios = np.flatnonzero(entra) + 1
    finales = np.flatnonzero(sale)
    if m[0]:
        inicios = np.concatenate([[0], inicios])
    if m[-1]:
        finales = np.concatenate([finales, [len(m) - 1]])
    return inicios if cual == "primera" else finales


MINUTOS_DIA = 24 * 60


def bucket_local(indice, minutos=10, zona="fija", desfase=0):
    """
    Número de tramo del día al que pertenece cada vela, en hora local.

    `desfase` corre la rejilla. Hace falta porque las ventanas del indicador no
    empiezan en punto: 09:55-10:05 se parte entre dos tramos de una rejilla
    alineada a :00, y compararla contra ellos sería compararla contra otra cosa.
    Con desfase 5 la propia ventana es uno de los 144 tramos y la comparación
    es la que se quería hacer.
    """
    return ((_minuto_del_dia(indice, zona) - desfase) % MINUTOS_DIA) // minutos


def inicio_de_bucket(b, minutos=10, desfase=0):
    """Hora local en la que arranca un tramo, como HH:MM."""
    minuto = (desfase + int(b) * minutos) % MINUTOS_DIA
    return f"{minuto // 60:02d}:{minuto % 60:02d}"


def tramos(bucket, marcas=None):
    """
    Trocea la serie en apariciones contiguas del mismo tramo del día.

    Devuelve el principio, el final y la etiqueta de cada aparición. Sirve para
    recorrer los 144 tramos del día de una vez en lugar de construir 144
    máscaras de catorce millones de elementos.

    Pasando `marcas` se corta también donde el histórico tenga huecos, que si
    no pegarían el tramo de un día con el del siguiente.
    """
    b = np.asarray(bucket)
    if len(b) == 0:
        return (np.array([], dtype=int),) * 3
    cambio = np.diff(b) != 0
    hueco = _huecos(marcas)
    if hueco is not None:
        cambio = cambio | hueco
    corte = np.flatnonzero(cambio) + 1
    inicios = np.concatenate([[0], corte]).astype(int)
    finales = np.concatenate([corte - 1, [len(b) - 1]]).astype(int)
    return inicios, finales, b[inicios]


def perfil(df, minutos=10, zona="fija", desfase=0):
    """
    Actividad media de cada tramo del día, en hora local.

    Devuelve una fila por tramo con la expansión (recorrido medio de cada vela,
    en puntos básicos), el rango alto-bajo y el volumen relativo. Es la tabla
    contra la que hay que leer cualquier ventana concreta.
    """
    bucket = bucket_local(df.index, minutos, zona, desfase)
    t = pd.DataFrame({
        "bucket": bucket,
        "exp_bp": df["close"].pct_change().abs().to_numpy() * 1e4,
        "rango_bp": ((df["high"] - df["low"]) / df["close"]).to_numpy() * 1e4,
        "volumen": df["volume"].to_numpy(),
    })
    g = t.groupby("bucket").mean().sort_index()
    g["vol_rel"] = g["volumen"] / g["volumen"].mean()
    g["hora"] = [inicio_de_bucket(b, minutos, desfase) for b in g.index]
    return g[["hora", "exp_bp", "rango_bp", "vol_rel"]]


def percentil(valores, valor):
    """Fracción de `valores` que queda por debajo de `valor`."""
    v = np.asarray(valores, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return float("nan")
    return float((v < valor).mean())


def direccion_por_barrido(alto, bajo, inicios, finales, previa):
    """
    Dirección que dicta el modelo de barrido y reversión.

    Si dentro de la ventana el precio perforó el mínimo del tramo anterior, se
    entiende que barrió las órdenes acumuladas ahí y la señal es al alza; si
    perforó el máximo, a la baja. Perforar los dos extremos, o ninguno, no da
    señal y devuelve cero.

    Todo lo que decide el signo ocurre antes de la vela de entrada —la última
    de la ventana—, así que la regla se puede ejecutar en tiempo real.
    """
    d = np.zeros(len(inicios), dtype=int)
    for k, (s, e) in enumerate(zip(inicios, finales)):
        desde = max(int(s) - previa, 0)
        if desde >= s or e < s:
            continue
        techo = alto[desde:s].max()
        suelo = bajo[desde:s].min()
        barrio_suelo = bajo[s:e + 1].min() < suelo
        barrio_techo = alto[s:e + 1].max() > techo
        if barrio_suelo and not barrio_techo:
            d[k] = 1
        elif barrio_techo and not barrio_suelo:
            d[k] = -1
    return d


def consistencia(marcas, valores, por="ME"):
    """
    En cuántos meses independientes el efecto tiene el mismo signo que el
    global, y qué probabilidad tendría ese acuerdo lanzando una moneda.

    Es el mismo listón que usa el módulo de patrones: un efecto que aparece en
    un mes y desaparece en once no es un patrón, por grande que sea la media.
    """
    if len(valores) == 0:
        return {}
    s = pd.Series(np.asarray(valores, dtype=float),
                  index=pd.DatetimeIndex(marcas)).sort_index()
    por_periodo = s.resample(por).mean().dropna()
    celda = patrones.Celda(
        claves={}, n=len(s), episodios=float(len(s)), efecto=float(s.mean()),
        periodos_positivos=int((por_periodo > 0).sum()),
        periodos_total=int(len(por_periodo)))
    return {
        "efecto": celda.efecto,
        "periodos": celda.periodos_total,
        "a_favor": (celda.periodos_positivos if celda.efecto >= 0
                    else celda.periodos_total - celda.periodos_positivos),
        "acuerdo": celda.acuerdo,
        "p": celda.p_valor,
    }


def win_rate_necesario(stop, objetivo, coste=0.0012):
    """
    Acierto que hace falta para no perder dinero con un bracket dado.

    Es la aritmética que decide si una geometría es siquiera discutible. Con
    stop y objetivo iguales sale 0,5 más el coste repartido sobre el recorrido,
    y ese segundo término crece muy deprisa cuando el bracket es pequeño: un
    1:1 de 200 puntos sobre BTC a 65.000 es un 0,31 %, y con 12 puntos básicos
    de coste exige acertar casi siete de cada diez.

    Con unas `Comisiones` el ganador y el perdedor cuestan distinto, así que la
    condición de equilibrio es p·(T − c_gana) = (1−p)·(S + c_pierde).
    """
    if stop + objetivo <= 0:
        return float("nan")
    if isinstance(coste, barreras.Comisiones):
        gana, pierde = coste.del_ganador(), coste.del_perdedor()
        denominador = stop + objetivo + pierde - gana
        if denominador <= 0:
            return float("nan")
        return float((stop + pierde) / denominador)
    return float((stop + coste) / (stop + objetivo))


NOMBRES_VENTANAS = {
    "01:00-04:00": (time(1, 0), time(4, 0)),
    "09:55-10:05": (time(9, 55), time(10, 5)),
    "10:25-10:35": (time(10, 25), time(10, 35)),
}
