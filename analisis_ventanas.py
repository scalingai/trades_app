#!/usr/bin/env python3
"""
Las ventanas horarias del indicador ICT: 01:00-04:00, 09:55-10:05 y 10:25-10:35.

Es la primera hipótesis del proyecto que se formula en minutos y no en horas, y
por eso ninguno de los análisis anteriores podía verla: todos agrupan por hora
UTC, y una ventana de diez minutos definida en hora de Nueva York se diluye
dentro de un bucket de sesenta.

Se contrasta en cuatro pasos, del más fácil de pasar al más difícil.

**1. ¿Pasa algo en esos minutos?** Se mide la expansión media de cada uno de los
144 tramos de diez minutos del día y se mira qué puesto ocupan los tres
señalados. La pregunta no es si su número es alto, sino si es alto *comparado
con las otras 143 opciones que había*, que es la única forma de que la respuesta
signifique algo.

**2. ¿Se puede operar la hora sola?** Un bracket simétrico abierto al empezar la
ventana, largo y corto. Una hora del día no dice hacia dónde ir, así que aquí no
debería haber nada; si lo hay, es deriva real.

**3. ¿Funciona el modelo?** Lo que el gráfico enseña no es "compra a las 09:55"
sino barrido y reversión: dentro de la ventana el precio perfora un extremo
previo y se da la vuelta. Eso sí tiene dirección, y se mide entrando al cerrar
la ventana. Se corre también en los 144 tramos para ver si el efecto es de esos
minutos o de la regla, que no es lo mismo.

**4. ¿Se repite?** Acuerdo mes a mes, que es lo que separa un patrón de una
racha.

Y por encima de todo está la aritmética del bracket del gráfico: 200 puntos de
stop y 200 de objetivo sobre 65.110 son un 0,307 %, y con 12 puntos básicos de
coste de ida y vuelta eso exige acertar el 69,5 % de las veces sólo para no
perder dinero. Ese número manda sobre todos los demás.

    python analisis_ventanas.py
    python analisis_ventanas.py --zona nueva-york --stop 0.005
"""

import argparse
import sys

import numpy as np
import pandas as pd

from backtest import barreras, ventanas
from descargar_datos import cargar_datos

COSTE = 0.0012
COSTE_MAKER = 0.00024
# Geometría del gráfico: 200 puntos sobre 65.110.
STOP_GRAFICO = 200 / 65110


def recorrido_por_grupo(des, etiquetas, stop, objetivo, coste):
    """Contraste de barrera desglosado por etiqueta, en una sola pasada."""
    if len(des) == 0:
        return pd.DataFrame()
    t = pd.DataFrame({
        "etiqueta": etiquetas,
        "objetivo": (des.motivo == barreras.OBJETIVO),
        "resuelta": (des.motivo != barreras.TIEMPO),
        "retorno": des.retorno,
    })
    g = t.groupby("etiqueta")
    r = pd.DataFrame({
        "n": g.size(),
        "resueltas": g["resuelta"].sum(),
        "frac_resueltas": g["resuelta"].mean(),
        "bruto": g["retorno"].mean(),
    })
    aciertos = t[t["resuelta"]].groupby("etiqueta")["objetivo"].mean()
    r["p_real"] = aciertos
    r["exceso"] = r["p_real"] - barreras.teorica(stop, objetivo)
    r["neto"] = r["bruto"] - coste
    return r


def entradas_de_ventana(indice, inicio, fin, zona):
    """Primera y última vela de cada aparición de la ventana."""
    m = ventanas.mascara_ventana(indice, inicio, fin, zona)
    primeras = ventanas.ocurrencias(m, "primera", marcas=indice)
    ultimas = ventanas.ocurrencias(m, "ultima", marcas=indice)
    n = min(len(primeras), len(ultimas))
    return primeras[:n], ultimas[:n]


# ========================
# 1. PERFIL DEL DÍA
# ========================

