#!/usr/bin/env python3
"""Corre las variantes de estrategia y GUARDA cada trade, etiquetado.

Hasta ahora cada script imprimía agregados y los trades se perdían. Eso hizo que
el bug intrabar sobreviviera varias rondas: sin las ejecuciones guardadas no hay
nada que auditar. Acá cada trade queda en `trades.sqlite` con su etiqueta de
estrategia, y el visor lo navega.

**Las variantes de salida son el punto de esta corrida.** Todo lo medido hasta
ahora sale al cierre o por stop. Faltaban las que se adaptan:

  · `trailing`  — el stop baja con el precio y nunca sube. Es la única forma
    conocida de cortar el perdedor sin cortar al ganador, y no estaba probada.
  · `nivel`     — cubrir en el mínimo del día o en el cierre previo, que son
    niveles que el mercado ya respetó.
  · `hora`      — cubrir a una hora fija, para tener la referencia.

Convención de siempre: si en el mismo minuto se tocan stop y objetivo, gana el
stop.

    python backtest.py                 # corre todo y guarda
    python backtest.py --resumen       # lee lo guardado
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config
from chavineta import clasificar_apertura
from dias import CIERRE_RTH, cargar, hora
from sesion import señales, señales_swing, stop_estructural

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE_PERIODO = "2025-08-17"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    estrategia TEXT NOT NULL,
    ticker TEXT NOT NULL,
    d      TEXT NOT NULL,
    hora_entrada REAL NOT NULL,
    hora_salida  REAL,
    precio_entrada REAL,
    precio_salida  REAL,
    stop_pct REAL,          -- distancia al stop, en % (define el tamaño)
    acciones REAL,
    pnl      REAL,          -- en dólares, ya neto de costos
    ret_pct  REAL,          -- retorno del trade sobre el precio de entrada
    mae_pct  REAL,          -- excursión adversa máxima
    mfe_pct  REAL,          -- excursión favorable máxima
    motivo   TEXT,
    periodo  TEXT,
    expansion REAL,
    liquidez  REAL,
    PRIMARY KEY (estrategia, ticker, d, hora_entrada)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_tr_est  ON trades(estrategia);
CREATE INDEX IF NOT EXISTS ix_tr_dia  ON trades(ticker, d);
"""


def ruta():
    return config.data_dir() / "trades.sqlite"


# ------------------------------------------------------------------ salidas

def salir(dia, i, p, stop_pct, *, salida, arrastre=50.0, hora_fija=16.0,
          nivel_pm_low=None):
    """Camina desde `i` y devuelve (precio de salida, hora, motivo, mae, mfe).

    `arrastre` es qué fracción de la ganancia máxima se cede antes de cubrir:
    con 50, el trailing cierra cuando el precio devuelve la mitad de lo que
    había ganado.
    """
    p_stop = p * (1 + stop_pct / 100.0)
    mejor = p          # el mínimo alcanzado: la ganancia máxima del short
    peor = p
    for b in dia.bars[i + 1:]:
        h = hora(b)
        if h > CIERRE_RTH:
            break
        alto, bajo, c = b[2], b[3], b[4]
        if alto:
            peor = max(peor, alto)
        # Stop duro primero: convención conservadora.
        if alto and alto >= p_stop:
            return p_stop, h, "stop", (peor / p - 1) * 100, (1 - mejor / p) * 100
        if bajo:
            mejor = min(mejor, bajo)

        if salida == "trailing" and mejor < p:
            # El stop sube (para un short, baja) con la ganancia y nunca vuelve.
            devuelto = p - (p - mejor) * (1 - arrastre / 100.0)
            if alto and alto >= devuelto and mejor < p * 0.98:
                return devuelto, h, "trailing", (peor / p - 1) * 100, (1 - mejor / p) * 100
        elif salida == "nivel" and nivel_pm_low and bajo and bajo <= nivel_pm_low:
            return nivel_pm_low, h, "nivel", (peor / p - 1) * 100, (1 - mejor / p) * 100
        elif salida == "hora" and h >= hora_fija:
            return c, h, "hora", (peor / p - 1) * 100, (1 - mejor / p) * 100

    c = dia.rth_close
    return c, CIERRE_RTH, "cierre", (peor / p - 1) * 100, (1 - mejor / p) * 100


