#!/usr/bin/env python3
"""
Verifica cada fuente que RESEARCH.md dice que se puede consumir.

El research afirma cosas concretas —que el archivo de Binance conserva los
símbolos deslistados, que la supply circulante se puede derivar, que CoinGecko
corta en 365 días— y esas afirmaciones envejecen: los proveedores cambian de
política sin avisar. DefiLlama tenía las emisiones abiertas y ahora devuelve
402.

Este script vuelve a preguntar. Cada chequeo imprime lo que obtuvo, no lo que
esperaba, así que si una fuente se cerró se ve acá antes de que aparezca como
un dataset corto en silencio.

    python verificar_fuentes.py              # todo
    python verificar_fuentes.py --solo supply universo

Sin API key, sin cuenta, sin dependencias fuera de la librería estándar salvo
requests.
"""

import argparse
import io
import random
import re
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from urllib.parse import urlencode

import requests

TIMEOUT = 25
ARCHIVO = "https://data.binance.vision"
LISTADO = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
COINGECKO = "https://api.coingecko.com/api/v3"

# Deslistados hace años. Si el archivo los conserva, no hay sesgo de
# supervivencia; si algún día devuelven 404, el estudio entero queda inválido y
# hay que enterarse por acá.
DESLISTADOS = ["SRMUSDT", "TOMOUSDT", "FTTUSDT", "BTCSTUSDT"]
MES_PRUEBA = "2022-10"

# Token de referencia para la derivación de supply: ARB tiene cliffs mensuales
# grandes y visibles, así que si la derivación funciona se ve a simple vista.
TOKEN_PRUEBA = ("arbitrum", "ARB")


class Resultado:
    """Acumula los chequeos para poder imprimir un veredicto al final."""

    def __init__(self):
        self.filas = []

    def añadir(self, capa, detalle, ok, nota=""):
        self.filas.append((capa, detalle, ok, nota))

    def resumen(self):
        print("\n" + "=" * 74)
        print("  VEREDICTO")
        print("=" * 74)
        for capa, detalle, ok, nota in self.filas:
            marca = "OK  " if ok else "FALLA"
            print(f"  [{marca}] {capa:<22} {detalle:<28} {nota}")
        fallas = [f for f in self.filas if not f[2]]
        print()
        if not fallas:
            print("  Todas las fuentes de RESEARCH.md §1 siguen disponibles.")
        else:
            print(f"  {len(fallas)} chequeo(s) fallaron. RESEARCH.md §1 quedó desactualizado")
            print("  en esos puntos: corregir el documento antes de seguir.")
        return len(fallas)


def _codigo(url, metodo="GET"):
    """Devuelve el código HTTP sin descargar de más cuando alcanza con HEAD."""
    try:
        r = requests.request(metodo, url, timeout=TIMEOUT, stream=True)
        return r.status_code
    except requests.RequestException as e:
        return f"ERR {type(e).__name__}"


# ───────────────────────────── archivo de Binance ──────────────────────────


def verificar_archivo(res):
    print("\n── 1. Archivo público de Binance ".ljust(74, "─"))

    rutas = {
        "klines futuros": f"{ARCHIVO}/data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2024-06.zip",
        "funding rate": f"{ARCHIVO}/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-06.zip",
        "metrics (OI)": f"{ARCHIVO}/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-03.zip",
        "bookDepth": f"{ARCHIVO}/data/futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-2024-06-03.zip",
    }
    for nombre, url in rutas.items():
        code = _codigo(url, "HEAD")
        ok = code == 200
        print(f"  {nombre:<18} HTTP {code}")
        res.añadir("archivo binance", nombre, ok, f"HTTP {code}")

    # El contenido de metrics es lo que hace único a este archivo: open interest
    # cada 5 minutos con historia, gratis. Vale confirmar las columnas y no solo
    # que el zip exista.
    try:
        r = requests.get(rutas["metrics (OI)"], timeout=TIMEOUT)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        lineas = z.read(z.namelist()[0]).decode().splitlines()
        cols = lineas[0].split(",")
        tiene_oi = "sum_open_interest" in cols
        print(f"\n  metrics: {len(lineas) - 1} filas, {len(cols)} columnas")
        print(f"    open interest presente: {tiene_oi}")
        print(f"    columnas: {', '.join(cols[:4])} …")
        res.añadir("archivo binance", "metrics tiene OI", tiene_oi,
                   f"{len(lineas)-1} filas/día")
    except Exception as e:
        print(f"  no se pudo leer metrics: {e}")
        res.añadir("archivo binance", "metrics tiene OI", False, str(e)[:30])


