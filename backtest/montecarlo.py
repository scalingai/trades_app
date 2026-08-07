"""
Simulación de Monte Carlo para medir robustez.

Un backtest devuelve una sola curva, y esa curva es una de las muchas que
podrían haber salido. El orden concreto en que llegaron las operaciones, que
justamente entrara en esa vela y no en la siguiente, el slippage exacto: nada
de eso se va a repetir. Monte Carlo repite el experimento cambiando al azar
esos detalles y devuelve la distribución de resultados en lugar del único
recorrido que tocó.

Lo que importa no es la mediana, sino la cola mala. Una estrategia cuyo
percentil 5 de drawdown es del 70 % es inoperable aunque su backtest original
mostrara un 30 %, porque ese 30 % fue suerte de ordenación.

Dos familias de pruebas:

- Sobre las operaciones (baraja, remuestrea, saltea, encarece). Son inmediatas
  porque no hay que reejecutar nada.
- Sobre los datos (ruido en el precio, inicio aleatorio). Hay que reejecutar la
  estrategia, así que son más lentas, pero son las únicas que comprueban si las
  señales sobreviven a que el precio hubiera sido un poco distinto.
"""

from dataclasses import dataclass

import numpy as np

from . import metricas as mod_metricas
from .indicadores import Contexto
from .motor import ejecutar


@dataclass
class ResultadoMC:
    retornos: np.ndarray          # retorno total de cada simulación
    drawdowns: np.ndarray         # max drawdown de cada simulación
    n: int
    tipo: str

    def percentiles(self, cuantiles=(5, 25, 50, 75, 95)):
        return {
            "retorno": {q: float(np.percentile(self.retornos, q)) for q in cuantiles},
            "drawdown": {q: float(np.percentile(self.drawdowns, q)) for q in cuantiles},
        }

    @property
    def prob_perdida(self):
        return float((self.retornos <= 0).mean())

    @property
    def prob_ruina(self):
        """Probabilidad de perder más de la mitad del capital en algún momento."""
        return float((self.drawdowns >= 0.5).mean())


def _curva(retornos, capital=10_000.0):
    return capital * np.cumprod(1 + retornos)


def _resumir(curvas_finales, drawdowns, capital, tipo, n):
    return ResultadoMC(
        retornos=np.asarray(curvas_finales) / capital - 1,
        drawdowns=np.asarray(drawdowns),
        n=n, tipo=tipo,
    )


# ========================
# SIMULACIONES SOBRE LAS OPERACIONES
# ========================

def sobre_operaciones(resultado, n=2000, tipo="barajar", saltar=0.1,
                      slippage_extra=0.0005, capital=10_000.0, semilla=42):
    """
    Repite la secuencia de operaciones alterándola al azar.

    tipo:
      barajar     — mismo conjunto de operaciones, distinto orden. Cambia el
                    drawdown pero no el retorno final: aísla el riesgo de que
                    las pérdidas se agrupen.
      remuestrear — bootstrap con reemplazo. Simula "otra muestra parecida" y
                    sí cambia el retorno final.
      saltar      — descarta un porcentaje de operaciones al azar. Si el
                    resultado depende de unas pocas, se hunde aquí.
      slippage    — encarece cada operación. Mide cuánto margen hay antes de
                    que los costes se coman el edge.
    """
    retornos = np.asarray(resultado.retorno, dtype=float)
    if len(retornos) == 0:
        return ResultadoMC(np.zeros(0), np.zeros(0), 0, tipo)

    rng = np.random.default_rng(semilla)
    finales, ddowns = [], []

    for _ in range(n):
        if tipo == "barajar":
            muestra = rng.permutation(retornos)
        elif tipo == "remuestrear":
            muestra = rng.choice(retornos, size=len(retornos), replace=True)
        elif tipo == "saltar":
            mascara = rng.random(len(retornos)) >= saltar
            muestra = retornos[mascara]
            if len(muestra) == 0:
                continue
        elif tipo == "slippage":
            # Coste adicional aleatorio, siempre en contra.
            muestra = retornos - np.abs(rng.normal(slippage_extra, slippage_extra / 2,
                                                   len(retornos)))
        else:
            raise ValueError(f"tipo desconocido: {tipo}")

        curva = _curva(muestra, capital)
        finales.append(curva[-1])
        ddowns.append(mod_metricas.max_drawdown(np.concatenate(([capital], curva))))

    return _resumir(finales, ddowns, capital, tipo, len(finales))


