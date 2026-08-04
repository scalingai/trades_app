"""
Parametros de la estrategia y de los limites auto-impuestos.

La estrategia se describe de dos formas posibles:
  1. Binaria    : win_rate + rr (aproximacion, util para explorar)
  2. Empirica   : array de R-multiplos observados (mucho mejor, requiere datos)

Los limites auto-impuestos (Guard) son la pieza que responde al problema
emocional: son mas estrictos que los de la firma y se aplican en codigo.
"""
from dataclasses import dataclass, field

import numpy as np


@dataclass
class StrategyParams:
    """Distribucion de resultados por trade, en multiplos de R."""

    win_rate: float = 0.55
    rr: float = 1.5                       # reward:risk del ganador
    risk_per_trade: float = 0.005         # 0.005 = 0.5% del balance INICIAL
    trades_per_day: int = 5

    # Si se provee, reemplaza a win_rate/rr: muestreo bootstrap de datos reales
    r_multiples: np.ndarray | None = None

    def edge_per_trade(self) -> float:
        """EV por trade como fraccion del balance inicial."""
        return self.risk_per_trade * self.expected_r()

    def expected_r(self) -> float:
        if self.r_multiples is not None:
            return float(np.mean(self.r_multiples))
        return self.win_rate * self.rr - (1.0 - self.win_rate)

    def std_r(self) -> float:
        if self.r_multiples is not None:
            return float(np.std(self.r_multiples))
        ex2 = self.win_rate * self.rr**2 + (1.0 - self.win_rate)
        return float(np.sqrt(ex2 - self.expected_r() ** 2))

    def draw(self, rng: np.random.Generator, size: int) -> np.ndarray:
        """Muestrea R-multiplos."""
        if self.r_multiples is not None:
            idx = rng.integers(0, len(self.r_multiples), size=size)
            return self.r_multiples[idx]
        wins = rng.random(size) < self.win_rate
        return np.where(wins, self.rr, -1.0)


@dataclass
class Guard:
    """
    Limites auto-impuestos, mas estrictos que los de la firma.

    El punto no es ser conservador por gusto: es convertir la barrera diaria
    de la firma (absorbente, mata la cuenta) en un stop propio (reflectante,
    solo perdes el dia). Se aplica en codigo, no por criterio.
    """

    # Stop diario propio, como fraccion del balance inicial. None = sin stop propio
    daily_stop: float | None = 0.02

    # Cortar el dia despues de N trades pase lo que pase
    max_trades_per_day: int | None = None

    # Si el colchon restante hasta el piso cae por debajo de este valor,
    # el riesgo por trade se multiplica por scale_factor
    scale_down_below: float | None = 0.03
    scale_factor: float = 0.5

    def describe(self) -> str:
        ds = f"-{self.daily_stop:.1%}" if self.daily_stop else "ninguno"
        sd = (
            f"riesgo x{self.scale_factor} si colchon < {self.scale_down_below:.1%}"
            if self.scale_down_below
            else "sin escalado"
        )
        return f"stop diario propio {ds} | {sd}"


@dataclass
class SimConfig:
    n_paths: int = 20_000
    initial_balance: float = 100_000.0
    seed: int = 7
    max_days_hard_cap: int = 250   # corta simulaciones eternas
