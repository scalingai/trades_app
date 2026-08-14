#!/usr/bin/env python3
"""Etapa 1 — la capa de dilución: supply circulante por token, point-in-time.

Dos pasos.

**Mapeo.** CoinGecko lista 18.402 monedas y el 16,1% de los símbolos está
duplicado: 'pepe' resuelve a 20 ids distintos. Resolver por símbolo a ciegas
mete la supply de otra moneda en las filas — un error silencioso que llegaría
al resultado disfrazado de ruido, como el share count corrupto de KPTI en
acciones. Se desambigua por capitalización: entre los candidatos con el mismo
símbolo gana el de mayor market cap, porque Binance lista el activo real y no
el clon. Lo dudoso queda marcado, no adivinado.

Aparte, 15 perpetuos llevan multiplicador en el nombre (`1000PEPEUSDT`): el
contrato vale 1.000 tokens. Si se ignora, la supply derivada sale mal por
órdenes de magnitud.

**Descarga.** CoinGecko no publica supply circulante como serie, pero se deriva:

    supply(t) = market_cap(t) / price(t)

Verificado sobre ARB: da +28,3% en 12 meses con los cliffs mensuales visibles.

LÍMITE DURO: 365 días. Probado `days=max`, `/history` y `market_chart/range`
con ventana antigua — los tres devuelven 401 con
"limited to querying historical data within the past 365 days". Eso obliga a
usar un lookback de 90 días en vez de 12 meses (ver `LOOKBACK_DIAS` abajo).

    python supply.py --mapeo        # construye y versiona mapeo.csv
    python supply.py --bajar        # descarga la supply de los mapeados
    python supply.py --stats
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import requests

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CG = "https://api.coingecko.com/api/v3"
MAPEO_CSV = Path(__file__).resolve().parent / "mapeo.csv"

# El free tier corta en 365 días. Con lookback L, los eventos utilizables van
# de (hoy-365+L) a hoy, o sea que la ventana de eventos es 365-L.
#   L=90  → 275 días de eventos  ← elegido
#   L=180 → 185 días
#   L=365 →   0 días (inútil)
# 90 días es un trimestre y se corresponde con el `dilution_3m` que ya existía
# en el trabajo de acciones. El de 12m no es alcanzable con datos gratis.
LOOKBACK_DIAS = 90

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mapeo (
    simbolo       TEXT PRIMARY KEY,
    coingecko_id  TEXT,
    ticker        TEXT,
    multiplicador REAL DEFAULT 1,
    mcap_rank     INTEGER,
    ambiguo       INTEGER DEFAULT 0,   -- había >1 candidato con ese símbolo
    dudoso        INTEGER DEFAULT 0,   -- match sospechoso: NO entra al análisis primario
    nota          TEXT
);

CREATE TABLE IF NOT EXISTS supply (
    coingecko_id TEXT NOT NULL,
    d            TEXT NOT NULL,
    price        REAL,
    mcap         REAL,
    supply       REAL,
    PRIMARY KEY (coingecko_id, d)
) WITHOUT ROWID;

-- Cuándo se descargó cada serie. Existe para poder medir el restatement:
-- CoinGecko puede recalcular el pasado y no avisa (RESEARCH.md §1.2).
CREATE TABLE IF NOT EXISTS supply_meta (
    coingecko_id  TEXT PRIMARY KEY,
    descargado_en TEXT,
    n_puntos      INTEGER
);
"""


# Columnas agregadas después de la primera versión del esquema. `CREATE TABLE
# IF NOT EXISTS` no toca una tabla que ya existe, así que sin esto una base
# vieja falla al insertar y hay que borrarla entera — perdiendo la supply ya
# descargada, que es lo caro de recuperar.
_MIGRACIONES = [
    ("mapeo", "dudoso", "INTEGER DEFAULT 0"),
]


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(config.db_path(), timeout=60)
    con.executescript(_SCHEMA)
    con.execute("PRAGMA journal_mode=WAL")
    for tabla, columna, tipo in _MIGRACIONES:
        cols = {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}
        if columna not in cols:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
            con.commit()
    return con


# ─────────────────────────────── throttle ──────────────────────────────────

