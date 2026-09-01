#!/usr/bin/env python3
"""Familia VENTANAS HORARIAS: la misma señal, repartida en momentos del día.

**Qué se busca acá, y qué NO.** No se busca la mejor hora. Se busca un conjunto
de horas cuyos resultados no se muevan juntos. Vamos a correr tres cuentas de
fondeo en paralelo y ya está medido que con la misma señal las tres revientan el
mismo día: la correlación entre cuentas es lo que convierte tres oportunidades
en una sola apuesta apalancada. Una estrategia que rinde menos pero pierde en
días distintos vale más que una que rinde más y pierde el mismo martes.

Por eso el entregable de este archivo es la MATRIZ DE CORRELACIÓN, y el número
que se mira al final no es el ret/nom más alto sino el trío con la correlación
más baja entre miembros individualmente rentables.

EL GATILLO ES UNO SOLO Y NO SE TOCA. Todas las variantes usan `señales_swing`
de `sesion.py` — el rebote del 8% desde el mínimo corriente y la barra que cierra
abajo de la anterior. Lo único que cambia entre variantes es CUÁNDO se permite
entrar y CUÁNDO se sale. Si además cambiara el gatillo, la comparación mediría
dos cosas a la vez y no serviría para nada.

  · El gatillo se abre a 09:30–16:00 (`desde=9.5, hasta=16.0`) en vez de los
    09:45–15:30 de fábrica. Sin eso, la ventana 09:30-10:00 arrancaría recién
    09:45 y la 15:30-16:00 estaría vacía por construcción — o sea, dos de las
    seis ventanas pedidas no existirían. Se paga con una referencia propia
    (`hora·dia-abierto`) para que la suma de las partes sea comparable con algo.

  · La población es **expansión ≥ 150%**, no 100%. Medido en la corrida
    exploratoria: con exp100 la brecha P1/P2 del día completo es de 16,2 puntos
    —ruido según el protocolo— y con exp150 baja a 3,0. Ventanas angostas sobre
    una base que ya no replica sería medir ruido con más decimales. El precio es
    muestra: 5,6 sesiones/mes en vez de 7,9.

EL PISO QUE HAY QUE PASAR. El locate se cobra como fracción del nominal (~20%),
así que **ret/nom ≤ 20% es una estrategia que pierde plata**. En las tablas, la
columna `neto20` ya lo descuenta: si es negativa, la ventana no se opera por
buena que se vea en bruto.

    python fam_horas.py
    python fam_horas.py --exp 100     # la misma corrida sobre la base ancha
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import Counter

from dias import hora
from motor import correlacion, encabezado, evaluar, linea, universo
from sesion import señales_swing

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

LOCATE = 20.0          # el punto de muerte, en ret/nom
MIN_SESIONES = 40      # abajo de esto no se saca conclusión, se reporta y listo
RUIDO = 15.0           # brecha P1/P2 arriba de esto = no replica

# Las seis ventanas pedidas. Son disjuntas y cubren la rueda entera.
VENTANAS = [
    ("0930-1000", 9.5, 10.0),
    ("1000-1100", 10.0, 11.0),
    ("1100-1230", 11.0, 12.5),
    ("1230-1400", 12.5, 14.0),
    ("1400-1530", 14.0, 15.5),
    ("1530-1600", 15.5, 16.0),
]


def gatillo(dia):
    """El gatillo común a toda la familia: swing con la rueda entera habilitada."""
    return señales_swing(dia, desde=9.5, hasta=16.0)


def en_ventana(desde, hasta):
    """Señal = el gatillo, filtrado por hora de entrada. Nada más.

    El filtro es sobre la hora de la barra de ENTRADA, no la de salida: una
    ventana de entrada deja correr el trade hasta el cierre. Que la ventana
    también acote la SALIDA es una decisión aparte (`salida_h`) y es justo la
    que más decorrelaciona, porque es la única que hace que dos estrategias no
    estén expuestas al mismo minuto de mercado.
    """
    def señal(dia):
        return [i for i in gatillo(dia) if desde <= hora(dia.bars[i]) < hasta]
    return señal


def solo_primero(dia):
    """El primer trade del día y nada más."""
    idx = gatillo(dia)
    return idx[:1]


def sin_primero(dia):
    """Todo menos el primero. Es la contracara exacta de `solo_primero`."""
    return gatillo(dia)[1:]


# --------------------------------------------------------------------------
# Registro: cada variante guarda su intervalo de entrada para que la búsqueda
# del trío no proponga tres estrategias que en realidad operan el mismo minuto.
# --------------------------------------------------------------------------

REGISTRO = []


def correr(nombre, señal, *, dias, exp, salida_h=None, intervalo=None,
           elegible=False, notas="", guardar=True):
    r = evaluar(f"hora·{nombre}", señal, dias=dias, familia="hora", stop=45.0,
                pob={"min_expansion": exp}, salida_h=salida_h, notas=notas,
                guardar=guardar)
    r["_intervalo"] = intervalo
    r["_elegible"] = elegible and "error" not in r
    REGISTRO.append(r)
    print(linea(r))
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Familia de ventanas horarias")
    ap.add_argument("--exp", type=float, default=150.0,
                    help="expansión mínima de la población (150 = la que replica)")
    ap.add_argument("--sin-guardar", action="store_true",
                    help="no escribir en el banco compartido")
    args = ap.parse_args(argv)
    exp = args.exp
    g = not args.sin_guardar
    dias = universo()

    print("=" * 118)
    print("  FAMILIA HORAS — la misma señal repartida en momentos del día")
    print(f"  gatillo: señales_swing(9:30–16:00) · población expansión ≥ {exp:.0f}% · "
          f"stop 45% · apertura fade · {len(dias)} días en el censo")
    print(f"  el piso: ret/nom ≤ {LOCATE:.0f}% es pérdida (el locate se lo come). "
          f"neto20 negativo = no se opera.")
    print("=" * 118)

    # ----------------------------------------------------------------- 0
    print("\n  [0] REFERENCIAS — el día completo, para saber contra qué se compara\n")
    print(encabezado())
    print("  " + "-" * 116)
    correr("dia-completo", lambda d: señales_swing(d), dias=dias, exp=exp,
           notas="gatillo de fábrica (09:45–15:30): reproduce base·swing", guardar=g)
    correr("dia-abierto", gatillo, dias=dias, exp=exp,
           notas="gatillo abierto 09:30–16:00: la referencia de la descomposición",
           guardar=g)

    # ----------------------------------------------------------------- 1
    print("\n  [1] VENTANAS DE ENTRADA disjuntas — se entra en la ventana, se sale")
    print("      cuando el trade termina (stop o cierre). Se solapan EN EL TIEMPO.\n")
    print(encabezado())
    print("  " + "-" * 116)
    for nm, a, b in VENTANAS:
        correr(nm, en_ventana(a, b), dias=dias, exp=exp, intervalo=(a, b),
               elegible=True, notas=f"entradas entre {a} y {b}, corre hasta el cierre",
               guardar=g)

    # ----------------------------------------------------------------- 2
    print("\n  [2] LAS MISMAS VENTANAS, CERRANDO AL FINAL DE LA VENTANA — acá sí")
    print("      dos estrategias nunca comparten un minuto de exposición.\n")
    print(encabezado())
    print("  " + "-" * 116)
    for nm, a, b in VENTANAS:
        correr(f"{nm}·cierra", en_ventana(a, b), dias=dias, exp=exp, salida_h=b,
               intervalo=(a, b), elegible=True,
               notas=f"entra {a}-{b} y cierra a las {b}: exposición disjunta",
               guardar=g)

    # ----------------------------------------------------------------- 3
    print("\n  [3] VENTANAS DE TENENCIA — entrar temprano y soltar a distintas horas.")
    print("      Misma entrada, distinta duración: aísla cuánto del edge es")
    print("      'entrar bien' y cuánto es 'aguantar'.\n")
    print(encabezado())
    print("  " + "-" * 116)
    for etiqueta, h in (("1100", 11.0), ("1300", 13.0), ("cierre", None)):
        correr(f"apertura→{etiqueta}", en_ventana(9.5, 10.0), dias=dias, exp=exp,
               salida_h=h, intervalo=(9.5, 10.0),
               notas=f"entra 09:30-10:00, suelta a las {etiqueta}", guardar=g)
    for etiqueta, h in (("1300", 13.0), ("cierre", None)):
        correr(f"manana→{etiqueta}", en_ventana(9.5, 11.0), dias=dias, exp=exp,
               salida_h=h, intervalo=(9.5, 11.0),
               notas=f"entra 09:30-11:00, suelta a las {etiqueta}", guardar=g)

    # ----------------------------------------------------------------- 3b
    print("\n  [3b] EL CONTROL QUE HACE FALTA: MISMA TENENCIA, DISTINTA HORA.")
    print("       Las ventanas del bloque [1] NO son comparables entre sí: la de")
    print("       las 09:30 puede correr seis horas hasta el cierre y la de las")
    print("       15:30 sólo treinta minutos. Si el número cae a lo largo del día,")
    print("       hasta acá no se sabe si es porque la hora es peor o porque queda")
    print("       menos rueda por delante. Se iguala: media hora para entrar, hora")
    print("       y media de tenencia, en cuatro momentos del día.\n")
    print(encabezado())
    print("  " + "-" * 116)
    for nm, a in (("0930", 9.5), ("1100", 11.0), ("1300", 13.0), ("1430", 14.5)):
        correr(f"{nm}+90min", en_ventana(a, a + 0.5), dias=dias, exp=exp,
               salida_h=min(16.0, a + 1.5), intervalo=(a, a + 0.5), elegible=True,
               notas="entrada de 30 min y tenencia de 90: el control de tiempo",
               guardar=g)

    # ----------------------------------------------------------------- 4
    print("\n  [4] EL PRIMERO CONTRA LOS QUE VIENEN DESPUÉS — ¿el edge está en el")
    print("      primer trade del día o en la insistencia?\n")
    print(encabezado())
    print("  " + "-" * 116)
    correr("primer-trade", solo_primero, dias=dias, exp=exp,
           notas="sólo la primera señal del día", guardar=g)
    correr("resto-del-dia", sin_primero, dias=dias, exp=exp,
           notas="todas menos la primera", guardar=g)

    horas_1ra = []
    for dia in dias:
        idx = gatillo(dia)
        if idx:
            horas_1ra.append(hora(dia.bars[idx[0]]))
    if horas_1ra:
        c = Counter(int(h) for h in horas_1ra)
        print(f"\n      cuándo cae la primera señal (n={len(horas_1ra)} días con señal, "
              f"mediana {statistics.median(horas_1ra):.2f}h):")
        for k in sorted(c):
            print(f"        {k:02d}:00–{k+1:02d}:00  {c[k]:>5}  "
                  f"{'#' * int(60 * c[k] / len(horas_1ra))}")

    # ----------------------------------------------------------------- 5
    print("\n  [5] AGREGADOS Y CORTES FINOS — para ver si algo de lo que pierde")
    print("      solo empieza a existir cuando se junta.\n")
    print(encabezado())
    print("  " + "-" * 116)
    correr("0930-0945", en_ventana(9.5, 9.75), dias=dias, exp=exp,
           intervalo=(9.5, 9.75), elegible=True,
           notas="los primeros 15 minutos, que el gatillo de fábrica se saltea",
           guardar=g)
    correr("0945-1000", en_ventana(9.75, 10.0), dias=dias, exp=exp,
           intervalo=(9.75, 10.0), elegible=True, notas="", guardar=g)
    correr("manana", en_ventana(9.5, 11.0), dias=dias, exp=exp,
           intervalo=(9.5, 11.0), elegible=True,
           notas="las dos ventanas de la mañana juntas", guardar=g)
    correr("mediodia", en_ventana(11.0, 14.0), dias=dias, exp=exp,
           intervalo=(11.0, 14.0), elegible=True,
           notas="11:00-14:00 como una sola ventana", guardar=g)
    correr("tarde", en_ventana(14.0, 16.0), dias=dias, exp=exp,
           intervalo=(14.0, 16.0), elegible=True,
           notas="14:00 al cierre como una sola ventana", guardar=g)
    correr("post1100", en_ventana(11.0, 16.0), dias=dias, exp=exp,
           intervalo=(11.0, 16.0), elegible=True,
           notas="todo lo que queda después de las 11: la otra mitad del día",
           guardar=g)
    correr("mediodia·cierra", en_ventana(11.0, 14.0), dias=dias, exp=exp,
           salida_h=14.0, intervalo=(11.0, 14.0), elegible=True,
           notas="11:00-14:00 y afuera a las 14:00", guardar=g)
    correr("tarde·cierra", en_ventana(14.0, 16.0), dias=dias, exp=exp,
           salida_h=15.75, intervalo=(14.0, 16.0), elegible=True,
           notas="14:00 al cierre, plano 15:45 (no cargar el cierre)", guardar=g)

    # ----------------------------------------------------------------- 6
    print("\n  [6] MATRIZ DE CORRELACIÓN — el entregable real de esta familia.")
    print("      Correlación del PnL diario sobre las fechas COMPARTIDAS. Un par")
    print("      con corr baja y las dos patas rentables es una cuenta más que")
    print("      se puede prender sin duplicar la apuesta.\n")

    vivos = [r for r in REGISTRO if "error" not in r]
    nombres = {r["nombre"]: r for r in vivos}

    def subconj(sufijos):
        return [nombres[f"hora·{s}"] for s in sufijos if f"hora·{s}" in nombres]

    matriz(subconj([v[0] for v in VENTANAS]),
           "(a) LAS SEIS VENTANAS DE ENTRADA — corren hasta el cierre")
    print()
    matriz(subconj([f"{v[0]}·cierra" for v in VENTANAS]),
           "(b) LAS MISMAS, CERRANDO AL FINAL DE LA VENTANA — exposición disjunta")
    print()
    matriz(subconj(["0930+90min", "1100+90min", "1300+90min", "1430+90min"]),
           "(c) EL CONTROL DE TENENCIA PAREJA — 30 min de entrada, 90 de tenencia")
    print()
    matriz(vivos, "(d) TODAS LAS VARIANTES CON VENTANA DEFINIDA")

    # ----------------------------------------------------------------- 7
    print("\n  [7] TABLA COMPLETA ordenada por ret/nom\n")
    tabla_final(vivos)

    print("\n  [8] EL MEJOR TRÍO DECORRELACIONADO\n")
    tríos(vivos)

    print("\n  [9] LO QUE CUESTA PARTIR EL DÍA EN N CUENTAS\n")
    fragmentar(nombres)

    print("""
  ================================================================================
  LO QUE CONTESTA ESTA FAMILIA

  1. El edge NO está repartido en la rueda: se apaga con la hora. Por trade, la
     media va de +0.077 R en los primeros quince minutos a +0.0015 R en la última
     media hora, bajando casi monótonamente. Y no es "queda menos rueda por
     delante": el bloque [3b] iguala la tenencia en 90 minutos para todos y el
     resultado es el mismo — 23.6% a las 09:30 contra 2.2% a las 11:00 y -0.8% a
     las 13:00.

  2. Como consecuencia, NO hay tres ventanas horarias rentables y disjuntas. Hay
     dos: la mañana y el mediodía. La tercera pata, la que sea, hoy no paga su
     locate. Esto es un resultado, no una falta de resultado: por esta vía no
     salen tres cuentas.

  3. La decorrelación SÍ existe y es fuerte: mañana contra 14:00-15:30 da +0.00
     y contra la tarde entera +0.01, y con salida forzada al final de la ventana
     la matriz [2] es casi toda negativa. El problema no es encontrar horas
     decorrelacionadas de la mañana: es que ninguna de ellas gana plata.

  4. Y hay un costo estructural que la matriz no muestra: el locate se reserva
     por cuenta, así que partir el día multiplica el costo fijo y reparte los
     mismos trades. Dos cuentas cuestan 1% del neto; tres cuestan 26%; seis dan
     negativo. La decorrelación por horario se paga en locate, y el precio sube
     rapidísimo después de la segunda cuenta.
  ================================================================================
