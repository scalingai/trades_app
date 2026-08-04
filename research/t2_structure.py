"""
TEST 2 — Hay estructura explotable, o es un paseo aleatorio?

Si los retornos son un paseo aleatorio, no existe edge direccional y todo lo
demas sobra. Antes de disenar entradas conviene saber si hay algo que
explotar. Tres pruebas independientes:

  Autocorrelacion   correlacion del retorno con el retorno pasado. Positiva
                    en lag 1 => momentum. Negativa => reversion.
  Variance ratio    la varianza de retornos a q periodos deberia ser q veces
                    la varianza a 1 periodo bajo paseo aleatorio. VR > 1
                    indica tendencia, VR < 1 reversion. Se usa el estadistico
                    de Lo-MacKinlay robusto a heterocedasticidad.
  Hurst             exponente de escalado. H = 0.5 paseo aleatorio, H > 0.5
                    persistencia, H < 0.5 antipersistencia.

Con ~17000 observaciones, efectos muy chicos pueden salir significativos sin
ser explotables: 0.02 de autocorrelacion es estadisticamente real y
economicamente nulo frente a comisiones. Se reporta ambas cosas.
"""
import numpy as np
from scipy import stats

from .data import fetch, log_returns

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def autocorr(r: np.ndarray, lags: int = 24) -> list[tuple[int, float, float]]:
    """Autocorrelacion con su estadistico t aproximado (se ~ 1/sqrt(n))."""
    out = []
    n = len(r)
    for lag in range(1, lags + 1):
        a, b = r[:-lag], r[lag:]
        c = float(np.corrcoef(a, b)[0, 1])
        t = c * np.sqrt(n - lag)
        out.append((lag, c, t))
    return out


def variance_ratio(r: np.ndarray, q: int) -> tuple[float, float]:
    """
    Variance ratio de Lo-MacKinlay con correccion por heterocedasticidad.

    Devuelve (VR, z). |z| > 1.96 rechaza paseo aleatorio al 5%.
    """
    n = len(r)
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / (n - 1)

    # Varianza de sumas solapadas de q retornos
    rq = np.convolve(r, np.ones(q), mode="valid")
    m = q * (n - q + 1) * (1 - q / n)
    varq = np.sum((rq - q * mu) ** 2) / m
    vr = varq / var1

    # Error estandar robusto a heterocedasticidad (Lo-MacKinlay 1988, ec. 18).
    # delta_j = sum[(r_t-mu)^2 (r_{t-j}-mu)^2] / [sum (r_t-mu)^2]^2
    # El denominador va al cuadrado sin dividir por n.
    dev = r - mu
    ss = np.sum(dev**2)
    theta = 0.0
    for j in range(1, q):
        num = np.sum((dev[j:] ** 2) * (dev[: n - j] ** 2))
        delta = num / (ss**2) if ss > 0 else 0.0
        theta += ((2 * (q - j) / q) ** 2) * delta
    z = (vr - 1) / np.sqrt(theta) if theta > 0 else np.nan
    return float(vr), float(z)


def hurst(prices: np.ndarray, max_lag: int = 200) -> float:
    """
    Exponente de Hurst por escalado de la desviacion de las diferencias.

    Recibe la SERIE DE NIVELES (log-precios), no los retornos: el metodo mide
    como escala la dispersion de las diferencias a distintos horizontes, y
    aplicarlo a una serie ya diferenciada devuelve H ~ 0 siempre.
    """
    lags = np.unique(np.logspace(np.log10(2), np.log10(max_lag), 30).astype(int))
    tau = []
    keep = []
    for lag in lags:
        if lag >= len(prices):
            continue
        d = prices[lag:] - prices[:-lag]
        s = np.std(d)
        if s > 0:
            tau.append(s)
            keep.append(lag)
    slope = np.polyfit(np.log(np.array(keep, float)), np.log(np.array(tau)), 1)[0]
    return float(slope)


def run(interval: str = "1h", n_candles: int = 17_000) -> dict:
    print("=" * 76)
    print(f"  TEST 2 — ESTRUCTURA vs PASEO ALEATORIO ({interval})")
    print("=" * 76)

    res = {}
    for sym in SYMBOLS:
        df = fetch(sym, interval, n_candles)
        r = log_returns(df)
        logpx = np.log(df["close"].to_numpy())
        res[sym] = r

        print(f"\n  --- {sym} ({len(r)} retornos) ---")
        print(f"  media {r.mean():+.6f} | desvio {r.std():.5f} | "
              f"asimetria {stats.skew(r):+.2f} | curtosis {stats.kurtosis(r):+.1f}")

        # Autocorrelacion: solo se muestran los lags significativos
        ac = autocorr(r, 24)
        signif = [(l, c, t) for l, c, t in ac if abs(t) > 1.96]
        print(f"  Autocorrelacion: {len(signif)}/24 lags significativos al 5%")
        if signif:
            top = sorted(signif, key=lambda x: -abs(x[1]))[:5]
            for l, c, t in top:
                tipo = "momentum" if c > 0 else "reversion"
                print(f"    lag {l:>2}: rho={c:+.4f} (t={t:+.2f})  {tipo}")
        # Bonferroni sobre 24 lags
        thr = stats.norm.ppf(1 - 0.025 / 24)
        strong = [(l, c, t) for l, c, t in ac if abs(t) > thr]
        print(f"    tras correccion por 24 tests (|t|>{thr:.2f}): {len(strong)} sobreviven")

        # Variance ratio
        print("  Variance ratio (VR<1 reversion, VR>1 tendencia):")
        for q in [2, 4, 8, 24]:
            vr, z = variance_ratio(r, q)
            veredicto = "paseo aleatorio" if abs(z) < 1.96 else ("REVERSION" if vr < 1 else "TENDENCIA")
            print(f"    q={q:>3}: VR={vr:.4f}  z={z:+.2f}  -> {veredicto}")

        h = hurst(logpx)
        print(f"  Hurst: {h:.4f} " + ("(reversion)" if h < 0.48 else "(tendencia)" if h > 0.52 else "(neutro)"))

    return res


if __name__ == "__main__":
    run()
