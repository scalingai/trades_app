"""
Simulador Monte Carlo de cuentas de fondeo.

Simula miles de caminos de equity trade por trade contra un rule set concreto
y reporta con que frecuencia cada barrera es la que decide el resultado.

La pregunta que responde NO es "cuanto gano" sino:

    P(tocar +target antes de morir contra alguna barrera)

que es una funcion objetivo distinta a retorno o Sharpe, y da respuestas
distintas — sobre todo respecto al tamano optimo por trade.
"""
from dataclasses import dataclass, field

import numpy as np

from .ruleset import RuleSet
from .strategy import Guard, SimConfig, StrategyParams

# Motivos de finalizacion de un camino
PASS = "pass"
FAIL_DAILY = "fail_daily_dd"
FAIL_MAXDD = "fail_max_dd"
FAIL_TIMEOUT = "fail_timeout"


@dataclass
class SimResult:
    rules_name: str
    n_paths: int
    outcomes: dict[str, int] = field(default_factory=dict)
    days_to_pass: np.ndarray = field(default_factory=lambda: np.array([]))
    days_to_fail: np.ndarray = field(default_factory=lambda: np.array([]))
    worst_dd_seen: np.ndarray = field(default_factory=lambda: np.array([]))
    consistency_forced_extra: int = 0

    @property
    def pass_rate(self) -> float:
        return self.outcomes.get(PASS, 0) / self.n_paths

    def rate(self, key: str) -> float:
        return self.outcomes.get(key, 0) / self.n_paths

    def report(self) -> str:
        lines = [
            f"  P(pasar)              : {self.pass_rate:6.1%}",
            f"  P(morir por daily DD) : {self.rate(FAIL_DAILY):6.1%}",
            f"  P(morir por max DD)   : {self.rate(FAIL_MAXDD):6.1%}",
            f"  P(no llegar a tiempo) : {self.rate(FAIL_TIMEOUT):6.1%}",
        ]
        if len(self.days_to_pass):
            p = self.days_to_pass
            lines.append(
                f"  Dias hasta pasar      : mediana {np.median(p):.0f} | "
                f"p10 {np.percentile(p, 10):.0f} | p90 {np.percentile(p, 90):.0f}"
            )
        if len(self.days_to_fail):
            lines.append(
                f"  Dias hasta morir      : mediana {np.median(self.days_to_fail):.0f}"
            )
        if len(self.worst_dd_seen):
            lines.append(
                f"  Peor DD en caminos ok : mediana {np.median(self.worst_dd_seen):.2%} | "
                f"p90 {np.percentile(self.worst_dd_seen, 90):.2%}"
            )
        if self.consistency_forced_extra:
            pct = self.consistency_forced_extra / self.n_paths
            lines.append(f"  Regla consistencia forzo seguir operando: {pct:.1%} de caminos")
        return "\n".join(lines)


