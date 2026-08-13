"""Tests del detector de eventos. Sin red, SQLite en memoria.

Cubre los tres lugares donde un bug corrompería la selección de candidatos:
  1. la ventana de referencia mira el FUTURO (look-ahead)
  2. mediana vs promedio (un pico previo esconde los siguientes)
  3. el filtro de operabilidad en dólares
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detect_events import compute  # noqa: E402

_BARS = """
CREATE TABLE bars_daily (
    ticker TEXT NOT NULL, d TEXT NOT NULL,
    o REAL, h REAL, l REAL, c REAL, v REAL, vw REAL, n INTEGER,
    PRIMARY KEY (ticker, d)
);
"""


def make_db(bars: list[tuple]) -> sqlite3.Connection:
    """bars: (ticker, dia_idx, open, high, low, close, volume)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(_BARS)
    base = date(2025, 1, 6)  # un lunes
    conn.executemany(
        "INSERT INTO bars_daily (ticker,d,o,h,l,c,v) VALUES (?,?,?,?,?,?,?)",
        [(t, (base + timedelta(days=i)).isoformat(), o, h, l, c, v)
         for (t, i, o, h, l, c, v) in bars],
    )
    conn.commit()
    return conn


def flat(ticker: str, n: int, *, vol: float, price: float = 10.0) -> list[tuple]:
    """n días planos: la línea de base contra la que se mide el pico."""
    return [(ticker, i, price, price, price, price, vol) for i in range(n)]


def run(conn, **kw) -> list[dict]:
    defaults = dict(min_rvol=3.0, min_dollar_vol=250_000, min_price=0.30, max_price=50.0)
    defaults.update(kw)
    compute(conn, **defaults)
    cur = conn.execute("SELECT * FROM events")
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur]


class TestPointInTime:
    def test_el_pico_no_entra_en_su_propia_referencia(self):
        """Si el día del pico entrara en su mediana, se auto-diluiría."""
        bars = flat("AAA", 25, vol=10_000)
        bars.append(("AAA", 25, 10.0, 12.0, 10.0, 12.0, 1_000_000))
        ev = run(make_db(bars))
        assert len(ev) == 1
        # mediana de los 20 previos = 10.000 exactos, no un valor contaminado
        assert ev[0]["med_volume"] == pytest.approx(10_000)
        assert ev[0]["rvol"] == pytest.approx(100.0)

    def test_no_mira_dias_posteriores(self):
        """Un volumen enorme DESPUÉS no debe alterar el evento anterior."""
        bars = flat("AAA", 25, vol=10_000)
        bars.append(("AAA", 25, 10.0, 12.0, 10.0, 12.0, 100_000))   # evento
        bars += [("AAA", 26 + k, 12.0, 12.0, 12.0, 12.0, 50_000_000) for k in range(5)]
        ev = {e["d"]: e for e in run(make_db(bars))}
        primero = min(ev)
        assert ev[primero]["med_volume"] == pytest.approx(10_000)
        assert ev[primero]["rvol"] == pytest.approx(10.0)

    def test_sin_historia_suficiente_no_hay_evento(self):
        bars = flat("AAA", 5, vol=10_000)
        bars.append(("AAA", 5, 10.0, 20.0, 10.0, 20.0, 5_000_000))
        assert run(make_db(bars)) == []


class TestMedianaVsPromedio:
    def test_un_pico_previo_no_esconde_el_siguiente(self):
        """Con promedio, el pico de 100x inflaría la base y taparía el segundo."""
        bars = flat("AAA", 21, vol=10_000)
        bars.append(("AAA", 21, 10.0, 10.0, 10.0, 10.0, 20_000_000))  # pico 1
        bars += [("AAA", 22 + k, 10.0, 10.0, 10.0, 10.0, 10_000) for k in range(3)]
        bars.append(("AAA", 25, 10.0, 12.0, 10.0, 12.0, 500_000))     # pico 2
        ev = run(make_db(bars))
        segundo = max(ev, key=lambda e: e["d"])
        # La mediana ignora el outlier previo: la base sigue siendo 10.000.
        assert segundo["med_volume"] == pytest.approx(10_000)
        assert segundo["rvol"] == pytest.approx(50.0)


class TestOperabilidad:
    def test_rvol_altisimo_pero_inoperable_se_descarta(self):
        """500 acciones normales -> 50.000 hoy: RVOL=100 y son $25.000."""
        bars = flat("PENNY", 25, vol=500, price=0.50)
        bars.append(("PENNY", 25, 0.50, 0.55, 0.50, 0.50, 50_000))
        assert run(make_db(bars)) == []

    def test_el_mismo_pico_con_volumen_en_dolares_si_pasa(self):
        bars = flat("AAA", 25, vol=50_000, price=10.0)
        bars.append(("AAA", 25, 10.0, 11.0, 10.0, 11.0, 5_000_000))
        ev = run(make_db(bars))
        assert len(ev) == 1
        assert ev[0]["dollar_volume"] == pytest.approx(55_000_000)

    def test_precio_fuera_de_rango_se_descarta(self):
        bars = flat("HIGH", 25, vol=100_000, price=500.0)
        bars.append(("HIGH", 25, 500.0, 550.0, 500.0, 550.0, 10_000_000))
        assert run(make_db(bars), max_price=50.0) == []


