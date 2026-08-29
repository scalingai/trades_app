#!/usr/bin/env python3
"""La Chavineta, con las definiciones que trajo Agus. Ya no es una caricatura.

La versión anterior (`test_reciclaje.py`) agregaba a pasos fijos de volatilidad
y era, con razón, una caricatura: **ellos agregan contra NIVELES**, no contra
un múltiplo de ATR. Con las respuestas del informe se puede emular de verdad.

LO QUE CAMBIA RESPECTO DE LA VERSIÓN ANTERIOR

  1. **Filtro de apertura.** Solo se opera el día si el gap FALLA. Reclaim
     —rompe el máximo de pre-market con volumen, lo consolida y hace nuevo
     máximo del día— es orden de no operar. Antes se operaban todos.
  2. **Entrada por agotamiento de volumen**, no a una hora fija: tras un clímax
     de volumen, el volumen cae a menos de la mitad y el precio deja de hacer
     máximos.
  3. **Adiciones contra niveles reales**: máximo de pre-market, máximo del día
     previo, VWAP. Nunca a pasos fijos.
  4. **Reducción estructural**: se cierra el tramo cuando el precio vuelve a
     caer por debajo del nivel desde el que se agregó.
  5. **Corte por reclaim en vivo**: si hace nuevo máximo del día por encima de
     la última resistencia, se cierra TODO. Es el "cortarse el brazo".
  6. **Locate del 20%**, aplicado como quita sobre la ganancia bruta (ver abajo).

LA CONTRADICCIÓN DEL INFORME SOBRE EL LOCATE, Y CÓMO SE RESUELVE

El resumen dice "20% del nominal", pero el ejemplo trabajado del mismo módulo
dice "un 10% de ganancia bruta puede convertirse en un 8% real". Eso es una
quita del **20% sobre la ganancia**, no sobre el nominal. Las dos lecturas
difieren por dos órdenes de magnitud y solo una es operable: cobrar 20% del
nominal por localizar exigiría mover 20% solo para empatar, y ningún trade de
esta muestra lo haría de forma sostenida. Se implementan las dos y se reportan
juntas — la literal está para mostrar que no puede ser la lectura correcta.

    python chavineta.py
    python chavineta.py --float-max 10e6      # el universo que declaran
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys

import config
from dias import APERTURA_RTH, CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

TRAMOS = 5
CORTE_PERIODO = "2025-08-17"


# ------------------------------------------------------------------ apertura

def clasificar_apertura(dia, *, hasta=10.0, minutos_consolida=5):
    """'reclaim' | 'fade' | None, según la definición del informe.

    Reclaim: rompe el máximo de pre-market, lo SOSTIENE —cierra arriba varios
    minutos seguidos— y hace nuevo máximo del día. Ahí no se opera corto.

    Fade: no logra romper el máximo de pre-market, o se lateraliza debajo del
    VWAP. Ahí se activa el protocolo.

    Todo se mide con barras de la apertura hasta `hasta`, así que la
    clasificación es observable a esa hora y no usa nada posterior.
    """
    pmh = dia.pm_high
    rth = [(i, b) for i, b in enumerate(dia.bars)
           if APERTURA_RTH <= hora(b) <= hasta]
    if not pmh or len(rth) < 10:
        return None

    rompio = any(b[2] and b[2] > pmh for _, b in rth)
    if rompio:
        seguidos = 0
        for _, b in rth:
            seguidos = seguidos + 1 if (b[4] and b[4] > pmh) else 0
            if seguidos >= minutos_consolida:
                # Consolidó arriba. ¿Hizo nuevo máximo después de consolidar?
                idx = [i for i, x in rth].index(_)
                despues = [x[2] for _, x in rth[idx:] if x[2]]
                if despues and max(despues) > pmh:
                    return "reclaim"
    i_fin, b_fin = rth[-1]
    if b_fin[4] and b_fin[4] < dia.vwap[i_fin]:
        return "fade"
    return "fade" if not rompio else "reclaim"


# ------------------------------------------------------------------ entrada

def agotamiento(dia, *, desde=9.75, hasta=14.0, caida=0.5, sin_maximo_min=10):
    """Primer minuto de agotamiento de volumen. Devuelve el índice, o None.

    Definición del informe: tras un clímax de volumen, el volumen de las velas
    siguientes cae a menos de la mitad del clímax Y el precio no logra seguir
    subiendo (máximos decrecientes o lateralización).

    `caida` y `sin_maximo_min` son los dos parámetros de esta definición. Se
    reportan en la grilla en vez de elegirse.
    """
    climax_vol = 0.0
    for i, b in enumerate(dia.bars):
        h = hora(b)
        if h < APERTURA_RTH:
            continue
        v = b[5] or 0.0
        if v > climax_vol:
            climax_vol = v
        if h < desde or h > hasta or climax_vol <= 0:
            continue
        ult = [x[5] or 0.0 for x in dia.bars[max(0, i - 4):i + 1]]
        if statistics.mean(ult) >= caida * climax_vol:
            continue
        if dia.edad_max[i] < sin_maximo_min:
            continue
        return i
    return None


# ------------------------------------------------------------------ niveles

def resistencias(dia, i, prev_high):
    """Los niveles contra los que agregan, ordenados hacia arriba.

    No hay escalera inventada: si arriba del precio no hay estructura, no hay
    adición. Eso es exactamente lo que diferencia esto de promediar a ciegas.
    """
    p = dia.bars[i][4]
    cand = [("pm_high", dia.pm_high), ("prev_high", prev_high),
            ("vwap", dia.vwap[i]), ("hod", dia.max_corriente[i])]
    niveles = sorted({round(v, 4) for _, v in cand if v and v > p})
    return niveles


# ------------------------------------------------------------------ el trade

def salida_gradual(bars, desde_idx, abiertos, disparo, *, minutos=30,
                   fraccion_inmediata=0.4):
    """Cierra en retrocesos en vez de liquidar todo al peor precio.

    **Por qué existe.** El modelo anterior liquidaba el 100% al cierre del
    minuto que confirmaba el reclaim, o sea en el peor precio disponible. Los
    operadores describen lo contrario: cierran una parte enseguida y el resto
    "cuando haga un retroceso", escalando la salida. Liquidar de golpe le
    inventa a la técnica un deslizamiento que la técnica evita.

    Se cubre `fraccion_inmediata` al toque y el resto contra el primer mínimo
    que mejore el precio de disparo, con `minutos` de plazo. Vencido el plazo,
    lo que queda sale a mercado — porque esperar indefinidamente sería asumir
    que siempre hay retroceso, que es justamente el caso WISA.
    """
    n = len(abiertos)
    salidas = [(disparo, fraccion_inmediata)]
    resto = 1.0 - fraccion_inmediata
    mejor = disparo
    t0 = bars[desde_idx][0]
    for b in bars[desde_idx + 1:]:
        if resto <= 0:
            break
        if (b[0] - t0).total_seconds() / 60.0 > minutos:
            break
        if b[3] and b[3] < mejor:
            # Retroceso: se cubre la mitad de lo que queda a ese precio.
            mejor = b[3]
            salidas.append((mejor, resto / 2))
            resto /= 2
    if resto > 0:
        ultimo = next((b[4] for b in bars[desde_idx + 1:]
                       if b[4] and (b[0] - t0).total_seconds() / 60.0 <= minutos),
                      disparo)
        salidas.append((ultimo, resto))
    # Precio medio de salida ponderado por lo que se cubrió en cada tramo.
    return sum(p * f for p, f in salidas) / sum(f for _, f in salidas), n


def operar(dia, prev_high, *, costo_accion, tope_perdida, quita_locate,
           minutos_reclaim=2, margen_reclaim=0.0, costo_salida=None,
           gradual=False, salida_be=None):
    """Un ciclo plano a plano. Devuelve un dict, o None si el día no se opera."""
    lado = clasificar_apertura(dia)
    if lado != "fade":
        return {"operado": False, "motivo": lado or "sin_datos"}
    i0 = agotamiento(dia)
    if i0 is None:
        return {"operado": False, "motivo": "sin_agotamiento"}

    p0 = dia.bars[i0][4]
    niveles = resistencias(dia, i0, prev_high)
    if not p0:
        return {"operado": False, "motivo": "sin_precio"}

    # (precio de entrada, nivel que lo disparó, índice de la barra que lo abrió).
    # El índice existe para impedir que un tramo se abra y se cierre en el mismo
    # minuto: ver la nota sobre intrabar en la reducción.
    abiertos = [(p0, None, i0)]
    realizado = 0.0                # dólares por acción, sobre el nominal completo
    ejecuciones = 1
    # Registro de ejecuciones. No participa del cálculo: existe para poder
    # DIBUJAR el trade sobre el gráfico y auditar a ojo lo que hizo el motor.
    # Una simulación que no se puede mirar es una simulación en la que hay que
    # creer.
    registro = [{"ts": dia.bars[i0][0], "tipo": "entrada", "precio": p0,
                 "tramos": 1, "medio": p0,
                 "nota": f"agotamiento · {len(niveles)} niveles arriba"}]
    peor = 0.0
    techo = (max(niveles) if niveles else p0 * 1.5) * (1 + margen_reclaim / 100)
    pendientes = list(niveles)
    seguidos_arriba = 0

    for b in dia.bars[i0 + 1:]:
        if hora(b) > CIERRE_RTH:
            break
        alto, bajo, c = b[2], b[3], b[4]
        if not c:
            continue
        i_barra = dia.bars.index(b)
        medio = sum(p for p, _, _ in abiertos) / len(abiertos)
        if alto:
            peor = max(peor, (alto / medio - 1) * 100 * len(abiertos) / TRAMOS)

        # Corte por reclaim en vivo. Se exige CONSOLIDACIÓN, no una mecha: el
        # propio informe define reclaim como romper Y sostener. Cortar con el
        # primer tick por encima convierte cada barrido en una pérdida máxima,
        # que es un artefacto del modelo y no la técnica.
        seguidos_arriba = seguidos_arriba + 1 if c > techo else 0
        if seguidos_arriba >= minutos_reclaim:
            idx = dia.bars.index(b)
            if gradual:
                salida, _ = salida_gradual(dia.bars, idx, abiertos, c)
                ejecuciones += len(abiertos) + 2   # sale en tramos, paga más
            else:
                salida = c
                ejecuciones += len(abiertos)
            realizado += sum(p - salida for p, _, _ in abiertos) / TRAMOS
            registro.append({"ts": b[0], "tipo": "salida", "precio": salida,
                             "tramos": len(abiertos), "medio": medio,
                             "nota": f"reclaim · cerró {minutos_reclaim} min sobre "
                                     f"{techo:.2f}"})
            return _cerrar(dia, p0, realizado, ejecuciones, peor, "reclaim_vivo",
                           costo_accion, quita_locate, len(niveles), costo_salida,
                           registro)

        # Tope duro de pérdida sobre el nominal completo.
        if alto and (alto / medio - 1) * 100 * len(abiertos) / TRAMOS >= tope_perdida:
            realizado += sum(p - alto for p, _, _ in abiertos) / TRAMOS
            ejecuciones += len(abiertos)
            registro.append({"ts": b[0], "tipo": "salida", "precio": alto,
                             "tramos": len(abiertos), "medio": medio,
                             "nota": f"tope de pérdida {tope_perdida:.0f}%"})
            return _cerrar(dia, p0, realizado, ejecuciones, peor, "tope",
                           costo_accion, quita_locate, len(niveles), costo_salida,
                           registro)

        # "No se casan con la entrada": si la posición ya se construyó —o sea,
        # el precio fue en contra y hubo que agregar— y después vuelve al precio
        # medio, se sale TODO a mercado en break-even o con poco. No se espera
        # el target. Es el mecanismo que explica un win rate alto con un ratio
        # riesgo/beneficio nominalmente malo: se rescatan trades que un stop
        # plano habría dado por perdidos.
        if salida_be is not None and len(abiertos) >= 2 and bajo:
            objetivo = medio * (1 - salida_be / 100.0)
            if bajo <= objetivo:
                realizado += sum(p - objetivo for p, _, _ in abiertos) / TRAMOS
                ejecuciones += len(abiertos)
                registro.append({"ts": b[0], "tipo": "salida", "precio": objetivo,
                                 "tramos": len(abiertos), "medio": medio,
                                 "nota": "vuelta al precio medio"})
                return _cerrar(dia, p0, realizado, ejecuciones, peor, "break_even",
                               costo_accion, quita_locate, len(niveles), costo_salida,
                               registro)

        # Adición: el precio subió hasta la próxima resistencia.
        while pendientes and alto and alto >= pendientes[0] and len(abiertos) < TRAMOS:
            nivel = pendientes.pop(0)
            abiertos.append((nivel, nivel, i_barra))
            ejecuciones += 1
            registro.append({
                "ts": b[0], "tipo": "adicion", "precio": nivel,
                "tramos": len(abiertos),
                "medio": sum(p for p, _, _ in abiertos) / len(abiertos),
                "nota": f"tocó resistencia {nivel:.2f}"})

        # Reducción: el precio volvió a caer debajo del nivel desde el que se
        # agregó → ese tramo cumplió su función y se cierra.
        if bajo:
            vivos = []
            for p, niv, i_abre in abiertos:
                # `i_abre < i_barra` es el arreglo: dentro de un mismo minuto no
                # se sabe si el máximo vino antes o después del mínimo, y
                # permitir abrir y cerrar en la misma barra asume la secuencia
                # más favorable posible. El resto del motor usa la convención
                # opuesta (ante la duda, gana el stop); esto la alinea.
                if niv is not None and bajo < niv and len(abiertos) > 1 \
                        and i_abre < i_barra:
                    realizado += (p - bajo) / TRAMOS
                    ejecuciones += 1
                    registro.append({
                        "ts": b[0], "tipo": "reduccion", "precio": bajo,
                        "tramos": len(abiertos) - 1, "medio": medio,
                        "nota": f"volvió debajo de {niv:.2f}"})
                else:
                    vivos.append((p, niv, i_abre))
            if vivos != abiertos:
                abiertos = vivos

    ultimo = next((x[4] for x in reversed(dia.bars)
                   if hora(x) <= CIERRE_RTH and x[4]), p0)
    realizado += sum(p - ultimo for p, _, _ in abiertos) / TRAMOS
    ejecuciones += len(abiertos)
    b_ult = next((x for x in reversed(dia.bars) if hora(x) <= CIERRE_RTH and x[4]), None)
    registro.append({"ts": b_ult[0] if b_ult else dia.bars[i0][0], "tipo": "salida",
                     "precio": ultimo, "tramos": len(abiertos),
                     "medio": sum(p for p, _, _ in abiertos) / len(abiertos),
                     "nota": "cierre de la sesión"})
    return _cerrar(dia, p0, realizado, ejecuciones, peor, "cierre",
                   costo_accion, quita_locate, len(niveles), costo_salida, registro)


def _cerrar(dia, p0, realizado, ejecuciones, peor, motivo, costo_accion,
            quita_locate, n_niveles, costo_salida=None, registro=None):
    bruto = realizado / p0 * 100
    # Las adiciones y las reducciones son órdenes LIMITADAS puestas en el nivel:
    # aportan liquidez, no la cruzan. La salida de emergencia sí cruza. Modelar
    # todo como cruce castiga la técnica por algo que la técnica no hace.
    c_salida = costo_accion if costo_salida is None else costo_salida
    comisiones = ((ejecuciones - 1) / TRAMOS * costo_accion
                  + 1 / TRAMOS * c_salida) / p0 * 100
    # Locate como QUITA sobre la ganancia bruta (lectura del ejemplo del informe:
    # 10% bruto → 8% neto). Una pérdida no se "descuenta": el locate se paga igual,
    # pero como fracción de la ganancia no aplica, así que solo castiga los ganadores.
    quita = bruto * quita_locate if bruto > 0 else 0.0
    return {
        "operado": True, "motivo": motivo, "bruto": bruto,
        "neto": bruto - comisiones - quita,
        "neto_sin_locate": bruto - comisiones,
        "ejecuciones": ejecuciones, "peor": peor, "niveles": n_niveles,
        "registro": registro or [],
        "d": dia.d, "ticker": dia.ticker, "precio": p0,
    }


# ------------------------------------------------------------------ reporte

def resumen(vals):
    if len(vals) < 20:
        return None
    return {"n": len(vals),
            "gana": 100 * sum(1 for x in vals if x > 0) / len(vals),
            "med": statistics.median(vals), "media": statistics.mean(vals),
            "desvio": statistics.pstdev(vals),
            "p10": sorted(vals)[int(.10 * len(vals))], "peor": min(vals)}


def linea(lab, r):
    if not r:
        print(f"  {lab:32}  (n insuficiente)")
        return
    print(f"  {lab:32} {r['n']:>5} {r['gana']:>6.1f}% {r['med']:>+8.2f}% "
          f"{r['media']:>+8.2f}% {r['desvio']:>7.2f} {r['p10']:>+8.2f}% {r['peor']:>+8.1f}%")


def cabecera():
    print(f"\n  {'':32} {'n':>5} {'gana':>7} {'mediana':>9} {'media':>9} "
          f"{'desvío':>7} {'p10':>9} {'peor':>9}")
    print("  " + "-" * 92)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="La Chavineta con niveles estructurales")
    ap.add_argument("--spread-cents", type=float, default=2.0)
    ap.add_argument("--comision", type=float, default=0.005)
    ap.add_argument("--tope-perdida", type=float, default=20.0)
    ap.add_argument("--quita-locate", type=float, default=0.20)
    ap.add_argument("--float-max", type=float, default=0.0,
                    help="máximo de acciones en circulación (0 = sin filtro)")
    ap.add_argument("--precio-min", type=float, default=0.20)
    ap.add_argument("--precio-max", type=float, default=10.0)
    ap.add_argument("--minutos-reclaim", type=int, default=2,
                    help="minutos consecutivos cerrando arriba del techo para cortar")
    ap.add_argument("--margen-reclaim", type=float, default=0.0,
                    help="%% por encima del techo antes de considerar reclaim")
    ap.add_argument("--pasivo", action="store_true",
                    help="adiciones y reducciones como órdenes limitadas: sin "
                         "cruzar spread, con rebate por aportar liquidez")
    ap.add_argument("--salida-be", type=float, default=None,
                    help="salir TODO al volver al precio medio (%% por debajo; "
                         "0 = break-even exacto). Solo si ya se construyó posición")
    ap.add_argument("--gradual", action="store_true",
                    help="salir del reclaim en retrocesos en vez de liquidar todo")
    ap.add_argument("--rebate", type=float, default=0.002,
                    help="rebate por acción al aportar liquidez (ECN)")
    args = ap.parse_args(argv)
    # Cruzando el spread en cada ejecución vs. poniendo limitadas en el nivel.
    costo = args.spread_cents / 100 + 2 * args.comision
    costo_pasivo = args.comision - args.rebate if args.pasivo else costo
    costo_salida = costo

    db = sqlite3.connect(config.bars_db_path())
    acciones = {(t, d): n for t, d, n in db.execute(
        "SELECT ticker,d,shares_outstanding FROM event_structure "
        "WHERE shares_outstanding IS NOT NULL")}

    res, saltados = [], {}
    for dia in cargar():
        if (dia.ratio_volumen or 0) < 3:
            continue
        p = dia.rth_open or 0
        if not (args.precio_min <= p <= args.precio_max):
            continue
        if args.float_max:
            n = acciones.get((dia.ticker, dia.d))
            if not n or n > args.float_max:
                continue
        prev = db.execute(
            "SELECT h FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT 1",
            (dia.ticker, dia.d)).fetchone()
        r = operar(dia, prev[0] if prev else None, costo_accion=costo_pasivo,
                   tope_perdida=args.tope_perdida, quita_locate=args.quita_locate,
                   minutos_reclaim=args.minutos_reclaim,
                   margen_reclaim=args.margen_reclaim,
                   costo_salida=costo_salida, gradual=args.gradual,
                   salida_be=args.salida_be)
        if r.get("operado"):
            r["per"] = "P1" if dia.d < CORTE_PERIODO else "P2"
            res.append(r)
        else:
            saltados[r["motivo"]] = saltados.get(r["motivo"], 0) + 1
    db.close()

    total = len(res) + sum(saltados.values())
    print("=" * 96)
    print("  LA CHAVINETA — adiciones contra NIVELES, no contra volatilidad")
    print(f"  universo: ${args.precio_min:.2f}–${args.precio_max:.0f}"
          + (f" · ≤{args.float_max/1e6:.0f}M acciones" if args.float_max else "")
          + f"  ·  {total} días candidatos")
    print(f"  costo {costo*100:.1f}c/acción por ejecución + locate como quita del "
          f"{args.quita_locate*100:.0f}% sobre la ganancia")
    print("=" * 96)

    print(f"\n  FILTRO DE APERTURA — se operaron {len(res)} de {total} días")
    for k, v in sorted(saltados.items(), key=lambda x: -x[1]):
        print(f"    descartados por {k:18} {v:>5}  ({100*v/total:.0f}%)")

    if not res:
        print("\n  nada que medir.")
        return 1

    cabecera()
    linea("bruto", resumen([r["bruto"] for r in res]))
    linea("neto de comisiones", resumen([r["neto_sin_locate"] for r in res]))
    linea(f"neto + locate {args.quita_locate*100:.0f}% de la ganancia",
          resumen([r["neto"] for r in res]))
    # La lectura literal del resumen del informe, para mostrar que no puede serlo.
    linea("neto + locate 20% del NOMINAL",
          resumen([r["neto_sin_locate"] - 20.0 for r in res]))

    print("\n  POR MOTIVO DE SALIDA")
    cabecera()
    for m in ("cierre", "break_even", "reclaim_vivo", "tope"):
        g = [r["neto"] for r in res if r["motivo"] == m]
        linea(m, resumen(g))

    print("\n  REPLICACIÓN")
    cabecera()
    for per in ("P1", "P2"):
        linea(per, resumen([r["neto"] for r in res if r["per"] == per]))

    ej = [r["ejecuciones"] for r in res]
    niv = [r["niveles"] for r in res]
    print(f"\n  ejecuciones por trade: mediana {statistics.median(ej):.0f} · "
          f"máx {max(ej)}")
    print(f"  niveles disponibles arriba de la entrada: mediana {statistics.median(niv):.0f}")
    print("\n  El win rate de acá es plano a plano, igual que el de ellos: cada fila")
    print("  es un ciclo completo, no una ejecución.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
