#!/usr/bin/env python3
"""Mecanismos de EXPOSICIÓN: cómo conseguir el mismo bruto con menos posición.

**Por qué existe este archivo.** `motor.jornada` tiene una sola forma de armar la
posición —abrir un tramo por señal y sostener todos hasta el cierre— así que el
pico de exposición simultánea crece con la cantidad de señales del día. Acá se
prueban las alternativas: rolar, topear, escalonar, condicionar.

LAS DOS IDENTIDADES QUE HAY QUE TENER EN LA CABEZA ANTES DE PROBAR NADA
-----------------------------------------------------------------------
El tamaño sale del riesgo: `acciones = riesgo / (p · stop%)`, así que el nominal
de un tramo es `riesgo / stop%` — **no depende del precio del papel**. Con
`stop=45%` y `riesgo=R/3`, todo tramo vale exactamente 0,741 R de nominal. De ahí:

    ret/nom     =  Σ pnl / (0,741 · picos)   =  el % promedio que se movió el
                                                papel, por unidad de exposición
                                                SIMULTÁNEA

    $ / acción  =  Σ pnl / acciones_pico     =  los DÓLARES promedio que se movió
                                                el papel, por acción prestada al
                                                mismo tiempo

Las dos miden lo mismo con distinta unidad, y la que importa es la segunda: el
locate se cobra **por acción**, no por dólar de nominal. Un papel de $10 que cae
12% y uno de $1 que cae 12% dan el mismo `ret/nom` y pagan el mismo locate en
centavos — o sea que el primero deja diez veces más margen. `ret/nom` es ciego al
precio por construcción, y por eso todos los barridos de precio de este proyecto
dieron nada: estaban midiendo con la unidad que borra justo esa variable.

Consecuencias que ahorran experimentos:

  1. **Mover el ancho del stop NO mueve ninguna de las dos por la vía del
     tamaño.** Un stop más ancho achica la posición Y achica el PnL en la misma
     proporción. Sólo cambia el resultado por dónde te saca del trade. Cualquier
     lectura de "con stop 55 el nominal baja" es una ilusión contable.
  2. **Agregar tramos que se solapan sube el pico linealmente.** Sube el bruto
     sólo si los tramos nuevos capturan tanto como los viejos.
  3. **Lo único que rompe el techo es el solapamiento**: si un tramo cierra
     antes de que abra el siguiente, el pico deja de ser la suma.
  4. **El precio de entrada es una palanca que no toca el edge.** Es la única
     que mueve `$/acción` sin tener que acertar más seguido, y se mide en
     `centavos.py`.

LOS MECANISMOS QUE SE MIDEN
---------------------------
  · `acumular`   — lo de hoy: cada señal abre un tramo y se sostiene al cierre.
  · `rolar`      — el tramo N se cierra cuando entra el N+1. Pico = 1 tramo.
  · `tope`       — máximo C tramos vivos; si está lleno, la señal se SALTEA.
  · `tope-rolar` — máximo C tramos vivos; si está lleno, se cierra el más viejo.
  · `escala`     — pesos por tramo (creciente, decreciente) en vez de parejo.
  · `condicional`— sólo se agrega si el tramo anterior está EN GANANCIA en ese
                   minuto (marcado a mercado con la barra de la entrada nueva,
                   no con el resultado final: eso sería mirar el futuro).

EL PRESUPUESTO DE RIESGO, Y EL ERROR QUE APARECIÓ ACÁ
-----------------------------------------------------
`motor.jornada` decide si abre el tramo N mirando el `pnl` acumulado, pero ese
`pnl` incluye tramos que **todavía no cerraron** a la hora de la entrada nueva:
el 80% de los tramos se abren con otro vivo. O sea que el corte por presupuesto
usa información del futuro. Acá el presupuesto es un parámetro explícito:

  · `futuro`    — lo que hace `motor.jornada` hoy (se conserva para comparar)
  · `realizado` — sólo cuentan los tramos ya CERRADOS a esa hora
  · `mtm`       — cerrados + los vivos marcados a mercado en esa barra. Es el
                  honesto, y además el que se parece a una cuenta de fondeo, que
                  mide el drawdown sobre la equity y no sobre lo realizado.
  · `ninguno`   — sin límite diario, para aislar el efecto

CONTROLES DE CORDURA (regla 4 del proyecto: si mejora mucho, es un bug)
----------------------------------------------------------------------
`python exposicion.py --control` corre cuatro identidades que TIENEN que dar
diferencia cero, y si alguna falla el archivo no sirve:

  · `tope=99` ≡ `acumular`            (un tope que nunca ata no cambia nada)
  · `escala` plana ≡ `acumular`
  · `rolar` sobre días de UN solo tramo ≡ `acumular` sobre esos mismos días
  · `acumular` + `presupuesto=futuro` ≡ `motor.jornada`, sesión por sesión

    python exposicion.py --control      # los controles, primero
    python exposicion.py                # la grilla de mecanismos
"""

