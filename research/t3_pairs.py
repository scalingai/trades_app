"""
TEST 3 — Cointegracion y trading de spreads.

El test 2 mostro que la direccion en 1h es paseo aleatorio. Pero la
correlacion de 0.80 entre los tres activos, que arruina la diversificacion,
es exactamente la condicion que hace posible operar el spread: si dos series
se mueven juntas, su diferencia puede ser estacionaria aunque cada una por
separado no lo sea.

Un spread estacionario es la mejor estructura posible para una cuenta de
fondeo: es neutral al mercado, no muere en un crash, y su reversion es
medible en vez de opinable.

Se testea con Engle-Granger:
  1. Regresion de log(A) contra log(B) => hedge ratio beta
  2. Test ADF sobre el residuo. Si rechaza raiz unitaria, hay cointegracion
  3. Vida media de reversion ajustando un Ornstein-Uhlenbeck al residuo

La trampa clasica: estimar beta sobre TODA la muestra y despues "testear"
sobre la misma muestra. Aca beta se estima solo con datos de entrenamiento y
la estacionariedad se verifica tambien fuera de muestra.
"""
import itertools

import numpy as np
from statsmodels.tsa.stattools import adfuller, coint

from .data import align, load_all

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def hedge_ratio(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """MCO de y sobre x con constante. Devuelve (alpha, beta)."""
    X = np.column_stack([np.ones(len(x)), x])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[0]), float(coef[1])


def half_life(spread: np.ndarray) -> float:
    """
    Vida media de reversion ajustando un OU discreto:
        d_spread_t = lambda * spread_{t-1} + eps
        half_life = -ln(2) / ln(1 + lambda)
    """
    lag = spread[:-1]
    d = np.diff(spread)
    X = np.column_stack([np.ones(len(lag)), lag])
    coef, *_ = np.linalg.lstsq(X, d, rcond=None)
    lam = coef[1]
    if lam >= 0:
        return np.inf
    return float(-np.log(2) / np.log(1 + lam))


def run(interval: str = "1h", n_candles: int = 17_000, train_frac: float = 0.70) -> dict:
    print("=" * 76)
    print(f"  TEST 3 — COINTEGRACION Y SPREADS ({interval})")
    print("=" * 76)
    dfs = load_all(SYMBOLS, interval, n_candles)
    px = align(dfs)
    logpx = {s: np.log(px[s].to_numpy()) for s in SYMBOLS}
    n = len(px)
    split = int(n * train_frac)
    print(f"\n  Entrenamiento: {px['dt'].iloc[0]:%Y-%m-%d} -> {px['dt'].iloc[split]:%Y-%m-%d} ({split} velas)")
    print(f"  Fuera de muestra: {px['dt'].iloc[split]:%Y-%m-%d} -> {px['dt'].iloc[-1]:%Y-%m-%d} ({n-split} velas)")

    # Primero: cada serie individual DEBE tener raiz unitaria. Si no la tiene,
    # la cointegracion no significa nada.
    print("\n  ADF sobre cada log-precio (se espera NO rechazar => raiz unitaria):")
    for s in SYMBOLS:
        stat, p, *_ = adfuller(logpx[s], maxlag=24, autolag="AIC")
        print(f"    {s:<9} ADF={stat:+.3f}  p={p:.3f}  -> "
              f"{'raiz unitaria (ok)' if p > 0.05 else 'ESTACIONARIA (raro)'}")

    print("\n  Cointegracion por par (beta estimado SOLO en entrenamiento):")
    print(f"  {'par':<20} {'beta':>8} {'ADF in':>9} {'p in':>7} {'ADF out':>9} {'p out':>7} {'vida media':>11}")
    print("  " + "-" * 78)

    resultados = {}
    for a, b in itertools.combinations(SYMBOLS, 2):
        ya, xb = logpx[a], logpx[b]
        alpha, beta = hedge_ratio(ya[:split], xb[:split])

        spread_in = ya[:split] - (alpha + beta * xb[:split])
        spread_out = ya[split:] - (alpha + beta * xb[split:])

        stat_i, p_i, *_ = adfuller(spread_in, maxlag=24, autolag="AIC")
        stat_o, p_o, *_ = adfuller(spread_out, maxlag=24, autolag="AIC")
        hl = half_life(spread_in)

        nombre = f"{a[:3]}/{b[:3]}"
        hl_txt = f"{hl:.1f}h" if np.isfinite(hl) else "inf"
        print(f"  {nombre:<20} {beta:>8.3f} {stat_i:>9.2f} {p_i:>7.3f} "
              f"{stat_o:>9.2f} {p_o:>7.3f} {hl_txt:>11}")

        resultados[nombre] = {
            "alpha": alpha, "beta": beta, "p_in": p_i, "p_out": p_o,
            "half_life": hl, "spread_in": spread_in, "spread_out": spread_out,
        }

    # Test de Engle-Granger completo sobre toda la muestra, como referencia
    print("\n  Test de cointegracion de Engle-Granger (muestra completa, referencia):")
    for a, b in itertools.combinations(SYMBOLS, 2):
        stat, p, _ = coint(logpx[a], logpx[b])
        veredicto = "COINTEGRADO" if p < 0.05 else "no cointegrado"
        print(f"    {a[:3]}/{b[:3]:<6} stat={stat:+.3f}  p={p:.4f}  -> {veredicto}")

    print("\n  Estabilidad del beta (ventanas moviles de 2000 velas):")
    for a, b in itertools.combinations(SYMBOLS, 2):
        betas = []
        for i in range(0, n - 2000, 500):
            _, bt = hedge_ratio(logpx[a][i:i + 2000], logpx[b][i:i + 2000])
            betas.append(bt)
        betas = np.array(betas)
        cv = betas.std() / abs(betas.mean()) if betas.mean() != 0 else np.inf
        estable = "estable" if cv < 0.15 else "INESTABLE"
        print(f"    {a[:3]}/{b[:3]:<6} beta medio {betas.mean():.3f} | "
              f"desvio {betas.std():.3f} | CV {cv:.1%} -> {estable}")

    return resultados


if __name__ == "__main__":
    run()
