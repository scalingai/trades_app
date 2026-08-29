"""Indicadores técnicos barra por barra, todos acumulativos hacia adelante.

Regla que no se rompe: `x[i]` usa las barras `0..i` y ninguna posterior. Es lo
que permite tratar cada minuto como un momento de decisión real.

Se calculan de una sola pasada por día porque el dataset de momentos los pide
para CADA minuto: hacerlo con una ventana móvil recalculada por minuto es un
orden de magnitud más caro y da lo mismo.

Los niveles (VWAP, POC, mínimo del día, mínimo de pre-market, cierre previo)
tienen un rol distinto al de los indicadores: son los candidatos a TARGET. Un
ratio atado a un nivel deja de ser un número elegido y pasa a ser una
consecuencia de dónde está la estructura.
"""

from __future__ import annotations

from dias import APERTURA_RTH, hora


def ema(valores, periodo):
    """EMA clásica. El primer valor siembra la serie; sin warm-up no hay EMA."""
    k = 2.0 / (periodo + 1)
    out, prev = [], None
    for v in valores:
        if v is None:
            out.append(prev)
            continue
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(cierres, periodo=14):
    """RSI de Wilder. Devuelve None hasta tener `periodo` variaciones."""
    out = [None]
    ganancia = perdida = 0.0
    for i in range(1, len(cierres)):
        a, b = cierres[i - 1], cierres[i]
        if a is None or b is None:
            out.append(out[-1])
            continue
        d = b - a
        g, p = max(d, 0.0), max(-d, 0.0)
        if i <= periodo:
            ganancia += g
            perdida += p
            if i == periodo:
                ganancia /= periodo
                perdida /= periodo
                out.append(100.0 if perdida == 0 else
                           100 - 100 / (1 + ganancia / perdida))
            else:
                out.append(None)
            continue
        ganancia = (ganancia * (periodo - 1) + g) / periodo
        perdida = (perdida * (periodo - 1) + p) / periodo
        out.append(100.0 if perdida == 0 else 100 - 100 / (1 + ganancia / perdida))
    return out


def perfil_volumen(bars, *, ancho_rel=0.005):
    """POC acumulado: el precio donde más volumen se operó HASTA cada barra.

    Es el histograma verde que se ve a la izquierda en DAS. Se acumula en
    baldes de ancho relativo al precio (0,5%) para que sirva igual en un papel
    de $0,80 que en uno de $12.

    Se devuelve también la fracción del volumen que quedó ARRIBA del precio
    actual: es el "papel atrapado" —gente comprada más arriba— y es una medida
    distinta de la distancia al POC.
    """
    ref = next((b[4] for b in bars if b[4]), 1.0)
    ancho = max(0.01, ancho_rel * ref)
    hist: dict[int, float] = {}
    pocs, arriba = [], []
    total = 0.0
    for b in bars:
        c, v = b[4], (b[5] or 0.0)
        if c:
            k = int(c / ancho)
            hist[k] = hist.get(k, 0.0) + v
            total += v
        if hist:
            kb = max(hist, key=hist.__getitem__)
            pocs.append((kb + 0.5) * ancho)
            if c and total > 0:
                ka = int(c / ancho)
                arriba.append(sum(x for k, x in hist.items() if k > ka) / total)
            else:
                arriba.append(None)
        else:
            pocs.append(None)
            arriba.append(None)
    return pocs, arriba


def maximos_decrecientes(bars, *, tramo_min=15):
    """Cuántos tramos consecutivos de 15 min vienen haciendo máximo más bajo.

    Es la lectura de "back side" sin depender del VWAP: la estructura de
    máximos decrecientes que se ve a ojo en el gráfico. El tramo de 15 minutos
    es una convención, y por eso el número se reporta como feature y no como
    filtro.
    """
    out = []
    tramos: list[float] = []
    max_tramo = None
    ini = None
    for b in bars:
        t = b[0]
        if ini is None:
            ini = t
        if (t - ini).total_seconds() / 60.0 >= tramo_min:
            if max_tramo is not None:
                tramos.append(max_tramo)
            max_tramo = None
            ini = t
        if b[2] and (max_tramo is None or b[2] > max_tramo):
            max_tramo = b[2]
        n = 0
        for a, c in zip(reversed(tramos), reversed(tramos[:-1])):
            if a < c:
                n += 1
            else:
                break
        out.append(n)
    return out


def calcular(dia):
    """Todos los indicadores de un día, alineados con `dia.bars`."""
    cierres = [b[4] for b in dia.bars]
    pocs, vol_arriba = perfil_volumen(dia.bars)
    pre = [b for b in dia.bars if hora(b) < APERTURA_RTH]
    pm_low = min((b[3] for b in pre if b[3]), default=None)

    # Mínimo corriente del día: el primer soporte obvio hacia abajo.
    minimos, mn = [], None
    for b in dia.bars:
        if b[3] and (mn is None or b[3] < mn):
            mn = b[3]
        minimos.append(mn)

    return {
        "ema9": ema(cierres, 9),
        "ema20": ema(cierres, 20),
        "rsi": rsi(cierres, 14),
        "poc": pocs,
        "vol_arriba": vol_arriba,
        "min_dia": minimos,
        "pm_low": pm_low,
        "max_dec": maximos_decrecientes(dia.bars),
    }
