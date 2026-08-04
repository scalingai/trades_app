"""
TEST 1 — Correlacion y tamano de muestra efectivo.

Este test puede invalidar la recomendacion de "operar varios activos en
paralelo para validar mas rapido". Esa idea asume que cada activo aporta
muestras independientes. Si BTC, ETH y SOL se mueven juntos, no las aporta:
un trade en cada uno es casi el mismo trade tres veces.

Tamano de muestra efectivo con n activos y correlacion promedio rho:

    n_eff = n / (1 + (n - 1) * rho)

Con rho = 0.8 y n = 5, n_eff = 1.19. Cinco activos aportarian lo mismo que
uno solo, y todo el argumento de velocidad de validacion se cae.
"""
import numpy as np

from .data import align, load_all

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def effective_n(n: int, rho: float) -> float:
    if n <= 1:
        return float(n)
    denom = 1 + (n - 1) * rho
    return n / denom if denom > 0 else float(n)


def run(interval: str = "1h", n_candles: int = 17_000) -> dict:
    print("=" * 76)
    print("  TEST 1 — CORRELACION Y TAMANO DE MUESTRA EFECTIVO")
    print("=" * 76)
    dfs = load_all(SYMBOLS, interval, n_candles)
    px = align(dfs)
    rets = np.diff(np.log(px[SYMBOLS].to_numpy()), axis=0)

    print(f"\n  Retornos log {interval}, {len(rets)} observaciones alineadas\n")

    C = np.corrcoef(rets.T)
    print("  Matriz de correlacion:")
    print(f"  {'':<10}" + "".join(f"{s[:3]:>9}" for s in SYMBOLS))
    for i, s in enumerate(SYMBOLS):
        print(f"  {s[:3]:<10}" + "".join(f"{C[i, j]:>9.3f}" for j in range(len(SYMBOLS))))

    off = C[np.triu_indices(len(SYMBOLS), k=1)]
    rho = float(off.mean())
    print(f"\n  Correlacion promedio entre pares: {rho:.3f}")

    print("\n  Tamano de muestra efectivo si se operan n activos con estas reglas:")
    print(f"  {'n activos':>10} {'n efectivo':>12} {'ganancia real':>15}")
    print("  " + "-" * 40)
    for n in [1, 2, 3, 5, 8]:
        ne = effective_n(n, rho)
        print(f"  {n:>10} {ne:>12.2f} {ne:>14.2f}x")

    # Correlacion en distintos regimenes: la correlacion sube en los crashes,
    # justo cuando importa. Un promedio la subestima.
    print("\n  Correlacion condicionada al tamano del movimiento de BTC:")
    btc = rets[:, 0]
    q = np.abs(btc)
    for label, mask in [
        ("dias tranquilos (|ret| < p50)", q < np.percentile(q, 50)),
        ("movimiento medio (p50-p90)", (q >= np.percentile(q, 50)) & (q < np.percentile(q, 90))),
        ("cola (|ret| > p90)", q >= np.percentile(q, 90)),
    ]:
        sub = rets[mask]
        Cs = np.corrcoef(sub.T)
        rho_s = float(Cs[np.triu_indices(len(SYMBOLS), k=1)].mean())
        print(f"    {label:<32} rho = {rho_s:.3f}  (n={mask.sum()})")

    # Un trade abierto simultaneamente en n activos correlacionados no arriesga
    # n x R: arriesga aproximadamente R * sqrt(n + n(n-1)rho).
    print("\n  Riesgo real de abrir posiciones simultaneas en la misma direccion:")
    print(f"  {'posiciones':>11} {'riesgo nominal':>16} {'riesgo real':>13} {'exceso':>9}")
    print("  " + "-" * 52)
    for n in [1, 2, 3]:
        nominal = n
        real = np.sqrt(n + n * (n - 1) * rho)
        print(f"  {n:>11} {nominal:>15.2f}R {real:>12.2f}R {real/nominal:>8.2f}x")

    return {"rho": rho, "corr_matrix": C, "n_obs": len(rets)}


if __name__ == "__main__":
    run()
