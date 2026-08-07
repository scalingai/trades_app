"""
Backtesting local sobre los datos que descarga descargar_datos.py.

Piezas, en el orden en que conviene usarlas:

    motor        ejecución de señales con costes, stop y objetivo
    metricas     rendimiento, riesgo y estabilidad
    estrategias  estrategias clásicas parametrizables
    optimizar    barrido de parámetros con separación in-sample / out-of-sample
    walkforward  optimizar en una ventana y validar en la siguiente, rodando
    montecarlo   robustez ante variaciones aleatorias
    generador    construcción de estrategias por programación genética
"""

from .motor import Config, Datos, Senales, desde_dataframe, ejecutar
from .metricas import calcular as calcular_metricas, formatear

__all__ = [
    "Config", "Datos", "Senales", "desde_dataframe", "ejecutar",
    "calcular_metricas", "formatear", "cargar",
]


def cargar(ruta, intervalo=None):
    """
    Carga un CSV descargado y lo deja listo para el motor.

    El intervalo se deduce del nombre del archivo (PAR_INTERVALO_FUENTE.csv)
    si no se indica; hace falta para anualizar CAGR y Sharpe.
    """
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from descargar_datos import cargar_datos

    if intervalo is None:
        partes = os.path.basename(ruta).split("_")
        intervalo = partes[1] if len(partes) >= 3 else "1h"

    return desde_dataframe(cargar_datos(ruta), intervalo)