# Las de SESIÓN llevan límite diario, que es lo que las separa de las de arriba.
# Medido: el límite es lo que convierte una base apenas break-even por trade en
# un sistema positivo por jornada. No es decoración, hace la mitad del trabajo.
SESIONES = [
    ("SESIÓN·swing·estructural", dict(modo="swing", stop_modo="estructural"), None),
    ("SESIÓN·swing·estructural·sin-chinas",
     dict(modo="swing", stop_modo="estructural"), "sin_chinas"),
    ("SESIÓN·swing·fijo15", dict(modo="swing", stop_modo="fijo"), None),
    ("SESIÓN·agotamiento·estructural",
     dict(modo="agotamiento", stop_modo="estructural"), None),
]

ESTRATEGIAS = [
    # (etiqueta, generador de señales, modo de stop, modo de salida)
    ("swing·estructural·cierre", "swing", "estructural", "cierre"),
    ("swing·estructural·trailing50", "swing", "estructural", "trailing"),
    ("swing·estructural·trailing33", "swing", "estructural", "trailing33"),
    ("swing·estructural·nivel", "swing", "estructural", "nivel"),
    ("swing·estructural·11:30", "swing", "estructural", "hora"),
    ("swing·fijo15·cierre", "swing", "fijo", "cierre"),
    ("agotamiento·estructural·cierre", "agotamiento", "estructural", "cierre"),
    ("agotamiento·estructural·trailing50", "agotamiento", "estructural", "trailing"),
]


def correr(*, riesgo_trade=16.67, costo_accion=0.04, min_liquidez=2.5e5,
           min_expansion=100.0, tope_stop=30.0, stop_fijo=15.0):
    import json as _json
    from sesion import jornada
    _f = config.data_dir() / "fichas_empresa.json"
    fichas = _json.loads(_f.read_text(encoding="utf-8")) if _f.exists() else {}

    conn = sqlite3.connect(ruta(), timeout=60)
    conn.executescript(_SCHEMA)
    conn.execute("DELETE FROM trades")
    filas = []
    n_dias = 0

    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3 or (dia.expansion_pct or 0) < min_expansion:
            continue
        if clasificar_apertura(dia) != "fade":
            continue
        n_dias += 1
        pm_low = min((b[3] for b in dia.pre if b[3]), default=None)
        cache = {}
        for etiqueta, gen, modo_stop, salida in ESTRATEGIAS:
            if gen not in cache:
                cache[gen] = (señales_swing(dia, min_liquidez=min_liquidez)
                              if gen == "swing"
                              else señales(dia, min_liquidez=min_liquidez))
            for i in cache[gen][:10]:
                p = dia.bars[i][4]
                if not p:
                    continue
                sp = (stop_estructural(dia, i, maximo=tope_stop)
                      if modo_stop == "estructural" else stop_fijo)
                if not sp:
                    continue
                arr = 33.0 if salida == "trailing33" else 50.0
                sal = "trailing" if salida.startswith("trailing") else salida
                q, hs, motivo, mae, mfe = salir(
                    dia, i, p, sp, salida=sal, arrastre=arr,
                    hora_fija=11.5, nivel_pm_low=pm_low)
                if not q:
                    continue
                acciones = riesgo_trade / (p * sp / 100.0)
                pnl = acciones * (p - q) - acciones * costo_accion
                filas.append((etiqueta, dia.ticker, dia.d, round(hora(dia.bars[i]), 5),
                              round(hs, 5), p, q, sp, acciones, pnl,
                              (p / q - 1) * 100, mae, mfe, motivo,
                              "P1" if dia.d < CORTE_PERIODO else "P2",
                              dia.expansion_pct, dia.liquidez_en(hora(dia.bars[i]))))
        # Las de sesión: se corre la jornada entera y se guardan sus trades.
        china = bool((fichas.get(dia.ticker) or {}).get("china"))
        for etiqueta, kw, cond in SESIONES:
            if cond == "sin_chinas" and china:
                continue
            j = jornada(dia, riesgo_dia=riesgo_trade * 3, riesgo_trade=riesgo_trade,
                        objetivo=0, stop_pct=stop_fijo, costo_accion=costo_accion,
                        max_trades=10, min_liquidez=min_liquidez,
                        colchon=1.0, tope_stop=tope_stop, **kw)
            if not j:
                continue
            for t in j["detalle"]:
                p = t["precio"]
                q = p * (1 - t["pnl"] / (t["acciones"] * p)) if t.get("acciones") else None
                filas.append((etiqueta, dia.ticker, dia.d, round(t["hora"], 5),
                              None, p, q, t["stop_pct"], t.get("acciones"),
                              t["pnl"], (p / q - 1) * 100 if q else None,
                              None, None, t["motivo"],
                              "P1" if dia.d < CORTE_PERIODO else "P2",
                              dia.expansion_pct, dia.liquidez_en(t["hora"])))

        if len(filas) >= 20000:
            conn.executemany(
                f"INSERT OR REPLACE INTO trades VALUES ({','.join('?'*17)})", filas)
            conn.commit()
            filas = []
    if filas:
        conn.executemany(
            f"INSERT OR REPLACE INTO trades VALUES ({','.join('?'*17)})", filas)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    print(f"  {n:,} trades guardados de {n_dias:,} días → {ruta()}")
    return n


