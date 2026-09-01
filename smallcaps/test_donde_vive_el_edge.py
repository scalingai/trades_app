#!/usr/bin/env python3
"""Cuanto se deja en la mesa: MFE contra lo que efectivamente se cobro.

Observacion de Agus mirando la bitacora: el trade del 02/10 en TIGR llego a
13,3% a favor y cerro en +3%. Su lectura fue "esto tiene que pasar muchisimo".
Aca se cuantifica sobre los ~1.300 trades persistidos, en vez de discutirlo.

La columna que importa es 'devuelto': que fraccion del maximo a favor se
devolvio antes de cerrar. Si la mediana es alta, hay plata sistematicamente
sobre la mesa; si es baja, el trade de TIGR fue un caso y no un patron.
"""
import sqlite3, statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config

c = sqlite3.connect(config.data_dir() / "trades.sqlite")
for est in ("limpio·fade·exp150", "limpio·reclaim·exp100"):
    fs = [dict(zip(("pe","ps","mae","mfe","pnl","motivo"), r)) for r in c.execute(
        "SELECT precio_entrada,precio_salida,mae_pct,mfe_pct,pnl,motivo "
        "FROM trades WHERE estrategia=?", (est,))]
    if not fs: continue
    print(f"\n  {est}  ·  {len(fs)} trades\n")
    # retorno realizado a favor del short, en %
    for f in fs:
        f["ret"] = 100 * (f["pe"] - f["ps"]) / f["pe"] if f["pe"] else 0.0
        f["dev"] = (f["mfe"] - f["ret"]) if f["mfe"] > 0 else 0.0
        f["frac"] = (f["dev"] / f["mfe"]) if f["mfe"] > 0.5 else None
    fr = [f["frac"] for f in fs if f["frac"] is not None]
    print(f"    MFE mediana        {statistics.median(f['mfe'] for f in fs):6.1f}%")
    print(f"    retorno mediano    {statistics.median(f['ret'] for f in fs):6.1f}%")
    print(f"    DEVUELTO mediano   {statistics.median(f['dev'] for f in fs):6.1f} puntos")
    if fr:
        print(f"    fraccion devuelta  mediana {100*statistics.median(fr):.0f}%  ·  "
              f"media {100*statistics.mean(fr):.0f}%")
    # cuantos llegaron a X a favor y terminaron peor
    print(f"\n    {'llego a':>9} {'trades':>7} {'terminaron':>11} {'devolvieron':>12}")
    print("    " + "-"*44)
    for u in (5, 10, 15, 20, 30):
        g = [f for f in fs if f["mfe"] >= u]
        if len(g) < 10: continue
        peor = sum(1 for f in g if f["ret"] < u)
        print(f"    {('>='+str(u)+'%'):>9} {len(g):>7} {peor:>10} "
              f"({100*peor/len(g):.0f}%) {statistics.median(f['dev'] for f in g):>9.1f} pts")
