"""
Validacion del simulador contra resultados cerrados conocidos.

    python -m sim.validate

Un simulador de riesgo que nadie valido es peor que no tener simulador:
produce confianza con la misma cara que produciria un numero correcto.
Estos chequeos lo anclan a casos donde la respuesta se conoce de antemano.
"""
import numpy as np

from .montecarlo import FAIL_TIMEOUT, simulate
from .ruleset import RuleSet
from .strategy import Guard, SimConfig, StrategyParams

NO_GUARD = Guard(daily_stop=None, scale_down_below=None)


def _ruina_clasica(target: float, max_dd: float) -> RuleSet:
    """Rule set sin barrera diaria ni reglas de forma: solo ruina del jugador."""
    return RuleSet(
        name="ruina clasica",
        profit_target=target,
        daily_dd=0.99,        # efectivamente desactivada
        max_dd=max_dd,
        trailing=False,
        min_trading_days=0,
        consistency_cap=None,
    )


def test_edge_cero_converge_a_ruina_del_jugador():
    """
    Con edge exactamente cero, P(tocar +T antes de -D) = D / (T + D).

    Requiere horizonte largo: con el tope de dias por defecto una fraccion
    grande de caminos termina en timeout y el resultado queda por debajo.
    """
    for target, max_dd in [(0.10, 0.06), (0.06, 0.06), (0.05, 0.10)]:
        rules = _ruina_clasica(target, max_dd)
        # win_rate 0.40 con rr 1.5 => E[R] = 0.4*1.5 - 0.6 = 0 exacto
        strat = StrategyParams(win_rate=0.40, rr=1.5, risk_per_trade=0.002, trades_per_day=5)
        cfg = SimConfig(n_paths=6000, seed=11, max_days_hard_cap=4000)
        res = simulate(rules, strat, NO_GUARD, cfg)

        teorico = max_dd / (target + max_dd)
        assert res.rate(FAIL_TIMEOUT) < 0.02, "horizonte insuficiente, el test no mide lo que cree"
        # Tolerancia amplia: el paso discreto sobrepasa la barrera y sesga
        # levemente hacia abajo. El sesgo es conservador, que es la direccion
        # correcta para una herramienta de riesgo.
        assert abs(res.pass_rate - teorico) < 0.03, (
            f"T={target} D={max_dd}: simulado {res.pass_rate:.1%} vs teorico {teorico:.1%}"
        )
        print(f"  ok  T=+{target:.0%} D=-{max_dd:.0%} -> sim {res.pass_rate:.1%} | teorico {teorico:.1%}")


def test_edge_negativo_casi_nunca_pasa():
    rules = _ruina_clasica(0.10, 0.06)
    strat = StrategyParams(win_rate=0.30, rr=1.5, risk_per_trade=0.002, trades_per_day=5)
    res = simulate(rules, strat, NO_GUARD, SimConfig(n_paths=4000, seed=3))
    assert res.pass_rate < 0.02, f"edge negativo dio {res.pass_rate:.1%}"
    print(f"  ok  edge negativo -> P(pasar) {res.pass_rate:.1%}")


def test_menos_riesgo_sube_probabilidad_con_edge_positivo():
    """
    Con drift positivo, el exponente 2u/s^2 escala como 1/riesgo.
    Achicar el tamano sube P(pasar) monotonamente. El costo es tiempo.
    """
    rules = _ruina_clasica(0.10, 0.06)
    cfg = SimConfig(n_paths=4000, seed=5, max_days_hard_cap=2000)
    previo = 0.0
    for risk in [0.02, 0.015, 0.01, 0.005, 0.0025]:
        strat = StrategyParams(win_rate=0.55, rr=1.2, risk_per_trade=risk, trades_per_day=5)
        res = simulate(rules, strat, NO_GUARD, cfg)
        assert res.pass_rate >= previo - 0.01, "P(pasar) deberia subir al bajar el riesgo"
        print(f"  ok  riesgo {risk:.2%} -> P(pasar) {res.pass_rate:.1%}")
        previo = res.pass_rate


