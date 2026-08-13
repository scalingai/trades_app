"""Estructura de papel derivada — el feature vector de Fase 0.

Todo lo de acá es **determinístico** (Capa 0): no hay LLM, no hay juicio.
Cada campo sale de un filing con fecha de publicación conocida, y todo se
resuelve point-in-time contra una `as_of`.

Lo que este módulo NO hace a propósito: puntuar, rankear o decidir. Emite
hechos. El scoring viene después, y sobre el dataset acumulado — no sobre
umbrales inventados hoy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from .facts import CompanyFacts, Fact
from .filings import Filing, filter_filings, load_filings
from .tickers import cik_for, ticker_for

# Un drop de share count de esta magnitud entre dos reportes consecutivos es
# un reverse split, no un buyback: ninguna micro cap recompra un tercio de sus
# acciones en un trimestre — no tienen la caja (ese es justamente su problema).
_SPLIT_RATIO_MIN = 1.5

_DAYS_PER_MONTH = 30.44


@dataclass(frozen=True, slots=True)
class ReverseSplit:
    """Reverse split inferido del salto en share count. Es una *inferencia*."""

    detected_between: tuple[date, date]
    approx_ratio: float
    shares_before: float
    shares_after: float
    known_at: date  # cuándo se hizo público el filing que lo reveló


@dataclass
class PaperStructure:
    """Snapshot point-in-time de la estructura de papel de un ticker."""

    ticker: str
    cik: int
    entity_name: str
    as_of: date

    # --- share count ---
    shares_outstanding: float | None = None
    shares_as_of: date | None = None
    shares_known_at: date | None = None
    shares_stale_days: int | None = None

    # --- dilución (ajustada por reverse splits) ---
    dilution_3m_pct: float | None = None
    dilution_12m_pct: float | None = None
    dilution_since_inception_pct: float | None = None
    reverse_splits: list[ReverseSplit] = field(default_factory=list)
    reverse_splits_12m: int = 0

    # --- caja y runway ---
    cash_usd: float | None = None
    cash_as_of: date | None = None
    monthly_burn_usd: float | None = None
    runway_months: float | None = None

    # --- cadencia de ofertas ---
    pricing_filings_12m: int = 0
    days_since_last_pricing: int | None = None
    last_pricing_form: str | None = None
    shelf_filings_12m: int = 0
    last_shelf_filed: date | None = None
    last_effect_filed: date | None = None
    shelf_effective: bool = False
    dilutive_8k_12m: int = 0

    # --- honestidad ---
    data_quality: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reverse_splits"] = [
            {
                "detected_between": [s.detected_between[0].isoformat(), s.detected_between[1].isoformat()],
                "approx_ratio": round(s.approx_ratio, 3),
                "shares_before": s.shares_before,
                "shares_after": s.shares_after,
                "known_at": s.known_at.isoformat(),
            }
            for s in self.reverse_splits
        ]
        for key in (
            "as_of", "shares_as_of", "shares_known_at", "cash_as_of",
            "last_shelf_filed", "last_effect_filed",
        ):
            if d.get(key) is not None:
                d[key] = d[key].isoformat()
        return d


def _split_adjusted(history: list[Fact]) -> tuple[list[float], list[ReverseSplit]]:
    """Expresa el histórico de share count en términos de las acciones de HOY.

    Sin esto, un reverse split se lee como dilución negativa y el feature
    central del sistema queda invertido justo en las empresas que más importan.
    """
    n = len(history)
    if n == 0:
        return [], []

    adjusted = [0.0] * n
    splits: list[ReverseSplit] = []
    divisor = 1.0
    adjusted[n - 1] = history[n - 1].val

    for i in range(n - 2, -1, -1):
        nxt = history[i + 1].val
        ratio = history[i].val / nxt if nxt else 1.0
        if ratio > _SPLIT_RATIO_MIN:
            divisor *= ratio
            splits.append(
                ReverseSplit(
                    detected_between=(history[i].end, history[i + 1].end),
                    approx_ratio=ratio,
                    shares_before=history[i].val,
                    shares_after=nxt,
                    known_at=history[i + 1].filed,
                )
            )
        adjusted[i] = history[i].val / divisor

    splits.reverse()
    return adjusted, splits


def _pct_change_over(
    history: list[Fact], adjusted: list[float], as_of: date, days: int
) -> float | None:
    """Variación % del share count ajustado en la ventana previa a `as_of`."""
    if len(history) < 2:
        return None
    cutoff = as_of - timedelta(days=days)
    # Referencia: la última observación cuyo `end` cae antes de la ventana.
    ref_idx = None
    for i, f in enumerate(history):
        if f.end <= cutoff:
            ref_idx = i
    if ref_idx is None or ref_idx == len(history) - 1:
        return None
    base = adjusted[ref_idx]
    if base <= 0:
        return None
    return (adjusted[-1] / base - 1.0) * 100.0


def _monthly_burn(opcf_history: list[Fact]) -> tuple[float | None, str]:
    """Burn mensual desde el cash flow operativo más reciente.

    Devuelve (burn_positivo_si_quema, calidad). Preferimos un período
    trimestral: el anual de una micro cap promedia trimestres muy distintos.
    """
    if not opcf_history:
        return None, "missing"

    quarterly = [f for f in opcf_history if f.duration_days and 60 <= f.duration_days <= 120]
    annual = [f for f in opcf_history if f.duration_days and 300 <= f.duration_days <= 400]

    chosen, quality = (quarterly[-1], "quarterly") if quarterly else (
        (annual[-1], "annual") if annual else (None, "missing")
    )
    if chosen is None or not chosen.duration_days:
        return None, "missing"

    months = chosen.duration_days / _DAYS_PER_MONTH
    # OPCF negativo = quema. Lo devolvemos como número positivo.
    burn = -chosen.val / months
    if burn <= 0:
        return None, f"{quality}_positive_cf"
    return burn, quality


def build(
    ticker: str,
    *,
    as_of: date | None = None,
    cache_hours: float = 12.0,
) -> PaperStructure:
    """Arma el snapshot point-in-time de estructura de papel para un ticker."""
    as_of = as_of or date.today()
    cik = cik_for(ticker)

    cf = CompanyFacts.load(cik, cache_hours=cache_hours)
    all_filings = load_filings(cik, cache_hours=cache_hours)
    # PIT: nada que se haya publicado después de `as_of` puede entrar.
    filings: list[Filing] = [f for f in all_filings if f.filed <= as_of]

    ps = PaperStructure(
        ticker=ticker.upper(),
        cik=cik,
        entity_name=cf.entity_name or (ticker_for(cik) or ""),
        as_of=as_of,
    )

    # --- share count + dilución ---
    shares_series = cf.shares()
    current = shares_series.asof(as_of)
    known_history = [f for f in shares_series.history() if f.filed <= as_of]

    if current is None:
        ps.data_quality["shares"] = "missing"
        ps.warnings.append(
            "sin dei:EntityCommonStockSharesOutstanding publicado a la fecha — "
            "no se puede derivar dilución"
        )
    else:
        ps.shares_outstanding = current.val
        ps.shares_as_of = current.end
        ps.shares_known_at = current.filed
        ps.shares_stale_days = (as_of - current.filed).days
        ps.data_quality["shares"] = "xbrl_cover_page"
        # Una small cap puede diluir 40% en las semanas entre reportes: el
        # dato es correcto pero viejo, y eso hay que decirlo, no esconderlo.
        if ps.shares_stale_days > 120:
            ps.warnings.append(
                f"share count con {ps.shares_stale_days} días de antigüedad "
                f"(último filing {current.form} del {current.filed})"
            )

        adjusted, splits = _split_adjusted(known_history)
        ps.reverse_splits = splits
        # Los forward splits NO se ajustan, a propósito: un salto de 4x hacia
        # arriba es indistinguible de una dilución del 300% mirando solo el
        # share count, y en micro caps la dilución del 300% es el caso normal.
        # Auto-detectarlos generaría falsos positivos justo en la población
        # objetivo. Se marca la ambigüedad y se sigue.
        for i in range(1, len(adjusted)):
            if adjusted[i - 1] > 0 and adjusted[i] / adjusted[i - 1] >= 3.0:
                ps.warnings.append(
                    f"salto de share count {adjusted[i - 1]:,.0f} → {adjusted[i]:,.0f} "
                    f"({known_history[i].end}): dilución fuerte o forward split, "
                    f"ambiguo desde XBRL. `dilution_since_inception_pct` no es "
                    f"confiable si hubo forward split."
                )
        ps.reverse_splits_12m = sum(
            1 for s in splits if (as_of - s.known_at).days <= 365
        )
        ps.dilution_3m_pct = _pct_change_over(known_history, adjusted, as_of, 92)
        ps.dilution_12m_pct = _pct_change_over(known_history, adjusted, as_of, 365)
        if len(adjusted) >= 2 and adjusted[0] > 0:
            ps.dilution_since_inception_pct = (adjusted[-1] / adjusted[0] - 1.0) * 100.0

    # --- caja y runway ---
    cash = cf.cash().asof(as_of)
    if cash is not None:
        ps.cash_usd = cash.val
        ps.cash_as_of = cash.end
        ps.data_quality["cash"] = "xbrl"
    else:
        ps.data_quality["cash"] = "missing"

    opcf_known = [f for f in cf.operating_cash_flow().history() if f.filed <= as_of]
    burn, burn_quality = _monthly_burn(opcf_known)
    ps.monthly_burn_usd = burn
    ps.data_quality["burn"] = burn_quality
    if burn and ps.cash_usd is not None:
        ps.runway_months = ps.cash_usd / burn
        if ps.runway_months < 6:
            ps.warnings.append(
                f"runway ~{ps.runway_months:.1f} meses — presión estructural a levantar capital"
            )

    # --- cadencia de ofertas ---
    year_ago = as_of - timedelta(days=365)
    pricing = filter_filings(filings, kinds={"pricing"}, since=year_ago)
    ps.pricing_filings_12m = len(pricing)

    all_pricing = filter_filings(filings, kinds={"pricing"})
    if all_pricing:
        last = all_pricing[-1]
        ps.days_since_last_pricing = (as_of - last.filed).days
        ps.last_pricing_form = last.form

    ps.shelf_filings_12m = len(filter_filings(filings, kinds={"shelf"}, since=year_ago))
    shelves = filter_filings(filings, kinds={"shelf"})
    if shelves:
        ps.last_shelf_filed = shelves[-1].filed

    effects = filter_filings(filings, kinds={"effect"})
    if effects:
        ps.last_effect_filed = effects[-1].filed
    # Un shelf sin EFFECT posterior todavía no se puede disparar. Es la
    # diferencia entre munición cargada y munición en la caja.
    ps.shelf_effective = bool(
        ps.last_shelf_filed
        and ps.last_effect_filed
        and ps.last_effect_filed >= ps.last_shelf_filed
    )

    ps.dilutive_8k_12m = sum(
        1
        for f in filings
        if f.kind == "current_report" and f.is_dilution_relevant and f.filed >= year_ago
    )

    return ps