def verificar_deslistados(res):
    """El chequeo que decide la viabilidad del estudio.

    Sin retención de deslistados solo se puede mirar lo que sobrevivió, y lo
    que sobrevivió no es una muestra aleatoria: los que más diluyeron son
    justamente los que Binance sacó del listado.
    """
    print("\n── 2. ¿El archivo conserva los deslistados? ".ljust(74, "─"))

    vivos = 0
    for sym in DESLISTADOS:
        url = f"{ARCHIVO}/data/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{MES_PRUEBA}.zip"
        code = _codigo(url, "HEAD")
        ok = code == 200
        vivos += ok
        print(f"  {sym:<12} klines {MES_PRUEBA}   HTTP {code}")

    todos = vivos == len(DESLISTADOS)
    print(f"\n  {vivos}/{len(DESLISTADOS)} deslistados conservan historia")
    if todos:
        print("  → sin sesgo de supervivencia por el lado del proveedor")
    else:
        print("  → CUIDADO: el archivo dejó de conservar deslistados")
    res.añadir("sesgo supervivencia", "deslistados retenidos", todos,
               f"{vivos}/{len(DESLISTADOS)}")


def obtener_universo():
    """Enumera los símbolos del archivo, incluidos los que ya no cotizan.

    Se usa el listado estilo S3 y no el endpoint REST porque `fapi.binance.com`
    devuelve 451 en varias regiones, y porque el REST solo lista lo vivo.
    """
    url = f"{LISTADO}?{urlencode({'delimiter': '/', 'prefix': 'data/futures/um/monthly/klines/'})}"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    simbolos = re.findall(
        r"<Prefix>data/futures/um/monthly/klines/([^/]+)/</Prefix>", r.text)
    truncado = "<IsTruncated>true</IsTruncated>" in r.text
    return simbolos, truncado


def verificar_universo(res):
    print("\n── 3. Universo histórico ".ljust(74, "─"))

    try:
        simbolos, truncado = obtener_universo()
    except Exception as e:
        print(f"  no se pudo enumerar: {e}")
        res.añadir("universo", "enumeración S3", False, str(e)[:30])
        return None

    usdt = [s for s in simbolos if s.endswith("USDT")]
    usdc = [s for s in simbolos if s.endswith("USDC")]
    busd = [s for s in simbolos if s.endswith("BUSD")]
    mult = [s for s in usdt if re.match(r"^1000+", s)]

    print(f"  símbolos en el archivo : {len(simbolos)}")
    print(f"    USDT                 : {len(usdt)}")
    print(f"    USDC                 : {len(usdc)}")
    print(f"    BUSD (discontinuada) : {len(busd)}")
    print(f"    con prefijo 1000x    : {len(mult)}  ← trampa de mapeo (§1.2)")
    print(f"  listado truncado       : {truncado}")

    presentes = [d for d in DESLISTADOS if d in simbolos]
    print(f"  deslistados en la lista: {len(presentes)}/{len(DESLISTADOS)}")

    ok = len(usdt) > 500 and not truncado
    res.añadir("universo", "enumeración S3", ok, f"{len(usdt)} perps USDT")
    return usdt