class Throttle:
    """Ritmo adaptativo: arranca en el límite configurado y se frena solo si
    aparece un 429. Un corte a mitad de 500 monedas cuesta más que ir lento."""

    def __init__(self, por_minuto: int):
        self.minimo = 60.0 / max(1, por_minuto)
        self.intervalo = self.minimo
        self.ultimo = 0.0
        self.exitos = 0

    def esperar(self) -> None:
        falta = self.intervalo - (time.monotonic() - self.ultimo)
        if falta > 0:
            time.sleep(falta)
        self.ultimo = time.monotonic()

    def frenar(self) -> None:
        self.intervalo = min(self.intervalo * 1.8, 12.0)
        self.exitos = 0
        print(f"    (429 — bajando a {60/self.intervalo:.1f} peticiones/min)",
              flush=True)

    def acelerar(self) -> None:
        """Recupera ritmo tras una racha limpia.

        Sin esto, un pico transitorio de 429 al principio deja la descarga
        lenta para siempre: 568 monedas a 5/min son casi dos horas, y el
        límite real suele ser bastante mayor. Se sube de a poco y nunca por
        encima del configurado.
        """
        self.exitos += 1
        if self.exitos >= 12 and self.intervalo > self.minimo:
            self.intervalo = max(self.minimo, self.intervalo / 1.4)
            self.exitos = 0
            print(f"    (racha limpia — subiendo a "
                  f"{60/self.intervalo:.1f} peticiones/min)", flush=True)


_throttle = Throttle(config.coingecko_rate_limit())


