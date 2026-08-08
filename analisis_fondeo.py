#!/usr/bin/env python3
"""
Cuánto arriesgar y cuántas cuentas llevar, para una evaluación concreta.

Contesta las tres preguntas que deciden el resultado antes de elegir ninguna
estrategia, y las contesta con los números de la cuenta que se le pasen.

**Cuánto arriesgar.** No hay una respuesta única porque depende de si existen
los resets. Sin resets se optimiza la probabilidad de pasar y conviene
achicar. Con resets baratos se optimiza el coste esperado hasta la primera
cuenta fondeada, y ahí conviene agrandar: pasar el doble de rápido a cambio de
medio reset más suele salir a cuenta. Este script calcula las dos y las pone
al lado.

**Cuántas cuentas.** Rotar diversifica y copiar no. Tres cuentas con las mismas
operaciones viven o mueren juntas y no suman nada; tres cuentas operando días
distintos multiplican las probabilidades como sucesos independientes. Es la
diferencia entre el 41 % y el 80 %.

**Y el aviso que hay que tener delante.** Con posiciones grandes la evaluación
dura tan pocas operaciones que la ventaja no llega a expresarse: con catorce
operaciones, un 55 % de acierto es indistinguible de un 50 %. Eso no invalida
la estrategia de ir rápido —si el reset es barato, comprar intentos es
racional— pero conviene saber que en ese régimen se está comprando varianza y
no explotando una ventaja, y que no se va a aprender nada sobre si la
estrategia sirve.

Los valores por defecto son los que se suelen publicar para una cuenta de
50.000, pero **hay que confirmarlos**: cambian seguido y el precio del reset,
que es el que da vuelta la recomendación, no aparece en ninguna parte fija.

    python analisis_fondeo.py --objetivo 3000 --umbral 2500 --reset 80
    python analisis_fondeo.py --acierto 0.53 --cuentas 3 --punto-dolar 2
"""

import argparse
import sys

import numpy as np

from backtest import fondeo


def un_intento(acierto, riesgo, reglas, rng, tope=8000):
    """Una evaluación entera. Devuelve si pasó y cuántas operaciones costó."""
    capital = pico = 0.0
    for k in range(tope):
        gana = rng.random() < acierto
        resultado = riesgo if gana else -riesgo
        # La ganadora llega hasta su objetivo; la perdedora llega hasta donde
        # le tocó antes de darse la vuelta, y eso también sube el umbral.
        mfe = riesgo if gana else rng.random() * riesgo
        pico = max(pico, capital + mfe)
        capital += resultado
        tope_umbral = (min(pico, reglas.bloqueo) if reglas.bloqueo is not None
                       else pico)
        suelo = tope_umbral - reglas.umbral if reglas.arrastra else -reglas.umbral
        if capital <= suelo:
            return False, k + 1
        if capital >= reglas.objetivo:
            return True, k + 1
    return False, tope