def paso_perfil(d, zona, desfase):
    print(f"[1] ¿Pasa algo distinto en esos minutos?  (hora local, zona {zona!r})\n")
    p = ventanas.perfil(d, minutos=10, zona=zona, desfase=desfase)

    print("     Los cinco tramos más expansivos del día, de 144:")
    for _, f in p.sort_values("exp_bp", ascending=False).head(5).iterrows():
        print(f"       {f['hora']}   {f['exp_bp']:.3f} pb por vela   "
              f"volumen {f['vol_rel']:.2f}x")

    print(f"\n     {'ventana':<14} {'expansión':>10} {'percentil':>10} "
          f"{'volumen':>9}")
    for nombre, (ini, fin) in ventanas.NOMBRES_VENTANAS.items():
        # La tabla ya está en hora local, así que basta con quedarse con las
        # filas cuya hora cae dentro de la ventana.
        dentro = p["hora"].map(lambda h: _dentro(h, ini, fin))
        sub = p[dentro]
        exp = float(sub["exp_bp"].mean())
        pct = ventanas.percentil(p["exp_bp"], exp)
        print(f"     {nombre:<14} {exp:>9.3f} pb {pct:>9.0%} "
              f"{sub['vol_rel'].mean():>8.2f}x")
    print()
    return p


def _dentro(hhmm, inicio, fin):
    h, m = (int(x) for x in hhmm.split(":"))
    minuto = h * 60 + m
    a, b = inicio.hour * 60 + inicio.minute, fin.hour * 60 + fin.minute
    return a <= minuto < b if a <= b else (minuto >= a or minuto < b)


# ========================
# 2. BRACKET CIEGO
# ========================

def paso_ciego(d, alto, bajo, cierre, zona, stop, objetivo, horizonte):
    print(f"[2] Bracket ciego abierto al empezar la ventana\n")
    print(f"     {'ventana':<14} {'lado':>6} {'n':>6} {'%res':>6} {'p_real':>8} "
          f"{'exceso':>8} {'neto':>9}")
    filas = []
    for nombre, (ini, fin) in ventanas.NOMBRES_VENTANAS.items():
        primeras, _ = entradas_de_ventana(d.index, ini, fin, zona)
        for direccion, etiqueta in ((1, "largo"), (-1, "corto")):
            des = barreras.recorrer(alto, bajo, cierre, primeras, stop, objetivo,
                                    horizonte, direccion)
            r = barreras.contraste(des, stop, objetivo, COSTE)
            if not r:
                continue
            filas.append({"ventana": nombre, "lado": etiqueta, **r})
            print(f"     {nombre:<14} {etiqueta:>6} {r['n']:>6,} "
                  f"{1 - r['frac_tiempo']:>5.0%} {r['p_real']:>8.4f} "
                  f"{r['exceso']:>+8.4f} {r['neto_medio']:>+8.4%}")
    print()
    return pd.DataFrame(filas)


# ========================
# 3. BARRIDO Y REVERSIÓN
# ========================

def modelo_barrido(alto, bajo, cierre, inicios, finales, previa, stop, objetivo,
                   horizonte, contrario=False):
    """
    Aplica la regla de barrido y reversión y devuelve los desenlaces.

    `contrario=True` invierte la señal, que es el control obligado: si entrar
    contra el barrido gana y entrar a favor pierde lo mismo, hay estructura; si
    los dos rondan cero, no hay nada y lo que se vea es coste.
    """
    d = ventanas.direccion_por_barrido(alto, bajo, inicios, finales, previa)
    if contrario:
        d = -d
    salidas = []
    for direccion in (1, -1):
        sel = finales[d == direccion]
        if len(sel) == 0:
            continue
        salidas.append(barreras.recorrer(alto, bajo, cierre, sel, stop, objetivo,
                                         horizonte, direccion))
    if not salidas:
        return None
    return barreras.Desenlaces(
        np.concatenate([s.entrada for s in salidas]),
        np.concatenate([s.salida for s in salidas]),
        np.concatenate([s.motivo for s in salidas]),
        np.concatenate([s.retorno for s in salidas]), 0)


