#!/usr/bin/env python3
"""El sistema corriendo en vivo sobre el feed de Trade The Pool.

**La decisión de diseño que sostiene todo lo demás:** este archivo NO tiene
lógica de estrategia. Construye un objeto `Dia` idéntico al que usa el backtest
y llama a las MISMAS funciones — `señales_swing`, `clasificar_apertura`,
`stop`. Si en vivo decidiera con otro código, el backtest dejaría de significar
nada y no habría forma de saberlo hasta perder plata.

Por eso lo único que hay acá es plomería: leer el archivo que escribe el
indicador, agrupar por papel, y armar el `Dia`.

QUÉ MUESTRA. Cada minuto imprime, por papel de la watchlist:
  · si el día califica (apertura reclaim, precio >= piso) y por qué no si no
  · las señales que dispararon, con precio de entrada, stop y acciones
  · la exposición simultánea acumulada, que es lo que hay que tener localizado
  · el presupuesto de riesgo consumido, marcado a mercado

NO MANDA ÓRDENES. A propósito: la operativa es semiautomática y las órdenes las
pone Agus mirando esta pantalla. El puente es de una sola vía.

    python puente/vivo.py
    python puente/vivo.py --riesgo 400 --piso 2 --una-vez
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from chavineta import clasificar_apertura
from dias import APERTURA_RTH, CIERRE_RTH, Dia, hora
from motor import jornada
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

FEED = Path(config.data_dir()) / "feed_vivo.jsonl"
# La MISMA zona que usa el censo (`massive/minutes.py`), no un offset fijo.
# Con -4 fijo, a partir del primer domingo de noviembre cada barra quedaria una
# hora corrida: el filtro de las 10:00 dejaria de ser las 10:00, la apertura se
# clasificaria con velas de las 09:00 y nada de eso avisaria. El unico sintoma
# seria que los numeros dejan de parecerse al backtest, en enero.
NY = ZoneInfo("America/New_York")

# La configuración candidata, la misma que quedó medida. Si esto se desvía del
# backtest, lo que se opera no es lo que se midió.
STOP_PCT = 45.0
DESDE = 10.0
EXPANSION_MIN = 0.0            # la variante de 7,5 sesiones/mes
APERTURA = "reclaim"
PISO_DEFECTO = 2.0
MAX_TRAMOS = 40               # "sin tope": el mismo de test_costos_reales
MIN_ORDEN, POR_ACCION = 0.75, 0.005   # comision real de Trade The Pool


def leer_feed(ruta=FEED):
    """Todas las barras del archivo, agrupadas por (símbolo, fecha NY).

    El archivo es append-only y lo escriben varios gráficos a la vez, así que
    puede haber líneas repetidas o a medio escribir: se deduplican por
    (símbolo, timestamp) y las rotas se saltean sin ruido.
    """
    if not ruta.exists():
        return {}
    por_papel, vistos = {}, set()
    with open(ruta, "r", encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or not linea.startswith("{"):
                continue
            try:
                r = json.loads(linea)
                # Se conserva la zona horaria: las barras del censo son
                # timezone-aware y el visor deriva el desfase del eje con
                # `utcoffset()`. Un `Dia` en vivo con fechas naive rompia la
                # vista y, peor, era un `Dia` distinto del que mide el
                # backtest — justo lo que este archivo existe para evitar.
                t = datetime.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).astimezone(NY)
            except Exception:
                continue
            k = (r["s"], t)
            if k in vistos:
                continue
            vistos.add(k)
            clave = (r["s"], t.date().isoformat())
            por_papel.setdefault(clave, {"bars": [], "pc": r.get("pc") or 0.0})
            por_papel[clave]["bars"].append(
                (t, r["o"], r["h"], r["l"], r["c"], r["v"]))
            if r.get("pc"):
                por_papel[clave]["pc"] = r["pc"]
    for v in por_papel.values():
        v["bars"].sort(key=lambda b: b[0])
    return por_papel


AVISO_TAMANO_MB = 25.0


def limpiar(ruta=FEED, hoy=None):
    """Archiva todo lo que no sea de hoy. Devuelve (archivadas, conservadas).

    POR QUE HACE FALTA. El indicador vuelca TODA la historia del grafico cada
    vez que arranca —es lo que resuelve el agujero del premarket— asi que el
    archivo crece con cada reinicio de la plataforma: 657 KB medidos por un
    solo papel con veinte dias de historia. Con cuatro papeles y un par de
    reinicios por dia son varios MB diarios, y `leer_feed` lo lee ENTERO en
    cada refresco.

    NO se puede resolver leyendo el archivo al reves y cortando: los volcados
    de historia agregan barras VIEJAS despues de las nuevas, asi que el orden
    del archivo no es cronologico.

    Se corre con el mercado cerrado, a proposito. Reescribir el archivo mientras
    el indicador escribe puede perder la barra de ese minuto, y una barra
    perdida cambia el dia.
    """
    hoy = hoy or datetime.now(NY).date().isoformat()
    if not ruta.exists():
        return (0, 0)
    quedan, fuera = [], []
    with open(ruta, "r", encoding="utf-8", errors="replace") as fh:
        for linea in fh:
            if not linea.strip().startswith("{"):
                continue
            try:
                r = json.loads(linea)
                t = datetime.strptime(r["t"], "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc).astimezone(NY)
            except Exception:
                continue
            (quedan if t.date().isoformat() == hoy else fuera).append(linea)
    if not fuera:
        return (0, len(quedan))
    archivo = ruta.with_name(ruta.stem + "_hasta_" + hoy + ".jsonl")
    with open(archivo, "a", encoding="utf-8") as fh:
        fh.writelines(fuera)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.writelines(quedan)
    return (len(fuera), len(quedan))


def armar_dia(ticker, fecha, datos):
    """Un `Dia` real, el mismo que usa el backtest.

    `vol_dia` va en 0 porque el volumen del día completo no se conoce en vivo —
    y no hace falta: la configuración candidata usa `min_ratio_vol=0`, que es
    justamente uno de los look-ahead que sacamos.
    """
    if not datos["bars"] or not datos["pc"]:
        return None
    return Dia(ticker, fecha, datos["bars"], datos["pc"], None, 0)


def evaluar(dia, riesgo, piso):
    """Qué haría el sistema con este papel, ahora. Sin lógica propia.

    **Llama a `motor.jornada`, no reimplementa nada.** La primera versión de
    esta función copiaba la regla de presupuesto a mano y ya divergía: mostraba
    los 14 tramos del día cuando el motor habría cortado antes por límite
    diario, y marcaba a mercado tramos que en realidad ya habían saltado por
    stop. Un tramo de más en esta pantalla es una orden de más en el mercado.

    Que `jornada` sirva en vivo no es casualidad: `_trade` camina las barras
    desde la entrada hasta la última disponible, y en vivo la última barra es
    ahora. Los tramos que tocaron el stop vuelven cerrados con su pérdida real;
    los que siguen abiertos vuelven valuados al precio actual. Es exactamente
    la foto que hace falta para decidir.
    """
    out = {"ticker": dia.ticker, "bars": len(dia.bars), "descartes": []}

    ahora = hora(dia.bars[-1])
    out["hora"] = ahora
    out["precio"] = dia.bars[-1][4]
    out["pm_high"] = dia.pm_high
    out["expansion"] = dia.expansion_pct

    if ahora < APERTURA_RTH:
        out["descartes"].append("todavia en pre-market")
        return out

    # SIN PREMARKET NO HAY EXPANSION, Y EL FILTRO NO SE DA CUENTA.
    #
    # Si el grafico de la plataforma viene sin sesion extendida, la primera
    # barra es de las 09:30 y `expansion_pct` queda en None. El filtro de abajo
    # hace `(None or 0) < 0`, que es False: el dia PASA el filtro como si
    # tuviera expansion medida. Es el peor tipo de falla —opera de mas y no
    # avisa—, asi que se corta explicito.
    if dia.pm_high is None or dia.expansion_pct is None:
        out["sin_premarket"] = True
        out["descartes"].append(
            "sin premarket: prendé la sesión extendida en el gráfico "
            "(sin eso no hay expansión y el filtro no sirve)")
        return out

    if (dia.expansion_pct or 0) < EXPANSION_MIN:
        out["descartes"].append(
            f"expansion {dia.expansion_pct:.0f}% < {EXPANSION_MIN:.0f}%")

    # La etiqueta de apertura necesita barras hasta las 10:00 y por eso no se
    # puede entrar antes: saltearse esto fue uno de los look-ahead del proyecto.
    ap = clasificar_apertura(dia, hasta=10.0) if ahora >= 10.0 else None
    out["apertura"] = ap
    if ahora < 10.0:
        out["descartes"].append("la apertura se clasifica a las 10:00")
        return out
    if ap != APERTURA:
        out["descartes"].append(f"abrio {ap}, se opera {APERTURA}")
        return out

    señal = lambda d: [i for i in señales_swing(d, desde=DESDE)
                       if (d.bars[i][4] or 0) >= piso]
    j = jornada(dia, señal, lado="short", stop_pct=STOP_PCT, riesgo=riesgo,
                max_trades=MAX_TRAMOS)
    if not j:
        out["tramos"] = []
        return out

    px = dia.bars[-1][4] or 0
    tramos, equity = [], 0.0
    for t in j["detalle"]:
        # `h_sal` es la ultima barra disponible para los que siguen abiertos, y
        # la barra del stop para los que saltaron. Se distinguen por el motivo.
        viva = t["motivo"] not in ("stop", "objetivo")
        tramos.append({
            "h": t["h_ent"], "precio": t["p_ent"],
            "stop": t["p_ent"] * (1 + STOP_PCT / 100.0),
            "acciones": t["acciones"], "nominal": t["nominal"],
            "viva": viva, "motivo": t["motivo"], "pnl": t["pnl"],
            "h_sal": t["h_sal"], "p_sal": t["p_sal"]})
        equity += t["pnl"]

    # PICO DE EXPOSICION SIMULTANEA — es lo que hay que tener localizado, y no
    # la suma de los tramos. El locate se reserva una vez por papel y por dia
    # para el maximo simultaneo; contarlo como suma lo sobreestimaba hasta 9x.
    ev = []
    for t in j["detalle"]:
        ev.append((t["h_ent"], +t["acciones"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0,
                   -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))
    a = pico = 0.0
    for _, da in ev:
        a += da
        pico = max(pico, a)

    vivas = sum(t["acciones"] for t in tramos if t["viva"])
    com = sum(2 * max(MIN_ORDEN, t["acciones"] * POR_ACCION) for t in tramos)
    out.update({"tramos": tramos, "pico": pico, "vivas": vivas,
                "nominal": pico * px, "equity": equity, "comision": com,
                "limite": -riesgo,
                "cerca_del_limite": equity - riesgo / 3.0 < -riesgo})
    return out


def pintar(res, riesgo, piso):
    ahora_ny = datetime.now(NY).strftime("%H:%M:%S")
    print("\033[2J\033[H", end="")
    print("=" * 88)
    print(f"  SISTEMA EN VIVO · {ahora_ny} NY · riesgo ${riesgo:.0f}/dia · "
          f"piso ${piso:.2f} · stop {STOP_PCT:.0f}%")
    print(f"  reclaim · expansion >={EXPANSION_MIN:.0f}% · entradas desde las "
          f"{int(DESDE):02d}:{int((DESDE % 1) * 60):02d}")
    print("=" * 88)
    if not res:
        print("\n  Sin datos todavia. El indicador TTPFeed esta puesto en algun "
              "grafico?")
        print(f"  Esperando en: {FEED}")
        return

    try:
        mb = FEED.stat().st_size / 1e6
        if mb > AVISO_TAMANO_MB:
            print(f"\n  ! el feed pesa {mb:.0f} MB — con el mercado cerrado: "
                  f"python puente/vivo.py --limpiar")
    except OSError:
        pass

    operables = [r for r in res if r.get("tramos")]
    for r in sorted(res, key=lambda x: -len(x.get("tramos") or [])):
        h = r.get("hora", 0)
        cab = (f"\n  {r['ticker']:<7} ${r.get('precio') or 0:>7.2f} · "
               f"{int(h):02d}:{int((h % 1) * 60):02d} · {r['bars']:>4} barras")
        if r.get("expansion") is not None:
            cab += f" · expansion {r['expansion']:>5.0f}%"
        if r.get("apertura"):
            cab += f" · abrio {r['apertura']}"
        print(cab)
        if r["descartes"]:
            for d in r["descartes"]:
                print(f"      x {d}")
            continue
        if not r.get("tramos"):
            print("      · califica, sin senal todavia")
            continue
        print(f"      {'#':>2} {'hora':>6} {'entra':>9} {'stop':>9} "
              f"{'acciones':>9} {'estado':>10} {'pnl':>9}")
        for k, t in enumerate(r["tramos"], 1):
            if t["viva"]:
                est = "ABIERTA"
            elif t["motivo"] == "stop":
                hs = t["h_sal"] or 0
                est = f"stop {int(hs):02d}:{int((hs % 1) * 60):02d}"
            else:
                est = str(t["motivo"])
            print(f"      {k:>2} {int(t['h']):02d}:{int((t['h'] % 1) * 60):02d}  "
                  f"${t['precio']:>8.2f} ${t['stop']:>8.2f} "
                  f"{t['acciones']:>9.0f} {est:>10} ${t['pnl']:>+8.2f}")
        print(f"      -> {r['vivas']:.0f} acciones ABIERTAS ahora · "
              f"pico del dia {r['pico']:.0f} (eso es lo que hay que localizar)")
        print(f"      -> equity ${r['equity']:+.2f} de ${r['limite']:.0f} · "
              f"comision ${r['comision']:.2f} · "
              f"neto ${r['equity'] - r['comision']:+.2f}")
        if r["cerca_del_limite"]:
            print("      ! EN EL LIMITE DIARIO — el sistema no abre mas tramos")

    print(f"\n  {len(operables)} papel(es) con senal · "
          f"{sum(len(r['tramos']) for r in operables)} tramos en total")
    print("\n  Las ordenes las pones vos. Esto no manda nada.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="El sistema, en vivo")
    ap.add_argument("--riesgo", type=float, default=400.0)
    ap.add_argument("--piso", type=float, default=PISO_DEFECTO)
    ap.add_argument("--cada", type=float, default=20.0, help="segundos")
    ap.add_argument("--una-vez", action="store_true")
    ap.add_argument("--feed", default=str(FEED))
    ap.add_argument("--limpiar", action="store_true",
                    help="archivar lo que no sea de hoy (mercado cerrado)")
    ap.add_argument("--fecha", default=None,
                    help="forzar una fecha (para probar con datos guardados)")
    args = ap.parse_args(argv)

    ruta = Path(args.feed)
    hoy = args.fecha or datetime.now(NY).date().isoformat()
    if args.limpiar:
        fuera, quedan = limpiar(ruta, hoy)
        print(f"  archivadas {fuera} lineas · quedan {quedan} de hoy")
        return 0
    while True:
        res = []
        for (tk, fecha), datos in leer_feed(ruta).items():
            if fecha != hoy:
                continue
            dia = armar_dia(tk, fecha, datos)
            if dia:
                res.append(evaluar(dia, args.riesgo, args.piso))
        pintar(res, args.riesgo, args.piso)
        if args.una_vez:
            return 0
        time.sleep(args.cada)


if __name__ == "__main__":
    raise SystemExit(main())
