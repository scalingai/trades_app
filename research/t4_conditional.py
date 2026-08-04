"""
TEST 4 — Edge condicional: horarios, volatilidad y barridos de liquidez.

Los tests 2 y 3 miraron la serie sin condicionar y no encontraron nada. Pero
un edge puede existir solo bajo ciertas condiciones y quedar diluido en el
promedio. Aca se condiciona por tres cosas:

  HORARIO       la tesis de "horarios clave" del ICT. Se testea si el retorno
                o la volatilidad dependen de la hora UTC, con correccion por
                estar probando 24 hipotesis a la vez.

  VOLATILIDAD   la volatilidad se predice mucho mejor que la direccion. Si eso
                se confirma, el edge explotable no esta en adivinar el lado
                sino en cuando y cuanto arriesgar.

  BARRIDOS      la tesis central del ICT: despues de que el precio barre un
                maximo o minimo previo y lo rechaza, revierte. Es una
                afirmacion falsable y se mide directamente.
"""
import numpy as np
from scipy import stats

from .data import fetch, log_returns

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def bloque_horarios(df, r):
    """Retorno y volatilidad por hora UTC, con correccion por 24 tests."""
    horas = df["dt"].dt.hour.to_numpy()[1:]
    print("\n  a) EFECTO HORA DEL DIA (UTC)")
    thr = stats.norm.ppf(1 - 0.025 / 24)
    print(f"     Umbral corregido por 24 tests: |t| > {thr:.2f}")

    filas = []
    for h in range(24):
        m = horas == h
        sub = r[m]
        t = sub.mean() / (sub.std() / np.sqrt(len(sub))) if len(sub) > 2 else 0.0
        filas.append((h, len(sub), sub.mean(), sub.std(), t))

    signif = [f for f in filas if abs(f[4]) > 1.96]
    fuertes = [f for f in filas if abs(f[4]) > thr]
    print(f"     Horas con retorno medio significativo al 5% sin corregir: {len(signif)}/24")
    print(f"     Horas que sobreviven la correccion: {len(fuertes)}/24")
    for h, n, m, s, t in sorted(filas, key=lambda x: -abs(x[4]))[:4]:
        marca = " *" if abs(t) > thr else ""
        print(f"       {h:02d}:00 UTC  n={n:>5}  ret medio {m:+.5f}  t={t:+.2f}{marca}")

    # La volatilidad por hora si suele tener estructura real
    vols = np.array([f[3] for f in filas])
    lo, hi = int(np.argmin(vols)), int(np.argmax(vols))
    f_stat = vols[hi] ** 2 / vols[lo] ** 2
    print(f"     Volatilidad: min {vols[lo]:.5f} a las {lo:02d}:00 | "
          f"max {vols[hi]:.5f} a las {hi:02d}:00 | ratio {f_stat:.2f}x")


def bloque_volatilidad(r):
    """Predictibilidad de la volatilidad vs predictibilidad de la direccion."""
    print("\n  b) VOLATILIDAD vs DIRECCION")
    absr = np.abs(r)
    # Autocorrelacion de |r| (volatilidad) contra la de r (direccion)
    for lag in [1, 6, 24]:
        ac_dir = np.corrcoef(r[:-lag], r[lag:])[0, 1]
        ac_vol = np.corrcoef(absr[:-lag], absr[lag:])[0, 1]
        t_dir = ac_dir * np.sqrt(len(r) - lag)
        t_vol = ac_vol * np.sqrt(len(r) - lag)
        print(f"     lag {lag:>2}h: autocorr direccion {ac_dir:+.4f} (t={t_dir:+6.1f}) | "
              f"volatilidad {ac_vol:+.4f} (t={t_vol:+6.1f})")

    # R^2 de predecir |r| con la volatilidad reciente
    win = 24
    prev = np.array([absr[max(0, i - win):i].mean() for i in range(win, len(absr))])
    fut = absr[win:]
    r2_vol = np.corrcoef(prev, fut)[0, 1] ** 2
    prev_dir = np.array([r[max(0, i - win):i].mean() for i in range(win, len(r))])
    r2_dir = np.corrcoef(prev_dir, r[win:])[0, 1] ** 2
    print(f"     R^2 prediciendo |retorno| con media movil de 24h : {r2_vol:.4f}")
    print(f"     R^2 prediciendo  retorno  con media movil de 24h : {r2_dir:.4f}")
    print(f"     La volatilidad es {r2_vol/max(r2_dir,1e-9):.0f}x mas predecible que la direccion")


def bloque_barridos(df, r, lookback: int = 24):
    """
    Tesis ICT: tras barrer un extremo previo y cerrar del lado contrario,
    el precio revierte. Se mide el retorno de las 1, 4 y 12 horas siguientes.
    """
    print(f"\n  c) BARRIDOS DE LIQUIDEZ (extremo de {lookback}h)")
    h = df["high"].to_numpy()
    lo = df["low"].to_numpy()
    c = df["close"].to_numpy()
    n = len(c)

    sweeps_hi, sweeps_lo = [], []
    for i in range(lookback, n - 12):
        prev_hi = h[i - lookback:i].max()
        prev_lo = lo[i - lookback:i].min()
        # Barrido alcista: la vela supera el maximo previo pero cierra por debajo
        if h[i] > prev_hi and c[i] < prev_hi:
            sweeps_hi.append(i)
        # Barrido bajista: perfora el minimo previo pero cierra por encima
        if lo[i] < prev_lo and c[i] > prev_lo:
            sweeps_lo.append(i)

    print(f"     Barridos detectados: {len(sweeps_hi)} de maximos, {len(sweeps_lo)} de minimos")
    if not sweeps_hi or not sweeps_lo:
        return

    base = r.std()
    for horizonte in [1, 4, 12]:
        # Tras barrer un maximo la tesis espera caida => se mide -retorno
        fwd_hi = np.array([np.log(c[i + horizonte] / c[i]) for i in sweeps_hi])
        fwd_lo = np.array([np.log(c[i + horizonte] / c[i]) for i in sweeps_lo])
        edge = np.concatenate([-fwd_hi, fwd_lo])
        t = edge.mean() / (edge.std() / np.sqrt(len(edge)))
        en_r = edge.mean() / base
        print(f"     +{horizonte:>2}h: retorno medio a favor de la tesis {edge.mean():+.5f} "
              f"({en_r:+.3f} sigma) t={t:+.2f} n={len(edge)}")


def run(interval: str = "1h", n_candles: int = 17_000):
    print("=" * 76)
    print(f"  TEST 4 — EDGE CONDICIONAL ({interval})")
    print("=" * 76)
    for sym in SYMBOLS:
        df = fetch(sym, interval, n_candles)
        r = log_returns(df)
        print(f"\n{'='*76}\n  {sym}\n{'='*76}")
        bloque_horarios(df, r)
        bloque_volatilidad(r)
        bloque_barridos(df, r)


if __name__ == "__main__":
    run()
