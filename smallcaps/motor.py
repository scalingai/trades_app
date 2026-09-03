#!/usr/bin/env python3
"""Banco de pruebas común. Toda estrategia se mide acá o no se compara con nada.

**Por qué existe.** Vamos a probar muchas estrategias en paralelo. Si cada una se
mide a su manera —distinto riesgo, distinto costo, distinta unidad— los números
no son comparables y la matriz de correlación, que es el objetivo real, no se
puede construir. Este módulo fija el protocolo.

LA UNIDAD DE MEDIDA, y por qué esta y no otra:

  · Todo se expresa en **R** = el riesgo en dólares de una sesión. Así el número
    no cambia cuando se escala la cuenta.
  · La métrica que manda es **ret/nom** = retorno sobre nominal. Con cuentas de
    fondeo el locate se cobra como fracción del nominal desplegado, así que
    `ret/nom` ES el punto de muerte: si el locate lo supera, la estrategia pierde
    plata por definición. Una estrategia con PnL alto y nominal enorme es peor
    que una con PnL menor y nominal chico.
  · **sesiones/mes** importa aparte: una estrategia excelente que opera 2 veces
    al mes no llega a pasar una evaluación.

EL CONTRATO DE UNA ESTRATEGIA:

    def mi_señal(dia) -> list[int]
        Devuelve índices de barras donde ENTRAR. Sólo puede mirar
        `dia.bars[:i+1]` — mirar hacia adelante invalida todo.

    evaluar("nombre", mi_señal, lado="short", stop=45.0)

VALIDACIÓN OBLIGATORIA: cada resultado trae P1 y P2 por separado (corte
2025-08-17). Una estrategia que no replica no entra a la cartera, por bueno que
sea su número global.

    python motor.py            # smoke test con las estrategias base
"""

from __future__ import annotations

import json
import math
import os
import pickle
import statistics
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import config
from chavineta import clasificar_apertura
from dias import APERTURA_RTH, CIERRE_RTH, cargar, hora

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CORTE = "2025-08-17"
MESES = 22.5                      # el censo va de 2024-10-02 a 2026-08-10
R_BASE = 50.0
COSTO_ACCION = 0.04
LOCATE_REF = 0.20                 # el pesimista de Espes, para la columna neta
RESULTADOS = Path(config.data_dir()) / "estrategias.json"
CACHE = Path(config.data_dir()) / "universo.pkl"


# --------------------------------------------------------------------------
# Carga del universo, cacheada. Recorrer el censo cuesta minutos y lo vamos a
# hacer decenas de veces; sin caché el experimento no es viable.
# --------------------------------------------------------------------------

