#!/usr/bin/env python3
"""Etapa 4 — el contraste de las hipótesis pre-registradas de RESEARCH.md §6.

Cruza cada evento con la dilución previa del token, medida point-in-time, y
pregunta si separa las distribuciones.

**Point-in-time.** El crecimiento de supply de un evento del día D se calcula
como supply(D) / supply(D−90) − 1. Las dos puntas son observaciones diarias
anteriores o iguales a D: no hay nada del futuro adentro. Es el equivalente de
la regla `filed`-no-`end` de EDGAR, con la diferencia —anotada en §1.2— de que
CoinGecko no garantiza que no reescriba el pasado.

**La medida primaria es el percentil, no el retorno.** Si BTC arrastra a las
500, arrastra también a la mediana del día. El retorno crudo se reporta al lado
para que se vea cuánto era mercado, pero no decide.

**Los dudosos no entran.** Los mapeos marcados como sospechosos (sin match, o
match con rank >2000: acciones tokenizadas y clones) quedan fuera del análisis
primario en vez de elegirse en silencio.

    python contraste.py
    python contraste.py --horizonte t5
    python contraste.py --incluir-ambiguos     # análisis de sensibilidad
"""

from __future__ import annotations

import argparse
import random
import sqlite3
import statistics
import sys
from collections import defaultdict

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

LOOKBACK = 90


def _series_supply(con) -> dict[str, list[tuple]]:
    """Toda la supply en memoria, ordenada por fecha. Son ~200k filas."""
    series: dict[str, list[tuple]] = defaultdict(list)
    for cg, d, sup, mcap in con.execute(
            "SELECT coingecko_id, d, supply, mcap FROM supply "
            "WHERE supply > 0 ORDER BY coingecko_id, d"):
        series[cg].append((d, sup, mcap))
    return series


def _en_o_antes(serie: list[tuple], limite: str, tolerancia_dias: int = 7):
    """Última observación con fecha ≤ `limite`, si no está más vieja que
    `tolerancia_dias`.

    Exigir la fecha exacta descartaba eventos en silencio cada vez que
    CoinGecko tenía un hueco. Se toma la observación anterior más cercana,
    que además es lo correcto point-in-time: usar una posterior sería mirar
    el futuro. La tolerancia evita comparar contra un dato viejísimo —el
    mismo criterio que `shares_stale_days` en acciones.
    """
    import bisect
    from datetime import date as _date

    i = bisect.bisect_right([s[0] for s in serie], limite)
    if i == 0:
        return None
    d, sup, mcap = serie[i - 1]
    if (_date.fromisoformat(limite) - _date.fromisoformat(d)).days > tolerancia_dias:
        return None
    return d, sup, mcap


def cargar(con, horizonte: str, min_rvol: float, min_vol: float,
           incluir_ambiguos: bool) -> list[dict]:
    """Eventos con su dilución previa, market cap y antigüedad."""
    from datetime import date as _date, timedelta as _td

    cond_amb = "" if incluir_ambiguos else "AND m.ambiguo = 0"
    sql = f"""
        SELECT e.simbolo, e.d, m.coingecko_id,
               r.pct_{horizonte}, r.r_{horizonte}, r.mae_t5,
               e.rvol, e.quote_volume, e.rango_pct,
               u.primer_dia
          FROM eventos e
          JOIN mapeo    m ON m.simbolo = e.simbolo
          JOIN universo u ON u.simbolo = e.simbolo
          JOIN retornos r ON r.simbolo = e.simbolo AND r.d = e.d
         WHERE m.dudoso = 0 {cond_amb} AND m.coingecko_id != ''
           AND r.pct_{horizonte} IS NOT NULL
           AND e.rvol >= ? AND e.quote_volume >= ?
    """
    series = _series_supply(con)
    filas = []
    for f in con.execute(sql, (min_rvol, min_vol)):
        (sim, d, cg, pct, raw, mae, rvol, vol, rango, primer) = f
        serie = series.get(cg)
        if not serie:
            continue
        hoy = _en_o_antes(serie, d)
        atras = _en_o_antes(
            serie, (_date.fromisoformat(d) - _td(days=LOOKBACK)).isoformat())
        if not hoy or not atras:
            continue
        sup_hoy, mcap = hoy[1], hoy[2]
        sup_ant = atras[1]
        crec = (sup_hoy / sup_ant - 1) * 100
        # Un salto de supply de más de 10x en 90 días casi siempre es una
        # redenominación o un dato corrupto, no dilución. Mismo criterio que el
        # filtro de escala de smallcaps: se descarta la forma imposible, no el
        # valor grande.
        if crec > 900 or crec < -50:
            continue
        filas.append({
            "simbolo": sim, "d": d, "crec": crec, "mcap": mcap or 0,
            "pct": pct, "raw": raw, "mae": mae, "rvol": rvol,
            "vol": vol, "rango": rango, "primer": primer,
        })
    return filas


