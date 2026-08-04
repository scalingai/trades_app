"""
TEST 5 — MFE/MAE, costo por horario, y si la volatilidad se convierte en edge.

El test 4 encontro una sola senal fuerte: la volatilidad se predice entre 187x
y 431x mejor que la direccion, y varia hasta 4.6x segun la hora UTC. Este test
verifica si eso sirve para algo operativamente.

  a) MFE/MAE       cuanto corre un movimiento a favor antes de girar. Es lo que
                   determina el RR alcanzable, y se mide en vez de suponerse.

  b) Costo/hora    el costo en R es comision/distancia_del_stop, y el stop
                   escala con la volatilidad. Operar en horas de alta
                   volatilidad abarata el costo en R sin cambiar la senal.

  c) Backtest      prueba honesta fuera de muestra de una entrada basada en
                   expansion de volatilidad, con comisiones incluidas.
"""
import numpy as np

from .data import fetch
from sim.power import FeeModel

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
FEES = FeeModel()


def atr(df, n=14):
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    out = np.full(len(df), np.nan)
    out[1:] = np.convolve(tr, np.ones(n) / n, mode="same")
    return out


def bloque_mfe_mae(df, horizonte=24):
    """
    Para cada barra, cuanto corre a favor (MFE) y en contra (MAE) en las
    siguientes `horizonte` barras, medido en multiplos del ATR de entrada.
    Sin condicionar por senal: es la linea de base que cualquier entrada
    tiene que superar.
    """
    print(f"\n  a) MFE/MAE INCONDICIONAL (horizonte {horizonte}h, en multiplos de ATR)")
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    a = atr(df)

    n = len(c) - horizonte
    idx = np.arange(20, n)
    mfe_l, mae_l = [], []
    for i in idx:
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        fut_h = h[i + 1:i + 1 + horizonte].max()
        fut_l = l[i + 1:i + 1 + horizonte].min()
        mfe_l.append((fut_h - c[i]) / a[i])
        mae_l.append((c[i] - fut_l) / a[i])
    mfe = np.array(mfe_l)
    mae = np.array(mae_l)

    print(f"     n={len(mfe)}")
    print(f"     {'percentil':>10} {'MFE (largo)':>13} {'MAE (largo)':>13}")
    for p in [25, 50, 75, 90]:
        print(f"     {p:>9}% {np.percentile(mfe, p):>13.2f} {np.percentile(mae, p):>13.2f}")

    # Para un stop en k*ATR, que fraccion de barras alcanza cada objetivo
    print("\n     Si el stop esta a 1.5 ATR, probabilidad de tocar el objetivo antes:")
    print(f"     {'objetivo':>10} {'RR':>6} {'P(MFE>=obj)':>13} {'P(MAE>=1.5)':>13}")
    p_stop = float((mae >= 1.5).mean())
    for tgt in [1.5, 2.25, 3.0, 4.5, 6.0]:
        p_tgt = float((mfe >= tgt).mean())
        print(f"     {tgt:>9.2f} {tgt/1.5:>6.1f} {p_tgt:>13.1%} {p_stop:>13.1%}")
    print("     (no es un win rate: ignora el orden en que se tocan. Es cota superior.)")


def bloque_costo_por_hora(df):
    """El costo en R depende de la volatilidad de la hora en que se opera."""
    print("\n  b) COSTO EN R SEGUN HORA UTC")
    a = atr(df)
    c = df["close"].to_numpy()
    horas = df["dt"].dt.hour.to_numpy()
    atr_pct = a / c

    rt = FEES.round_trip(True, False)  # maker entrada, taker salida
    filas = []
    for hh in range(24):
        m = (horas == hh) & np.isfinite(atr_pct)
        v = float(np.nanmean(atr_pct[m]))
        stop = 1.5 * v
        filas.append((hh, v, stop, rt / stop))

    filas.sort(key=lambda x: x[3])
    print(f"     Comision ida+vuelta asumida: {rt:.3%} (maker entrada, taker salida)")
    print(f"     {'hora':>6} {'ATR%':>8} {'stop 1.5x':>10} {'costo en R':>11}")
    print("     " + "-" * 38)
    for hh, v, stop, cr in filas[:4]:
        print(f"     {hh:02d}:00 {v:>8.3%} {stop:>10.3%} {cr:>11.3f}  <- mas barato")
    print("     ...")
    for hh, v, stop, cr in filas[-4:]:
        print(f"     {hh:02d}:00 {v:>8.3%} {stop:>10.3%} {cr:>11.3f}  <- mas caro")
    mejor, peor = filas[0][3], filas[-1][3]
    print(f"     Diferencia entre la mejor y la peor hora: {peor/mejor:.2f}x en costo")