from __future__ import annotations

import argparse
import statistics
import sys

import motor
from chavineta import clasificar_apertura as _clasificar
from dias import CIERRE_RTH, hora
from motor import COSTO_ACCION, R_BASE, poblacion, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# Un tramo, simulado UNA sola vez y sin política encima.
# --------------------------------------------------------------------------

def _tramo_crudo(dia, i, *, lado, stop_pct):
    """El trade que saldría si nadie lo interrumpiera. Tamaño unitario.

    Devuelve todo en **fracciones**, no en dólares: `ret` es el retorno a favor
    del lado operado por dólar de nominal, y el costo por acción se pasa a
    fracción del precio de entrada. Así el mismo tramo sirve para cualquier peso
    de escalonado sin volver a recorrer las barras — que es lo que hace viable
    barrer decenas de políticas sobre 2.000 días.

    `salida_i` es el índice de la barra donde el trade muere solo. Una política
    que lo cierre ANTES sólo puede hacerlo en una barra anterior a ésa, y ahí el
    precio de salida es el cierre de esa barra: el stop no llegó a tocarse, así
    que el camino previo es idéntico. Ese es el único motivo por el que se puede
    re-politizar sin re-simular, y por eso `_ret_forzado` exige `j < salida_i`.
    """
    p = dia.bars[i][4]
    if not p or stop_pct <= 0:
        return None
    signo = -1.0 if lado == "short" else 1.0
    p_stop = p * (1 - signo * stop_pct / 100.0)
    costo_frac = COSTO_ACCION / p

    ult = None
    for j in range(i + 1, len(dia.bars)):
        b = dia.bars[j]
        if hora(b) > CIERRE_RTH:
            break
        ult = j
        toca = (b[2] and b[2] >= p_stop) if lado == "short" else (b[3] and b[3] <= p_stop)
        if toca:
            return {"i": i, "h_ent": hora(dia.bars[i]), "p_ent": p,
                    "salida_i": j, "h_sal": hora(b), "p_sal": p_stop,
                    "ret": -stop_pct / 100.0 - costo_frac, "motivo": "stop"}
    c = dia.rth_close
    if not c or ult is None:
        return None
    return {"i": i, "h_ent": hora(dia.bars[i]), "p_ent": p,
            "salida_i": ult, "h_sal": CIERRE_RTH, "p_sal": c,
            "ret": signo * (c - p) / p - costo_frac, "motivo": "cierre"}


def _ret_forzado(dia, t, j, *, lado):
    """Retorno si el tramo `t` se cierra a la fuerza en la barra `j`.

    Sólo se llama con `j < t['salida_i']`: si el stop ya se tocó, el trade está
    muerto y no hay nada que forzar. Se sale al cierre de esa barra.
    """
    p_sal = dia.bars[j][4]
    if not p_sal:
        return None
    signo = -1.0 if lado == "short" else 1.0
    return signo * (p_sal - t["p_ent"]) / t["p_ent"] - COSTO_ACCION / t["p_ent"]


