"""
CLI del simulador de cuentas de fondeo.

    python simulate.py                      # corrida base + barridos
    python simulate.py --wr 0.58 --rr 1.2   # otra estrategia
    python simulate.py --rules eval_1step_estricta
    python simulate.py --plan               # imprime el plan operativo derivado

El objetivo del simulador no es predecir cuanto vas a ganar. Es fijar los
numeros del plan (riesgo por trade, stop diario, trades por dia) con evidencia
en vez de con intuicion, y medir cuanto puede estar equivocado tu edge
estimado antes de que la cuenta deje de ser viable.
"""
import argparse

from sim import (
    TEMPLATES,
    Guard,
    SimConfig,
    StrategyParams,
    breakeven_winrate,
    simulate,
    sweep_risk,
    sweep_winrate,
)


def hr(title: str = "") -> None:
    print("\n" + "=" * 68)
    if title:
        print(f"  {title}")
        print("=" * 68)


def run_base(rules, strat, guard, cfg):
    hr("RULE SET")
    print(rules.summary())

    hr("ESTRATEGIA")
    print(f"  Win rate           : {strat.win_rate:.1%}")
    print(f"  RR                 : 1:{strat.rr}")
    print(f"  Riesgo por trade   : {strat.risk_per_trade:.2%} del balance inicial")
    print(f"  Trades por dia     : {strat.trades_per_day}")
    print(f"  E[R] por trade     : {strat.expected_r():+.3f} R")
    print(f"  Edge por trade     : {strat.edge_per_trade():+.3%} del balance")
    print(f"  WR de breakeven    : {breakeven_winrate(strat):.1%}")
    print(f"  Limites propios    : {guard.describe()}")

    hr("RESULTADO BASE")
    res = simulate(rules, strat, guard, cfg)
    print(res.report())
    return res


