#!/usr/bin/env python3
"""Prueba chica de las hipótesis de timing, sobre pocos eventos.

Testea dos ideas concretas, ninguna medible con barras diarias:

  A) **¿A qué hora ocurre el máximo?** Si es temprano, esperar tiene sentido.
     Si se reparte todo el día, "esperar a que termine la subida" no es una
     regla, es una ilusión retrospectiva.

  B) **Barrido y desplome al día siguiente.** Con diarias solo sabíamos si el
     máximo del día 2 superó al del día 1 — no CUÁNDO. Acá se puede separar
     "picó temprano y se derrumbó" de "subió todo el día".

Se corre sobre una muestra chica a propósito: si el método no distingue casos
que ya sabemos que son opuestos, no tiene sentido bajar 21 horas de datos.

    python probe_timing.py --fetch 30    # baja 30 eventos (~6 min) y analiza
    python probe_timing.py               # analiza lo ya bajado
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from datetime import date, timedelta

import config
from massive import MassiveClient
from massive.minutes import MinuteStore, fetch_event

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def elegir_muestra(conn, n: int) -> list[tuple]:
    """Mitad que se dieron vuelta, mitad que siguieron subiendo.

    Estratificar a propósito: si el análisis no separa estos dos grupos —que
    por construcción son opuestos— el método no sirve y mejor saberlo ya.
    """
    q = """SELECT ticker, d, close_pos, range_pct, close, day_return_pct
           FROM events
           WHERE range_pct>50 AND dollar_volume>=2e6 AND close BETWEEN 1 AND 20
             AND close_pos IS NOT NULL AND d < date('now','-10 day')
           ORDER BY {} LIMIT ?"""
    fade = conn.execute(q.format("close_pos ASC"), (n // 2,)).fetchall()
    rip = conn.execute(q.format("close_pos DESC"), (n - n // 2,)).fetchall()
    return [(*r, "se dio vuelta") for r in fade] + [(*r, "siguió subiendo") for r in rip]


def _hora_del_max(bars) -> tuple[float | None, float]:
    """Hora ET (decimal) del máximo del día, y qué fracción del volumen fue antes."""
    if not bars:
        return None, 0.0
    i_max = max(range(len(bars)), key=lambda i: bars[i][2] or 0)
    t = bars[i_max][0]
    vol_antes = sum(b[5] or 0 for b in bars[:i_max + 1])
    vol_total = sum(b[5] or 0 for b in bars) or 1
    return t.hour + t.minute / 60.0, vol_antes / vol_total


def _entrar_a(bars, hora: float) -> tuple[float, float] | None:
    """Precio a esa hora ET y retorno hasta el cierre. Para 'entrar al mediodía'."""
    cand = [b for b in bars if (b[0].hour + b[0].minute / 60.0) >= hora]
    if not cand or not bars:
        return None
    entrada = cand[0][4]
    cierre = bars[-1][4]
    if not entrada:
        return None
    return entrada, (cierre / entrada - 1.0) * 100.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Prueba de hipótesis de timing")
    ap.add_argument("--fetch", type=int, default=0, help="cuántos eventos bajar")
    args = ap.parse_args(argv)

    conn = sqlite3.connect(config.bars_db_path())
    store = MinuteStore()
    muestra = elegir_muestra(conn, args.fetch or 30)

    if args.fetch:
        client = MassiveClient()
        ya = store.done()
        pend = [m for m in muestra if (m[0], m[1]) not in ya]
        print(f"bajando {len(pend)} eventos (~{len(pend)/5:.0f} min)…", flush=True)
        for i, (t, d, *_rest) in enumerate(pend, 1):
            n, st = fetch_event(client, store, t, date.fromisoformat(d))
            print(f"  [{i}/{len(pend)}] {t:6} {d}  {n:>6,} barras  {st}", flush=True)

    print("\n" + "=" * 76)
    print("  A) ¿A QUÉ HORA OCURRE EL MÁXIMO DEL DÍA?")
    print("=" * 76)
    horas = {"se dio vuelta": [], "siguió subiendo": []}
    volf = {"se dio vuelta": [], "siguió subiendo": []}
    filas = []
    for t, d, cp, rng, cl, dret, grupo in muestra:
        bars = store.day_bars(t, date.fromisoformat(d))
        if len(bars) < 20:
            continue
        h, vf = _hora_del_max(bars)
        if h is None:
            continue
        horas[grupo].append(h)
        volf[grupo].append(vf)
        med = _entrar_a(bars, 12.0)
        filas.append((t, d, grupo, h, vf, cp, med[1] if med else None, len(bars)))

    for g in horas:
        if len(horas[g]) < 3:
            print(f"  {g:18} muestra insuficiente")
            continue
        hs = sorted(horas[g])
        print(f"  {g:18} n={len(hs):>3}  máximo a las "
              f"{int(statistics.median(hs)):02d}:{int(statistics.median(hs)%1*60):02d} ET (mediana)  ·  "
              f"antes del máximo pasó el {100*statistics.median(volf[g]):.0f}% del volumen")

    print("\n" + "=" * 76)
    print("  B) ENTRAR A LAS 12:00 Y SOSTENER HASTA EL CIERRE")
    print("=" * 76)
    for g in ("se dio vuelta", "siguió subiendo"):
        v = [f[6] for f in filas if f[2] == g and f[6] is not None]
        if len(v) < 3:
            print(f"  {g:18} muestra insuficiente")
            continue
        neg = sum(1 for x in v if x < 0)
        print(f"  {g:18} n={len(v):>3}  mediana={statistics.median(v):>7.2f}%  "
              f"baja el {100*neg/len(v):.0f}% de las veces")

    print("\n  DETALLE")
    print(f"  {'ticker':7} {'fecha':11} {'grupo':16} {'max':>6} {'vol antes':>10} "
          f"{'12:00→cierre':>13} {'barras':>7}")
    for t, d, g, h, vf, cp, r12, nb in sorted(filas, key=lambda x: x[3]):
        print(f"  {t:7} {d:11} {g:16} {int(h):02d}:{int(h%1*60):02d}  "
              f"{100*vf:>9.0f}% {(f'{r12:+.1f}%' if r12 is not None else '—'):>13} {nb:>7,}")

    store.close()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