def _mtm(dia, t, j, *, lado):
    """Marcado a mercado del tramo `t` en la barra `j`, sin cobrar la salida."""
    p = dia.bars[j][4]
    if not p:
        return 0.0
    signo = -1.0 if lado == "short" else 1.0
    return signo * (p - t["p_ent"]) / t["p_ent"]


# --------------------------------------------------------------------------
# La política de exposición
# --------------------------------------------------------------------------

def _pesos(escala, n):
    """Pesos por tramo, normalizados a que el PRIMERO valga 1.

    Se normaliza al primero y no a la suma a propósito: así `escala=None` es
    idéntico al baseline, y un escalonado se lee como "el tramo 3 pesa 0,5 del
    primero" sin depender de cuántos tramos hubo ese día — que es un número que
    no se conoce cuando se abre el primero.
    """
    if escala in (None, "plano"):
        return [1.0] * n
    if escala == "decreciente":
        return [1.0 / (k + 1) for k in range(n)]
    if escala == "mitad":
        return [0.5 ** k for k in range(n)]
    if escala == "creciente":
        return [float(k + 1) for k in range(n)]
    if isinstance(escala, (list, tuple)):
        return [float(escala[min(k, len(escala) - 1)]) for k in range(n)]
    raise ValueError(f"escala desconocida: {escala}")


def jornada_exp(dia, señal, *, lado="short", stop_pct=45.0, riesgo=R_BASE,
                max_trades=10, modo="acumular", tope=None, escala=None,
                presupuesto="futuro", tope_r=None, **_ignorado):
    """Una sesión con política de exposición explícita. Formato de `motor.jornada`.

    Devuelve `{"pnl", "nominal", "trades", "detalle"}` para ser intercambiable con
    `motor.jornada`, de modo que `motor.evaluar` persista los resultados en el
    visor sin tocar el motor.

    `tope_r` topea la exposición concurrente en R de NOMINAL, no en cantidad de
    tramos. Es el límite que razona una cuenta de fondeo: dólares desplegados,
    no cuántas órdenes mandaste.
    """
    idx = señal(dia)
    if not idx:
        return None
    r_tramo = riesgo / 3.0
    nom_unit = r_tramo / (stop_pct / 100.0)      # nominal de un tramo con peso 1
    pesos = _pesos(escala, len(idx))

    vivos = []      # [(tramo, peso)] abiertos, en orden de entrada
    cerrados = []   # [(tramo, peso, ret_final, salida_i)]
    realizado = 0.0
    n = 0

    def _cosechar(j):
        """Pasa a cerrados todo lo que murió solo en o antes de la barra `j`."""
        nonlocal realizado
        quedan = []
        for t, w in vivos:
            if t["salida_i"] <= j:
                cerrados.append((t, w, t["ret"], t["salida_i"]))
                realizado += w * nom_unit * t["ret"]
            else:
                quedan.append((t, w))
        vivos[:] = quedan

    def _forzar(t, w, j):
        nonlocal realizado
        r = _ret_forzado(dia, t, j, lado=lado)
        if r is None:
            r, j = t["ret"], t["salida_i"]
        cerrados.append((t, w, r, j))
        realizado += w * nom_unit * r

    for k, i in enumerate(idx):
        if n >= max_trades:
            break
        _cosechar(i)
        w = pesos[k]

        # ---- el presupuesto del día ------------------------------------
        if presupuesto != "ninguno":
            if presupuesto == "realizado":
                base = realizado
            elif presupuesto == "mtm":
                base = realizado + sum(
                    wv * nom_unit * _mtm(dia, tv, i, lado=lado) for tv, wv in vivos)
            elif presupuesto == "futuro":     # lo que hace motor.jornada
                base = realizado + sum(wv * nom_unit * tv["ret"] for tv, wv in vivos)
            else:
                raise ValueError(f"presupuesto desconocido: {presupuesto}")
            if base - w * r_tramo < -riesgo:
                break

        # ---- la política de exposición ---------------------------------
        if modo == "rolar":
            for t, wv in list(vivos):
                _forzar(t, wv, i)
            vivos.clear()
        elif modo in ("tope", "tope-rolar") and tope is not None:
            if len(vivos) >= tope:
                if modo == "tope":
                    continue                      # se saltea la señal
                t, wv = vivos.pop(0)              # se cierra el más viejo
                _forzar(t, wv, i)
        elif modo == "condicional":
            # ¿el último tramo abierto está en ganancia AHORA? Si no hay ninguno
            # abierto, manda el resultado del último que cerró.
            if vivos:
                if _mtm(dia, vivos[-1][0], i, lado=lado) <= 0:
                    continue
            elif cerrados and cerrados[-1][2] <= 0:
                continue

        if tope_r is not None:
            vivo_nom = sum(wv * nom_unit for _, wv in vivos)
            while vivos and vivo_nom + w * nom_unit > tope_r * riesgo:
                t, wv = vivos.pop(0)
                _forzar(t, wv, i)
                vivo_nom -= wv * nom_unit
            if vivo_nom + w * nom_unit > tope_r * riesgo:
                continue                          # ni un tramo solo entra

        t = _tramo_crudo(dia, i, lado=lado, stop_pct=stop_pct)
        if not t:
            continue
        vivos.append((t, w))
        n += 1

    _cosechar(len(dia.bars))
    for t, w in vivos:                    # los que llegaron vivos al cierre RTH
        cerrados.append((t, w, t["ret"], t["salida_i"]))
        realizado += w * nom_unit * t["ret"]
    if not cerrados:
        return None

    detalle = []
    for t, w, ret, sal_i in cerrados:
        propio = sal_i == t["salida_i"]
        detalle.append({
            "pnl": w * nom_unit * ret,
            "motivo": t["motivo"] if propio else "politica",
            "nominal": w * nom_unit,
            "acciones": w * nom_unit / t["p_ent"],
            "h_ent": t["h_ent"], "p_ent": t["p_ent"],
            "h_sal": t["h_sal"] if propio else hora(dia.bars[sal_i]),
            "p_sal": t["p_sal"] if propio else dia.bars[sal_i][4],
            "stop_pct": stop_pct, "mae_pct": 0.0, "mfe_pct": 0.0})
    detalle.sort(key=lambda d: d["h_ent"])
    return {"pnl": sum(d["pnl"] for d in detalle),
            "nominal": motor._nominal_pico(detalle),
            "acciones": acciones_pico(detalle),
            "trades": len(detalle), "detalle": detalle}