# ========================
# SIMULACIONES SOBRE LOS DATOS
# ========================

def con_ruido(datos, generar_senales, config, n=200, ruido=0.001, semilla=42):
    """
    Reejecuta la estrategia sobre versiones del precio con ruido añadido.

    Cada vela se multiplica por un factor aleatorio, lo que mantiene la
    coherencia del OHLC (máximo por encima de apertura y cierre, etc.) pero
    desplaza ligeramente el nivel. Si un cambio del 0,1 % rompe la estrategia,
    es que las señales estaban clavadas en velas concretas del histórico.

    generar_senales recibe un Contexto y devuelve Senales.
    """
    rng = np.random.default_rng(semilla)
    finales, ddowns = [], []

    for _ in range(n):
        factor = 1 + rng.normal(0, ruido, len(datos))
        alterados = type(datos)(
            fechas=datos.fechas,
            open=datos.open * factor, high=datos.high * factor,
            low=datos.low * factor, close=datos.close * factor,
            volume=datos.volume, intervalo=datos.intervalo,
        )
        senales = generar_senales(Contexto(alterados))
        if senales is None:
            continue
        res = ejecutar(alterados, senales, config)
        finales.append(res.equity[-1])
        ddowns.append(mod_metricas.max_drawdown(res.equity))

    return _resumir(finales, ddowns, config.capital, "ruido", len(finales))


def inicio_aleatorio(datos, generar_senales, config, n=100, recorte=0.2, semilla=42):
    """
    Reejecuta empezando en puntos distintos de la serie.

    Comprueba si el resultado depende de haber arrancado justo donde arrancó.
    `recorte` es la fracción máxima de serie que se puede saltar al principio.
    """
    rng = np.random.default_rng(semilla)
    maximo_salto = int(len(datos) * recorte)
    finales, ddowns = [], []

    for _ in range(n):
        desde = int(rng.integers(0, max(maximo_salto, 1)))
        tramo = datos.tramo(desde, len(datos))
        senales = generar_senales(Contexto(tramo))
        if senales is None:
            continue
        res = ejecutar(tramo, senales, config)
        finales.append(res.equity[-1])
        ddowns.append(mod_metricas.max_drawdown(res.equity))

    return _resumir(finales, ddowns, config.capital, "inicio", len(finales))


# ========================
# INFORME
# ========================

def formatear(resultado, original=None):
    """Resumen legible de una simulación."""
    if resultado.n == 0:
        return f"  {resultado.tipo}: sin operaciones que simular."

    p = resultado.percentiles()
    lineas = [
        f"  {resultado.tipo}  ({resultado.n} simulaciones)",
        f"    retorno   p5 {p['retorno'][5]:>8.1%}   mediana {p['retorno'][50]:>8.1%}"
        f"   p95 {p['retorno'][95]:>8.1%}",
        f"    drawdown  p50 {p['drawdown'][50]:>7.1%}   p95 {p['drawdown'][95]:>8.1%}"
        f"   peor {resultado.drawdowns.max():>7.1%}",
        f"    probabilidad de acabar en pérdidas  {resultado.prob_perdida:>6.1%}",
        f"    probabilidad de perder más del 50 % {resultado.prob_ruina:>6.1%}",
    ]
    if original is not None:
        lineas.append(f"    (el backtest original dio {original:.1%})")
    return "\n".join(lineas)


def informe(resultado_backtest, datos=None, generar_senales=None, config=None,
            n_operaciones=2000, n_datos=200, capital=10_000.0):
    """
    Batería completa: las cuatro pruebas sobre operaciones y, si se pasan los
    datos y la función de señales, también las dos sobre los datos.
    """
    salida = []
    original = resultado_backtest.equity[-1] / capital - 1

    for tipo in ("barajar", "remuestrear", "saltar", "slippage"):
        r = sobre_operaciones(resultado_backtest, n=n_operaciones, tipo=tipo, capital=capital)
        salida.append(formatear(r, original if tipo == "barajar" else None))

    if datos is not None and generar_senales is not None and config is not None:
        salida.append(formatear(con_ruido(datos, generar_senales, config, n=n_datos)))
        salida.append(formatear(inicio_aleatorio(datos, generar_senales, config,
                                                 n=max(n_datos // 2, 20))))
    return "\n".join(salida)