def _pedir(ruta: str, params: dict, reintentos: int = 5):
    key = config.coingecko_key()
    if key:
        params = dict(params, x_cg_demo_api_key=key)
    for _ in range(reintentos):
        _throttle.esperar()
        try:
            r = requests.get(f"{CG}/{ruta}", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(3)
            continue
        if r.status_code == 200:
            _throttle.acelerar()
            return r.json()
        if r.status_code == 429:
            _throttle.frenar()
            time.sleep(8)
            continue
        if r.status_code in (401, 404):
            return None  # fuera de rango o moneda inexistente: no se reintenta
        time.sleep(3)
    return None


# ──────────────────────────────── mapeo ────────────────────────────────────

def _limpiar_simbolo(simbolo: str) -> tuple[str, float]:
    """`1000PEPEUSDT` → ('PEPE', 1000). Devuelve ticker y multiplicador.

    Binance usa dos convenciones para los tokens de precio muy chico, y las
    dos hay que leerlas bien: `1000X`, `1000000X` (un 1 seguido de ceros) y
    `1MX` (millón). Sacar de a cuatro caracteres deja `1000000BOB` como
    `000BOB`, que no matchea con nada — y un ticker mal cortado se pierde en
    silencio en vez de fallar.
    """
    base = simbolo[:-4] if simbolo.endswith("USDT") else simbolo
    mult = 1.0
    m = re.match(r"^1(0+)([A-Z].*)$", base)
    if m:
        return m.group(2), float(10 ** len(m.group(1)))
    m = re.match(r"^1M([A-Z].*)$", base)
    if m:
        return m.group(1), 1e6
    return base, mult


def construir_mapeo(limite_rank: int = 4000) -> None:
    """Cruza los perpetuos del archivo contra el top de CoinGecko por mcap."""
    import archivo

    print("bajando el ranking de CoinGecko por capitalización…")
    mercado: dict[str, list[dict]] = {}
    for pagina in range(1, limite_rank // 250 + 1):
        datos = _pedir("coins/markets", {
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": 250, "page": pagina})
        if not datos:
            break
        for m in datos:
            mercado.setdefault(m["symbol"].lower(), []).append(m)
        print(f"  página {pagina}: {len(datos)} monedas", flush=True)

    simbolos = [s for s in archivo.listar_simbolos() if s.endswith("USDT")]
    print(f"\nmapeando {len(simbolos)} perpetuos…")

    filas, sin_match, ambiguos = [], 0, 0
    for simbolo in simbolos:
        ticker, mult = _limpiar_simbolo(simbolo)
        candidatos = mercado.get(ticker.lower(), [])
        if not candidatos:
            sin_match += 1
            filas.append({"simbolo": simbolo, "coingecko_id": "",
                          "ticker": ticker, "multiplicador": mult,
                          "mcap_rank": "", "ambiguo": 0, "dudoso": 1,
                          "nota": "sin match en el ranking"})
            continue
        # El de mayor capitalización. Binance lista el activo real.
        mejor = max(candidatos, key=lambda m: m.get("market_cap") or 0)
        amb = len(candidatos) > 1
        rank = mejor.get("market_cap_rank") or 0
        # Un match cuyo mejor candidato está muy abajo en el ranking es
        # sospechoso: Binance no lista perpetuos de la moneda número 10.000.
        # MEMEUSDT resolviendo a 'memetoon' (rank 10.274) es el caso típico.
        # Se marca en vez de elegirlo en silencio — misma regla que
        # `data_quality: 'conflict'` en smallcaps/RESEARCH.md §1.3.
        dudoso = (not rank) or rank > 2000
        ambiguos += amb
        notas = []
        if amb:
            notas.append(f"{len(candidatos)} candidatos")
        if dudoso:
            notas.append(f"RANK PROFUNDO ({rank}) — verificar a mano")
        filas.append({
            "simbolo": simbolo, "coingecko_id": mejor["id"], "ticker": ticker,
            "multiplicador": mult,
            "mcap_rank": rank or "",
            "ambiguo": int(amb),
            "dudoso": int(dudoso),
            "nota": "; ".join(notas),
        })

    campos = ["simbolo", "coingecko_id", "ticker", "multiplicador",
              "mcap_rank", "ambiguo", "dudoso", "nota"]
    with MAPEO_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)

    con = conectar()
    con.execute("DELETE FROM mapeo")
    con.executemany(
        "INSERT INTO mapeo (simbolo,coingecko_id,ticker,multiplicador,"
        "mcap_rank,ambiguo,dudoso,nota) VALUES (:simbolo,:coingecko_id,:ticker,"
        ":multiplicador,:mcap_rank,:ambiguo,:dudoso,:nota)",
        [dict(f, mcap_rank=f["mcap_rank"] or None) for f in filas])
    con.commit()

    resueltos = sum(1 for f in filas if f["coingecko_id"])
    print(f"\n  resueltos : {resueltos}/{len(filas)}")
    print(f"  sin match : {sin_match}   (monedas fuera del top {limite_rank})")
    dudosos = sum(f["dudoso"] for f in filas)
    print(f"  ambiguos  : {ambiguos}   ← más de un candidato con ese símbolo")
    print(f"  dudosos   : {dudosos}   ← EXCLUIDOS del análisis primario")
    print("               (sin match, o match con rank >2000: acciones")
    print("                tokenizadas y clones que no son el token real)")
    print(f"\nescrito en {MAPEO_CSV}")
    print("El CSV se versiona en git a propósito: es la pieza que hay que")
    print("poder auditar y corregir a mano cuando un mapeo salga mal.")


# ─────────────────────────────── descarga ──────────────────────────────────

def bajar_supply(limite: int | None = None) -> None:
    """Descarga la supply, priorizando lo que el análisis realmente necesita.

    El free tier tolera ~5 peticiones/min sostenidas, así que el orden importa:
    de las 568 monedas mapeadas solo 456 tienen algún evento, y las 300 con más
    eventos cubren el 90% de la muestra. Bajar por ranking de capitalización
    gastaba el presupuesto en monedas grandes que casi nunca disparan el
    detector.
    """
    con = conectar()
    tiene_eventos = {t[0] for t in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='eventos'")}
    if tiene_eventos:
        ids = [r[0] for r in con.execute("""
            SELECT m.coingecko_id
              FROM mapeo m
              LEFT JOIN eventos e ON e.simbolo = m.simbolo
                   AND e.rvol >= 5 AND e.quote_volume >= 2e6
             WHERE m.coingecko_id != '' AND m.dudoso = 0
             GROUP BY m.coingecko_id
             ORDER BY COUNT(e.d) DESC, m.mcap_rank IS NULL, m.mcap_rank
        """).fetchall()]
    else:
        ids = [r[0] for r in con.execute(
            "SELECT DISTINCT coingecko_id FROM mapeo "
            "WHERE coingecko_id != '' AND dudoso = 0 "
            "ORDER BY mcap_rank IS NULL, mcap_rank").fetchall()]
    ya = {r[0] for r in con.execute(
        "SELECT coingecko_id FROM supply_meta WHERE n_puntos > 100").fetchall()}
    pendientes = [i for i in ids if i not in ya]
    if limite:
        pendientes = pendientes[:limite]

    print(f"monedas mapeadas: {len(ids)}  ·  ya bajadas: {len(ya)}  "
          f"·  pendientes: {len(pendientes)}")
    if not pendientes:
        print("nada que bajar")
        return

    hoy = datetime.now(timezone.utc).isoformat()
    ok = vacias = 0
    for i, cg_id in enumerate(pendientes, 1):
        datos = _pedir(f"coins/{cg_id}/market_chart",
                       {"vs_currency": "usd", "days": 365, "interval": "daily"})
        if not datos or not datos.get("prices"):
            vacias += 1
            con.execute("INSERT OR REPLACE INTO supply_meta VALUES (?,?,?)",
                        (cg_id, hoy, 0))
            con.commit()
            continue

        precios = {t: v for t, v in datos["prices"]}
        mcaps = {t: v for t, v in datos.get("market_caps", [])}
        filas = []
        for t in sorted(set(precios) & set(mcaps)):
            p, m = precios[t], mcaps[t]
            if not p or not m:
                continue
            d = datetime.fromtimestamp(t / 1000, tz=timezone.utc).date()
            filas.append((cg_id, d.isoformat(), p, m, m / p))

        if filas:
            con.executemany(
                "INSERT OR REPLACE INTO supply VALUES (?,?,?,?,?)", filas)
            ok += 1
        con.execute("INSERT OR REPLACE INTO supply_meta VALUES (?,?,?)",
                    (cg_id, hoy, len(filas)))
        con.commit()

        if i % 25 == 0 or i == len(pendientes):
            print(f"  {i}/{len(pendientes)}  ·  ok {ok}  ·  vacías {vacias}",
                  flush=True)

    print(f"\nlisto: {ok} series descargadas, {vacias} sin datos")


def estadisticas() -> None:
    con = conectar()
    n, nid, d0, d1 = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT coingecko_id), MIN(d), MAX(d) "
        "FROM supply").fetchone()
    if not n:
        print("no hay supply todavía — corré `python supply.py --mapeo` y luego `--bajar`")
        return
    print(f"puntos de supply : {n:,}")
    print(f"monedas          : {nid}")
    print(f"rango            : {d0} → {d1}")
    print(f"lookback elegido : {LOOKBACK_DIAS} días "
          f"→ ventana de eventos ≈ {365-LOOKBACK_DIAS} días")

    print(f"\ncrecimiento de supply a {LOOKBACK_DIAS}d — los 12 que más diluyeron:")
    filas = con.execute(f"""
        WITH ult AS (
            SELECT coingecko_id, MAX(d) d FROM supply GROUP BY coingecko_id
        )
        SELECT s2.coingecko_id,
               (s2.supply / s1.supply - 1) * 100 crec,
               s2.supply
          FROM ult u
          JOIN supply s2 ON s2.coingecko_id = u.coingecko_id AND s2.d = u.d
          JOIN supply s1 ON s1.coingecko_id = u.coingecko_id
               AND s1.d = date(u.d, '-{LOOKBACK_DIAS} days')
         WHERE s1.supply > 0
         ORDER BY crec DESC LIMIT 12
    """).fetchall()
    for cg_id, crec, sup in filas:
        print(f"  {cg_id:<28} {crec:>+9.1f}%   {sup:>18,.0f} tokens")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mapeo", action="store_true", help="construir mapeo.csv")
    p.add_argument("--bajar", action="store_true", help="descargar supply")
    p.add_argument("--limite", type=int, help="tope de monedas a bajar")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args()

    if args.mapeo:
        construir_mapeo()
    if args.bajar:
        bajar_supply(args.limite)
    if args.stats or not (args.mapeo or args.bajar):
        estadisticas()
    return 0


if __name__ == "__main__":
    sys.exit(main())