def verificar_ancho_temporal(res, usdt, n=60, semilla=7):
    """Estima cuántos perpetuos estaban vivos en cada momento.

    Importa porque el método depende del ancho del corte transversal: ir más
    atrás en el tiempo compra historia a cambio de perder instrumentos, y en
    algún punto deja de convenir.
    """
    print("\n── 4. Ancho del corte transversal en el tiempo ".ljust(74, "─"))
    if not usdt:
        print("  (sin universo, se omite)")
        return

    random.seed(semilla)
    muestra = random.sample(usdt, min(n, len(usdt)))

    def existe(sym, mes):
        url = f"{ARCHIVO}/data/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{mes}.zip"
        return _codigo(url, "HEAD") == 200

    print(f"  muestra de {len(muestra)} símbolos, semilla {semilla}\n")
    for mes in ["2022-06", "2023-06", "2024-06", "2025-06"]:
        with ThreadPoolExecutor(20) as ex:
            vivos = sum(ex.map(lambda s: existe(s, mes), muestra))
        est = round(vivos / len(muestra) * len(usdt))
        print(f"    {mes}:  {vivos:>2}/{len(muestra)}  → estimado ~{est} de {len(usdt)}")

    res.añadir("universo", "ancho temporal", True, "ver tabla")


# ──────────────────────────────── capa de supply ───────────────────────────


def verificar_supply(res):
    """La capa que sostiene la tesis y la única que no es gratis del todo."""
    print("\n── 5. Capa de supply (el cuello de botella) ".ljust(74, "─"))

    cg_id, ticker = TOKEN_PRUEBA

    # 5a. Lo que sí funciona gratis.
    url = f"{COINGECKO}/coins/{cg_id}/market_chart?vs_currency=usd&days=365&interval=daily"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        code = r.status_code
        d = r.json() if code == 200 else {}
    except Exception as e:
        code, d = f"ERR {type(e).__name__}", {}

    precios = {t: v for t, v in d.get("prices", [])}
    mcaps = {t: v for t, v in d.get("market_caps", [])}
    print(f"  market_chart days=365   HTTP {code}  ({len(precios)} puntos)")
    ok365 = code == 200 and len(precios) > 300
    res.añadir("supply", "CoinGecko 365d", ok365, f"HTTP {code}")

    # 5b. La derivación. Si esto no reproduce los cliffs, el feature no existe.
    if ok365:
        ts = sorted(set(precios) & set(mcaps))
        serie = [(t, mcaps[t] / precios[t]) for t in ts if precios[t]]
        if len(serie) > 30:
            ini, fin = serie[0][1], serie[-1][1]
            crec = (fin / ini - 1) * 100
            saltos = [
                (t, (serie[i][1] / serie[i - 1][1] - 1) * 100)
                for i, (t, _) in enumerate(serie)
                if i and serie[i][1] / serie[i - 1][1] - 1 > 0.008
            ]
            print(f"\n  {ticker}: supply derivada = market_cap / price")
            print(f"    inicio  {ini:>18,.0f} tokens")
            print(f"    final   {fin:>18,.0f} tokens")
            print(f"    crecimiento 12m      {crec:+.1f}%")
            print(f"    saltos >0,8% (cliffs) {len(saltos)}")
            for t, ch in saltos[:5]:
                # UTC explícito: las velas y los cortes de funding son UTC, y
                # una fecha corrida un día desalinearía el cliff del evento.
                dia = datetime.fromtimestamp(t / 1000, tz=timezone.utc).date()
                print(f"      {dia}  {ch:+.2f}%")
            derivable = len(saltos) > 0
            res.añadir("supply", "derivación mcap/price", derivable,
                       f"{crec:+.1f}% 12m, {len(saltos)} cliffs")

    # 5c. Lo que NO funciona. Se prueba para que el research no mienta por
    # omisión cuando alguna de estas se reabra.
    print("\n  fuentes de historia larga:")
    cerradas = {
        "CoinGecko days=max": f"{COINGECKO}/coins/{cg_id}/market_chart?vs_currency=usd&days=max&interval=daily",
        "CoinGecko /history": f"{COINGECKO}/coins/{cg_id}/history?date=01-06-2024&localization=false",
        "CoinPaprika histórico": "https://api.coinpaprika.com/v1/tickers/arb-arbitrum/historical?start=2023-04-01&interval=1d",
        "CryptoCompare histoday": "https://min-api.cryptocompare.com/data/v2/histoday?fsym=ARB&tsym=USD&limit=100",
        "DefiLlama /emissions": "https://api.llama.fi/emissions",
    }
    reabierta = []
    for nombre, u in cerradas.items():
        code = _codigo(u)
        estado = "ABIERTA" if code == 200 else "cerrada"
        if code == 200:
            reabierta.append(nombre)
        print(f"    {nombre:<24} HTTP {code}  {estado}")

    # Que sigan cerradas es lo que RESEARCH.md §1.2 documenta, así que el
    # chequeo pasa. Lo que invalida el documento es que alguna se REABRA: ahí
    # la limitación de 12m de §2 y §7.1 deja de aplicar y hay que reescribir.
    if reabierta:
        print(f"\n  Se reabrió: {', '.join(reabierta)}")
        print("  → RESEARCH.md §1.2 quedó desactualizado A FAVOR. Actualizar:")
        print("    con historia larga gratis desaparece la limitación de 12m (§2, §7.1).")
    res.añadir("supply", "historia larga", not reabierta,
               "sigue de pago, como dice §1.2" if not reabierta
               else f"REABIERTA: {', '.join(reabierta)}")


