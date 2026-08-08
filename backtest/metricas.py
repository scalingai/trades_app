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


def wilson_inferior(aciertos, total, z=1.96):
    """
    Extremo inferior del intervalo de confianza al 95 % de una proporción
    (puntuación de Wilson).

    Un 65 % de acierto sacado de 20 operaciones y otro sacado de 500 no valen
    lo mismo, y la diferencia no se ve en el porcentaje. Con 20 el suelo del
    intervalo está en torno al 43 %; con 500, cerca del 61 %. Optimizar por
    este suelo en vez de por el win rate crudo hace que la muestra pequeña
    deje de ser una ventaja para el sobreajuste.
    """
    if total <= 0:
        return 0.0
    p = aciertos / total
    denominador = 1 + z ** 2 / total
    centro = (p + z ** 2 / (2 * total)) / denominador
    margen = z * np.sqrt(p * (1 - p) / total + z ** 2 / (4 * total ** 2)) / denominador
    return float(max(0.0, centro - margen))


def win_rate_equilibrio(retornos):
    """
    Win rate que haría falta para no perder dinero, dados el tamaño medio de
    las ganancias y de las pérdidas realmente observados.

    Con ratio 1:1 exacto y sin costes saldría 50 %. Los costes lo empujan
    arriba, y cuanto más pequeño es el stop más lo empujan: con stop del 0,3 %
    y 0,12 % de coste ida y vuelta, hace falta un 60 %.
    """
    ganancias = retornos[retornos > 0]
    perdidas = retornos[retornos <= 0]
    if len(ganancias) == 0 or len(perdidas) == 0:
        return float("nan")
    media_ganancia = ganancias.mean()
    media_perdida = -perdidas.mean()
    if media_ganancia + media_perdida <= 0:
        return float("nan")
    return float(media_perdida / (media_ganancia + media_perdida))


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
            "win_rate_inf": 0.0, "win_rate_equilibrio": float("nan"), "margen_acierto": 0.0,
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

    aciertos = int((retornos > 0).sum())
    win_rate = aciertos / len(retornos)
    equilibrio = win_rate_equilibrio(retornos)
    # Margen: cuántos puntos porcentuales sobra el acierto por encima del que
    # haría falta sólo para cubrir costes. Es la cifra que decide si una
    # estrategia de ratio 1:1 gana dinero o no.
    margen = win_rate - equilibrio if np.isfinite(equilibrio) else 0.0

    return {
        "retorno_total": float(retorno_total),
        "cagr": float(cagr),
        "max_drawdown": float(dd),
        # Return/DD: el criterio principal de SQ. Sin drawdown no hay ratio.
        "return_dd": float(cagr / dd) if dd > 1e-9 else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "profit_factor": profit_factor,
        "win_rate": float(win_rate),
        # Suelo del intervalo de confianza al 95 %: con pocas operaciones cae
        # mucho, que es exactamente lo que se busca al optimizar por acierto.
        "win_rate_inf": wilson_inferior(aciertos, len(retornos)),
        "win_rate_equilibrio": float(equilibrio),
        "margen_acierto": float(margen),
        "n_operaciones": int(len(retornos)),
        "retorno_medio": float(retornos.mean()),
        "estabilidad": estabilidad(equity),
        "exposicion": float(barras_dentro / n),
        "racha_perdedora": racha_perdedora(retornos),
        "buy_hold": buy_hold,
        "capital_final": capital_final,
    }


def formatear_acierto(m):
    """
    Bloque centrado en la efectividad, para estrategias de ratio fijo.

    Con ratio 1:1 lo único que decide es si el acierto supera al de equilibrio,
    y por cuánto. El suelo del intervalo dice si ese margen se sostiene o es
    ruido de una muestra corta.
    """
    equilibrio = m["win_rate_equilibrio"]
    if not np.isfinite(equilibrio):
        return "  sin operaciones ganadoras y perdedoras a la vez: no hay acierto que medir"

    veredicto = ""
    if m["win_rate_inf"] > equilibrio:
        veredicto = "  ✅ el suelo del intervalo ya supera el equilibrio"
    elif m["win_rate"] > equilibrio:
        veredicto = "  ⚠️  gana de media, pero el intervalo llega por debajo del equilibrio:\n" \
                    "      con estas operaciones no se puede descartar que sea suerte"
    else:
        veredicto = "  ❌ el acierto no cubre ni los costes"

    return (
        f"  acierto              {m['win_rate']:>8.1%}   sobre {m['n_operaciones']} operaciones\n"
        f"  suelo del intervalo  {m['win_rate_inf']:>8.1%}   (95 % de confianza)\n"
        f"  acierto de equilibrio{equilibrio:>8.1%}   el mínimo para cubrir costes\n"
        f"  margen               {m['margen_acierto']:>+8.1%}\n"
        f"{veredicto}"
    )


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