""")
    return 0


def fragmentar(nombres):
    """Cuánto se paga por repartir la rueda entre N cuentas de fondeo.

    Este es el número que la matriz de correlación no muestra y que decide todo.
    El locate se cobra sobre el NOMINAL DESPLEGADO, y cada cuenta despliega el
    suyo: una cuenta que opera el día entero reserva el nominal UNA vez y todos
    los trades del día lo reciclan gratis. Dos cuentas que se reparten el mismo
    día reservan dos veces y se reparten los mismos trades.

    O sea: la decorrelación por horario no sale gratis, se paga en locate. Acá
    está el precio, en R por sesión, para cada forma de partir el día. `bruto`
    suma lo que ganan las patas; `locate` es 20% del nominal de CADA una.
    """
    esquemas = [
        ("1 cuenta — la rueda entera", ["dia-abierto"]),
        ("2 cuentas — mañana / resto", ["manana", "post1100"]),
        ("2 cuentas — mañana / mediodía", ["manana", "mediodia"]),
        ("3 cuentas — mañana / mediodía / tarde", ["manana", "mediodia", "tarde"]),
        ("6 cuentas — una por ventana", [v[0] for v in VENTANAS]),
    ]
    print(f"      {'esquema':<40} {'patas':>6} {'bruto':>8} {'locate':>8} "
          f"{'neto':>8}  vs 1 cuenta")
    print("      " + "-" * 92)
    base = None
    for etiqueta, patas in esquemas:
        rs = [nombres[f"hora·{p}"] for p in patas if f"hora·{p}" in nombres]
        if len(rs) != len(patas):
            continue
        bruto = sum(r["bruto_R"] for r in rs)
        loc = sum(LOCATE / 100.0 * r["nom_R"] for r in rs)
        neto = bruto - loc
        if base is None:
            base = neto
        print(f"      {etiqueta:<40} {len(rs):>6} {bruto:>+8.3f} {loc:>8.3f} "
              f"{neto:>+8.3f}  {100 * neto / base - 100:>+6.0f}%")
    print("""
      Se lee así: la suma de las patas gana MÁS en bruto que la cuenta única
      —cada pata tiene su propio límite diario, así que un día malo se corta
      tres veces en vez de una— pero cada pata paga su locate completo. A
      partir de la tercera cuenta el locate se come todo lo que agregó la
      fragmentación, y a la sexta la estrategia deja de existir.""")


def matriz(res, titulo="TODAS LAS VARIANTES CON VENTANA DEFINIDA"):
    """Matriz cuadrada de correlaciones. `—` = menos de 20 fechas compartidas.

    Las columnas van numeradas y la leyenda va aparte: los nombres completos no
    entran en 8 caracteres y truncarlos hacía que `1100-1230` y
    `1100-1230·cierra` se vieran igual, que es la peor forma posible de leer una
    matriz de correlación.
    """
    ks = [r for r in res if r["_intervalo"] is not None]
    if not ks:
        return
    etq = [r["nombre"].replace("hora·", "") for r in ks]
    ancho = max(len(e) for e in etq)
    print(f"      {titulo}\n")
    print("      " + " " * (ancho + 4) + "".join(f"{i+1:>6}" for i in range(len(ks))))
    for i, a in enumerate(ks):
        fila = []
        for b in ks:
            c = correlacion(a["serie"], b["serie"])
            fila.append(f"{c:>6.2f}" if c is not None else f"{'—':>6}")
        print(f"      {i+1:>2}  {etq[i]:<{ancho}}" + "".join(fila))


def r_por_trade(r):
    """R por trade. Separa 'la hora es peor' de 'la ventana hace menos trades'.

    `ret/nom` premia mecánicamente a la variante que hace MÁS trades, porque el
    nominal se reserva una vez (el máximo del día) y todos los trades siguientes
    lo reciclan gratis. Sin esta columna, una ventana angosta parece mala cuando
    lo único que pasa es que opera menos veces.
    """
    tr = r["trades_mes"] or 0
    return r["bruto_R"] * r["ses_mes"] / tr if tr else 0.0


def tabla_final(res):
    orden = sorted(res, key=lambda r: -r["ret_nom"])
    print(f"      {'estrategia':<24} {'ses':>5} {'ses/m':>6} {'tr/m':>5} "
          f"{'ret/nom':>8} {'R/trade':>8} {'neto20':>8} {'P1':>7} {'P2':>7} "
          f"{'brecha':>7}  veredicto")
    print("      " + "-" * 114)
    for r in orden:
        n = r["n"]
        rep = r["replica"]
        v = []
        if r["ret_nom"] <= LOCATE:
            v.append("MUERE con locate 20%")
        if n < MIN_SESIONES:
            v.append(f"muestra corta ({n})")
        if rep is not None and rep > RUIDO:
            v.append(f"no replica ({rep:.0f}p)")
        if rep is None:
            v.append("sin P2 medible")
        print(f"      {r['nombre'].replace('hora·',''):<24} {n:>5} {r['ses_mes']:>6.1f} "
              f"{r['trades_mes']:>5} {r['ret_nom']:>7.1f}% {r_por_trade(r):>+8.4f} "
              f"{r['neto20_R']:>+8.3f} "
              f"{(r['P1'] or {}).get('ret_nom', 0):>6.1f}% "
              f"{(r['P2'] or {}).get('ret_nom', 0):>6.1f}% "
              f"{(f'{rep:.1f}p' if rep is not None else '—'):>7}  "
              + (" · ".join(v) if v else "OK"))


def tríos(res):
    """Busca el trío de ventanas disjuntas, rentables y poco correlacionadas.

    Las tres condiciones son duras y en ese orden:

      1. **Disjuntas en el tiempo.** Tres cuentas que entran en el mismo rango
         horario no son tres cuentas, son la misma con tres nombres. Se exige
         que los intervalos de entrada no se pisen.
      2. **Rentables por separado**, con el locate ya descontado. Sumar una pata
         que pierde para bajar la correlación es comprar diversificación con
         plata; el objetivo es prender una cuenta más, no una excusa más.
      3. **Muestra suficiente** (≥ 40 sesiones) y que replique P1→P2.

    Recién con eso se ordena por la correlación máxima del par más acoplado, que
    es lo que manda: un trío con dos patas a 0,7 no diversifica nada aunque el
    promedio dé bajo.
    """
    cand = [r for r in res if r["_elegible"] and r["ret_nom"] > LOCATE
            and r["n"] >= MIN_SESIONES
            and r["replica"] is not None and r["replica"] <= RUIDO]
    print(f"      candidatos que pasan los tres filtros "
          f"(ret/nom > {LOCATE:.0f}%, n ≥ {MIN_SESIONES}, replica ≤ {RUIDO:.0f}p): "
          f"{len(cand)}")
    for r in cand:
        print(f"        · {r['nombre']:<28} ret/nom {r['ret_nom']:>5.1f}%  "
              f"n={r['n']:>3}  {r['ses_mes']:.1f}/mes")
    if len(cand) < 2:
        print("\n      No hay con qué armar un par, mucho menos un trío.")
        _pares_relajados(res)
        return

    def pisa(a, b):
        (a0, a1), (b0, b1) = a["_intervalo"], b["_intervalo"]
        return a0 < b1 and b0 < a1

    def listar(combos, k):
        filas = []
        for j, c in enumerate(combos):
            if any(pisa(x, y) for x, y in itertools.combinations(c, 2)):
                continue
            cs = [correlacion(x["serie"], y["serie"])
                  for x, y in itertools.combinations(c, 2)]
            if any(v is None for v in cs):
                continue
            # El `j` es desempate: sin él, dos tríos con la misma correlación
            # hacen que sort() compare los dicts que vienen atrás y explote.
            filas.append((max(cs), sum(cs) / len(cs), j, c, cs))
        filas.sort()
        if not filas:
            print(f"      no hay ningún {k} disjunto con las tres condiciones.")
            return None
        print(f"\n      {k.upper()}S disjuntos, ordenados por la correlación del par "
              f"más acoplado:")
        for mx, prom, _, c, cs in filas[:6]:
            nombres = " + ".join(x["nombre"].replace("hora·", "") for x in c)
            print(f"        corr_max {mx:>+5.2f}  prom {prom:>+5.2f}   {nombres}")
            for (x, y), v in zip(itertools.combinations(c, 2), cs):
                print(f"            {x['nombre'].replace('hora·',''):<18} vs "
                      f"{y['nombre'].replace('hora·',''):<18} {v:>+6.2f}")
            print("            " + "  ".join(
                f"{x['nombre'].replace('hora·','')}: {x['ret_nom']:.0f}% / "
                f"{x['ses_mes']:.1f}me" for x in c))
            colas = [f"{x['nombre'].replace('hora·','')}∩"
                     f"{y['nombre'].replace('hora·','')}={dias_malos(x, y)}/10"
                     for x, y in itertools.combinations(c, 2)]
            print("            peores 10 días compartidos:  " + "  ".join(colas))
        return filas[0]

    listar(itertools.combinations(cand, 3), "trío")
    listar(itertools.combinations(cand, 2), "par")
    _trios_forzados(res)
    _pares_relajados(res)


def _trios_forzados(res, k=6):
    """El mejor trío disjunto SIN exigir que las tres patas ganen plata.

    Existe porque la respuesta "no hay trío" es cierta pero inútil sola: si Agus
    igual va a prender tres cuentas, hay que decirle CUÁL es el mejor trío
    posible y CUÁNTO cuesta la tercera pata. La columna `neto` es la suma de las
    tres patas con el locate del 20% ya descontado a cada una — comparala con el
    +0.356 R de la cuenta única del bloque [9].
    """
    cand = [r for r in res if r["_elegible"] and r["n"] >= MIN_SESIONES]
    filas = []
    for j, c in enumerate(itertools.combinations(cand, 3)):
        iv = sorted(x["_intervalo"] for x in c)
        if any(iv[i][1] > iv[i + 1][0] for i in range(2)):
            continue
        cs = [correlacion(x["serie"], y["serie"])
              for x, y in itertools.combinations(c, 2)]
        if any(v is None for v in cs):
            continue
        neto = sum(x["bruto_R"] - LOCATE / 100.0 * x["nom_R"] for x in c)
        filas.append((-neto, j, c, cs, max(cs)))
    filas.sort()
    if not filas:
        print("\n      Ni siquiera relajando la rentabilidad hay tres ventanas "
              "disjuntas con muestra.")
        return
    print("\n      TRÍOS DISJUNTOS SIN EXIGIR RENTABILIDAD — ordenados por lo que")
    print("      DEJAN, no por lo poco que se parecen. Ordenarlos por correlación")
    print("      pone arriba tríos donde las tres patas pierden plata: bajísima")
    print("      correlación y ninguna razón para prenderlas.")
    for _n, _j, c, cs, mx in filas[:k]:
        neto = -_n
        print(f"\n        corr_max {mx:>+5.2f}   neto conjunto {neto:>+6.3f} R "
              f"(cuenta única: +0.356 R)")
        for x in c:
            marca = "OK   " if x["ret_nom"] > LOCATE else "MUERE"
            print(f"          {marca} {x['nombre'].replace('hora·',''):<18} "
                  f"ret/nom {x['ret_nom']:>5.1f}%  {x['ses_mes']:.1f}/mes  n={x['n']}")
        print("          corr: " + "  ".join(
            f"{x['nombre'].replace('hora·','')}–{y['nombre'].replace('hora·','')} "
            f"{v:>+.2f}" for (x, y), v in zip(itertools.combinations(c, 2), cs)))
        print("          peores 10 días compartidos: " + "  ".join(
            f"{x['nombre'].replace('hora·','')}∩{y['nombre'].replace('hora·','')} "
            f"{dias_malos(x, y)}/10"
            for x, y in itertools.combinations(c, 2)))


def dias_malos(a, b, k=10):
    """De los `k` peores días de cada una, ¿cuántos son EL MISMO día?

    La correlación es un promedio y puede esconder justo lo que importa: dos
    curvas que casi no se parecen pero que se hunden el mismo martes. Con tres
    cuentas de fondeo, lo que rompe la cuenta es la coincidencia de las colas,
    no la del cuerpo. Este conteo mira sólo las colas.
    """
    pa = sorted(a["serie"].items(), key=lambda kv: kv[1])[:k]
    pb = sorted(b["serie"].items(), key=lambda kv: kv[1])[:k]
    return len({d for d, _ in pa} & {d for d, _ in pb})


def _pares_relajados(res):
    """Qué habría si se aceptaran patas que NO pasan el piso del locate.

    Se imprime aparte y con la etiqueta puesta: sirve para ver si la
    decorrelación existe en los datos aunque hoy no se pueda cobrar. Si el único
    par decorrelacionado necesita una pata que pierde plata, la conclusión es
    que por esta vía no hay tres cuentas — y eso también es un resultado.
    """
    cand = [r for r in res if r["_elegible"] and r["n"] >= 40]
    if len(cand) < 2:
        return
    filas = []
    for j, (x, y) in enumerate(itertools.combinations(cand, 2)):
        (a0, a1), (b0, b1) = x["_intervalo"], y["_intervalo"]
        if a0 < b1 and b0 < a1:
            continue
        c = correlacion(x["serie"], y["serie"])
        if c is not None:
            filas.append((abs(c), c, j, x, y))
    filas.sort()
    print("\n      SIN el filtro de rentabilidad — los pares disjuntos menos")
    print("      correlacionados que existen en los datos (la marca dice si la pata")
    print(f"      aguanta el locate del {LOCATE:.0f}%):")
    for _, c, _j, x, y in filas[:8]:
        def m(r):
            return "OK " if r["ret_nom"] > LOCATE else "MUERE"
        print(f"        {c:>+5.2f}   {x['nombre'].replace('hora·',''):<18} "
              f"[{m(x)} {x['ret_nom']:>5.1f}%]  vs  "
              f"{y['nombre'].replace('hora·',''):<18} [{m(y)} {y['ret_nom']:>5.1f}%]")


if __name__ == "__main__":
    raise SystemExit(main())