def test_barrera_diaria_inalcanzable_por_construccion():
    """
    Si trades_por_dia * riesgo < daily_dd, la barrera diaria no puede
    tocarse ni en el peor camino posible. Es aritmetica, no probabilidad.
    """
    rules = RuleSet(
        name="daily test", profit_target=0.10, daily_dd=0.04, max_dd=0.06,
        trailing=False, min_trading_days=0,
    )
    # 5 x 0.5% = 2.5% de exposicion maxima diaria < 4%
    seguro = StrategyParams(win_rate=0.52, rr=1.2, risk_per_trade=0.005, trades_per_day=5)
    res = simulate(rules, seguro, NO_GUARD, SimConfig(n_paths=4000, seed=9))
    assert res.rate("fail_daily_dd") == 0.0, "no deberia poder morir por daily DD"
    print(f"  ok  exposicion 2.5% < 4% -> muertes por daily DD: {res.rate('fail_daily_dd'):.1%}")

    # 12 x 1.0% = 12% de exposicion maxima diaria > 4%
    riesgoso = StrategyParams(win_rate=0.52, rr=1.2, risk_per_trade=0.010, trades_per_day=12)
    res2 = simulate(rules, riesgoso, NO_GUARD, SimConfig(n_paths=4000, seed=9))
    assert res2.rate("fail_daily_dd") > 0.10, "deberia morir por daily DD seguido"
    print(f"  ok  exposicion 12% > 4% -> muertes por daily DD: {res2.rate('fail_daily_dd'):.1%}")


def test_stop_propio_mejora_supervivencia():
    """El stop diario propio convierte una barrera absorbente en perder el dia."""
    rules = RuleSet(
        name="guard test", profit_target=0.10, daily_dd=0.04, max_dd=0.06,
        trailing=False, min_trading_days=0,
    )
    strat = StrategyParams(win_rate=0.52, rr=1.2, risk_per_trade=0.005, trades_per_day=20)
    cfg = SimConfig(n_paths=4000, seed=13)

    sin = simulate(rules, strat, NO_GUARD, cfg)
    con = simulate(rules, strat, Guard(daily_stop=0.02, scale_down_below=None), cfg)
    assert con.pass_rate > sin.pass_rate, "el stop propio deberia ayudar"
    print(f"  ok  sin guard {sin.pass_rate:.1%} -> con guard {con.pass_rate:.1%}")


def test_consistencia_empuja_el_objetivo():
    """La regla de consistencia sube el profit necesario cuando hay un dia grande."""
    base = RuleSet(
        name="sin consistencia", profit_target=0.10, daily_dd=0.99, max_dd=0.10,
        trailing=False, min_trading_days=0, consistency_cap=None,
    )
    con = RuleSet(
        name="con consistencia", profit_target=0.10, daily_dd=0.99, max_dd=0.10,
        trailing=False, min_trading_days=0, consistency_cap=0.20,
    )
    # RR alto y pocos trades => dias muy desparejos => la regla muerde
    strat = StrategyParams(win_rate=0.40, rr=3.0, risk_per_trade=0.01, trades_per_day=2)
    cfg = SimConfig(n_paths=4000, seed=17)

    r_base = simulate(base, strat, NO_GUARD, cfg)
    r_con = simulate(con, strat, NO_GUARD, cfg)
    assert r_con.pass_rate < r_base.pass_rate, "la consistencia deberia bajar P(pasar)"
    print(
        f"  ok  sin regla {r_base.pass_rate:.1%} -> con cap 20% {r_con.pass_rate:.1%} "
        f"(forzo seguir operando en {r_con.consistency_forced_extra/r_con.n_paths:.1%})"
    )


def main():
    tests = [
        ("Edge cero converge a ruina del jugador", test_edge_cero_converge_a_ruina_del_jugador),
        ("Edge negativo casi nunca pasa", test_edge_negativo_casi_nunca_pasa),
        ("Menos riesgo sube P(pasar)", test_menos_riesgo_sube_probabilidad_con_edge_positivo),
        ("Barrera diaria inalcanzable por construccion", test_barrera_diaria_inalcanzable_por_construccion),
        ("Stop propio mejora supervivencia", test_stop_propio_mejora_supervivencia),
        ("Consistencia empuja el objetivo", test_consistencia_empuja_el_objetivo),
    ]
    fallos = 0
    for nombre, fn in tests:
        print(f"\n{nombre}")
        try:
            fn()
        except AssertionError as e:
            print(f"  FALLO: {e}")
            fallos += 1
    print("\n" + "=" * 60)
    print("TODOS LOS CHEQUEOS OK" if not fallos else f"{fallos} CHEQUEO(S) FALLARON")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