def paso_modelo(d, alto, bajo, cierre, zona, previa, stop, objetivo, horizonte):
    print(f"[3] Barrido y reversión: entrada al cerrar la ventana\n")
    necesario = ventanas.win_rate_necesario(stop, objetivo, COSTE)
    print(f"     {'ventana':<14} {'sentido':>12} {'n':>6} {'%res':>6} "
          f"{'acierto':>8} {'exceso':>8} {'neto':>9} {'meses':>10} {'p':>7}")

    filas = []
    for nombre, (ini, fin) in ventanas.NOMBRES_VENTANAS.items():
        primeras, ultimas = entradas_de_ventana(d.index, ini, fin, zona)
        for contrario, etiqueta in ((False, "reversión"), (True, "continuación")):
            des = modelo_barrido(alto, bajo, cierre, primeras, ultimas, previa,
                                 stop, objetivo, horizonte, contrario)
            if des is None or len(des) < 100:
                continue
            r = barreras.contraste(des, stop, objetivo, COSTE)
            cons = ventanas.consistencia(d.index[des.entrada], des.retorno - COSTE)
            filas.append({"ventana": nombre, "sentido": etiqueta, **r, **cons})
            marca = "  ←" if r["neto_medio"] > 0 else ""
            print(f"     {nombre:<14} {etiqueta:>12} {r['n']:>6,} "
                  f"{1 - r['frac_tiempo']:>5.0%} {r['p_real']:>8.4f} "
                  f"{r['exceso']:>+8.4f} {r['neto_medio']:>+8.4%} "
                  f"{cons['a_favor']:>4}/{cons['periodos']:<5} {cons['p']:>6.3f}{marca}")

    print(f"\n     Acierto necesario para no perder: {necesario:.1%}. "
          f"Un paseo aleatorio da {barreras.teorica(stop, objetivo):.1%}.\n")
    return pd.DataFrame(filas)


def paso_control_ancho(d, alto, bajo, cierre, zona, previa, stop, objetivo,
                       horizonte, horas=3):
    """
    La misma regla, con ventanas del mismo ancho que arrancan a cada hora.

    Es el control que le faltaba a la ventana de tres horas. Los tramos de diez
    minutos ya se comparan contra los 143 restantes, pero 01:00-04:00 no se
    compara contra nada mientras no se corra también a las 02:00, a las 03:00 y
    a las veintiuna horas que quedan. Sin eso no hay forma de saber si lo que
    se mide es esa ventana o cualquier ventana de tres horas.
    """
    from datetime import time as _t

    print(f"[5] Ventanas de {horas} h arrancando a cada hora, misma regla\n")
    filas = []
    for h in range(24):
        ini, fin = _t(h, 0), _t((h + horas) % 24, 0)
        primeras, ultimas = entradas_de_ventana(d.index, ini, fin, zona)
        if len(primeras) < 100:
            continue
        for contrario, etiqueta in ((False, "reversión"), (True, "continuación")):
            des = modelo_barrido(alto, bajo, cierre, primeras, ultimas, previa,
                                 stop, objetivo, horizonte, contrario)
            if des is None or len(des) < 100:
                continue
            r = barreras.contraste(des, stop, objetivo, COSTE)
            cons = ventanas.consistencia(d.index[des.entrada], des.retorno - COSTE)
            filas.append({"inicio": f"{h:02d}:00", "sentido": etiqueta,
                          **r, **cons})

    t = pd.DataFrame(filas)
    if t.empty:
        return t

    cont = t[t["sentido"] == "continuación"].sort_values("neto_medio", ascending=False)
    if cont.empty:
        return t
    print(f"     {'inicio':>7} {'n':>6} {'acierto':>8} {'exceso':>8} {'neto':>9} "
          f"{'meses':>10} {'p':>7}")
    for _, f in cont.iterrows():
        marca = "  ←" if f["inicio"] == "01:00" else ""
        print(f"     {f['inicio']:>7} {int(f['n']):>6,} {f['p_real']:>8.4f} "
              f"{f['exceso']:>+8.4f} {f['neto_medio']:>+8.4%} "
              f"{int(f['a_favor']):>4}/{int(f['periodos']):<5} {f['p']:>6.3f}{marca}")

    referencia = cont[cont["inicio"] == "01:00"]
    positivos = int((cont["neto_medio"] > 0).sum())
    if not referencia.empty:
        puesto = int((cont["neto_medio"] > referencia["neto_medio"].iloc[0]).sum()) + 1
        print(f"\n     La ventana del indicador queda {puesto}ª de {len(cont)} "
              f"en continuación.")
    print(f"     {positivos} de {len(cont)} arranques dan neto positivo; "
          f"~{len(cont) * 0.05:.1f} saldrían por azar.\n")
    return t