def verificar_mapeo(res):
    """Cuantifica la colisión de símbolos, que es la vía más probable de meter
    supply de la moneda equivocada en el dataset."""
    print("\n── 6. Mapeo símbolo → moneda ".ljust(74, "─"))

    try:
        r = requests.get(f"{COINGECKO}/coins/list", timeout=TIMEOUT)
        monedas = r.json()
    except Exception as e:
        print(f"  no se pudo obtener la lista: {e}")
        res.añadir("mapeo", "coins/list", False, str(e)[:30])
        return

    from collections import Counter

    cuenta = Counter(m["symbol"].lower() for m in monedas)
    dup = [s for s, n in cuenta.items() if n > 1]
    pct = 100 * len(dup) / len(cuenta) if cuenta else 0

    print(f"  monedas en CoinGecko   : {len(monedas)}")
    print(f"  símbolos duplicados    : {len(dup)}  ({pct:.1f}%)")
    print("\n  ejemplos de colisión:")
    for s in ["pepe", "sol", "arb", "op"]:
        ids = [m["id"] for m in monedas if m["symbol"].lower() == s]
        print(f"    {s!r:<8} → {len(ids):>2} ids   {ids[:3]}")

    print("\n  → el mapeo NO se resuelve por símbolo. mapeo.csv, a mano, versionado.")
    # No es una falla: es una restricción de diseño confirmada.
    res.añadir("mapeo", "colisión de símbolos", True, f"{pct:.1f}% duplicados")


CHEQUEOS = {
    "archivo": verificar_archivo,
    "deslistados": verificar_deslistados,
    "supply": verificar_supply,
    "mapeo": verificar_mapeo,
}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo", nargs="+",
                   choices=list(CHEQUEOS) + ["universo"],
                   help="correr solo estos chequeos")
    p.add_argument("--sin-ancho", action="store_true",
                   help="omitir el muestreo temporal (240 peticiones)")
    args = p.parse_args()

    res = Resultado()
    pedidos = args.solo or (list(CHEQUEOS) + ["universo"])

    print("=" * 74)
    print("  VERIFICACIÓN DE FUENTES — cripto/RESEARCH.md §1")
    print(f"  {date.today()}")
    print("=" * 74)

    for nombre in ["archivo", "deslistados"]:
        if nombre in pedidos:
            CHEQUEOS[nombre](res)

    if "universo" in pedidos:
        usdt = verificar_universo(res)
        if not args.sin_ancho:
            verificar_ancho_temporal(res, usdt)

    for nombre in ["supply", "mapeo"]:
        if nombre in pedidos:
            CHEQUEOS[nombre](res)

    return 1 if res.resumen() else 0


if __name__ == "__main__":
    sys.exit(main())
