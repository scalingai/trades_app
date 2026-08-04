"""Simulador Monte Carlo de reglas de cuentas de fondeo."""

from .montecarlo import (
    FAIL_DAILY,
    FAIL_MAXDD,
    FAIL_TIMEOUT,
    PASS,
    SimResult,
    breakeven_winrate,
    simulate,
    sweep_risk,
    sweep_winrate,
)
from .ruleset import TEMPLATES, RuleSet
from .strategy import Guard, SimConfig, StrategyParams

__all__ = [
    "RuleSet",
    "TEMPLATES",
    "StrategyParams",
    "Guard",
    "SimConfig",
    "simulate",
    "sweep_risk",
    "sweep_winrate",
    "breakeven_winrate",
    "SimResult",
    "PASS",
    "FAIL_DAILY",
    "FAIL_MAXDD",
    "FAIL_TIMEOUT",
]