def paso_todo_el_dia(d, alto, bajo, cierre, zona, previa, stop, objetivo,
                     horizonte, desfase, minutos=10):
    """
    La misma regla en los 144 tramos del día. Es el control que decide.

    Si el barrido y reversión funciona igual de bien a las 03:20 que a las
    09:55, entonces lo que se está midiendo es la regla y no la hora, y las
    ventanas del indicador no aportan nada.
    """
    print(f"[4] La misma regla en los 144 tramos del día\n")
    bucket = ventanas.bucket_local(d.index, minutos, zona, desfase)
    inicios, finales, _ = ventanas.tramos(bucket, marcas=d.index)
    direccion = ventanas.direccion_por_barrido(alto, bajo, inicios, finales, previa)

    trozos, etiquetas = [], []
    for lado in (1, -1):
        sel = direccion == lado
        if not sel.any():
            continue
        des = barreras.recorrer(alto, bajo, cierre, finales[sel], stop, objetivo,
                                horizonte, lado)
        trozos.append(des)
        # `recorrer` descarta las entradas sin horizonte por delante, así que la
        # etiqueta se recupera del índice de entrada y no de la máscara.
        etiquetas.append(bucket[des.entrada])
    if not trozos:
        return pd.DataFrame()

    des = barreras.Desenlaces(
        np.concatenate([t.entrada for t in trozos]),
        np.concatenate([t.salida for t in trozos]),
        np.concatenate([t.motivo for t in trozos]),
        np.concatenate([t.retorno for t in trozos]), 0)
    tabla = recorrido_por_grupo(des, np.concatenate(etiquetas), stop, objetivo, COSTE)
    tabla["hora"] = [ventanas.inicio_de_bucket(b, minutos, desfase)
                     for b in tabla.index]

    print("     Los cinco mejores tramos del día con esta regla:")
    for _, f in tabla.sort_values("neto", ascending=False).head(5).iterrows():
        print(f"       {f['hora']}   n={int(f['n']):>5,}   acierto {f['p_real']:.4f}   "
              f"exceso {f['exceso']:+.4f}   neto {f['neto']:+.4%}")

    print(f"\n     {'ventana':<14} {'n':>6} {'acierto':>8} {'exceso':>8} "
          f"{'neto':>9} {'percentil':>10}")
    for nombre, (ini, fin) in ventanas.NOMBRES_VENTANAS.items():
        dentro = tabla["hora"].map(lambda h: _dentro(h, ini, fin))
        sub = tabla[dentro]
        if sub.empty:
            continue
        # Media ponderada por operaciones: los tramos no tienen la misma muestra.
        peso = sub["n"] / sub["n"].sum()
        neto = float((sub["neto"] * peso).sum())
        exceso = float((sub["exceso"] * peso).sum())
        acierto = float((sub["p_real"] * peso).sum())
        pct = ventanas.percentil(tabla["neto"], neto)
        print(f"     {nombre:<14} {int(sub['n'].sum()):>6,} {acierto:>8.4f} "
              f"{exceso:>+8.4f} {neto:>+8.4%} {pct:>9.0%}")

    positivos = int((tabla["neto"] > 0).sum())
    print(f"\n     {positivos} de {len(tabla)} tramos dan neto positivo. "
          f"Con 144 pruebas, ~{len(tabla) * 0.05:.0f} saldrían")
    print(f"     positivos por azar aunque la regla no valiera nada.\n")
    return tabla


