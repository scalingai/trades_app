#!/usr/bin/env python3
"""El radar: las tres capas del protocolo, sobre los datos que ya están.

  Capa 1 — régimen del mes, leído en la primera semana. Decide el sesgo y el
           tamaño, no qué ticker mirar.
  Capa 2 — el escáner: precio, float, gap, volumen pre-market, origen y sector.
  Capa 3 — viabilidad: historial de fallo del ticker, niveles estructurales.

**Qué NO está y hay que saberlo antes de usar esto.** El costo de locate y el
estado hard-to-borrow no existen en ningún dato que tengamos, y el protocolo los
pone —con razón— como criterio de descarte. Un ticker que el radar marca como
candidato puede ser inoperable por borrow y esto no se va a enterar. Es la
frontera del sistema, no un pendiente menor.

El origen y el sector salen de EDGAR gratis: `countryCode` del domicilio
comercial y el SIC. F4 es China; E9, Islas Caimán. Se cachea en disco.

    python radar.py --fecha 2026-08-11
    python radar.py --mes 2026-08
    python radar.py --regimen 2026-08
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

import config
from dias import cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# SIC de biotecnología y farma: los sectores donde un binario regulatorio
# produce el gap. No es una lista exhaustiva de "salud", es la de los binarios.
SIC_BIOTECH = {"2834", "2833", "2836", "8731", "8071", "2835"}
PAIS_CHINA = {"F4"}          # código EDGAR de China
INCORP_OFFSHORE = {"E9", "D8"}   # Caimán, Islas Vírgenes Británicas

_FICHAS = config.data_dir() / "fichas_empresa.json"


def _cargar_fichas() -> dict:
    if _FICHAS.exists():
        try:
            return json.loads(_FICHAS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def ficha_empresa(ticker: str, cache: dict) -> dict:
    """Sector y origen desde EDGAR. Cacheado en disco: no cambia día a día."""
    if ticker in cache:
        return cache[ticker]
    try:
        from edgar import client, tickers
        cik = tickers.cik_for(ticker)
        j = client.fetch_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        ba = (j.get("addresses") or {}).get("business") or {}
        f = {
            "sic": str(j.get("sic") or ""),
            "sector": j.get("sicDescription") or "",
            "pais": ba.get("countryCode") or "US",
            "incorp": j.get("stateOfIncorporation") or "",
        }
    except Exception:
        f = {"sic": "", "sector": "", "pais": "", "incorp": ""}
    f["biotech"] = f["sic"] in SIC_BIOTECH
    f["china"] = f["pais"] in PAIS_CHINA or f["incorp"] in INCORP_OFFSHORE
    cache[ticker] = f
    return f


# ------------------------------------------------------------------ capa 1

def regimen(db, mes: str) -> dict:
    """Diagnóstico del mes leyendo solo los días 1 a 7."""
    filas = db.execute(
        "SELECT d, intraday_pct FROM events WHERE d LIKE ? AND gap_pct >= 20 "
        "AND dollar_volume >= 1e6 AND intraday_pct IS NOT NULL", (mes + "%",)).fetchall()
    sem1 = [x for d, x in filas if int(d[8:10]) <= 7]
    if len(sem1) < 10:
        return {"mes": mes, "n": len(sem1), "veredicto": "sin muestra"}
    tasa = 100.0 * sum(1 for x in sem1 if x < 0) / len(sem1)
    if tasa >= 60:
        v, tam = "fading", "tamaño normal"
    elif tasa >= 50:
        v, tam = "mixto", "mitad de tamaño"
    else:
        v, tam = "reclaims", "NO operar corto"
    return {"mes": mes, "n": len(sem1), "tasa": tasa, "veredicto": v, "tamaño": tam}


# ------------------------------------------------------------------ capa 3

def historial(db, *, min_gap=20.0) -> dict:
    """Tasa de fallo previa por (ticker, fecha). Point-in-time por construcción."""
    previos = defaultdict(lambda: [0, 0])
    out = {}
    for t, d, intra in db.execute(
        "SELECT ticker, d, intraday_pct FROM events WHERE gap_pct >= ? "
        "AND intraday_pct IS NOT NULL ORDER BY ticker, d", (min_gap,)
    ):
        n, fall = previos[t]
        out[(t, d)] = (100.0 * fall / n, n) if n else (None, 0)
        previos[t] = [n + 1, fall + (1 if intra < 0 else 0)]
    return out


def niveles_previos(db, ticker: str, d: str, *, dias=60, top=3) -> list[float]:
    """Resistencias de volumen: los máximos de los días de más volumen previos.

    Es la versión barata del "perfil de volumen en diario" del protocolo: los
    días que más se operaron son los que dejaron papel atrapado arriba.
    """
    filas = db.execute(
        "SELECT h, v FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT ?",
        (ticker, d, dias)).fetchall()
    if not filas:
        return []
    return sorted({round(h, 4) for h, _ in
                   sorted(filas, key=lambda x: -(x[1] or 0))[:top] if h})


# ------------------------------------------------------------------ capa 2

def escanear(db, fechas, *, hist, fichas, precio_min, precio_max, min_gap,
             float_max, min_vol_pre):
    """Los candidatos de un conjunto de fechas, con todas las capas resueltas."""
    acciones = {(t, d): n for t, d, n in db.execute(
        "SELECT ticker,d,shares_outstanding FROM event_structure "
        "WHERE shares_outstanding IS NOT NULL")}
    dil = {(t, d): x for t, d, x in db.execute(
        "SELECT ticker,d,dilution_12m_pct FROM event_structure "
        "WHERE dilution_12m_pct IS NOT NULL")}

    salida = []
    for dia in cargar():
        if dia.d not in fechas:
            continue
        p = dia.rth_open
        gap = ((p / dia.prev_close - 1) * 100) if (p and dia.prev_close) else None
        vol_pre = sum(b[5] or 0 for b in dia.pre)
        acc = acciones.get((dia.ticker, dia.d))
        h, n_h = hist.get((dia.ticker, dia.d), (None, 0))
        f = ficha_empresa(dia.ticker, fichas)

        # Prefijo `ok_` obligatorio: sin él las claves booleanas pisan a las
        # numéricas del mismo nombre y la tabla imprime 1.00 en la columna de
        # precio. Ya pasó una vez en el visor; acá se evita por convención.
        pasos = {
            "ok_precio": bool(p and precio_min <= p <= precio_max),
            "ok_gap": bool(gap is not None and gap >= min_gap),
            "ok_float": bool(acc and acc <= float_max),
            "ok_vol_pre": vol_pre >= min_vol_pre,
            "ok_volumen": bool((dia.ratio_volumen or 0) >= 3),
        }
        salida.append({
            "ticker": dia.ticker, "d": dia.d, "precio": p, "gap": gap,
            "expansion": dia.expansion_pct, "vol_pre": vol_pre,
            "acciones": acc, "hist": h, "n_hist": n_h,
            "dil": dil.get((dia.ticker, dia.d)),
            "china": f["china"], "biotech": f["biotech"], "sector": f["sector"],
            "niveles": niveles_previos(db, dia.ticker, dia.d),
            "intra": ((dia.rth_close / p - 1) * 100) if (p and dia.rth_close) else None,
            **pasos, "candidato": all(pasos.values()),
            "falla_en": [k[3:] for k, v in pasos.items() if not v],
        })
    return salida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Radar de candidatos")
    ap.add_argument("--fecha", help="un día concreto (AAAA-MM-DD)")
    ap.add_argument("--mes", help="un mes entero (AAAA-MM)")
    ap.add_argument("--regimen", help="solo el diagnóstico de régimen de un mes")
    ap.add_argument("--precio-min", type=float, default=0.70)
    ap.add_argument("--precio-max", type=float, default=5.00)
    ap.add_argument("--min-gap", type=float, default=70.0)
    ap.add_argument("--float-max", type=float, default=10e6)
    ap.add_argument("--min-vol-pre", type=float, default=3e6)
    args = ap.parse_args(argv)

    db = sqlite3.connect(config.bars_db_path())

    if args.regimen:
        r = regimen(db, args.regimen)
        print(f"\n  RÉGIMEN {r['mes']}  ·  n={r['n']} eventos en la semana 1")
        if "tasa" in r:
            print(f"  fadea el {r['tasa']:.0f}%  →  {r['veredicto'].upper()}  ·  {r['tamaño']}")
        else:
            print(f"  {r['veredicto']}")
        db.close()
        return 0

    if args.fecha:
        fechas = {args.fecha}
        mes = args.fecha[:7]
    elif args.mes:
        fechas = {d for (d,) in db.execute(
            "SELECT DISTINCT d FROM events WHERE d LIKE ?", (args.mes + "%",))}
        mes = args.mes
    else:
        print("hace falta --fecha, --mes o --regimen")
        return 1

    r = regimen(db, mes)
    fichas = _cargar_fichas()
    hist = historial(db)
    filas = escanear(db, fechas, hist=hist, fichas=fichas,
                     precio_min=args.precio_min, precio_max=args.precio_max,
                     min_gap=args.min_gap, float_max=args.float_max,
                     min_vol_pre=args.min_vol_pre)
    _FICHAS.write_text(json.dumps(fichas), encoding="utf-8")

    print("=" * 100)
    print(f"  RADAR  ·  {args.fecha or args.mes}")
    print(f"  CAPA 1 — régimen del mes: {r.get('veredicto','?').upper()}"
          + (f" (fadea el {r['tasa']:.0f}% en la semana 1) → {r['tamaño']}"
             if "tasa" in r else ""))
    print(f"  CAPA 2 — ${args.precio_min:.2f}-${args.precio_max:.2f} · "
          f"gap >= {args.min_gap:.0f}% · float <= {args.float_max/1e6:.0f}M · "
          f"vol pre >= {args.min_vol_pre/1e6:.0f}M")
    print("=" * 100)

    cand = [f for f in filas if f["candidato"]]
    print(f"\n  {len(filas)} días con minutos en el período · {len(cand)} candidatos\n")
    if not filas:
        db.close()
        return 0

    print(f"  {'ticker':7} {'fecha':11} {'precio':>7} {'gap':>7} {'exp':>7} "
          f"{'vol pre':>9} {'acciones':>9} {'hist':>6} {'dil12m':>8} {'flags':<12} {'intra':>7}")
    print("  " + "-" * 106)
    for f in sorted(filas, key=lambda x: (not x["candidato"], x["d"]))[:60]:
        flags = ("CN " if f["china"] else "") + ("BIO " if f["biotech"] else "")
        marca = "*" if f["candidato"] else " "
        n = lambda v, s="": "—" if v is None else f"{v:,.0f}{s}"  # noqa: E731
        h_txt = f"{f['hist']:.0f}%" if f["hist"] is not None else "—"
        print(f" {marca}{f['ticker']:6} {f['d']:11} "
              f"{f['precio'] or 0:>7.2f} {n(f['gap'],'%'):>7} {n(f['expansion'],'%'):>7} "
              f"{f['vol_pre']/1e6:>8.1f}M {n(f['acciones']):>9} "
              f"{h_txt:>6} "
              f"{n(f['dil'],'%'):>8} {flags:<12} {n(f['intra'],'%'):>7}")

    print("\n  * = candidato (pasa las cinco de la capa 2)")
    print("  hist = % de gaps previos de ESE ticker que cerraron en rojo (point-in-time)")
    print("\n  LO QUE ESTE RADAR NO SABE: si hay borrow y cuánto cuesta el locate.")
    print("  El protocolo lo pone como criterio de descarte y no hay dato. Un")
    print("  candidato de acá puede ser inoperable y esto no se entera.")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
