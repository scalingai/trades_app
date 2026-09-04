#!/usr/bin/env python3
"""La watchlist del día, armada por la app en vez de a ojo.

**QUE PROBLEMA RESUELVE.** Hasta hoy el embudo de `/vivo` empezaba en "los
papeles que alguien tipeó". `OPERATIVA.md` §1 lo dice sin vueltas: abrir
`Tools → Gainers/Losers`, filtro `Vol>1M Price<10`, y anotar "los que suban
fuerte". Esa última frase es **la única parte de todo el sistema que no está
medida ni es reproducible**: dos días con el mismo mercado pueden dar dos
watchlists distintas según qué viste primero.

El backtest, en cambio, no elige a ojo. `poblacion_observable.py` construye un
CENSO —no una muestra— con tres criterios que se conocen ANTES de la campana:

    gap ≥ 25%   ·   liquidez previa ≥ $150k   ·   precio previo $0.20–$20

Eso da ~2.050 eventos en 472 días hábiles: **4,3 papeles por día**. Este script
aplica esos mismos criterios en vivo, así lo que se opera sale de la misma
población sobre la que se midió.

**POR QUE YAHOO Y NO POLYGON.** Lo medí el 2026-09-03 contra las dos APIs:

    Polygon free   snapshot del mercado          NOT_AUTHORIZED
                   agregado diario de HOY        NOT_AUTHORIZED
                   minutos de HOY                NOT_AUTHORIZED
                   -> no ve el día en curso. Sirve para histórico y nada más.
                   Y a 5 llamadas/min, mirar los 3.178 candidatos elegibles
                   uno por uno son 10,6 horas.

    Trade The Pool `InstrumentsManager` expone GetInstruments(symbol),
                   Subscribe y los eventos de quotes. NO expone el universo:
                   en todo `TradeApi.dll` no hay un solo tipo con Screener,
                   Watchlist, Gainer o Scanner en el nombre. La lista de
                   gainers vive únicamente en el panel de la UI.

    Yahoo          screener a medida, sin cuenta y sin clave. Filtra por
                   region / percentchange / intradayprice / dayvolume, que
                   son exactamente los criterios del censo.

**LA CONTRA, QUE ES REAL.** Es una API no oficial: Yahoo la puede romper sin
avisar, y ya lo hizo en 2023 cuando agregó el crumb. Por eso este script NO es
un eslabón del que dependa la operativa: escribe un archivo de texto que
después se puede editar a mano. Si Yahoo se cae una mañana, tipeás la watchlist
como hasta ayer y no se rompe nada más.

**QUIEN DA QUE DATO.** Yahoo elige los NOMBRES; Trade The Pool sigue dando los
PRECIOS con los que se opera. El precio que este script escribe al lado del
ticker es de referencia y cumple un solo trabajo: desambiguar. Un mismo símbolo
existe en varios mercados y `GetInstruments("SSM")` devolvía uno de $59 cuando
el nuestro estaba a $3,85.

    python escaner.py               # muestra qué encontró, NO escribe
    python escaner.py --escribir    # reemplaza watchlist.txt
    python escaner.py --gap 20      # afloja el umbral para ver qué entra
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.cookiejar
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

NY = ZoneInfo("America/New_York")

# Los umbrales del censo (poblacion_observable.py). No son opinables: son los
# que definen la población sobre la que se midieron TODOS los resultados del
# proyecto. Cambiarlos hace que lo que se opera deje de ser lo que se midió.
GAP_MIN = 25.0
LIQ_MIN = 1.5e5          # mediana en dólares de los 20 días previos
PRECIO_MIN = 0.20
PRECIO_MAX = 20.0

# Filtro extra de OPERATIVA.md §1, que NO está en el censo. Se aplica aparte y
# se reporta aparte, para que se vea cuántos papeles cuesta.
PISO_OPERATIVO = 2.0
# OTC no entra: no se puede shortear en TradeZero y Yahoo no tiene barras de 1
# minuto para armar el feed (SIVEF, 2026-09-04: en la watchlist y sin una sola
# barra). Son los codigos de mercado de Yahoo para Pink, OTCQB y OTCQX.
OTC = {"PNK", "OQB", "OQX", "OEM", "OBB", "OTC"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      " (KHTML, like Gecko) Chrome/125.0 Safari/537.36")


class Yahoo:
    """Cliente mínimo, sólo stdlib — igual que `massive/client.py`.

    El crumb es un token anti-abuso que Yahoo pide desde 2023. Se saca solo:
    una visita cualquiera deja las cookies, y con ellas `getcrumb` lo entrega.
    No hace falta cuenta, ni clave, ni tarjeta.
    """

    def __init__(self) -> None:
        cj = http.cookiejar.CookieJar()
        self._op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj))
        self._op.addheaders = [("User-Agent", UA), ("Accept", "*/*")]
        self.crumb = ""
        self.llamadas = 0

    def _abrir(self, req, timeout=30):
        self.llamadas += 1
        with self._op.open(req, timeout=timeout) as r:
            return r.read()

    def _get(self, url):
        return self._abrir(urllib.request.Request(url))

    def autenticar(self) -> None:
        # Timeout corto a proposito: `fc.yahoo.com` a veces tarda ocho segundos
        # en contestar un 404 que igual no nos sirve. Con las dos semillas al
        # timeout de 30 la autenticacion sola se comia 9s de los 51 que tardaba
        # el escaneo entero.
        for semilla in ("https://fc.yahoo.com",
                        "https://finance.yahoo.com/quote/AAPL"):
            try:
                self._abrir(urllib.request.Request(semilla), timeout=5)
            except Exception:
                pass   # una de las dos alcanza; la otra puede tirar 404
        try:
            self.crumb = self._get(
                "https://query1.finance.yahoo.com/v1/test/getcrumb").decode().strip()
        except Exception:
            self.crumb = ""

    def predefinido(self, nombre: str, cuantos: int = 100) -> list[dict]:
        """Screeners que Yahoo ya trae armados. NO piden crumb.

        Se usan como red de arrastre: en pre-market el `percentchange` del
        screener a medida todavía es el de AYER —el campo que cambia es
        `preMarketChangePercent`, que no se puede filtrar— así que la única
        forma de no perderse un gapper es traer un pool amplio y calcular el
        gap nosotros, papel por papel, con las cotizaciones en lote.
        """
        u = ("https://query1.finance.yahoo.com/v1/finance/screener/predefined/"
             f"saved?scrIds={nombre}&count={cuantos}&formatted=false")
        try:
            d = json.loads(self._get(u))
        except Exception:
            return []
        res = (d.get("finance", {}).get("result") or [{}])[0]
        return res.get("quotes") or []

    def screener(self, *, gap: float, cuantos: int = 100) -> list[dict]:
        """El screener a medida, con los criterios del censo."""
        cuerpo = {
            "size": cuantos, "offset": 0,
            "sortField": "percentchange", "sortType": "DESC",
            "quoteType": "EQUITY", "userId": "", "userIdType": "guid",
            "query": {"operator": "AND", "operands": [
                {"operator": "eq", "operands": ["region", "us"]},
                {"operator": "gt", "operands": ["percentchange", gap]},
                {"operator": "gt", "operands": ["intradayprice", PRECIO_MIN]},
                {"operator": "lt", "operands": ["intradayprice", PRECIO_MAX]},
            ]},
        }
        url = "https://query1.finance.yahoo.com/v1/finance/screener"
        if self.crumb:
            url += "?crumb=" + urllib.parse.quote(self.crumb)
        req = urllib.request.Request(
            url, data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"})
        try:
            d = json.loads(self._abrir(req))
        except urllib.error.HTTPError as e:
            print(f"  ! el screener a medida devolvió HTTP {e.code} — se sigue "
                  f"con los predefinidos", file=sys.stderr)
            return []
        except Exception as e:
            print(f"  ! el screener a medida falló ({type(e).__name__}) — se "
                  f"sigue con los predefinidos", file=sys.stderr)
            return []
        res = (d.get("finance", {}).get("result") or [{}])[0]
        return res.get("quotes") or []

    def cotizaciones(self, simbolos: list[str]) -> list[dict]:
        """Datos completos de una lista de símbolos, en tandas.

        Acá vienen los campos que el screener no da: el cierre previo (sin el
        no hay gap), el volumen promedio (la liquidez) y, en pre-market, el
        `preMarketChangePercent`, que es EL dato del día.
        """
        # EN TANDAS CHICAS Y EN PARALELO. Medido, porque la intuicion fallo:
        #
        #   6 tandas de 50, en fila india   32,7s
        #   2 tandas de 200, en paralelo    49,7s   <- peor
        #   6 tandas de 50, en paralelo     ~11s
        #
        # Yahoo tarda MAS que proporcional con muchos simbolos por llamada, asi
        # que agrandar la tanda para hacer menos llamadas es exactamente el
        # movimiento equivocado. Lo que paga es el paralelismo, y para eso
        # hacen falta varias tandas.
        tandas = [simbolos[i:i + 50] for i in range(0, len(simbolos), 50)]

        def pedir(tanda):
            u = ("https://query1.finance.yahoo.com/v7/finance/quote?symbols="
                 + urllib.parse.quote(",".join(tanda)))
            if self.crumb:
                u += "&crumb=" + urllib.parse.quote(self.crumb)
            try:
                d = json.loads(self._get(u))
            except Exception:
                return []
            return d.get("quoteResponse", {}).get("result") or []

        if len(tandas) == 1:
            return pedir(tandas[0])
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            return [q for parte in ex.map(pedir, tandas) for q in parte]


def gap_de(q: dict) -> tuple[float | None, str]:
    """El gap del papel y de dónde salió.

    En pre-market el número que importa es `preMarketChangePercent`: el
    `regularMarketChangePercent` todavía es el de ayer y usarlo sería mirar la
    película equivocada. Con el mercado abierto, al revés.
    """
    estado = q.get("marketState") or "?"
    if estado in ("PRE", "PREPRE"):
        v = q.get("preMarketChangePercent")
        if v is not None:
            return float(v), "pre-market"
        # Sin dato de pre-market el papel todavía no operó afuera de hora: no
        # es un gap de 0%, es "no se sabe". Devolverlo como 0 lo descartaría
        # por la razón equivocada.
        return None, "sin dato pre-market"
    v = q.get("regularMarketChangePercent")
    return (float(v), "sesión") if v is not None else (None, "sin dato")


def liquidez_de(q: dict) -> float | None:
    """Dólares operados por día, promedio. Es el proxy de `med_dollar_volume`.

    El censo usa la MEDIANA de los 20 días previos y Yahoo da el PROMEDIO de
    10 o de 3 meses. No es lo mismo —el promedio lo infla un solo día de
    locura— así que este filtro es más permisivo que el del censo, no más
    estricto. Preferible: deja entrar algún papel de más antes que perderse
    uno que el backtest sí contaba.
    """
    px = q.get("regularMarketPreviousClose") or q.get("regularMarketPrice")
    for campo in ("averageDailyVolume10Day", "averageDailyVolume3Month"):
        v = q.get(campo)
        if v and px:
            return float(v) * float(px)
    return None


def escanear(y: Yahoo, *, gap: float, verboso: bool = False) -> list[dict]:
    """Pool amplio -> cotizaciones completas -> criterios del censo."""
    pool: dict[str, dict] = {}
    for fila in y.screener(gap=gap):
        if fila.get("symbol"):
            pool[fila["symbol"]] = fila
    n_medida = len(pool)
    # Los tres predefinidos son independientes entre si: van juntos.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for filas in ex.map(y.predefinido,
                            ("day_gainers", "small_cap_gainers", "most_actives")):
            for fila in filas:
                if fila.get("symbol"):
                    pool.setdefault(fila["symbol"], fila)
    # PODAR ANTES DE PREGUNTAR. Las filas del screener YA traen el precio, y
    # pedir las cotizaciones completas es la parte cara del escaneo (~23s de
    # los 34). `most_actives` son cien nombres que en su mayoria cotizan muy
    # arriba de $20 y no van a pasar nunca: preguntar por ellos es pagar por
    # un descarte que se puede hacer gratis aca.
    #
    # En pre-market esto es ademas EXACTO, no una aproximacion: el
    # `regularMarketPrice` de esas filas todavia es el cierre de ayer, que es
    # justo contra lo que el censo define la banda de precio.
    def en_banda(fila):
        px = fila.get("regularMarketPrice")
        return px is None or PRECIO_MIN <= float(px) <= PRECIO_MAX

    antes = len(pool)
    pool = {k: v for k, v in pool.items() if en_banda(v)}
    if verboso:
        print(f"  pool: {n_medida} del screener a medida + "
              f"{antes - n_medida} de los predefinidos = {antes}"
              f" · {antes - len(pool)} podados por precio -> {len(pool)}")
    if not pool:
        return []

    qs = y.cotizaciones(sorted(pool))
    salida, descartes = [], {}
    for q in qs:
        tk = q.get("symbol")
        if not tk:
            continue
        g, origen = gap_de(q)
        prev = q.get("regularMarketPreviousClose")
        px = q.get("preMarketPrice") or q.get("regularMarketPrice") or prev
        liq = liquidez_de(q)

        def fuera(por):
            descartes[por] = descartes.get(por, 0) + 1

        if (q.get("exchange") or "").upper() in OTC:
            fuera("OTC"); continue
        if g is None:
            fuera("sin gap medible"); continue
        if g < gap:
            fuera(f"gap < {gap:.0f}%"); continue
        if not prev or not (PRECIO_MIN <= prev <= PRECIO_MAX):
            fuera("precio previo fuera de $0.20–$20"); continue
        if liq is None or liq < LIQ_MIN:
            fuera("liquidez previa < $150k"); continue
        salida.append({
            "ticker": tk, "precio": float(px or 0), "gap": g, "origen": origen,
            "prev": float(prev), "liq": liq,
            "float": q.get("sharesOutstanding"),
            "vol": q.get("regularMarketVolume"),
        })
    if verboso and descartes:
        print("  descartes:", " · ".join(
            f"{v} por {k}" for k, v in sorted(descartes.items(),
                                              key=lambda x: -x[1])))
    salida.sort(key=lambda x: -x["gap"])
    return salida


def escribir(papeles: list[dict], ruta: Path, *, piso: float) -> None:
    hoy = datetime.now(NY).strftime("%Y-%m-%d")
    lineas = [
        f"# Watchlist {hoy} · armada por escaner.py (Yahoo)",
        f"# censo: gap >= {GAP_MIN:.0f}% · liquidez previa >= ${LIQ_MIN:,.0f}"
        f" · precio previo ${PRECIO_MIN:.2f}-${PRECIO_MAX:.0f}"
        + (f" · piso operativo ${piso:.2f}" if piso else ""),
        "# TICKER precio_de_referencia",
        "#",
        "# El precio NO es decoracion: un mismo simbolo existe en varios",
        "# mercados y `GetInstruments` puede devolver el que no es.",
    ]
    lineas += [f"{p['ticker']} {p['precio']:.2f}" for p in papeles]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gap", type=float, default=GAP_MIN,
                    help=f"umbral de gap en %% (censo: {GAP_MIN:.0f})")
    ap.add_argument("--piso", type=float, default=PISO_OPERATIVO,
                    help=f"precio mínimo operativo (OPERATIVA §1: {PISO_OPERATIVO})")
    ap.add_argument("--escribir", action="store_true",
                    help="reemplaza watchlist.txt (sin esto sólo muestra)")
    a = ap.parse_args()

    ahora = datetime.now(NY)
    print(f"escáner · {ahora:%Y-%m-%d %H:%M} Nueva York")

    y = Yahoo()
    y.autenticar()
    print(f"  crumb: {'ok' if y.crumb else 'sin crumb (van los predefinidos)'}")

    papeles = escanear(y, gap=a.gap, verboso=True)
    print(f"  {y.llamadas} llamadas a Yahoo")

    if not papeles:
        print("\nNingún papel pasa los criterios. Eso es un resultado válido: "
              "el censo tiene 38 días con un solo papel y varios con ninguno.")
        return 0

    arriba = [p for p in papeles if p["precio"] >= a.piso]
    abajo = len(papeles) - len(arriba)

    print(f"\n{len(papeles)} pasan el censo"
          + (f", {len(arriba)} además el piso de ${a.piso:.2f}"
             f" ({abajo} quedan abajo)" if abajo else "") + "\n")
    print(f"  {'papel':<7} {'precio':>8} {'gap':>8} {'liquidez':>12} "
          f"{'float':>9}  origen")
    for p in papeles:
        marca = " " if p["precio"] >= a.piso else "·"
        fl = f"{p['float']/1e6:.1f}M" if p.get("float") else "—"
        print(f"{marca} {p['ticker']:<7} ${p['precio']:>7.2f} {p['gap']:>7.1f}%"
              f" ${p['liq']/1e6:>10.1f}M {fl:>9}  {p['origen']}")

    print(f"\nEl censo dice que un día típico tiene 4,3 papeles. "
          f"Hoy salieron {len(arriba)}.")
    if len(arriba) > 12:
        print("  ! Muy por encima de lo esperado: revisá el umbral antes de usarla.")

    ruta = Path(config.data_dir()) / "watchlist.txt"
    if not a.escribir:
        print(f"\nNo se escribió nada. Para reemplazar {ruta}:")
        print("  python escaner.py --escribir")
        return 0
    escribir(arriba, ruta, piso=a.piso)
    print(f"\nEscritos {len(arriba)} papeles en {ruta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