def acciones_pico(detalle):
    """La MÁXIMA cantidad de acciones prestadas al mismo tiempo.

    **No es lo mismo que el nominal pico, y la diferencia es el proyecto.** El
    locate se cobra por ACCIÓN, no por dólar: 5.000 acciones de un papel de $1 y
    500 de uno de $10 son el mismo nominal y cuestan diez veces distinto. Por eso
    hace falta un barrido propio — y además los dos picos pueden caer en minutos
    distintos, así que tomar el nominal pico y dividirlo por un precio promedio
    da un número que no existió nunca.

    Misma mecánica que `motor._nominal_pico`: se barre el día por eventos, cada
    apertura suma acciones, cada cierre las resta, y se registra el máximo.
    """
    ev = []
    for t in detalle:
        ev.append((t["h_ent"], +t["acciones"]))
        ev.append((t["h_sal"] if t["h_sal"] is not None else 24.0, -t["acciones"]))
    ev.sort(key=lambda x: (x[0], -x[1]))   # ante empate, primero abre
    vivo = pico = 0.0
    for _, delta in ev:
        vivo += delta
        pico = max(pico, vivo)
    return pico


def con_politica(**politica):
    """Un `jornada` con la política adentro, para inyectar en `motor.evaluar`.

    `motor.evaluar` resuelve `jornada` por atributo de módulo, así que pisar
    `motor.jornada` alcanza para que la persistencia, los cortes P1/P2 y las
    series por sesión sigan andando sin tocar el motor.
    """
    def f(dia, señal, **kw):
        kw.update(politica)
        return jornada_exp(dia, señal, **kw)
    return f


