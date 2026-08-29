#!/usr/bin/env python3
"""Metadata de empresa desde EDGAR, en lote y cacheada. País, SIC, sector.

Lo que pidió Agus: automatizar la extracción del país de domicilio y el código
SIC para que entren al pipeline en vez de resolverse a demanda. Hasta ahora
`radar.py` los pedía uno por uno cuando los necesitaba, y eso hacía que la
primera corrida de cualquier análisis tardara minutos.

**Es gratis y no cambia.** EDGAR no pide API key, el rate limit es 10 req/s, y
el país y el SIC de una empresa no se mueven día a día. Se bajan una vez y
quedan en disco.

Cobertura del universo: 8.040 tickers en `events`, 1.184 en el censo observable,
1.022 con gap ≥ 50% y volumen ≥ $1M. Por defecto se fichan estos últimos —
fichar los 8.040 son ~15 minutos y la mayoría nunca va a ser candidato.

**EL SESGO DE SUPERVIVENCIA DE ESTA CAPA, MEDIDO.** De 1.596 tickers fichados,
655 (41%) no resuelven CIK: el mapa ticker→CIK de EDGAR solo tiene los vigentes.
Y esos NO son un grupo cualquiera — de los que sí resuelven, el **98%** seguía
cotizando al final de la serie; de los que no, apenas el **46%**. O sea que lo
que falta son, mayoritariamente, los que murieron.

Ahora, lo que eso rompe y lo que no:

- **NO rompe la medición del día del evento.** Con ficha da −8,70% de mediana
  con 65% de caídas; sin ficha, −8,52% con 64%. Idénticos. Para el retorno
  intradía, tener o no metadata no cambia nada.
- **SÍ rompe cualquier conclusión por sector o por país.** El "18% chinas" es
  18% **de los sobrevivientes**. La proporción real en la población histórica es
  desconocida y probablemente distinta, porque justo las que se deslistaron son
  las que no se pueden clasificar.

Usar esta capa para filtrar candidatos está bien. Usarla para decir "el X% del
universo es biotech" no.

**El otro límite del dato:** el `countryCode`
es el del domicilio COMERCIAL declarado, y `stateOfIncorporation` es dónde está
constituida. Una empresa china que opera desde Nueva York figura como US; una
americana constituida en Caimán figura como offshore. Es un proxy razonable del
perfil "hiper-volátil, atrapa cortos", no un dato de nacionalidad.

    python fichas.py                 # las que faltan del universo relevante
    python fichas.py --todos         # los 8.040 tickers de events
    python fichas.py --stats
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

RUTA = config.data_dir() / "fichas_empresa.json"

# SIC donde un binario regulatorio produce el gap. No es "salud": es la lista
# de los binarios.
SIC_BIOTECH = {"2833", "2834", "2835", "2836", "8071", "8731"}
PAIS_CHINA = {"F4"}                 # código EDGAR de China
INCORP_OFFSHORE = {"E9", "D8"}      # Islas Caimán, Islas Vírgenes Británicas


def cargar() -> dict:
    if RUTA.exists():
        try:
            return json.loads(RUTA.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def guardar(fichas: dict) -> None:
    RUTA.write_text(json.dumps(fichas, sort_keys=True), encoding="utf-8")


def _derivar(f: dict) -> dict:
    f["biotech"] = f.get("sic", "") in SIC_BIOTECH
    f["china"] = f.get("pais") in PAIS_CHINA or f.get("incorp") in INCORP_OFFSHORE
    return f


def fichar(ticker: str) -> dict:
    """Una empresa. Devuelve la ficha aunque falle — con `ok: False`."""
    try:
        from edgar import client, tickers
        cik = tickers.cik_for(ticker)
        if not cik:
            return _derivar({"ok": False, "motivo": "sin CIK"})
        j = client.fetch_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        ba = (j.get("addresses") or {}).get("business") or {}
        return _derivar({
            "ok": True,
            "cik": cik,
            "nombre": j.get("name") or "",
            "sic": str(j.get("sic") or ""),
            "sector": j.get("sicDescription") or "",
            "pais": ba.get("countryCode") or "US",
            "estado": ba.get("stateOrCountry") or "",
            "incorp": j.get("stateOfIncorporation") or "",
        })
    except Exception as exc:
        return _derivar({"ok": False, "motivo": str(exc)[:120]})


def universo(db, *, todos: bool, min_gap: float, min_dv: float) -> list[str]:
    if todos:
        q = "SELECT DISTINCT ticker FROM events ORDER BY ticker"
        return [t for (t,) in db.execute(q)]
    q = ("SELECT DISTINCT ticker FROM events WHERE gap_pct >= ? AND dollar_volume >= ? "
         "UNION SELECT DISTINCT ticker FROM poblacion_obs ORDER BY ticker")
    try:
        return [t for (t,) in db.execute(q, (min_gap, min_dv))]
    except sqlite3.OperationalError:   # todavía no existe el censo
        return [t for (t,) in db.execute(
            "SELECT DISTINCT ticker FROM events WHERE gap_pct >= ? AND dollar_volume >= ? "
            "ORDER BY ticker", (min_gap, min_dv))]


def estadisticas(fichas: dict) -> None:
    ok = {t: f for t, f in fichas.items() if f.get("ok")}
    print(f"  {len(fichas):,} fichadas · {len(ok):,} con datos "
          f"({len(fichas)-len(ok)} sin CIK o con error)")
    if not ok:
        return
    print(f"\n  chinas / offshore   {sum(1 for f in ok.values() if f['china']):>5} "
          f"({100*sum(1 for f in ok.values() if f['china'])/len(ok):.0f}%)")
    print(f"  biotech             {sum(1 for f in ok.values() if f['biotech']):>5} "
          f"({100*sum(1 for f in ok.values() if f['biotech'])/len(ok):.0f}%)")
    print("\n  los 10 sectores más frecuentes")
    for sec, n in Counter(f["sector"] for f in ok.values() if f["sector"]).most_common(10):
        print(f"    {n:>5}  {sec[:60]}")
    print("\n  los 8 países de domicilio más frecuentes")
    for p, n in Counter(f["pais"] for f in ok.values() if f.get("pais")).most_common(8):
        print(f"    {n:>5}  {p}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fichas de empresa desde EDGAR")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--min-gap", type=float, default=50.0)
    ap.add_argument("--min-dollar-vol", type=float, default=1e6)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--refichar", action="store_true",
                    help="volver a pedir las que fallaron")
    args = ap.parse_args(argv)

    fichas = cargar()
    if args.stats:
        estadisticas(fichas)
        return 0

    db = sqlite3.connect(config.bars_db_path())
    univ = universo(db, todos=args.todos, min_gap=args.min_gap,
                    min_dv=args.min_dollar_vol)
    db.close()

    pend = [t for t in univ
            if t not in fichas or (args.refichar and not fichas[t].get("ok"))]

    print("=" * 68)
    print("  FICHAS DE EMPRESA (EDGAR)")
    print(f"  universo: {len(univ):,} tickers · ya fichados {len(univ)-len(pend):,} · "
          f"pendientes {len(pend):,}")
    print(f"  ~{len(pend)/10/60:.1f} min al límite de 10 req/s de la SEC")
    print("=" * 68, flush=True)

    if not pend:
        estadisticas(fichas)
        return 0

    t0 = time.time()
    for i, t in enumerate(pend, 1):
        fichas[t] = fichar(t)
        if i % 100 == 0 or i == len(pend):
            guardar(fichas)   # guardar seguido: si se corta, no se pierde nada
            el = time.time() - t0
            print(f"  [{i:>5}/{len(pend)}] {el/60:.1f} min · "
                  f"faltan ~{(el/i)*(len(pend)-i)/60:.1f} min", flush=True)
    guardar(fichas)
    print()
    estadisticas(fichas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