def resumen():
    conn = sqlite3.connect(ruta())
    print("=" * 104)
    print("  VARIANTES DE ESTRATEGIA — cada trade guardado y etiquetado")
    print("=" * 104)
    print(f"\n  {'estrategia':32} {'n':>5} {'PnL total':>10} {'media':>8} "
          f"{'mediana':>8} {'gana':>6} {'MAE p90':>8} {'P1':>8} {'P2':>8}")
    print("  " + "-" * 102)
    ests = [r[0] for r in conn.execute(
        "SELECT estrategia, SUM(pnl) s FROM trades GROUP BY 1 ORDER BY s DESC")]
    for e in ests:
        v = [r[0] for r in conn.execute(
            "SELECT pnl FROM trades WHERE estrategia=?", (e,))]
        # Las estrategias de SESIÓN no guardan MAE por trade: el riesgo ahí se
        # controla a nivel jornada, no a nivel trade, y poner un número por
        # trade sería inventarlo.
        m = sorted(r[0] for r in conn.execute(
            "SELECT mae_pct FROM trades WHERE estrategia=? AND mae_pct IS NOT NULL",
            (e,)))
        per = []
        for p in ("P1", "P2"):
            g = [r[0] for r in conn.execute(
                "SELECT pnl FROM trades WHERE estrategia=? AND periodo=?", (e, p))]
            per.append(f"{statistics.mean(g):+7.2f}" if len(g) >= 20 else "      —")
        print(f"  {e:32} {len(v):>5} {sum(v):>+10.0f} {statistics.mean(v):>+7.2f} "
              f"{statistics.median(v):>+7.2f} "
              f"{100*sum(1 for x in v if x>0)/len(v):>5.0f}% "
              f"{(f'{m[int(.9*len(m))]:.1f}%' if m else '—'):>8} {per[0]} {per[1]}")
    print("\n  PnL total es la suma de todos los trades de esa variante, con")
    print("  $16,67 de riesgo por trade. No es una curva de capital: los trades")
    print("  del mismo día se solapan y no se pueden tomar todos.")
    conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Backtest con trades guardados")
    ap.add_argument("--resumen", action="store_true")
    ap.add_argument("--riesgo-trade", type=float, default=16.67)
    ap.add_argument("--costo", type=float, default=0.04)
    args = ap.parse_args(argv)
    if not args.resumen:
        correr(riesgo_trade=args.riesgo_trade, costo_accion=args.costo)
    resumen()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