# --------------------------------------------------------------------------
# Los controles de cordura. Sin esto no se mira ningún resultado.
# --------------------------------------------------------------------------

def _serie(dias, señal, **pol):
    out = {}
    for d in dias:
        j = jornada_exp(d, señal, lado="short", stop_pct=45.0, riesgo=R_BASE,
                        max_trades=10, **pol)
        if j:
            out[(d.ticker, d.d)] = (round(j["pnl"], 6), round(j["nominal"], 6),
                                    j["trades"])
    return out


def _serie_motor(dias, señal):
    out = {}
    for d in dias:
        j = motor.jornada(d, señal, lado="short", stop_pct=45.0, riesgo=R_BASE,
                          max_trades=10)
        if j:
            out[(d.ticker, d.d)] = (round(j["pnl"], 6), round(j["nominal"], 6),
                                    j["trades"])
    return out


def _diff(a, b, etiqueta):
    faltan = set(a) ^ set(b)
    comunes = set(a) & set(b)
    peor = 0.0
    distintos = 0
    for k in comunes:
        if a[k] != b[k]:
            distintos += 1
            peor = max(peor, abs(a[k][0] - b[k][0]), abs(a[k][1] - b[k][1]))
    ok = not faltan and not distintos
    print(f"  {'OK  ' if ok else 'FALLA'} {etiqueta:<52} "
          f"días distintos {len(faltan):>3} · sesiones distintas {distintos:>4} "
          f"· peor delta {peor:.6f}")
    return ok


def controles(dias):
    print("\n  CONTROLES DE CORDURA — todos tienen que dar diferencia cero\n")
    sig = lambda d: señales_swing(d, desde=10.0)
    pob = poblacion(dias, min_ratio_vol=0.0, min_expansion=150.0, min_dolar=0.0)
    pob = [d for d in pob if _clasificar(d, hasta=10.0) == "fade"]
    print(f"  base del control: {len(pob)} días fade·exp150\n")

    # `motor.jornada` pasó a usar el presupuesto honesto el 2026-09-01, así que
    # la identidad contra el motor ahora se chequea con `mtm`. La identidad con
    # `futuro` se conserva aparte: es la que prueba que este banco reproducía el
    # motor VIEJO, y por lo tanto que la diferencia medida entre presupuestos era
    # del presupuesto y no de haber reimplementado otra cosa.
    base = _serie(pob, sig, modo="acumular", presupuesto="mtm")
    ok = True
    ok &= _diff(base, _serie_motor(pob, sig),
                "acumular+mtm     ==  motor.jornada (hoy)")
    ok &= _diff(base, _serie(pob, sig, modo="tope", tope=99, presupuesto="mtm"),
                "tope=99          ==  acumular")
    ok &= _diff(base, _serie(pob, sig, modo="tope-rolar", tope=99, presupuesto="mtm"),
                "tope-rolar=99    ==  acumular")
    ok &= _diff(base, _serie(pob, sig, escala="plano", presupuesto="mtm"),
                "escala plana     ==  acumular")
    ok &= _diff(base, _serie(pob, sig, tope_r=99.0, presupuesto="mtm"),
                "tope_r=99R       ==  acumular")

    # Rolar sólo puede diferir donde hay más de un tramo. En los días de un
    # tramo tiene que ser idéntico, y ese es el control que separa "cambió por
    # el mecanismo" de "cambió porque rompí algo".
    un_tramo = [d for d in pob if len(sig(d)) == 1]
    a = _serie(un_tramo, sig, modo="rolar", presupuesto="mtm")
    b = _serie(un_tramo, sig, modo="acumular", presupuesto="mtm")
    ok &= _diff(a, b, f"rolar == acumular en los {len(un_tramo)} días de 1 tramo")

    print(f"\n  {'TODOS OK' if ok else 'HAY AL MENOS UN CONTROL EN ROJO'}\n")
    return ok