def main():
    global COSTE
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datos", default="data/BTCUSDT_10s_binance.csv")
    parser.add_argument("--zona", default="fija", choices=sorted(ventanas.ZONAS),
                        help="'fija' = GMT-4 todo el año (lo que dibuja el "
                             "indicador); 'nueva-york' = con horario de verano")
    parser.add_argument("--stop", type=float, default=round(STOP_GRAFICO, 5))
    parser.add_argument("--ratio", type=float, default=1.0)
    parser.add_argument("--horizonte", type=int, default=720,
                        help="Velas de 10 s (720 = 2 h)")
    parser.add_argument("--previa", type=int, default=240,
                        help="Minutos de referencia para el barrido")
    parser.add_argument("--desde", default=None,
                        help="Recortar el histórico, p. ej. 2023-01-01")
    parser.add_argument("--desfase", type=int, default=5,
                        help="Minutos que se corre la rejilla de 144 tramos. Con 5, "
                             "09:55-10:05 y 10:25-10:35 son tramos exactos")
    parser.add_argument("--coste", type=float, default=COSTE,
                        help=f"Ida y vuelta. {COSTE:.2%} es taker, "
                             f"{COSTE_MAKER:.3%} es maker")
    args = parser.parse_args()
    COSTE = args.coste

    d = cargar_datos(args.datos)
    if args.desde:
        d = d[d.index >= pd.Timestamp(args.desde, tz="UTC")]
    print(f"{len(d):,} velas de 10 s   {d.index[0]:%Y-%m-%d} → {d.index[-1]:%Y-%m-%d}")

    objetivo = args.stop * args.ratio
    print(f"\nLa geometría del gráfico: stop {args.stop:.3%}, objetivo {objetivo:.3%}, "
          f"horizonte {args.horizonte * 10 / 60:.0f} min")
    print(f"  acierto de un paseo aleatorio        "
          f"{barreras.teorica(args.stop, objetivo):>6.1%}")
    print(f"  necesario con el coste aplicado ({COSTE:.3%}) "
          f"{ventanas.win_rate_necesario(args.stop, objetivo, COSTE):>6.1%}")
    print(f"  necesario con comisiones de maker ({COSTE_MAKER:.3%}) "
          f"{ventanas.win_rate_necesario(args.stop, objetivo, COSTE_MAKER):>6.1%}\n")

    alto = d["high"].to_numpy(dtype=float)
    bajo = d["low"].to_numpy(dtype=float)
    cierre = d["close"].to_numpy(dtype=float)
    previa = args.previa * 6      # minutos → velas de 10 s

    paso_perfil(d, args.zona, args.desfase)
    paso_ciego(d, alto, bajo, cierre, args.zona, args.stop, objetivo, args.horizonte)
    paso_modelo(d, alto, bajo, cierre, args.zona, previa, args.stop, objetivo,
                args.horizonte)
    paso_todo_el_dia(d, alto, bajo, cierre, args.zona, previa, args.stop, objetivo,
                     args.horizonte, args.desfase)
    paso_control_ancho(d, alto, bajo, cierre, args.zona, previa, args.stop,
                       objetivo, args.horizonte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