def bloque_backtest_vol(df, train_frac=0.70):
    """
    Entrada por expansion de volatilidad, evaluada fuera de muestra.

    Regla: si el rango de la barra supera k veces el ATR, entrar en la
    direccion de la barra. Stop 1.5 ATR, objetivo 2.25 ATR (RR 1.5).
    Es deliberadamente simple: si algo tan directo no funciona, conviene
    saberlo antes de construir 261 variantes encima.
    """
    print("\n  c) BACKTEST FUERA DE MUESTRA — EXPANSION DE VOLATILIDAD")
    c = df["close"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    a = atr(df)
    rng_bar = h - l
    n = len(c)
    split = int(n * train_frac)

    rt = FEES.round_trip(True, False)

    def correr(lo_i, hi_i, k, direccion=1):
        """direccion=+1 sigue la barra, -1 la contraria."""
        trades = []
        i = lo_i
        while i < hi_i - 24:
            if np.isfinite(a[i]) and a[i] > 0 and rng_bar[i] > k * a[i]:
                lado = direccion * (1 if c[i] > (h[i] + l[i]) / 2 else -1)
                entry = c[i]
                stop_d = 1.5 * a[i]
                tgt_d = 2.25 * a[i]
                stop = entry - lado * stop_d
                tgt = entry + lado * tgt_d
                res = None
                for j in range(i + 1, min(i + 25, hi_i)):
                    if lado == 1:
                        if l[j] <= stop:
                            res = -1.0; break
                        if h[j] >= tgt:
                            res = 1.5; break
                    else:
                        if h[j] >= stop:
                            res = -1.0; break
                        if l[j] <= tgt:
                            res = 1.5; break
                if res is None:
                    res = lado * (c[min(i + 24, hi_i - 1)] - entry) / stop_d
                # Comision expresada en R
                res -= rt / (stop_d / entry)
                trades.append(res)
                i += 24
            else:
                i += 1
        return np.array(trades)

    print(f"     {'k':>5} {'dir':>5} {'n in':>6} {'E[R] in':>9} {'n out':>6} {'E[R] out':>10} {'t out':>7}")
    print("     " + "-" * 56)
    for k in [1.5, 2.0, 2.5]:
        for direccion, etiqueta in [(1, "sigue"), (-1, "fade")]:
            tr_in = correr(20, split, k, direccion)
            tr_out = correr(split, n, k, direccion)
            if len(tr_in) < 20 or len(tr_out) < 20:
                continue
            t_out = tr_out.mean() / (tr_out.std() / np.sqrt(len(tr_out))) if tr_out.std() > 0 else 0
            print(f"     {k:>5.1f} {etiqueta:>5} {len(tr_in):>6} {tr_in.mean():>+9.3f} "
                  f"{len(tr_out):>6} {tr_out.mean():>+10.3f} {t_out:>+7.2f}")


def run(interval="1h", n_candles=17_000):
    print("=" * 76)
    print(f"  TEST 5 — MFE/MAE, COSTO POR HORARIO Y BACKTEST ({interval})")
    print("=" * 76)
    for sym in SYMBOLS:
        df = fetch(sym, interval, n_candles)
        print(f"\n{'='*76}\n  {sym}\n{'='*76}")
        bloque_mfe_mae(df)
        bloque_costo_por_hora(df)
        bloque_backtest_vol(df)


if __name__ == "__main__":
    run()