def run_sweeps(rules, strat, guard, cfg):
    fast = SimConfig(n_paths=max(4000, cfg.n_paths // 4), seed=cfg.seed)

    hr("BARRIDO 1 — RIESGO POR TRADE")
    print("  Con edge positivo, mas chico casi siempre gana. El costo es tiempo.\n")
    print(f"  {'riesgo':>8} | {'P(pasar)':>9} | {'daily DD':>9} | {'max DD':>8} | {'dias(med)':>10}")
    print("  " + "-" * 58)
    for r, res in sweep_risk(rules, strat, [0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02], guard, fast):
        med = f"{res.days_to_pass.mean():.0f}" if len(res.days_to_pass) else "-"
        print(
            f"  {r:>7.2%} | {res.pass_rate:>8.1%} | {res.rate('fail_daily_dd'):>8.1%} | "
            f"{res.rate('fail_max_dd'):>7.1%} | {med:>10}"
        )

    hr("BARRIDO 2 — ROBUSTEZ AL ERROR DE ESTIMACION DEL EDGE")
    print("  Cuanto puede estar equivocado tu backtest antes de que se derrumbe.")
    print(f"  Breakeven de este RR: {breakeven_winrate(strat):.1%}\n")
    print(f"  {'win rate':>9} | {'P(pasar)':>9} | {'daily DD':>9} | {'max DD':>8}")
    print("  " + "-" * 46)
    base = strat.win_rate
    for wr, res in sweep_winrate(
        rules, strat, [base - 0.10, base - 0.05, base - 0.02, base, base + 0.05], guard, fast
    ):
        tag = "  <-- tu estimacion" if abs(wr - base) < 1e-9 else ""
        print(
            f"  {wr:>8.1%} | {res.pass_rate:>8.1%} | {res.rate('fail_daily_dd'):>8.1%} | "
            f"{res.rate('fail_max_dd'):>7.1%}{tag}"
        )

    hr("BARRIDO 3 — VALOR DEL STOP DIARIO PROPIO")
    print("  Convierte la barrera diaria de la firma en 'perdiste el dia',")
    print("  no 'perdiste la cuenta'.\n")
    print(f"  {'stop propio':>12} | {'P(pasar)':>9} | {'daily DD':>9} | {'max DD':>8}")
    print("  " + "-" * 48)
    for ds in [None, 0.03, 0.02, 0.015, 0.01]:
        g = Guard(
            daily_stop=ds,
            scale_down_below=guard.scale_down_below,
            scale_factor=guard.scale_factor,
        )
        res = simulate(rules, strat, g, fast)
        label = f"-{ds:.1%}" if ds else "ninguno"
        print(
            f"  {label:>12} | {res.pass_rate:>8.1%} | {res.rate('fail_daily_dd'):>8.1%} | "
            f"{res.rate('fail_max_dd'):>7.1%}"
        )


def print_plan(rules, strat, guard):
    """Plan operativo derivado del rule set — numeros, no criterio."""
    initial = 100_000.0
    hr("PLAN OPERATIVO (por cada 100k de cuenta)")
    risk_abs = strat.risk_per_trade * initial
    stop_abs = (guard.daily_stop or rules.daily_dd / 2) * initial
    max_losses = int(stop_abs // risk_abs)

    print(f"  Riesgo por trade        : ${risk_abs:,.0f}  ({strat.risk_per_trade:.2%})")
    print(f"  Stop diario propio      : ${stop_abs:,.0f}  ({stop_abs/initial:.2%})")
    print(f"  = perdidas seguidas     : {max_losses} trades y se cierra el dia")
    print(f"  Limite de la firma      : ${rules.daily_dd*initial:,.0f} ({rules.daily_dd:.1%})")
    print(f"  Margen de seguridad     : {rules.daily_dd*initial/stop_abs:.1f}x")
    print(f"  Max trades por dia      : {strat.trades_per_day}")

    # Restriccion aritmetica, no probabilistica: si la exposicion maxima
    # posible en un dia es menor que el limite diario, ese limite no puede
    # tocarse ni en el peor camino imaginable.
    exposure = strat.trades_per_day * strat.risk_per_trade
    print()
    print(f"  Exposicion maxima/dia   : {exposure:.2%}  ({strat.trades_per_day} x {strat.risk_per_trade:.2%})")
    if exposure < rules.daily_dd:
        print(f"  -> La barrera diaria de la firma ({rules.daily_dd:.1%}) es INALCANZABLE.")
        print("     No es que sea improbable: es aritmeticamente imposible.")
    else:
        margen = rules.daily_dd / strat.risk_per_trade
        print(f"  -> ALERTA: la barrera diaria SI es alcanzable ({margen:.0f} perdidas seguidas).")
        print(f"     Bajar a {rules.daily_dd/strat.trades_per_day:.3%} por trade la vuelve imposible.")
    if rules.consistency_cap:
        max_day = rules.consistency_cap * rules.profit_target * initial
        print(f"  Techo de ganancia diaria: ${max_day:,.0f} (regla de consistencia)")
        print(f"  = RR maximo por dia     : {max_day/risk_abs:.1f}R acumulado")
    print()
    print("  Reglas que van en codigo, no en la cabeza:")
    print("   1. Alcanzado el stop diario, se cierra la plataforma. Sin excepciones.")
    print("   2. Alcanzado el maximo de trades, se cierra. Aunque haya setup.")
    print("   3. El tamano se calcula solo. No se escribe a mano nunca.")
    print("   4. Despues de un dia de stop, el dia siguiente va a riesgo mitad.")
    print("   5. Nada de esto se puede anular durante la sesion.")


def main():
    ap = argparse.ArgumentParser(description="Simulador Monte Carlo de cuentas de fondeo")
    ap.add_argument("--rules", default="eval_1step_estricta", choices=list(TEMPLATES))
    ap.add_argument("--wr", type=float, default=0.55, help="win rate estimado")
    ap.add_argument("--rr", type=float, default=1.5, help="reward:risk")
    ap.add_argument("--risk", type=float, default=0.005, help="riesgo por trade")
    ap.add_argument("--trades", type=int, default=5, help="trades por dia")
    ap.add_argument("--daily-stop", type=float, default=0.02, help="stop diario propio")
    ap.add_argument("--paths", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--plan", action="store_true", help="imprimir solo el plan operativo")
    ap.add_argument("--no-sweeps", action="store_true")
    args = ap.parse_args()

    rules = TEMPLATES[args.rules]
    strat = StrategyParams(
        win_rate=args.wr, rr=args.rr, risk_per_trade=args.risk, trades_per_day=args.trades
    )
    guard = Guard(daily_stop=args.daily_stop, scale_down_below=0.03, scale_factor=0.5)
    cfg = SimConfig(n_paths=args.paths, seed=args.seed)

    if args.plan:
        print_plan(rules, strat, guard)
        return

    run_base(rules, strat, guard, cfg)
    if not args.no_sweeps:
        run_sweeps(rules, strat, guard, cfg)
    print_plan(rules, strat, guard)

    hr("ADVERTENCIA")
    print("  Estos numeros asumen que el win rate y el RR de entrada son REALES.")
    print("  Un backtest sobreajustado los infla y el simulador te devuelve")
    print("  confianza infundada. El Barrido 2 esta para medir exactamente eso:")
    print("  mira cuanto cae P(pasar) con 5 puntos menos de win rate.")
    print()


if __name__ == "__main__":
    main()
