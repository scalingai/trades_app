"""
Reglas de una cuenta de fondeo, expresadas como restricciones simulables.

IMPORTANTE: los presets de abajo son PLANTILLAS GENERICAS con valores tipicos
de la industria. NO son las reglas verificadas de ninguna firma en particular,
y las firmas cambian sus reglas seguido. Antes de usar cualquiera para decidir
tamano de riesgo, copiar los numeros reales del contrato de tu firma.
"""
from dataclasses import dataclass


@dataclass
class RuleSet:
    """Restricciones de una fase de evaluacion o de una cuenta fondeada."""

    name: str

    # Barrera superior
    profit_target: float          # 0.10 = +10% sobre balance inicial

    # Barreras inferiores (fracciones del balance inicial)
    daily_dd: float               # 0.04 = perder 4% en un dia mata la cuenta
    max_dd: float                 # 0.06 = drawdown total maximo

    # El max drawdown sube con el equity (trailing) o queda fijo en el inicial
    trailing: bool = False
    # Si trailing: el piso deja de subir al llegar al balance inicial
    trailing_locks_at_initial: bool = True

    # Restricciones de forma
    min_trading_days: int = 0
    max_calendar_days: int | None = None   # None = sin limite de tiempo
    consistency_cap: float | None = None   # 0.30 = ningun dia > 30% del profit total

    def floor(self, initial: float, hwm: float) -> float:
        """Equity minimo permitido dado el high-water mark alcanzado."""
        if not self.trailing:
            return initial - initial * self.max_dd
        trailing_floor = hwm - initial * self.max_dd
        if self.trailing_locks_at_initial:
            return min(trailing_floor, initial)
        return trailing_floor

    def summary(self) -> str:
        dd_type = "trailing" if self.trailing else "estatico"
        cons = f"{self.consistency_cap:.0%}" if self.consistency_cap else "sin regla"
        days = self.max_calendar_days if self.max_calendar_days else "sin limite"
        return (
            f"{self.name}\n"
            f"  Target        : +{self.profit_target:.0%}\n"
            f"  Daily DD      : -{self.daily_dd:.0%}\n"
            f"  Max DD        : -{self.max_dd:.0%} ({dd_type})\n"
            f"  Dias minimos  : {self.min_trading_days}\n"
            f"  Dias maximos  : {days}\n"
            f"  Consistencia  : {cons}"
        )


# ---------------------------------------------------------------------------
# Plantillas genericas — VERIFICAR contra el contrato real antes de usar
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, RuleSet] = {
    "eval_2step_fase1": RuleSet(
        name="Evaluacion 2 pasos - Fase 1 (plantilla generica)",
        profit_target=0.10,
        daily_dd=0.05,
        max_dd=0.10,
        trailing=False,
        min_trading_days=4,
        max_calendar_days=None,
        consistency_cap=None,
    ),
    "eval_2step_fase2": RuleSet(
        name="Evaluacion 2 pasos - Fase 2 (plantilla generica)",
        profit_target=0.05,
        daily_dd=0.05,
        max_dd=0.10,
        trailing=False,
        min_trading_days=4,
        max_calendar_days=None,
        consistency_cap=None,
    ),
    "eval_1step_estricta": RuleSet(
        name="Evaluacion 1 paso estricta (plantilla generica)",
        profit_target=0.10,
        daily_dd=0.04,
        max_dd=0.06,
        trailing=True,
        trailing_locks_at_initial=True,
        min_trading_days=5,
        max_calendar_days=None,
        consistency_cap=0.30,
    ),
    "fondeada": RuleSet(
        name="Cuenta fondeada - primer payout (plantilla generica)",
        profit_target=0.08,
        daily_dd=0.05,
        max_dd=0.10,
        trailing=False,
        min_trading_days=10,
        max_calendar_days=None,
        consistency_cap=0.25,
    ),
}
