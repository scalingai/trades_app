"""
Validacion de los estadisticos contra series sinteticas de propiedades conocidas.

Mismo principio que sim/validate.py: un estadistico mal implementado no avisa,
devuelve un numero con la misma cara que devolveria uno correcto. Antes de
concluir "esto es un paseo aleatorio" hay que probar que el test sabe
distinguir un paseo aleatorio de algo que no lo es.

    python -m research.validate_stats
"""
import numpy as np

from .t2_structure import hurst, variance_ratio

N = 20_000


def series_paseo_aleatorio(rng, n=N):
    r = rng.normal(0, 0.005, n)
    return r, np.cumsum(r)


def series_con_reversion(rng, n=N, phi=-0.10):
    """AR(1) con coeficiente negativo => reversion a la media."""
    r = np.zeros(n)
    e = rng.normal(0, 0.005, n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]
    return r, np.cumsum(r)


def series_con_tendencia(rng, n=N, phi=0.10):
    """AR(1) con coeficiente positivo => persistencia."""
    r = np.zeros(n)
    e = rng.normal(0, 0.005, n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + e[i]
    return r, np.cumsum(r)


def main():
    rng = np.random.default_rng(42)
    fallos = 0

    print("=" * 70)
    print("  VALIDACION DE ESTADISTICOS CONTRA SERIES SINTETICAS")
    print("=" * 70)

    print("\n  El variance ratio es el test primario. Hurst se reporta como")
    print("  descriptivo: es monotono pero de baja potencia (ver abajo).\n")

    casos = [
        ("Paseo aleatorio  (VR = 1)", series_paseo_aleatorio, (-2.5, 2.5)),
        ("Reversion phi=-0.10 (VR < 1)", series_con_reversion, (-100, -2.5)),
        ("Tendencia  phi=+0.10 (VR > 1)", series_con_tendencia, (2.5, 100)),
    ]

    for nombre, gen, z_rango in casos:
        r, px = gen(rng)
        h = hurst(px)
        vr2, z2 = variance_ratio(r, 2)
        vr8, z8 = variance_ratio(r, 8)

        z_ok = z_rango[0] <= z2 <= z_rango[1]
        estado = "ok  " if z_ok else "FALLO"
        if not z_ok:
            fallos += 1

        print(f"  {estado} {nombre}")
        print(f"       VR(q=2)    = {vr2:.4f}  z = {z2:+.2f}  (esperado z en {z_rango})")
        print(f"       VR(q=8)    = {vr8:.4f}  z = {z8:+.2f}")
        print(f"       Hurst      = {h:.4f}   (descriptivo)")

    # Hurst: se exige monotonia, no umbrales. Su desvio respecto de 0.5 es de
    # ~0.03 en todo el rango de phi de -0.5 a +0.5, mientras el z del variance
    # ratio recorre de -58 a +58 sobre las mismas series. Sirve para ordenar,
    # no para decidir.
    print("\n  Monotonia de Hurst respecto de la fuerza del efecto:")
    hs = []
    for phi in [-0.5, -0.3, -0.1, 0.0, 0.1, 0.3, 0.5]:
        rr = np.zeros(N)
        e = np.random.default_rng(7).normal(0, 0.005, N)
        for i in range(1, N):
            rr[i] = phi * rr[i - 1] + e[i]
        h = hurst(np.cumsum(rr))
        hs.append(h)
        print(f"       phi={phi:+.2f} -> H={h:.4f}")
    if not all(hs[i] < hs[i + 1] for i in range(len(hs) - 1)):
        print("       FALLO: Hurst deberia crecer con phi")
        fallos += 1
    else:
        print(f"       ok  monotono, pero rango total solo {hs[-1]-hs[0]:.3f}")

    # El z bajo la nula debe comportarse como una normal estandar
    print("\n  Distribucion de z bajo la hipotesis nula (100 paseos aleatorios):")
    zs = []
    for i in range(100):
        r, _ = series_paseo_aleatorio(np.random.default_rng(1000 + i), 5000)
        _, z = variance_ratio(r, 4)
        zs.append(z)
    zs = np.array(zs)
    rechazos = float(np.mean(np.abs(zs) > 1.96))
    print(f"       media {zs.mean():+.3f} (esperado ~0) | desvio {zs.std():.3f} (esperado ~1)")
    print(f"       tasa de rechazo al 5%: {rechazos:.1%} (esperado ~5%)")
    if not (0.0 <= rechazos <= 0.15) or abs(zs.std() - 1.0) > 0.35:
        print("       FALLO: el estadistico no esta calibrado")
        fallos += 1

    print("\n" + "=" * 70)
    print("TODOS LOS CHEQUEOS OK" if not fallos else f"{fallos} CHEQUEO(S) FALLARON")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
