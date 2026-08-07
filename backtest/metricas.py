"""
Métricas de rendimiento de un backtest.

Incluye las que StrategyQuant usa para puntuar estrategias: Return/Drawdown
como criterio principal y la estabilidad (R² de la curva de capital) para
distinguir una curva que sube de forma sostenida de otra que debe todo su
resultado a dos operaciones afortunadas.
"""

import numpy as np

SEGUNDOS_POR_ANIO = 365.25 * 24 * 3600

INTERVALOS_SEG = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "8h": 28800,
    "12h": 43200, "1d": 86400, "3d": 259200, "1w": 604800,
}


def barras_por_anio(intervalo):
    """Cripto cotiza 24/7, así que el año son 365,25 días completos."""
    return SEGUNDOS_POR_ANIO / INTERVALOS_SEG.get(intervalo, 3600)


def max_drawdown(equity):
    """Caída máxima desde máximo previo, como fracción (0,25 = 25 %)."""
    if len(equity) == 0:
        return 0.0
    maximos = np.maximum.accumulate(equity)
    caidas = np.where(maximos > 0, (maximos - equity) / maximos, 0.0)
    return float(caidas.max())


def estabilidad(equity):
    """
    R² de la curva de capital contra una recta. Cerca de 1 significa
    crecimiento sostenido; cerca de 0, que el resultado depende de saltos
    puntuales. Se calcula sobre el log del capital para no premiar sólo al
    tramo final por efecto del interés compuesto.
    """
    if len(equity) < 3 or np.any(equity <= 0):
        return 0.0
    y = np.log(equity)
    x = np.arange(len(y), dtype=float)
    varianza = ((y - y.mean()) ** 2).sum()
    if varianza <= 0:
        return 0.0
    pendiente, corte = np.polyfit(x, y, 1)
    residuos = ((y - (pendiente * x + corte)) ** 2).sum()
    return float(max(0.0, 1 - residuos / varianza))


def racha_perdedora(retornos):
    """Mayor número de operaciones perdedoras seguidas."""
    peor = actual = 0
    for r in retornos:
        actual = actual + 1 if r <= 0 else 0
        peor = max(peor, actual)
    return peor


def calcular(resultado, intervalo="1h", capital_inicial=10_000.0):
    """Resumen completo de un Resultado del motor."""
    equity = resultado.equity
    retornos = resultado.retorno
    n = len(equity)

    if n == 0 or resultado.n_operaciones == 0:
        return {
            "retorno_total": 0.0, "cagr": 0.0, "max_drawdown": 0.0, "return_dd": 0.0,
            "sharpe": 0.0, "sortino": 0.0, "profit_factor": 0.0, "win_rate": 0.0,
            "n_operaciones": 0, "retorno_medio": 0.0, "estabilidad": 0.0,
            "exposicion": 0.0, "racha_perdedora": 0, "buy_hold": 0.0,
            "capital_final": capital_inicial,
        }

    por_anio = barras_por_anio(intervalo)
    anios = max(n / por_anio, 1e-9)

    capital_final = float(equity[-1])
    retorno_total = capital_final / capital_inicial - 1
    cagr = (capital_final / capital_inicial) ** (1 / anios) - 1 if capital_final > 0 else -1.0

    dd = max_drawdown(equity)

    # Sharpe y Sortino sobre el rendimiento barra a barra del capital, no sobre
    # el de las operaciones: así el tiempo fuera de mercado también cuenta.
    variacion = np.diff(equity) / np.where(equity[:-1] != 0, equity[:-1], 1)
    desviacion = variacion.std(ddof=1) if len(variacion) > 1 else 0.0
    sharpe = float(variacion.mean() / desviacion * np.sqrt(por_anio)) if desviacion > 0 else 0.0

    negativos = variacion[variacion < 0]
    desv_baja = negativos.std(ddof=1) if len(negativos) > 1 else 0.0
    sortino = float(variacion.mean() / desv_baja * np.sqrt(por_anio)) if desv_baja > 0 else 0.0

    ganancias = retornos[retornos > 0].sum()
    perdidas = -retornos[retornos < 0].sum()
    profit_factor = float(ganancias / perdidas) if perdidas > 0 else (np.inf if ganancias > 0 else 0.0)

    barras_dentro = int((resultado.salida_idx - resultado.entrada_idx).sum())

    precio = resultado.datos.close if resultado.datos is not None else None
    buy_hold = float(precio[-1] / precio[0] - 1) if precio is not None and precio[0] > 0 else 0.0

    return {
        "retorno_total": float(retorno_total),
        "cagr": float(cagr),
        "max_drawdown": float(dd),
        # Return/DD: el criterio principal de SQ. Sin drawdown no hay ratio.
        "return_dd": float(cagr / dd) if dd > 1e-9 else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "profit_factor": profit_factor,
        "win_rate": float((retornos > 0).mean()),
        "n_operaciones": int(len(retornos)),
        "retorno_medio": float(retornos.mean()),
        "estabilidad": estabilidad(equity),
        "exposicion": float(barras_dentro / n),
        "racha_perdedora": racha_perdedora(retornos),
        "buy_hold": buy_hold,
        "capital_final": capital_final,
    }


def formatear(m):
    """Resumen legible para consola."""
    pf = "∞" if np.isinf(m["profit_factor"]) else f"{m['profit_factor']:.2f}"
    return (
        f"  retorno total   {m['retorno_total']:>10.1%}      operaciones   {m['n_operaciones']:>8}\n"
        f"  CAGR            {m['cagr']:>10.1%}      win rate      {m['win_rate']:>8.1%}\n"
        f"  max drawdown    {m['max_drawdown']:>10.1%}      profit factor {pf:>8}\n"
        f"  return/DD       {m['return_dd']:>10.2f}      estabilidad   {m['estabilidad']:>8.2f}\n"
        f"  Sharpe          {m['sharpe']:>10.2f}      exposición    {m['exposicion']:>8.1%}\n"
        f"  Sortino         {m['sortino']:>10.2f}      racha perd.   {m['racha_perdedora']:>8}\n"
        f"  buy & hold      {m['buy_hold']:>10.1%}      capital final {m['capital_final']:>8,.0f}"
    )
