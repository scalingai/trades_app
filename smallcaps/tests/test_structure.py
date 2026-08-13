"""Tests de la lógica derivada. Sin red: todos los hechos son sintéticos.

Cubre los tres lugares donde un bug silencioso corrompería el dataset entero:
  1. resolución point-in-time (look-ahead)
  2. ajuste por reverse split (invierte el signo de la dilución)
  3. cálculo de burn/runway
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edgar.facts import Fact, Series  # noqa: E402
from edgar.structure import (  # noqa: E402
    _drop_spike_outliers,
    _monthly_burn,
    _pct_change_over,
    _split_adjusted,
)


def f(end: str, val: float, filed: str, form: str = "10-Q", start: str | None = None) -> Fact:
    return Fact(
        end=date.fromisoformat(end),
        val=val,
        form=form,
        filed=date.fromisoformat(filed),
        accn="x",
        unit="shares",
        start=date.fromisoformat(start) if start else None,
    )


# --------------------------------------------------------------------------
# 1. Point-in-time
# --------------------------------------------------------------------------

class TestPointInTime:
    def test_ignora_hechos_no_publicados(self):
        """El caso que arruina backtests: el dato existe pero aún no era público."""
        s = Series("dei:Shares", [
            f("2026-03-31", 1_000_000, filed="2026-04-10"),
            f("2026-06-30", 5_000_000, filed="2026-07-10"),
        ])
        # El 2026-05-01 el mercado sabía solo el primero, aunque el segundo
        # ya "corresponde" a un período que empezó.
        got = s.asof(date(2026, 5, 1))
        assert got is not None and got.val == 1_000_000

    def test_sin_hechos_publicados_devuelve_none(self):
        s = Series("dei:Shares", [f("2026-03-31", 1_000_000, filed="2026-04-10")])
        assert s.asof(date(2026, 1, 1)) is None

    def test_restatement_gana_el_filed_mas_reciente(self):
        s = Series("dei:Shares", [
            f("2026-03-31", 1_000_000, filed="2026-04-10"),
            f("2026-03-31", 1_200_000, filed="2026-05-20", form="10-Q/A"),
        ])
        got = s.asof(date(2026, 6, 1))
        assert got is not None and got.val == 1_200_000

    def test_el_filed_manda_sobre_el_end(self):
        """Un filing tardío de un período viejo no debe pisar uno más nuevo."""
        s = Series("dei:Shares", [
            f("2026-06-30", 5_000_000, filed="2026-07-10"),
            f("2026-03-31", 1_000_000, filed="2026-08-01", form="10-Q/A"),
        ])
        got = s.asof(date(2026, 8, 15))
        # Gana el de mayor `end`, no el de mayor `filed`.
        assert got is not None and got.val == 5_000_000

    def test_history_deduplica_por_end(self):
        s = Series("dei:Shares", [
            f("2026-03-31", 1_000_000, filed="2026-04-10"),
            f("2026-03-31", 1_200_000, filed="2026-05-20"),
            f("2026-06-30", 5_000_000, filed="2026-07-10"),
        ])
        hist = s.history()
        assert [x.val for x in hist] == [1_200_000, 5_000_000]


# --------------------------------------------------------------------------
# 2. Reverse splits
# --------------------------------------------------------------------------

class TestSplitAdjust:
    def test_sin_split_no_toca_los_valores(self):
        hist = [
            f("2026-03-31", 1_000_000, filed="2026-04-10"),
            f("2026-06-30", 1_500_000, filed="2026-07-10"),
        ]
        adj, splits = _split_adjusted(hist)
        assert splits == []
        assert adj == [1_000_000, 1_500_000]

    def test_detecta_reverse_split_y_ajusta_hacia_atras(self):
        """1:10 — sin ajuste esto se leería como −90% de dilución."""
        hist = [
            f("2025-12-31", 50_000_000, filed="2026-01-10"),
            f("2026-03-31", 5_000_000, filed="2026-04-10"),
            f("2026-06-30", 7_500_000, filed="2026-07-10"),
        ]
        adj, splits = _split_adjusted(hist)
        assert len(splits) == 1
        assert splits[0].approx_ratio == pytest.approx(10.0)
        # El valor viejo queda expresado en acciones post-split.
        assert adj == pytest.approx([5_000_000, 5_000_000, 7_500_000])

    def test_dilucion_positiva_pese_al_split(self):
        """La patología real: reverse split seguido de dilución agresiva."""
        hist = [
            f("2025-06-30", 40_000_000, filed="2025-07-10"),
            f("2025-12-31", 2_000_000, filed="2026-01-10"),   # 1:20
            f("2026-06-30", 8_000_000, filed="2026-07-10"),   # +300% real
        ]
        adj, splits = _split_adjusted(hist)
        assert len(splits) == 1
        pct = _pct_change_over(hist, adj, date(2026, 8, 1), 365)
        assert pct is not None and pct == pytest.approx(300.0)

    def test_recompra_moderada_no_es_split(self):
        """−20% de share count es plausible sin split: no debe disparar."""
        hist = [
            f("2026-03-31", 1_000_000, filed="2026-04-10"),
            f("2026-06-30", 800_000, filed="2026-07-10"),
        ]
        _, splits = _split_adjusted(hist)
        assert splits == []

    def test_multiples_splits_encadenados(self):
        hist = [
            f("2024-12-31", 100_000_000, filed="2025-01-10"),
            f("2025-06-30", 5_000_000, filed="2025-07-10"),   # 1:20
            f("2025-12-31", 500_000, filed="2026-01-10"),     # 1:10
            f("2026-06-30", 2_000_000, filed="2026-07-10"),
        ]
        adj, splits = _split_adjusted(hist)
        assert len(splits) == 2
        assert adj == pytest.approx([500_000, 500_000, 500_000, 2_000_000])

    def test_serie_vacia(self):
        assert _split_adjusted([]) == ([], [])


# --------------------------------------------------------------------------
# 3. Ventanas de dilución
# --------------------------------------------------------------------------

class TestPctChange:
    def test_devuelve_none_sin_referencia_previa(self):
        hist = [f("2026-06-30", 1_000_000, filed="2026-07-10")]
        assert _pct_change_over(hist, [1_000_000], date(2026, 8, 1), 365) is None

    def test_ventana_muy_corta_sin_referencia(self):
        hist = [
            f("2026-05-31", 1_000_000, filed="2026-06-10"),
            f("2026-06-30", 2_000_000, filed="2026-07-10"),
        ]
        # A 3 meses no hay observación anterior a la ventana.
        assert _pct_change_over(hist, [1_000_000, 2_000_000], date(2026, 7, 15), 92) is None


# --------------------------------------------------------------------------
# 4. Burn y runway
# --------------------------------------------------------------------------

class TestBurn:
    def test_prefiere_trimestral_sobre_anual(self):
        hist = [
            f("2025-12-31", -12_000_000, filed="2026-02-01", form="10-K", start="2025-01-01"),
            f("2026-03-31", -900_000, filed="2026-05-01", start="2026-01-01"),
        ]
        burn, quality = _monthly_burn(hist)
        assert quality == "quarterly"
        assert burn == pytest.approx(900_000 / (89 / 30.44), rel=1e-3)

    def test_cae_a_anual_si_no_hay_trimestral(self):
        hist = [f("2025-12-31", -12_000_000, filed="2026-02-01", form="10-K", start="2025-01-01")]
        burn, quality = _monthly_burn(hist)
        assert quality == "annual"
        assert burn == pytest.approx(1_000_000, rel=0.02)

    def test_cash_flow_positivo_no_es_burn(self):
        hist = [f("2026-03-31", 500_000, filed="2026-05-01", start="2026-01-01")]
        burn, quality = _monthly_burn(hist)
        assert burn is None
        assert quality == "quarterly_positive_cf"

    def test_sin_datos(self):
        assert _monthly_burn([]) == (None, "missing")

    def test_ignora_duraciones_raras(self):
        """Un período de 6 meses no es ni trimestral ni anual: no se usa."""
        hist = [f("2026-06-30", -3_000_000, filed="2026-08-01", start="2026-01-01")]
        burn, quality = _monthly_burn(hist)
        assert burn is None and quality == "missing"


# --------------------------------------------------------------------------
# 5. Outliers de escala en el filing (caso KPTI)
# --------------------------------------------------------------------------

class TestSpikeOutliers:
    def test_descarta_pico_aislado(self):
        """KPTI reportó 17.050.876.000 acciones y al filing siguiente 18.343.968."""
        hist = [
            f("2025-08-06", 8_671_278, filed="2025-08-11"),
            f("2025-10-30", 17_050_876_000, filed="2025-11-03"),
            f("2026-02-05", 18_343_968, filed="2026-02-13"),
        ]
        clean, dropped = _drop_spike_outliers(hist)
        assert len(dropped) == 1
        assert dropped[0].val == 17_050_876_000
        assert [c.val for c in clean] == [8_671_278, 18_343_968]

    def test_no_genera_split_fantasma(self):
        """Sin el filtro, el retorno al valor correcto se lee como 1:929."""
        hist = [
            f("2025-08-06", 8_671_278, filed="2025-08-11"),
            f("2025-10-30", 17_050_876_000, filed="2025-11-03"),
            f("2026-02-05", 18_343_968, filed="2026-02-13"),
        ]
        _, splits_sucio = _split_adjusted(hist)
        assert len(splits_sucio) == 1 and splits_sucio[0].approx_ratio > 900

        clean, _ = _drop_spike_outliers(hist)
        _, splits_limpio = _split_adjusted(clean)
        assert splits_limpio == []

    def test_dilucion_monotona_extrema_se_preserva(self):
        """FOXO: 45M -> 526M -> 3.732M acciones. Brutal pero REAL, no es pico."""
        hist = [
            f("2025-08-18", 45_767_410, filed="2025-08-19"),
            f("2025-11-07", 526_520_303, filed="2025-11-10"),
            f("2026-04-10", 3_732_660_151, filed="2026-04-15"),
        ]
        clean, dropped = _drop_spike_outliers(hist)
        assert dropped == []
        assert len(clean) == 3

    def test_serie_corta_no_se_toca(self):
        hist = [f("2026-03-31", 1_000_000, filed="2026-04-10"),
                f("2026-06-30", 2_000_000, filed="2026-07-10")]
        clean, dropped = _drop_spike_outliers(hist)
        assert dropped == [] and len(clean) == 2