def simulate(
    rules: RuleSet,
    strat: StrategyParams,
    guard: Guard | None = None,
    cfg: SimConfig | None = None,
) -> SimResult:
    """Corre la simulacion completa y devuelve estadisticas agregadas."""
    guard = guard if guard is not None else Guard(daily_stop=None, scale_down_below=None)
    cfg = cfg or SimConfig()

    rng = np.random.default_rng(cfg.seed)
    initial = cfg.initial_balance
    max_days = rules.max_calendar_days or cfg.max_days_hard_cap

    trades_cap = strat.trades_per_day
    if guard.max_trades_per_day is not None:
        trades_cap = min(trades_cap, guard.max_trades_per_day)

    target_abs = rules.profit_target * initial
    daily_dd_abs = rules.daily_dd * initial
    own_stop_abs = guard.daily_stop * initial if guard.daily_stop else None

    outcomes: dict[str, int] = {PASS: 0, FAIL_DAILY: 0, FAIL_MAXDD: 0, FAIL_TIMEOUT: 0}
    days_pass: list[int] = []
    days_fail: list[int] = []
    worst_dds: list[float] = []
    forced_extra = 0

    for _ in range(cfg.n_paths):
        equity = initial
        hwm = initial
        trading_days = 0
        best_day_profit = 0.0
        worst_dd = 0.0
        outcome = FAIL_TIMEOUT
        end_day = max_days
        hit_consistency_wall = False

        for day in range(1, max_days + 1):
            day_start = equity
            r_draws = strat.draw(rng, trades_cap)

            for r in r_draws:
                floor = rules.floor(initial, hwm)
                buffer_frac = (equity - floor) / initial

                risk = strat.risk_per_trade
                if guard.scale_down_below is not None and buffer_frac < guard.scale_down_below:
                    risk *= guard.scale_factor

                equity += float(r) * risk * initial

                if equity > hwm:
                    hwm = equity
                worst_dd = max(worst_dd, (hwm - equity) / initial)

                # Barrera dura de la firma: drawdown total
                if equity <= rules.floor(initial, hwm):
                    outcome, end_day = FAIL_MAXDD, day
                    break
                # Barrera dura de la firma: perdida diaria
                if equity <= day_start - daily_dd_abs:
                    outcome, end_day = FAIL_DAILY, day
                    break
                # Barrera blanda propia: se corta el dia, la cuenta sigue viva
                if own_stop_abs is not None and equity <= day_start - own_stop_abs:
                    break

            trading_days += 1

            if outcome in (FAIL_MAXDD, FAIL_DAILY):
                break

            day_profit = equity - day_start
            best_day_profit = max(best_day_profit, day_profit)

            # Objetivo efectivo: la regla de consistencia lo empuja hacia arriba.
            # Si el mejor dia representa mas del cap del profit total, hay que
            # seguir operando para diluirlo — no alcanza con tocar el target.
            needed = target_abs
            if rules.consistency_cap:
                needed = max(needed, best_day_profit / rules.consistency_cap)
                if needed > target_abs:
                    hit_consistency_wall = True

            if equity - initial >= needed and trading_days >= rules.min_trading_days:
                outcome, end_day = PASS, day
                break

        outcomes[outcome] += 1
        if outcome == PASS:
            days_pass.append(end_day)
            worst_dds.append(worst_dd)
            if hit_consistency_wall:
                forced_extra += 1
        elif outcome in (FAIL_DAILY, FAIL_MAXDD):
            days_fail.append(end_day)

    return SimResult(
        rules_name=rules.name,
        n_paths=cfg.n_paths,
        outcomes=outcomes,
        days_to_pass=np.array(days_pass),
        days_to_fail=np.array(days_fail),
        worst_dd_seen=np.array(worst_dds),
        consistency_forced_extra=forced_extra,
    )


# ---------------------------------------------------------------------------
# Barridos de sensibilidad
# ---------------------------------------------------------------------------

def sweep_risk(
    rules: RuleSet,
    strat: StrategyParams,
    risks: list[float],
    guard: Guard | None = None,
    cfg: SimConfig | None = None,
) -> list[tuple[float, SimResult]]:
    """P(pasar) en funcion del riesgo por trade. Busca el tamano optimo."""
    out = []
    for r in risks:
        s = StrategyParams(
            win_rate=strat.win_rate,
            rr=strat.rr,
            risk_per_trade=r,
            trades_per_day=strat.trades_per_day,
            r_multiples=strat.r_multiples,
        )
        out.append((r, simulate(rules, s, guard, cfg)))
    return out


def sweep_winrate(
    rules: RuleSet,
    strat: StrategyParams,
    win_rates: list[float],
    guard: Guard | None = None,
    cfg: SimConfig | None = None,
) -> list[tuple[float, SimResult]]:
    """
    P(pasar) en funcion del win rate real.

    Este es el barrido mas importante del simulador: mide cuanto puede estar
    equivocado tu backtest antes de que la probabilidad de pasar se derrumbe.
    """
    out = []
    for wr in win_rates:
        s = StrategyParams(
            win_rate=wr,
            rr=strat.rr,
            risk_per_trade=strat.risk_per_trade,
            trades_per_day=strat.trades_per_day,
        )
        out.append((wr, simulate(rules, s, guard, cfg)))
    return out


def breakeven_winrate(strat: StrategyParams) -> float:
    """Win rate al que el edge se anula, dado el RR."""
    return 1.0 / (1.0 + strat.rr)
