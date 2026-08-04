# Simulador Monte Carlo de cuentas de fondeo

## Qué hace

Simula miles de caminos de equity trade por trade contra las reglas de una
cuenta de fondeo, y responde:

    P(tocar +target antes de morir contra alguna barrera)

Esa es la función objetivo correcta para una cuenta de fondeo, y **no** es la
misma que retorno o Sharpe. Da respuestas distintas — sobre todo en tamaño
por trade, donde el óptimo suele ser mucho más chico de lo que sugiere
maximizar retorno.

Lo que el simulador **no** hace: predecir cuánto vas a ganar, ni validar que
tu estrategia tenga edge. Toma el edge como input. Si le das un win rate
sobreajustado, te devuelve confianza infundada con cara de número correcto.

## Uso

```bash
pip install numpy

python simulate.py                          # corrida completa + barridos
python simulate.py --wr 0.52 --rr 1.2       # otra estrategia
python simulate.py --rules eval_2step_fase1
python simulate.py --plan                   # solo el plan operativo
python -m sim.validate                      # chequeos contra teoría
```

## Los tres barridos

1. **Riesgo por trade** — con edge positivo, más chico casi siempre gana; el
   único costo es tiempo. El exponente de la fórmula de barreras escala como
   `1/riesgo`.
2. **Robustez al error de estimación** — cuánto puede estar equivocado tu
   backtest antes de que P(pasar) se derrumbe. Es el barrido más importante.
3. **Valor del stop diario propio** — convierte la barrera diaria de la firma
   (absorbente: mata la cuenta) en un stop propio (reflectante: perdés el día).

## Hallazgo estructural

Si `trades_por_día × riesgo_por_trade < daily_dd`, la barrera diaria de la
firma **no puede tocarse ni en el peor camino posible**. Es aritmética, no
probabilidad. Con daily DD de 4%, 5 trades a 0.5% dan 2.5% de exposición
máxima: imposible morir por límite diario.

Esto convierte el problema de "no romper la regla diaria" de un problema de
disciplina a un problema de configuración.

## Validación

`python -m sim.validate` ancla el simulador a casos con respuesta conocida:

| Chequeo | Resultado |
|---|---|
| Edge cero, T=+10% D=-6% | sim 36.8% vs teórico D/(T+D) = 37.5% |
| Edge cero, T=+6% D=-6% | sim 48.9% vs teórico 50.0% |
| Edge cero, T=+5% D=-10% | sim 65.7% vs teórico 66.7% |
| Edge negativo | P(pasar) 0.0% |
| Menos riesgo con edge positivo | monótonamente creciente |
| Exposición < daily DD | 0.0% de muertes por límite diario |
| Stop propio (20 trades/día) | 79.4% → 94.7% |

El sesgo residual de ~0.7pp contra la teoría es overshoot por paso discreto:
la barrera se cruza saltando, no rozándola. Va en dirección conservadora, que
es la correcta para una herramienta de riesgo.

Nota: el test de edge cero necesita horizonte largo (`max_days_hard_cap=4000`).
Con el tope por defecto de 250 días, ~28% de los caminos terminan en timeout y
P(pasar) baja a 23% — no es un error del modelo, es que la teoría asume tiempo
infinito.

## Rule sets

Los presets en `ruleset.py` son **plantillas genéricas** con valores típicos de
la industria, no las reglas verificadas de ninguna firma. Antes de usar
cualquiera para decidir tamaño, copiar los números reales del contrato.

Parámetros que más cambian el resultado:
- `trailing` vs estático en el max DD (cambia el cálculo entero)
- `consistency_cap` (acota aritméticamente el RR máximo por día)
- `min_trading_days`

## Distribución empírica

`StrategyParams` acepta `r_multiples`: un array de R-múltiplos reales
observados. Reemplaza a `win_rate`/`rr` y se muestrea por bootstrap. Es mucho
mejor que la aproximación binaria porque captura la cola — que es exactamente
lo que decide la supervivencia.

```python
import numpy as np
from sim import StrategyParams

r_reales = np.loadtxt("data/mis_r_multiples.csv")
strat = StrategyParams(r_multiples=r_reales, risk_per_trade=0.005, trades_per_day=5)
```

Ese array es el output natural de un diario de trades. Es la razón principal
para llevarlo.