class TestDerivados:
    def test_gap_retorno_y_posicion_de_cierre(self):
        bars = flat("AAA", 25, vol=100_000, price=10.0)
        # cierre previo 10 -> abre 12 (gap +20%), rango 12-18, cierra 15
        bars.append(("AAA", 25, 12.0, 18.0, 12.0, 15.0, 5_000_000))
        e = run(make_db(bars))[0]
        assert e["gap_pct"] == pytest.approx(20.0)
        assert e["day_return_pct"] == pytest.approx(50.0)
        assert e["intraday_pct"] == pytest.approx(25.0)
        assert e["range_pct"] == pytest.approx(60.0)
        assert e["close_pos"] == pytest.approx(0.5)

    def test_cierre_en_maximos_y_en_minimos(self):
        bars = flat("UP", 25, vol=100_000, price=10.0)
        bars.append(("UP", 25, 10.0, 20.0, 10.0, 20.0, 5_000_000))
        assert run(make_db(bars))[0]["close_pos"] == pytest.approx(1.0)

        bars2 = flat("DOWN", 25, vol=100_000, price=10.0)
        bars2.append(("DOWN", 25, 20.0, 20.0, 10.0, 10.0, 5_000_000))
        assert run(make_db(bars2))[0]["close_pos"] == pytest.approx(0.0)

    def test_dia_sin_rango_no_rompe(self):
        """h == l: división por cero en close_pos si no está guardada."""
        bars = flat("AAA", 25, vol=100_000, price=10.0)
        bars.append(("AAA", 25, 10.0, 10.0, 10.0, 10.0, 5_000_000))
        e = run(make_db(bars))[0]
        assert e["close_pos"] is None
        assert e["range_pct"] == pytest.approx(0.0)


class TestAislamiento:
    def test_los_tickers_no_se_contaminan_entre_si(self):
        bars = flat("AAA", 25, vol=10_000) + flat("BBB", 25, vol=10_000_000)
        bars.append(("AAA", 25, 10.0, 11.0, 10.0, 11.0, 300_000))
        ev = run(make_db(bars))
        assert len(ev) == 1 and ev[0]["ticker"] == "AAA"
        assert ev[0]["med_volume"] == pytest.approx(10_000)


class TestFiltroDeMovimiento:
    def test_volumen_sin_movimiento_se_descarta(self):
        """El ruido que inflaba el dataset: RVOL alto, precio clavado."""
        bars = flat("QUIET", 25, vol=100_000, price=10.0)
        bars.append(("QUIET", 25, 10.0, 10.05, 9.95, 10.0, 5_000_000))
        assert run(make_db(bars), min_move_pct=10.0) == []

    def test_dia_que_sube_y_se_da_vuelta_SI_cuenta(self):
        """Sube 40%, se da vuelta, cierra plano. Es exactamente lo que buscamos:
        el retorno es ~0 pero el rango delata la parabólica."""
        bars = flat("REV", 25, vol=100_000, price=10.0)
        bars.append(("REV", 25, 10.0, 14.0, 9.8, 10.1, 5_000_000))
        ev = run(make_db(bars), min_move_pct=10.0)
        assert len(ev) == 1
        assert ev[0]["range_pct"] == pytest.approx(42.0)
        assert abs(ev[0]["day_return_pct"]) < 2

    def test_caida_fuerte_tambien_cuenta(self):
        bars = flat("DOWN", 25, vol=100_000, price=10.0)
        bars.append(("DOWN", 25, 9.9, 9.9, 7.0, 7.2, 5_000_000))
        assert len(run(make_db(bars), min_move_pct=10.0)) == 1


class TestVolumenEnDolares:
    def test_usa_vwap_no_cierre(self):
        """MCLE: 253.962 acciones, cierre $6,17, VWAP $1,33.
        Con cierre parece $1,57M operados; los reales son $0,34M."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(_BARS)
        base = date(2025, 1, 6)
        filas = [("MCLE", (base + timedelta(days=i)).isoformat(),
                  1.0, 1.0, 1.0, 1.0, 5_000, 1.0, None) for i in range(25)]
        filas.append(("MCLE", (base + timedelta(days=25)).isoformat(),
                      0.10, 6.35, 0.10, 6.17, 253_962, 1.33, None))
        conn.executemany(
            "INSERT INTO bars_daily (ticker,d,o,h,l,c,v,vw,n) VALUES (?,?,?,?,?,?,?,?,?)", filas)
        conn.commit()
        # Con el umbral de $1M queda AFUERA: sus dólares reales son 0,34M.
        compute(conn, min_rvol=3.0, min_dollar_vol=1_000_000,
                min_price=0.30, max_price=50.0, min_move_pct=10.0)
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0

    def test_fallback_a_cierre_sin_vwap(self):
        """0,5% de las barras vienen sin vw: no se pierden, se usa el cierre."""
        bars = flat("AAA", 25, vol=50_000, price=10.0)
        bars.append(("AAA", 25, 10.0, 11.0, 10.0, 11.0, 5_000_000))
        ev = run(make_db(bars))  # make_db no setea vw -> NULL
        assert len(ev) == 1
        assert ev[0]["dollar_volume"] == pytest.approx(55_000_000)