def hasta_fondear(acierto, riesgo, reglas, repeticiones=3000, semilla=7,
                  max_intentos=25):
    """Resets y operaciones esperados hasta lograr una cuenta fondeada."""
    rng = np.random.default_rng(semilla)
    resets, operaciones, pasos, exitos = [], [], [], 0
    for _ in range(repeticiones):
        usadas, intentos = 0, 0
        while True:
            ok, k = un_intento(acierto, riesgo, reglas, rng)
            usadas += k
            intentos += 1
            if intentos == 1:
                pasos.append(k)
                exitos += ok
            if ok or intentos >= max_intentos:
                break
        resets.append(intentos - 1)
        operaciones.append(usadas)
    return {
        "p": exitos / repeticiones,
        "ops_intento": float(np.mean(pasos)),
        "resets": float(np.mean(resets)),
        "ops_total": float(np.mean(operaciones)),
    }


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--objetivo", type=float, default=3000,
                        help="Beneficio que pide la evaluación")
    parser.add_argument("--umbral", type=float, default=2500,
                        help="Drawdown máximo")
    parser.add_argument("--bloqueo", type=float, default=2600,
                        help="Beneficio al que el umbral deja de arrastrarse. "
                             "0 para que arrastre siempre")
    parser.add_argument("--fijo", action="store_true",
                        help="El umbral no arrastra (otras firmas)")
    parser.add_argument("--acierto", type=float, default=0.55)
    parser.add_argument("--ratio", type=float, default=1.0)
    parser.add_argument("--mensual", type=float, default=19.70,
                        help="Suscripción mensual. En Apex es el coste real: "
                             "no se paga por intento sino por tiempo")
    parser.add_argument("--reset", type=float, default=0,
                        help="Precio de un reset, si se paga aparte")
    parser.add_argument("--activacion", type=float, default=125,
                        help="Pago único al activar la cuenta fondeada")
    parser.add_argument("--cuentas", type=int, default=3)
    parser.add_argument("--por-dia", type=float, default=4,
                        help="Operaciones por día que se pueden ejecutar")
    parser.add_argument("--punto-dolar", type=float, default=2.0,
                        help="Dólares por punto del instrumento: MNQ 2, NQ 20, "
                             "MYM 0,50, YM 5")
    args = parser.parse_args()

    reglas = fondeo.Reglas(objetivo=args.objetivo, umbral=args.umbral,
                           bloqueo=None if args.bloqueo <= 0 else args.bloqueo,
                           arrastra=not args.fijo)

    print(f"Objetivo ${reglas.objetivo:,.0f}   umbral ${reglas.umbral:,.0f}   "
          f"{'fijo' if args.fijo else 'por rastro'}"
          + (f", bloqueo en ${reglas.bloqueo:,.0f}" if reglas.bloqueo else ""))
    print(f"Acierto supuesto {args.acierto:.0%} a {args.ratio:.1f}:1   "
          f"${args.mensual:,.2f}/mes   {args.por_dia:.0f} operaciones/día\n")

    print(f"  Tirando una moneda, sin ninguna ventaja:")
    print(f"    umbral fijo        {fondeo.teorica_fija(reglas.objetivo, reglas.umbral):.1%}")
    print(f"    umbral por rastro  {fondeo.teorica_arrastrada(reglas.objetivo, reglas.umbral):.1%}"
          f"   ← lo que cuesta la definición de la cuenta\n")

    riesgos = [r for r in (600, 400, 250, 150, 100, 60) if r < reglas.umbral / 2]
    print(f"{'riesgo':>7} {'stop':>9} {'P(pasar)':>9} {'ops/int':>8} {'resets':>7} "
          f"{'coste':>8} {'meses':>7} {'P(1 de ' + str(args.cuentas) + ')':>12}")
    filas = []
    for riesgo in riesgos:
        r = hasta_fondear(args.acierto, riesgo, reglas)
        meses = r["ops_total"] / args.por_dia / 21
        # En Apex el coste lo marca el calendario, no el número de intentos:
        # tardar el triple cuesta el triple aunque no se resetee nunca.
        coste = max(meses, 1) * args.mensual + r["resets"] * args.reset
        cartera = 1 - (1 - r["p"]) ** args.cuentas
        filas.append({"riesgo": riesgo, "coste": coste, "meses": meses, **r})
        print(f"{'$' + str(riesgo):>7} {riesgo / args.punto_dolar:>7.0f} pt "
              f"{r['p']:>9.1%} {r['ops_intento']:>8.0f} {r['resets']:>7.2f} "
              f"{'$' + f'{coste:,.0f}':>8} {meses:>7.1f} {cartera:>12.1%}")

    mejor_p = max(filas, key=lambda f: f["p"])
    mas_rapido = min(filas, key=lambda f: f["meses"])
    barato = min(filas, key=lambda f: f["coste"])
    print(f"\n  Más probable por intento: ${mejor_p['riesgo']} "
          f"({mejor_p['p']:.0%} en {mejor_p['meses']:.1f} meses, "
          f"${mejor_p['coste']:,.0f}).")
    print(f"  Más rápido:               ${mas_rapido['riesgo']} "
          f"({mas_rapido['p']:.0%} en {mas_rapido['meses']:.1f} meses, "
          f"${mas_rapido['coste']:,.0f}).")
    print(f"  Más barato:               ${barato['riesgo']} "
          f"({barato['p']:.0%} en {barato['meses']:.1f} meses, "
          f"${barato['coste']:,.0f}).")
    if barato["riesgo"] == mas_rapido["riesgo"]:
        print(f"\n  El más rápido es además el más barato, y no es casualidad: la\n"
              f"  suscripción se paga por mes, así que tardar el triple cuesta el\n"
              f"  triple. Aquí no hay canje entre tiempo y dinero: van juntos.")

    sin_ventaja = fondeo.teorica_arrastrada(reglas.objetivo, reglas.umbral)
    print(f"\n  Pero el contrapeso: sin ninguna ventaja se pasa el "
          f"{sin_ventaja:.0%} de las veces.")
    print(f"  Cuanto más corta es la evaluación, mayor parte de los aprobados lo son")
    print(f"  por varianza. Y pasar sin ventaja no es ganar: son ${args.activacion:,.0f} de")
    print(f"  activación más la mensualidad para descubrirlo en la cuenta fondeada,")
    print(f"  donde ya no hay reset. Ir rápido conviene sólo si la ventaja existe.")

    if mas_rapido["ops_intento"] < 40:
        print(f"\n  Aviso: a ${mas_rapido['riesgo']} la evaluación dura "
              f"{mas_rapido['ops_intento']:.0f} operaciones. Con esa muestra un "
              f"{args.acierto:.0%}")
        print(f"  no se distingue de un 50 %, así que ahí se compra varianza y no se")
        print(f"  explota una ventaja. Se pasa o no se pasa, pero no se aprende nada.")

    print(f"\n  Y una vez fondeada la lógica se invierte: no hay reset, así que el")
    print(f"  tamaño vuelve a ser el de la primera columna. Rápido para pasar,")
    print(f"  chico para durar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