def _resumen(vals: list[float]) -> tuple[float, float, int]:
    if not vals:
        return (0.0, 0.0, 0)
    return (statistics.median(vals), statistics.fmean(vals), len(vals))


def _baldes(filas: list[dict], clave: str, n: int = 3) -> list[tuple]:
    """Terciles por el valor de `clave`, con sus cortes."""
    ordenadas = sorted(filas, key=lambda f: f[clave])
    corte = len(ordenadas) // n
    grupos = []
    for i in range(n):
        ini = i * corte
        fin = (i + 1) * corte if i < n - 1 else len(ordenadas)
        grupos.append(ordenadas[ini:fin])
    return grupos


def tabla_gradiente(filas: list[dict], titulo: str, clave: str = "crec") -> list[float]:
    print(f"\n{titulo}")
    grupos = _baldes(filas, clave)
    etiquetas = ["bajo", "medio", "ALTO"]
    print(f"  {'balde':<8} {'rango':>18} {'n':>6} {'pct med':>9} "
          f"{'pct medio':>10} {'crudo med':>11}")
    medianas = []
    for etq, g in zip(etiquetas, grupos):
        if not g:
            continue
        lo, hi = g[0][clave], g[-1][clave]
        pm, pmed, n = _resumen([x["pct"] for x in g])
        rm, _, _ = _resumen([x["raw"] for x in g if x["raw"] is not None])
        medianas.append(pm)
        print(f"  {etq:<8} {lo:>8.1f}%→{hi:>7.1f}% {n:>6} {pm:>9.3f} "
              f"{pmed:>10.3f} {rm*100:>10.2f}%")
    if len(medianas) == 3:
        mono = medianas[0] > medianas[1] > medianas[2] or \
               medianas[0] < medianas[1] < medianas[2]
        delta = medianas[2] - medianas[0]
        print(f"  → monotónico: {'SÍ' if mono else 'NO'}   "
              f"Δ(alto − bajo) = {delta:+.3f} en percentil")
    return medianas


def control_bandas(filas: list[dict], horizonte: str) -> None:
    """El confusor es el tamaño: los que más diluyen son más chicos.

    Si el gradiente solo existe en agregado y desaparece dentro de las bandas
    de market cap, lo que se midió fue tamaño y no dilución.
    """
    print("\n\nCONTROL — dentro de bandas de capitalización")
    print("(el efecto tiene que sobrevivir acá, no solo en agregado)")
    bandas = [("< $50M", 0, 5e7), ("$50-250M", 5e7, 2.5e8),
              ("$250M-1B", 2.5e8, 1e9), ("> $1B", 1e9, 9e99)]
    print(f"\n  {'banda':<12} {'n':>6} {'dil ALTA':>10} {'dil BAJA':>10} "
          f"{'Δ':>9}  veredicto")
    sobreviven = evaluadas = 0
    for nombre, lo, hi in bandas:
        sub = [f for f in filas if lo <= f["mcap"] < hi]
        if len(sub) < 100:
            print(f"  {nombre:<12} {len(sub):>6}   (n insuficiente)")
            continue
        g = _baldes(sub, "crec")
        alta, _, na = _resumen([x["pct"] for x in g[2]])
        baja, _, nb = _resumen([x["pct"] for x in g[0]])
        delta = alta - baja
        evaluadas += 1
        ok = delta < 0
        sobreviven += ok
        print(f"  {nombre:<12} {len(sub):>6} {alta:>10.3f} {baja:>10.3f} "
              f"{delta:>+9.3f}  {'mantiene' if ok else 'se da vuelta'}")
    if evaluadas:
        print(f"\n  → {sobreviven}/{evaluadas} bandas mantienen el signo "
              f"(el criterio de §6 pide 3 de 4)")


