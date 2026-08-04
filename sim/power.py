"""
Cuantos trades hacen falta para distinguir edge real de suerte.

Esta es la pregunta que decide el diseno entero de la estrategia, y casi
siempre se contesta mal. Antes de elegir activo, timeframe o RR, conviene
saber cuanto tiempo calendario cuesta *demostrar* que cada configuracion
funciona. Una estrategia excelente que necesita dos anos de datos para
validarse es, en la practica, una estrategia que no podes usar.

Tres calculos:
  1. Poder estadistico  -> cuantos trades para detectar un edge dado
  2. Modelo de costos   -> distancia minima de stop para que las comisiones
                           no se coman el edge
  3. Testeo multiple    -> cuanto sube la vara al probar N variantes
"""
import math
from dataclasses import dataclass

# Cuantiles normales, para no depender de scipy
Z = {0.80: 0.8416, 0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263}


def _z(p: float) -> float:
    """Cuantil normal inverso (aproximacion de Acklam, suficiente aca)."""
    if p in Z:
        return Z[p]
    a = [-39.6968302866538, 220.946098424521, -275.928510446969,
         138.357751867269, -30.6647980661472, 2.50662827745924]
    b = [-54.4760987982241, 161.585836858041, -155.698979859887,
         66.8013118877197, -13.2806815528857]
    c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184,
         -2.54973253934373, 4.37466414146497, 2.93816398269878]
    d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ---------------------------------------------------------------------------
# 1. Poder estadistico
# ---------------------------------------------------------------------------

def sigma_r(win_rate: float, rr: float) -> float:
    """Desvio de la distribucion de R-multiplos para un sistema binario."""
    mean = win_rate * rr - (1 - win_rate)
    ex2 = win_rate * rr**2 + (1 - win_rate)
    return math.sqrt(ex2 - mean**2)


def expected_r(win_rate: float, rr: float) -> float:
    return win_rate * rr - (1 - win_rate)


def trades_needed(
    edge_r: float,
    sigma: float,
    alpha: float = 0.05,
    power: float = 0.80,
    one_sided: bool = True,
) -> int:
    """
    Trades necesarios para detectar un edge de `edge_r` R por trade.

    Es un test de una muestra sobre la media. La hipotesis nula es "no hay
    edge" (media cero), y queremos rechazarla con probabilidad `power` cuando
    el edge real es `edge_r`.

        n = (z_alpha + z_power)^2 / (edge_r / sigma)^2

    One-sided por defecto: solo interesa demostrar edge positivo.
    """
    if edge_r <= 0:
        return math.inf
    z_a = _z(1 - alpha) if one_sided else _z(1 - alpha / 2)
    z_b = _z(power)
    d = edge_r / sigma
    return math.ceil((z_a + z_b) ** 2 / d**2)


def calendar_time(n_trades: int, trades_per_day: float, days_per_week: float = 7) -> dict:
    """Traduce numero de trades a tiempo calendario."""
    if trades_per_day <= 0:
        return {"dias": math.inf, "semanas": math.inf, "meses": math.inf}
    dias_operativos = n_trades / trades_per_day
    dias_calendario = dias_operativos * (7 / days_per_week)
    return {
        "dias": dias_calendario,
        "semanas": dias_calendario / 7,
        "meses": dias_calendario / 30.4,
    }


# ---------------------------------------------------------------------------
# 2. Modelo de costos
# ---------------------------------------------------------------------------

@dataclass
class FeeModel:
    """
    Comisiones como fraccion del notional, por lado.

    Los defaults son valores tipicos de perpetuos en Binance para VIP 0.
    VERIFICAR contra el schedule vigente de tu cuenta: cambian, y dependen
    del nivel VIP y del descuento por pagar en BNB.
    """
    maker: float = 0.0002      # 0.020%
    taker: float = 0.0005      # 0.050%
    slippage: float = 0.0002   # estimacion propia, no es una comision

    def round_trip(self, entry_maker: bool = False, exit_maker: bool = False) -> float:
        e = self.maker if entry_maker else self.taker
        x = self.maker if exit_maker else self.taker
        return e + x + self.slippage


def cost_in_r(fee_round_trip: float, stop_distance: float) -> float:
    """
    Costo de ida y vuelta expresado en R.

    El tamano de posicion es inversamente proporcional a la distancia del
    stop: stop mas cerca => posicion mas grande => mas notional => mas
    comision por el mismo R arriesgado. Por eso el scalping de stop corto
    se muere de costos aunque la senal sea buena.
    """
    if stop_distance <= 0:
        return math.inf
    return fee_round_trip / stop_distance


def min_stop_distance(fee_round_trip: float, max_cost_r: float = 0.10) -> float:
    """Distancia minima de stop para que el costo no exceda `max_cost_r` R."""
    return fee_round_trip / max_cost_r


# ---------------------------------------------------------------------------
# 3. Testeo multiple
# ---------------------------------------------------------------------------

def false_positives_expected(n_variants: int, alpha: float = 0.05) -> float:
    """Variantes que van a parecer significativas por puro azar."""
    return n_variants * alpha


def bonferroni_alpha(n_variants: int, alpha: float = 0.05) -> float:
    return alpha / n_variants


def t_threshold_corrected(n_variants: int, alpha: float = 0.05) -> float:
    """|t| minimo exigible al probar n_variants configuraciones."""
    return _z(1 - bonferroni_alpha(n_variants, alpha))


def trades_needed_multiple_testing(
    edge_r: float, sigma: float, n_variants: int, alpha: float = 0.05, power: float = 0.80
) -> int:
    """Trades necesarios cuando se prueban n_variants configuraciones."""
    return trades_needed(edge_r, sigma, alpha=bonferroni_alpha(n_variants, alpha), power=power)
