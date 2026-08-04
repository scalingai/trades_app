"""
Elige activo, timeframe y distancia de stop con datos reales, no por gusto.

    python analyze_params.py
    python analyze_params.py --edge 0.20 --symbols BTCUSDT ETHUSDT SOLUSDT

Tres restricciones que se pelean entre si:

  COSTOS       piden stops anchos (timeframe alto). El costo en R es
               comision_ida_y_vuelta / distancia_del_stop, asi que un stop
               corto multiplica la posicion y con ella la comision.

  VALIDACION   pide muchos trades (timeframe bajo). Hacen falta cientos de
               trades para separar edge de suerte, y un timeframe alto tarda
               anos en producirlos.

  REGLAS       de la cuenta de fondeo acotan el riesgo por trade y el RR
               maximo por dia.

La salida es la zona donde las tres se satisfacen a la vez. Si esa zona esta
vacia para un activo, ese activo no sirve para este enfoque — y es mejor
saberlo antes de operarlo que despues.
"""
import argparse
import json
import statistics as st
import urllib.request

from sim.power import (
    FeeModel,
    calendar_time,
    cost_in_r,
    expected_r,
    sigma_r,
    trades_needed,
    trades_needed_multiple_testing,
)

# Endpoint publico de datos de mercado de Binance (sin API key).
# api.binance.com devuelve 451 desde varias regiones; este mirror responde.
BASE = "https://data-api.binance.vision/api/v3/klines"

# Setups aproximados por dia y por activo para cada timeframe. Son ordenes de
# magnitud para dimensionar el tiempo de validacion, no una medicion.
SETUPS_POR_DIA = {"1m": 30.0, "5m": 10.0, "15m": 4.0, "1h": 1.5, "4h": 0.5}


def fetch_atr(symbol: str, interval: str, limit: int = 1000) -> tuple[float, float]:
    """ATR medio y mediano como fraccion del precio."""
    url = f"{BASE}?symbol={symbol}&interval={interval}&limit={limit}"
    k = json.load(urllib.request.urlopen(url, timeout=30))
    trs = []
    for i in range(1, len(k)):
        h, l, c, pc = float(k[i][2]), float(k[i][3]), float(k[i][4]), float(k[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)) / c)
    return st.mean(trs), st.median(trs)


def analizar(symbols, intervals, fees, edge_bruto, stop_mult, n_variants, n_assets_live):
    print("=" * 78)
    print("  VOLATILIDAD REAL Y VIABILIDAD POR COSTOS")
    print("=" * 78)
    print(f"  Comisiones: maker {fees.maker:.3%} | taker {fees.taker:.3%} | slippage {fees.slippage:.3%}")
    print(f"  Stop asumido: {stop_mult} x ATR")
    print(f"  Edge bruto asumido: {edge_bruto:+.2f} R por trade (antes de costos)")
    print()

    rt_taker = fees.round_trip(False, False)
    rt_maker = fees.round_trip(True, True)

    print(f"  {'activo':<9} {'TF':>4} {'ATR':>8} {'stop':>8} "
          f"{'costo R':>9} {'edge neto':>10} {'costo R':>9} {'edge neto':>10}")
    print(f"  {'':<9} {'':>4} {'':>8} {'':>8} {'(taker)':>9} {'(taker)':>10} {'(maker)':>9} {'(maker)':>10}")
    print("  " + "-" * 72)

    viables = []
    for sym in symbols:
        for tf in intervals:
            try:
                atr, _ = fetch_atr(sym, tf)
            except Exception as e:
                print(f"  {sym:<9} {tf:>4}  ERROR {type(e).__name__}")
                continue
            stop = atr * stop_mult
            c_t = cost_in_r(rt_taker, stop)
            c_m = cost_in_r(rt_maker, stop)
            neto_t = edge_bruto - c_t
            neto_m = edge_bruto - c_m
            flag = "" if neto_m > 0 else "  <- muerto"
            print(f"  {sym:<9} {tf:>4} {atr:>7.3%} {stop:>7.3%} "
                  f"{c_t:>9.3f} {neto_t:>+10.3f} {c_m:>9.3f} {neto_m:>+10.3f}{flag}")
            if neto_m > 0:
                viables.append((sym, tf, stop, neto_t, neto_m))
        print()

    return viables


def tiempo_validacion(viables, wr, rr, n_variants, n_assets_live):
    print("=" * 78)
    print("  TIEMPO DE VALIDACION DE LAS CONFIGURACIONES VIABLES")
    print("=" * 78)
    sigma = sigma_r(wr, rr)
    print(f"  Sistema de referencia: WR {wr:.0%} @ 1:{rr} | sigma {sigma:.2f} R")
    print(f"  Variantes a testear: {n_variants} | activos en paralelo: {n_assets_live}")
    print()
    print(f"  {'activo':<9} {'TF':>4} {'edge neto':>10} {'trades':>8} "
          f"{'setups/dia':>11} {'meses':>8}")
    print("  " + "-" * 58)

    vistos = set()
    for sym, tf, stop, neto_t, neto_m in viables:
        if neto_m <= 0:
            continue
        n = (
            trades_needed_multiple_testing(neto_m, sigma, n_variants)
            if n_variants > 1
            else trades_needed(neto_m, sigma)
        )
        setups = SETUPS_POR_DIA.get(tf, 1.0) * n_assets_live
        t = calendar_time(n, setups)
        key = (sym, tf)
        if key in vistos:
            continue
        vistos.add(key)
        print(f"  {sym:<9} {tf:>4} {neto_m:>+10.3f} {n:>8} {setups:>11.1f} {t['meses']:>8.1f}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--intervals", nargs="+", default=["5m", "15m", "1h", "4h"])
    ap.add_argument("--edge", type=float, default=0.20, help="edge bruto en R por trade")
    ap.add_argument("--stop-mult", type=float, default=1.5, help="stop en multiplos de ATR")
    ap.add_argument("--wr", type=float, default=0.40)
    ap.add_argument("--rr", type=float, default=2.0)
    ap.add_argument("--variants", type=int, default=1, help="variantes testeadas (correccion de testeo multiple)")
    ap.add_argument("--assets-live", type=int, default=1, help="activos operados en paralelo")
    ap.add_argument("--maker", type=float, default=0.0002)
    ap.add_argument("--taker", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.0002)
    args = ap.parse_args()

    fees = FeeModel(maker=args.maker, taker=args.taker, slippage=args.slippage)
    viables = analizar(
        args.symbols, args.intervals, fees, args.edge,
        args.stop_mult, args.variants, args.assets_live,
    )
    if viables:
        tiempo_validacion(viables, args.wr, args.rr, args.variants, args.assets_live)
    else:
        print("Ninguna configuracion sobrevive a los costos con ese edge bruto.")

    print("=" * 78)
    print("  LECTURA")
    print("=" * 78)
    print("  El costo en R es comision / distancia_del_stop. No depende del")
    print("  activo ni de la senal: solo de cuan cerca este el stop. Por eso")
    print("  bajar de timeframe sube el costo aunque la senal sea igual de buena.")
    print()
    print("  Operar varios activos con las MISMAS reglas multiplica la tasa de")
    print("  muestreo sin tocar el timeframe. Es la unica palanca que acorta la")
    print("  validacion sin empeorar los costos — y ademas obliga a que el edge")
    print("  sea estructural y no una particularidad de un simbolo.")
    print()


if __name__ == "__main__":
    main()