def control_negativo(filas: list[dict], semilla: int = 7) -> None:
    """H5. Baraja la dilución entre símbolos y exige que NO aparezca gradiente.

    Si aparece, el pipeline está roto y todo lo demás se descarta.
    """
    print("\n\nH5 — CONTROL NEGATIVO (dilución barajada entre símbolos)")
    random.seed(semilla)
    por_simbolo = defaultdict(list)
    for f in filas:
        por_simbolo[f["simbolo"]].append(f)
    simbolos = list(por_simbolo)
    valores = [por_simbolo[s][0]["crec"] for s in simbolos]
    random.shuffle(valores)
    falso = {s: v for s, v in zip(simbolos, valores)}
    barajadas = [dict(f, crec=falso[f["simbolo"]]) for f in filas]
    med = tabla_gradiente(barajadas, "  con el feature barajado:")
    if len(med) == 3:
        delta = med[2] - med[0]
        print(f"  → {'SOSPECHOSO: aparece gradiente sin señal' if abs(delta) > 0.02 else 'OK: sin gradiente, como debe ser'}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--horizonte", default="t1", choices=["t1", "t5"])
    p.add_argument("--min-rvol", type=float, default=5.0)
    p.add_argument("--min-vol", type=float, default=2e6)
    p.add_argument("--incluir-ambiguos", action="store_true")
    args = p.parse_args()

    con = sqlite3.connect(config.db_path(), timeout=60)
    filas = cargar(con, args.horizonte, args.min_rvol, args.min_vol,
                   args.incluir_ambiguos)

    print("=" * 74)
    print(f"  CONTRASTE — H1: dilución previa {LOOKBACK}d vs desempeño {args.horizonte}")
    print("=" * 74)
    print(f"\neventos con dilución calculable : {len(filas):,}")
    if len(filas) < 200:
        print("\nmuestra insuficiente. ¿Terminó `python supply.py --bajar`?")
        return 1
    print(f"símbolos distintos              : {len({f['simbolo'] for f in filas})}")
    print(f"filtro                          : RVOL≥{args.min_rvol} "
          f"vol≥${args.min_vol/1e6:.0f}M")
    print(f"mapeos ambiguos                 : "
          f"{'INCLUIDOS (sensibilidad)' if args.incluir_ambiguos else 'excluidos'}")

    cr = [f["crec"] for f in filas]
    cr.sort()
    print(f"\ndistribución de dilución {LOOKBACK}d:")
    print(f"  mediana {statistics.median(cr):>7.1f}%   "
          f"p75 {cr[int(.75*len(cr))]:>7.1f}%   p90 {cr[int(.90*len(cr))]:>7.1f}%   "
          f"máx {cr[-1]:>8.1f}%")

    print("\n\nH1 — ¿la dilución previa separa las distribuciones?")
    print("(percentil bajo = peor desempeño relativo ese día)")
    tabla_gradiente(filas, "  agregado:")

    control_bandas(filas, args.horizonte)
    control_negativo(filas)

    print("\n\nH3 — antigüedad: ¿los recién listados rinden peor?")
    nuevos = [f for f in filas if f["primer"] and f["primer"] > "2025-06-15"]
    viejos = [f for f in filas if not (f["primer"] and f["primer"] > "2025-06-15")]
    for etq, g in (("listados en la ventana", nuevos), ("preexistentes", viejos)):
        m, mm, n = _resumen([x["pct"] for x in g])
        print(f"  {etq:<24} n={n:>6}  pct mediana {m:.3f}  media {mm:.3f}")

    print("\n" + "=" * 74)
    print("  Recordar: el n efectivo sale de test_correlacion.py, no de acá.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
