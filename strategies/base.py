"""
Base classes for the strategy engine.
Strategy, Signal, and StrategyVariant definitions.
"""
from dataclasses import dataclass, field
from typing import Optional
from itertools import product


@dataclass
class Signal:
    """Output of a strategy evaluation."""
    strategy_name: str
    variant_id: str
    symbol: str
    direction: str          # "long", "short", "neutral"
    score: float            # 0-100
    confidence: float       # 0-100%
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    rr: Optional[float] = None
    factors_active: dict = field(default_factory=dict)
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "variant": self.variant_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "score": self.score,
            "confidence": self.confidence,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "rr": self.rr,
            "factors": self.factors_active,
            "details": self.details,
        }


class Strategy:
    """Base class for all trading strategies.

    Subclasses define:
    - name: strategy identifier
    - param_grid: dict of param_name -> [values] for generating variants
    - evaluate(snapshot, params) -> Signal
    """
    name: str = "base"
    param_grid: dict = {}

    def get_variants(self) -> list[dict]:
        """Generate all parameter combinations from the grid."""
        if not self.param_grid:
            return [{}]

        keys = list(self.param_grid.keys())
        values = list(self.param_grid.values())
        variants = []
        for combo in product(*values):
            variant = dict(zip(keys, combo))
            variants.append(variant)
        return variants

    def variant_id(self, params: dict) -> str:
        """Generate unique ID for a parameter variant."""
        parts = [f"{k}={v}" for k, v in sorted(params.items())]
        return f"{self.name}__{'_'.join(parts)}" if parts else self.name

    def evaluate(self, snapshot: dict, params: dict) -> Signal:
        """Evaluate market snapshot with given parameters. Override in subclass."""
        raise NotImplementedError

    def run_all_variants(self, snapshot: dict) -> list[Signal]:
        """Run all parameter variants against the snapshot."""
        signals = []
        for params in self.get_variants():
            try:
                signal = self.evaluate(snapshot, params)
                signals.append(signal)
            except Exception as e:
                signals.append(Signal(
                    strategy_name=self.name,
                    variant_id=self.variant_id(params),
                    symbol=snapshot.get("symbol", "?"),
                    direction="neutral",
                    score=0,
                    confidence=0,
                    details=f"Error: {str(e)}",
                ))
        return signals