def universo(refrescar: bool = False):
    """Todos los días del censo con sus features derivados, una sola vez.

    El caché es pickle a propósito: guarda objetos `Dia` ya armados, con sus
    listas de VWAP y máximos corrientes, y rearmarlos desde SQLite cuesta
    minutos por corrida. Es seguro porque el archivo lo escribe este mismo
    módulo en el directorio de datos local — nunca se carga un pickle de otra
    procedencia. Si algún día el caché viniera de afuera, esto tiene que
    cambiar a un formato sin ejecución (JSON/columnas).
    """
    if CACHE.exists() and not refrescar:
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)

    db = sqlite3.connect(config.bars_db_path())
    flo = {}
    for t, d, so in db.execute(
            "SELECT ticker,d,shares_outstanding FROM event_structure"):
        if so:
            flo[(t, d)] = so
    db.close()

    out = []
    for dia in cargar(censo=True):
        dia.dolar_dia = sum((b[5] or 0) * (b[4] or 0) for b in dia.bars)
        dia.float_acciones = flo.get((dia.ticker, dia.d))
        out.append(dia)
    with open(CACHE, "wb") as fh:
        pickle.dump(out, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return out


# --------------------------------------------------------------------------
# Poblaciones. Una estrategia declara sobre QUÉ días opera; es la mitad de la
# decisión y donde vive casi toda la decorrelación entre estrategias.
# --------------------------------------------------------------------------

def poblacion(dias, *, min_ratio_vol=3.0, min_expansion=100.0, max_expansion=None,
              min_dolar=137e6, max_dolar=None, max_float=47e6, min_precio=None,
              max_precio=None):
    """Filtra días por observables PREVIOS a la apertura (más volumen del día).

    Ojo con `min_dolar`: el volumen en dólares del día completo NO se conoce a
    las 09:30. Se usa igual porque en la práctica se aproxima con el volumen
    premarket, pero es una licencia y hay que decirlo.
    """
    out = []
    for dia in dias:
        if (dia.ratio_volumen or 0) < min_ratio_vol:
            continue
        e = dia.expansion_pct or 0
        if e < min_expansion or (max_expansion is not None and e > max_expansion):
            continue
        if min_dolar and dia.dolar_dia <= min_dolar:
            continue
        if max_dolar and dia.dolar_dia > max_dolar:
            continue
        f = dia.float_acciones
        if max_float and f is not None and f > max_float:
            continue
        p = dia.bars[0][4] if dia.bars else None
        if min_precio and (not p or p < min_precio):
            continue
        if max_precio and (not p or p > max_precio):
            continue
        out.append(dia)
    return out


# --------------------------------------------------------------------------
# El simulador. Un trade, una jornada, una estrategia.
# --------------------------------------------------------------------------

def _trade(dia, i, *, lado, stop_pct, riesgo, objetivo_pct=None, salida_h=None,
           trail_ancho=None, trail_devuelve=None, trail_arma=0.0):
    """Un trade con tamaño por riesgo. Devuelve el registro completo o None.

    Convención conservadora de siempre: si en el mismo minuto se tocan stop y
    objetivo, gana el stop. No se sabe cuál vino primero dentro de la barra.

    Devuelve TODO lo necesario para volver a dibujarlo sobre las velas —hora y
    precio de entrada y salida, stop, MAE/MFE— porque una estrategia que no se
    puede mirar no se puede auditar, y en este proyecto el bug de las reducciones
    intrabar apareció justo así: dibujando el trade, no leyendo el promedio.
    """
    p = dia.bars[i][4]
    if not p or stop_pct <= 0:
        return None
    acciones = riesgo / (p * stop_pct / 100.0)
    nominal = acciones * p
    signo = -1.0 if lado == "short" else 1.0
    p_stop = p * (1 - signo * stop_pct / 100.0)
    p_obj = p * (1 + signo * objetivo_pct / 100.0) if objetivo_pct else None
    h_ent = hora(dia.bars[i])

    def cerrar(pnl, motivo, h_sal, p_sal, mae, mfe):
        return {"pnl": pnl, "motivo": motivo, "nominal": nominal,
                "acciones": acciones, "h_ent": h_ent, "p_ent": p,
                "h_sal": h_sal, "p_sal": p_sal, "stop_pct": stop_pct,
                "mae_pct": round(mae, 2), "mfe_pct": round(mfe, 2)}

    mae = mfe = 0.0
    # Nivel de trailing, calculado SOLO con barras ya cerradas. Se chequea antes
    # de actualizarlo con la barra en curso: si se usara el extremo de la misma
    # barra para fijar el nivel que esa barra dispara, el resultado sería
    # imposible de ejecutar. Es la misma convención conservadora que ya rige
    # cuando stop y objetivo caen en el mismo minuto.
    p_trail = None
    for b in dia.bars[i + 1:]:
        h = hora(b)
        if h > CIERRE_RTH:
            break

        # 1) ¿La barra dispara el trailing que venía de antes?
        if p_trail is not None:
            toca_tr = (b[2] and b[2] >= p_trail) if lado == "short" else (
                b[3] and b[3] <= p_trail)
            if toca_tr:
                return cerrar(
                    signo * acciones * (p_trail - p) - acciones * COSTO_ACCION,
                    "trailing", h, p_trail, mae, mfe)

        # Excursiones en % medidas A FAVOR del lado operado: para un short, que
        # el precio baje es favorable.
        if b[2] and b[3]:
            fav = (p - b[3]) if lado == "short" else (b[2] - p)
            adv = (b[2] - p) if lado == "short" else (p - b[3])
            mfe = max(mfe, 100 * fav / p)
            mae = min(mae, -100 * adv / p)
        toca_stop = (b[2] and b[2] >= p_stop) if lado == "short" else (
            b[3] and b[3] <= p_stop)
        if toca_stop:
            return cerrar(-riesgo - acciones * COSTO_ACCION, "stop", h, p_stop,
                          mae, mfe)

        # 2) Recién ahora se mueve el nivel, con la barra ya cerrada.
        if (trail_ancho or trail_devuelve) and mfe >= trail_arma:
            if trail_devuelve:
                # Devolver una fracción del máximo a favor: el nivel se pone
                # donde el trade conserva (1 - devuelve) de lo que llegó a ganar.
                queda = mfe * (1 - trail_devuelve / 100.0)
                nivel = p * (1 + signo * queda / 100.0)
            else:
                # Ancho fijo desde el extremo corriente A FAVOR.
                #
                # OJO CON EL SIGNO — acá tuve el error. Para un short el extremo
                # favorable es el MÍNIMO (por debajo de la entrada) y el stop va
                # POR ENCIMA de él. Con el signo invertido el nivel quedaba
                # debajo de la entrada y la primera barra lo "tocaba", cerrando
                # con una ganancia del 23% a un precio que el mercado nunca
                # operó: daba 104% de ret/nom con brecha de 1 punto. Cuando una
                # variante mejora seis veces y replica perfecto, es un bug.
                extremo = p * (1 + signo * mfe / 100.0)
                nivel = extremo * (1 - signo * trail_ancho / 100.0)
            # Nunca aflojar: el trailing sólo se mueve a favor.
            if p_trail is None:
                p_trail = nivel
            else:
                p_trail = min(p_trail, nivel) if lado == "short" else max(p_trail, nivel)
            # Y nunca peor que el stop original.
            p_trail = min(p_trail, p_stop) if lado == "short" else max(p_trail, p_stop)
        if p_obj is not None:
            toca_obj = (b[3] and b[3] <= p_obj) if lado == "short" else (
                b[2] and b[2] >= p_obj)
            if toca_obj:
                return cerrar(
                    signo * acciones * (p_obj - p) - acciones * COSTO_ACCION,
                    "objetivo", h, p_obj, mae, mfe)
        if salida_h is not None and h >= salida_h:
            ps = b[4] or p
            return cerrar(signo * acciones * (ps - p) - acciones * COSTO_ACCION,
                          "hora", h, ps, mae, mfe)
    c = dia.rth_close
    if not c:
        return None
    return cerrar(signo * acciones * (c - p) - acciones * COSTO_ACCION, "cierre",
                  CIERRE_RTH, c, mae, mfe)


def jornada(dia, señal, *, lado, stop_pct, riesgo, max_trades=10,
            objetivo_pct=None, salida_h=None, trail_ancho=None,
            trail_devuelve=None, trail_arma=0.0,
            corte_h=None, corte_umbral=5.0, corte_reentra=False,
            tope_usd=None):
    """Una sesión: varios trades hasta agotar el presupuesto de riesgo.

    **La regla de presupuesto miraba el futuro, y era el error más caro de los
    siete.** Decía —lo escribí yo— que "un ganador temprano devuelve margen para
    seguir operando, y ese detalle está medido". Lo que estaba medido era el
    look-ahead.

    El mecanismo: `_trade` simula cada tramo hasta su cierre antes de pasar al
    siguiente, así que el `pnl` acumulado contenía el resultado FINAL de tramos
    que a la hora de la nueva entrada seguían abiertos — el 80% de los casos,
    porque la señal de swing abre varios tramos en la misma bajada. El corte no
    era un límite de riesgo: era un filtro que sacaba justo los tramos que iban
    a perder.

    El delator, y vale como regla general: la versión con look-ahead tomaba
    MENOS trades y ganaba MÁS. Un buen límite de riesgo no hace eso.

    Ahora el presupuesto se mide **a mercado en el minuto de la entrada**: los
    tramos ya cerrados a valor final, los vivos marcados contra el precio de esa
    barra. Es lo que se sabe en ese momento, y además es lo que mide una cuenta
    de fondeo, que corta por drawdown de equity y no por PnL realizado.

    Costo de la corrección: fade 7,5% -> 3,8% de ret/nom, reclaim 16,4% -> 11,5%.
    Verificado por dos implementaciones independientes que coinciden.
    """
    idx = señal(dia)
    if not idx:
        return None
    r_trade = riesgo / 3.0
    n = 0
    detalle = []
    pnl = 0.0

    # EL BUCLE ES UNA FUNCION PARA PODER CORRERLO DOS VECES.
    #
    # Con reentrada despues del corte hacen falta dos pasadas: una hasta la hora
    # del corte y otra despues, con el resultado del corte YA REALIZADO adentro
    # del presupuesto. Aplicar el corte al final —como estaba— no permitia eso:
    # los tramos de la segunda mitad se abrian con un presupuesto calculado
    # sobre posiciones que a esa altura ya estaban cerradas.
    def abrir(indices):
        nonlocal n, pnl
        for i in indices:
            if n >= max_trades:
                break
            # Equity a mercado en ESTE minuto — nada de resultados futuros.
            # Ojo: variable propia, NO `pnl`. Reusar el acumulador de la
            # jornada acá hace que la función devuelva el equity de la última
            # entrada en lugar del total del día, y el número queda mal por un
            # factor grande.
            h_ahora = hora(dia.bars[i])
            px = dia.bars[i][4]
            equity = 0.0
            for t in detalle:
                if t["h_sal"] is not None and t["h_sal"] <= h_ahora:
                    equity += t["pnl"]
                elif px:
                    signo = -1.0 if lado == "short" else 1.0
                    equity += signo * t["acciones"] * (px - t["p_ent"])
            if equity - r_trade < -riesgo:       # el límite diario del día
                break
            r = _trade(dia, i, lado=lado, stop_pct=stop_pct, riesgo=r_trade,
                       objetivo_pct=objetivo_pct, salida_h=salida_h,
                       trail_ancho=trail_ancho, trail_devuelve=trail_devuelve,
                       trail_arma=trail_arma)
            if not r:
                continue
            pnl += r["pnl"]
            n += 1
            detalle.append(r)

    if corte_h is None:
        abrir(idx)
    else:
        # Primera pasada: hasta la hora del corte.
        abrir([i for i in idx if hora(dia.bars[i]) < corte_h])
    if not n and corte_h is None:
        return None

    # EL CORTE POR HORA. Si a `corte_h` la posición no está al menos
    # `corte_umbral`% a favor, se cierra todo y ese papel no se opera más.
    #
    # POR QUE ES OPCIONAL Y VIENE APAGADA. Esta función es el arnés donde se
    # midieron ~450 estrategias, y cambiarle el comportamiento por defecto
    # invalidaría cada número guardado en la base. La operativa la prende; los
    # tests históricos siguen midiendo lo que midieron.
    #
    # QUE COMPRA. Es lo único que hace la estrategia operable en una cuenta de
    # fondeo: el drawdown pasa de $-3.684 a $-856 contra un tope de $1.000. No
    # gana mas plata —al contrario— pero los $36.495 sin corte son incobrables
    # porque la cuenta se liquida antes de cobrarlos.
    #
    # Corta PERDEDORES, que es lo que la distingue de los trece intentos de
    # asegurar que fallaron: aquellos cortaban ganadores y la estrategia vive de
    # la cola derecha.
    if corte_h is not None:
        i_corte = dia.idx_en(corte_h)
        px = dia.bars[i_corte][4] if i_corte is not None else None
        cortado = False
        if px and detalle:
            h_corte = hora(dia.bars[i_corte])
            vivos = [t for t in detalle
                     if t["h_sal"] is None or t["h_sal"] > h_corte]
            if vivos:
                acc = sum(t["acciones"] for t in vivos)
                prom = sum(t["p_ent"] * t["acciones"] for t in vivos) / acc
                signo = -1.0 if lado == "short" else 1.0
                favor = 100.0 * signo * (px - prom) / prom
                if favor < corte_umbral:
                    cortado = True
                    for t in vivos:
                        t["h_sal"], t["p_sal"], t["motivo"] = h_corte, px, "corte"
                        t["pnl"] = (signo * t["acciones"] * (px - t["p_ent"])
                                    - t["acciones"] * COSTO_ACCION)
                    pnl = sum(t["pnl"] for t in detalle)

        # SEGUNDA PASADA. Si no hubo corte, el dia sigue normal. Si hubo y
        # `corte_reentra`, tambien sigue — pero ahora el presupuesto ya tiene la
        # perdida del corte REALIZADA adentro, asi que lo que queda de caja es
        # menos. Esa es la diferencia entre reentrar y empezar el dia de nuevo.
        if not cortado or corte_reentra:
            abrir([i for i in idx if hora(dia.bars[i]) >= corte_h])

    # EL TOPE POR SIMBOLO — la regla de consistencia de la evaluacion.
    #
    # Trade The Pool exige que la mejor POSICION —el total en un simbolo, con
    # los tramos sumados, y lo dicen explicito: "whether through a single
    # oversized order or multiple smaller orders"— no ponga mas del 50% del
    # objetivo de la evaluacion. Nuestra estrategia vive de la cola derecha y
    # el mejor papel-dia ronda el 115% del objetivo, asi que sin esto la
    # evaluacion no se pasa limpia casi nunca (19-37% medido).
    #
    # La unica forma de cumplir es CERRAR el simbolo cuando su ganancia del dia
    # toca el tope, y no volver a entrar. Cuesta la cola derecha — pero en
    # evaluacion la cola no sirve, porque rompe la regla. Medido en
    # `evaluacion.py` con arranques rodantes: con tope al 70% del limite, todos
    # los papeles y sin corte, $150-200 por papel pasa limpio en ~100 dias
    # esperados. Solo aplica en modo evaluacion; fondeada no tiene consistencia.
    #
    # Se mide sobre la equity a mercado del papel —cerrados a valor final,
    # vivos contra el close de la barra—, igual que el presupuesto y el
    # drawdown. Va DESPUES del corte a proposito: si el tope llega antes de las
    # 11, el dia termina ahi y lo que el corte hubiera hecho no existe.
    if tope_usd is not None and detalle:
        signo = -1.0 if lado == "short" else 1.0
        i0 = min((dia.idx_en(t["h_ent"]) or 0) for t in detalle)
        for k in range(i0, len(dia.bars)):
            b = dia.bars[k]
            h = hora(b)
            if h > CIERRE_RTH:
                break
            px = b[4]
            if not px:
                continue
            eq = 0.0
            for t in detalle:
                if t["h_ent"] > h:
                    continue
                if t["h_sal"] is not None and t["h_sal"] <= h:
                    eq += signo * t["acciones"] * (t["p_sal"] - t["p_ent"])
                else:
                    eq += signo * t["acciones"] * (px - t["p_ent"])
            if eq >= tope_usd:
                for t in detalle:
                    if t["h_ent"] <= h and (t["h_sal"] is None or t["h_sal"] > h):
                        t["h_sal"], t["p_sal"], t["motivo"] = h, px, "tope"
                        t["pnl"] = (signo * t["acciones"] * (px - t["p_ent"])
                                    - t["acciones"] * COSTO_ACCION)
                # Los tramos que entraban despues no existen: el dia se cerro.
                detalle = [t for t in detalle if t["h_ent"] <= h]
                n = len(detalle)
                pnl = sum(t["pnl"] for t in detalle)
                break

    if not n:
        return None
    return {"pnl": pnl, "nominal": _nominal_pico(detalle), "trades": n,
            "detalle": detalle}


def _nominal_pico(detalle):
    """La MÁXIMA exposición simultánea del día, no el trade más grande.

    **El error que esto corrige valía hasta 9x.** La señal de swing entra varias
    veces en la misma bajada y todos los tramos se sostienen hasta el cierre: el
    19/12/2024 en PRFX abrió diez posiciones entre las 10:07 y las 10:42, y las
    diez seguían abiertas a las 16:00. Eso no son diez trades, es UNA posición
    construida en diez tramos.

    Como el locate se paga por las acciones que hay que tener reservadas, lo que
    manda es cuánto papel se necesita **al mismo tiempo**. Tomar el máximo de un
    solo tramo subestimaba el costo por el número de tramos concurrentes — y el
    locate es justamente la variable que decide si el sistema es un negocio.

    Se barre el día por eventos: cada apertura suma nominal, cada cierre lo
    resta, y se registra el pico.
    """
    ev = []
    for t in detalle:
        ev.append((t["h_ent"], +t["nominal"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["nominal"]))
    ev.sort(key=lambda x: (x[0], -x[1]))   # ante empate, primero abre
    vivo = pico = 0.0
    for _, delta in ev:
        vivo += delta
        pico = max(pico, vivo)
    return pico


# --------------------------------------------------------------------------
# La medición estándar
# --------------------------------------------------------------------------

def _metricas(filas):
    if len(filas) < 20:
        return None
    m = statistics.mean(x[1] for x in filas)
    n = statistics.mean(x[2] for x in filas)
    return {
        "n": len(filas),
        "bruto_R": round(m, 4),
        "nom_R": round(n, 3),
        "ret_nom": round(100 * m / n, 1) if n else 0.0,
        "neto20_R": round(m - LOCATE_REF * n, 4),
        "positivas": round(100 * sum(1 for x in filas if x[1] > 0) / len(filas)),
    }


def evaluar(nombre, señal, *, dias=None, lado="short", stop=45.0, pob=None,
            max_trades=10, objetivo_pct=None, salida_h=None, guardar=True,
            apertura="fade", familia="", notas="", trail_ancho=None,
            trail_devuelve=None, trail_arma=0.0):
    """Corre una estrategia y devuelve el diccionario estándar de resultados.

    `apertura` filtra por cómo abrió el día: "fade" (abre y cae bajo el VWAP),
    "reclaim" (recupera), o None para no filtrar. El default es "fade" porque es
    lo que usa toda la línea de base validada del proyecto — cambiarlo sin
    querer fue lo que hizo que la primera versión de este harness no
    reprodujera los números conocidos.
    """
    if dias is None:
        dias = universo()
    pobl = poblacion(dias, **(pob or {}))
    if apertura:
        # `hasta=9.75` NO es un detalle: `clasificar_apertura` por defecto mira
        # barras hasta las 10:00, pero las señales entran desde las 09:45. Usar
        # el default etiqueta el día con información que a la hora de entrar
        # todavía no existe — look-ahead puro. Medido: inflaba la línea de base
        # 12,1 puntos de ret/nom (45,5% contra 33,4% real). Se clasifica con lo
        # que se ve a las 09:45, que es cuando se puede entrar por primera vez.
        pobl = [d for d in pobl if clasificar_apertura(d, hasta=9.75) == apertura]

    por_fecha = defaultdict(list)
    for dia in pobl:
        por_fecha[dia.d].append(dia)

    filas = []          # (fecha, pnl en R, nominal en R)
    trades, registros = 0, []
    for d in sorted(por_fecha):
        cands = por_fecha[d]
        cuota = R_BASE / len(cands)
        pnl, nom, hubo = 0.0, 0.0, False
        for dia in cands:
            j = jornada(dia, señal, lado=lado, stop_pct=stop, riesgo=cuota,
                        max_trades=max_trades, objetivo_pct=objetivo_pct,
                        salida_h=salida_h, trail_ancho=trail_ancho,
                        trail_devuelve=trail_devuelve, trail_arma=trail_arma)
            if not j:
                continue
            hubo = True
            pnl += j["pnl"]
            nom += j["nominal"]
            trades += j["trades"]
            for t in j["detalle"]:
                registros.append((
                    nombre, dia.ticker, d, t["h_ent"], t["h_sal"],
                    t["p_ent"], t["p_sal"], t["stop_pct"], t["acciones"],
                    t["pnl"],
                    round(100 * (t["p_sal"] / t["p_ent"] - 1), 3) if t["p_ent"] else None,
                    t["mae_pct"], t["mfe_pct"], t["motivo"],
                    "P1" if d < CORTE else "P2",
                    round(dia.expansion_pct or 0, 1),
                    dia.liquidez_en(t["h_ent"]) or 0))
        if hubo:
            filas.append((d, pnl / R_BASE, nom / R_BASE))

    g = _metricas(filas)
    if not g:
        return {"nombre": nombre, "error": f"muestra corta ({len(filas)})"}
    p1 = _metricas([x for x in filas if x[0] < CORTE])
    p2 = _metricas([x for x in filas if x[0] >= CORTE])

    res = {
        "nombre": nombre, "familia": familia, "lado": lado, "stop": stop,
        "apertura": apertura, "pob": pob or {},
        "objetivo_pct": objetivo_pct, "salida_h": salida_h, "notas": notas,
        "ses_mes": round(len(filas) / MESES, 1),
        "trades_mes": round(trades / MESES),
        **g,
        "P1": p1, "P2": p2,
        "replica": (round(abs(p1["ret_nom"] - p2["ret_nom"]), 1)
                    if p1 and p2 else None),
        "serie": {d: round(v, 4) for d, v, _ in filas},
    }
    if guardar:
        _guardar(res, registros, filas)
    return res


_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    estrategia TEXT NOT NULL, ticker TEXT NOT NULL, d TEXT NOT NULL,
    hora_entrada REAL NOT NULL, hora_salida REAL,
    precio_entrada REAL, precio_salida REAL,
    stop_pct REAL, acciones REAL, pnl REAL, ret_pct REAL,
    mae_pct REAL, mfe_pct REAL, motivo TEXT, periodo TEXT,
    expansion REAL, liquidez REAL,
    PRIMARY KEY (estrategia, ticker, d, hora_entrada)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_tr_est ON trades(estrategia);
CREATE INDEX IF NOT EXISTS ix_tr_dia ON trades(ticker, d);

-- Una fila por estrategia: la configuración COMPLETA más sus métricas. Tiene
-- que alcanzar para reproducir la corrida sin leer el código que la generó.
CREATE TABLE IF NOT EXISTS estrategia (
    nombre TEXT PRIMARY KEY, familia TEXT, lado TEXT, stop REAL, apertura TEXT,
    pob TEXT, objetivo_pct REAL, salida_h REAL, notas TEXT,
    ses_mes REAL, trades_mes INTEGER, n INTEGER,
    bruto_R REAL, nom_R REAL, ret_nom REAL, neto20_R REAL, positivas REAL,
    p1_ret_nom REAL, p2_ret_nom REAL, replica REAL, creado TEXT
);

-- La serie por sesión: es lo que se correlaciona entre estrategias y lo que
-- dibuja la curva de capital. Sin esto no hay cartera posible.
CREATE TABLE IF NOT EXISTS sesion (
    estrategia TEXT NOT NULL, d TEXT NOT NULL,
    pnl_R REAL, nominal_R REAL,
    PRIMARY KEY (estrategia, d)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_se_est ON sesion(estrategia);
"""


def db_path():
    return Path(config.data_dir()) / "trades.sqlite"


def _conn():
    c = sqlite3.connect(db_path(), timeout=60)
    c.execute("PRAGMA journal_mode=WAL")     # varios subagentes escriben a la vez
    c.executescript(_SCHEMA)
    return c


def _guardar(res, registros, filas):
    """Persiste todo: trades, serie por sesión y metadatos.

    Se guarda en el MISMO sqlite que ya lee el visor, así cualquier estrategia
    nueva aparece en /historial con sus velas sin tocar el front.
    """
    import datetime as _dt
    c = _conn()
    nom = res["nombre"]
    with c:
        c.execute("DELETE FROM trades WHERE estrategia=?", (nom,))
        c.execute("DELETE FROM sesion WHERE estrategia=?", (nom,))
        c.executemany(
            "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            registros)
        c.executemany("INSERT OR REPLACE INTO sesion VALUES (?,?,?,?)",
                      [(nom, d, p, n) for d, p, n in filas])
        c.execute(
            "INSERT OR REPLACE INTO estrategia VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (nom, res.get("familia", ""), res["lado"], res["stop"],
             res.get("apertura"), json.dumps(res["pob"]), res["objetivo_pct"],
             res["salida_h"], res["notas"], res["ses_mes"], res["trades_mes"],
             res["n"], res["bruto_R"], res["nom_R"], res["ret_nom"],
             res["neto20_R"], res["positivas"],
             (res["P1"] or {}).get("ret_nom"), (res["P2"] or {}).get("ret_nom"),
             res["replica"], _dt.datetime.now().isoformat(timespec="seconds")))
    c.close()

    # El JSON queda como espejo legible para inspección rápida.
    #
    # El temporal lleva el PID adentro y el `replace` reintenta: varios subagentes
    # corren familias distintas AL MISMO TIEMPO, y con un nombre de temporal fijo
    # los dos escriben el mismo archivo y el `replace` del segundo muere con
    # WinError 32 (el otro proceso lo tiene abierto) — llevándose puesta la corrida
    # entera, no sólo el espejo.
    #
    # Lo que esto NO arregla: dos procesos que leen el JSON a la vez pisan el
    # resultado del otro (lost update). Se acepta a propósito. La fuente de verdad
    # es el sqlite, que sí está preparado para concurrencia (WAL + timeout); este
    # archivo es un espejo de lectura y se reconstruye solo en la próxima corrida.
    data = {}
    if RESULTADOS.exists():
        try:
            data = json.loads(RESULTADOS.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[nom] = res
    tmp = RESULTADOS.with_name(f"{RESULTADOS.stem}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for intento in range(10):
        try:
            tmp.replace(RESULTADOS)
            break
        except OSError:
            time.sleep(0.05 * (intento + 1))
    else:
        tmp.unlink(missing_ok=True)      # el espejo no vale abortar la corrida


def linea(res):
    """Una línea legible por estrategia."""
    if "error" in res:
        return f"  {res['nombre']:<38} {res['error']}"
    r = res
    rep = f"{r['replica']:>5.1f}p" if r["replica"] is not None else "    —"

    def mitad(m):
        """'sin dato' NO es lo mismo que 0%, y escribir 0% ahí es mentir.

        `_metricas` devuelve None cuando la mitad tiene menos de 20 sesiones.
        Esta función imprimía 0.0% en ese caso, que se lee como "midió cero"
        cuando lo que pasa es que no se midió. Ya nos confundió dos veces:
        una estrategia con P2 vacío parecía replicar perfecto.
        """
        return f"{m['ret_nom']:>6.1f}%" if m else f"{'s/dato':>7}"

    return (f"  {r['nombre']:<38} {r['ses_mes']:>5.1f}/m {r['trades_mes']:>4}tr "
            f"{r['bruto_R']:>+7.3f} {r['nom_R']:>6.2f} {r['ret_nom']:>6.1f}% "
            f"{r['neto20_R']:>+7.3f} "
            f"{mitad(r['P1'])} {mitad(r['P2'])} {rep}")


def encabezado():
    return ("  " + "estrategia".ljust(38) + "  ses/m trades  bruto   nom  ret/nom "
            "  neto20  P1     P2    brecha")


def correlacion(a, b):
    """Correlación entre dos estrategias sobre las fechas que COMPARTEN.

    Si comparten menos de 20 fechas, devuelve None: dos estrategias que casi no
    se solapan en el calendario ya están decorrelacionadas por construcción, y
    forzar un número ahí sería inventarlo.
    """
    comunes = sorted(set(a) & set(b))
    if len(comunes) < 20:
        return None
    x = [a[d] for d in comunes]
    y = [b[d] for d in comunes]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if not sx or not sy:
        return None
    return sum((x[i] - mx) * (y[i] - my) for i in range(len(x))) / (sx * sy)


if __name__ == "__main__":
    from sesion import señales_swing
    dias = universo()
    print(f"  universo: {len(dias)} días en caché\n")
    print(encabezado())
    print("  " + "-" * 104)
    for u in (100, 150):
        r = evaluar(f"base·swing·exp{u}", lambda d: señales_swing(d),
                    dias=dias, stop=45.0, pob={"min_expansion": u},
                    notas="línea de base del proyecto")
        print(linea(r))