# --------------------------------------------------------------------------

CASOS = [
    ("fade·exp150", "fade", 150.0, 999),
    ("reclaim·exp100", "reclaim", 100.0, 60),
]

POLITICAS = [
    ("acumular",            dict(modo="acumular")),
    ("rolar",               dict(modo="rolar")),
    ("tope-2·saltea",       dict(modo="tope", tope=2)),
    ("tope-3·saltea",       dict(modo="tope", tope=3)),
    ("tope-4·saltea",       dict(modo="tope", tope=4)),
    ("tope-2·rola",         dict(modo="tope-rolar", tope=2)),
    ("tope-3·rola",         dict(modo="tope-rolar", tope=3)),
    ("tope-4·rola",         dict(modo="tope-rolar", tope=4)),
    ("escala·decreciente",  dict(escala="decreciente")),
    ("escala·mitad",        dict(escala="mitad")),
    ("escala·creciente",    dict(escala="creciente")),
    ("condicional",         dict(modo="condicional")),
    ("tope_r·1R",           dict(tope_r=1.0)),
    ("tope_r·2R",           dict(tope_r=2.0)),
    ("tope_r·3R",           dict(tope_r=3.0)),
]


def ventana(mins, desde=10.0):
    """Sólo los tramos dentro de `mins` minutos del primero del día."""
    def f(d):
        idx = señales_swing(d, desde=desde)
        if not idx:
            return idx
        h0 = hora(d.bars[idx[0]])
        return [i for i in idx if hora(d.bars[i]) - h0 <= mins / 60.0]
    return f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true", help="sólo los controles")
    ap.add_argument("--presupuesto", default="mtm",
                    choices=("futuro", "realizado", "mtm", "ninguno"))
    ap.add_argument("--guardar", action="store_true",
                    help="persistir en trades.sqlite para el visor")
    args = ap.parse_args(argv)

    motor.clasificar_apertura = lambda d, **k: _clasificar(d, hasta=10.0)
    dias = universo()
    if args.control:
        return 0 if controles(dias) else 1

    orig = motor.jornada
    print("=" * 100)
    print(f"  MECANISMOS DE EXPOSICIÓN · presupuesto={args.presupuesto}")
    print("=" * 100)
    for lab, ap_, ex, vm in CASOS:
        print(f"\n  {lab.upper()}\n")
        print(f"  {'política':<22} {'ses/m':>6} {'trades':>7} {'bruto R':>9} "
              f"{'nom R':>7} {'ret/nom':>9} {'neto@20%':>10} {'P1':>7} {'P2':>7} {'brecha':>8}")
        print("  " + "-" * 100)
        for pol_nom, pol in POLITICAS:
            motor.jornada = con_politica(presupuesto=args.presupuesto, **pol)
            r = motor.evaluar(f"exp·{pol_nom}·{lab}", ventana(vm), dias=dias,
                              familia="exposicion", stop=45.0, apertura=ap_,
                              pob={"min_expansion": ex, "min_ratio_vol": 0.0,
                                   "min_dolar": 0.0},
                              guardar=args.guardar,
                              notas=f"{pol_nom}, presupuesto {args.presupuesto}")
            if "error" in r:
                print(f"  {pol_nom:<22} {r['error']}")
                continue
            print(f"  {pol_nom:<22} {r['ses_mes']:>6.1f} {r['trades_mes']:>7} "
                  f"{r['bruto_R']:>+9.3f} {r['nom_R']:>7.2f} {r['ret_nom']:>8.1f}% "
                  f"{r['neto20_R']:>+10.3f} "
                  f"{(r['P1'] or {}).get('ret_nom', 0):>6.1f}% "
                  f"{(r['P2'] or {}).get('ret_nom', 0):>6.1f}% "
                  f"{(r['replica'] if r['replica'] is not None else 0):>7.1f}p")
    motor.jornada = orig
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
