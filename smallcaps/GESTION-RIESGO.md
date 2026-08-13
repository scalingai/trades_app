# Protocolo de gestión de riesgo

> Derivado de la distribución **medida**, no de teoría. Cuenta de referencia:
> $25.000 de buying power, límite diario 2%, drawdown máximo 4%.
> **No validado en vivo.** Ver §5 antes de usar.

## 1. El problema que este protocolo resuelve

La estrategia gana en promedio pero **el 72% de esa ganancia viene del 10%
mejor de los trades**. Sacando esa cola, la media cae de +9,5% a +2,7%.

Eso significa que tu muestra real de trades puede perfectamente **no incluir la
cola**, y tenés que sobrevivir hasta que aparezca. Todo el dimensionamiento
sale de ahí.

Rachas perdedoras medidas: **5 seguidas es lo típico**, 9 en el percentil 95,
15 en el peor caso de 2.000 simulaciones de 100 trades.

## 2. Tamaño de posición

**Arriesgar 0,25% del buying power por trade.**

| | |
|---|---|
| riesgo por trade | $62,50 |
| stop | 12% desde la entrada |
| **posición** | **$521** |
| en una acción de $4 | ~130 acciones |

**Por qué 0,25% y no más.** El límite diario del 2% permitiría arriesgar ocho
veces eso. Sería un error: el binding constraint no es el límite diario sino el
**drawdown máximo combinado con la dependencia de la cola**. Probabilidad de
perder la cuenta en 6 meses, con la cola removida:

| riesgo/trade | 1 trade/día | 3 trades/día |
|---|---|---|
| **0,25%** | **0%** | **2%** |
| 0,50% | 20% | 56% |
| 0,75% | 64% | 96% |

No hay zona intermedia: de 0,25% a 0,50% la probabilidad de muerte se
multiplica por diez.

## 3. Reglas de operación

**Entrada.** Short al mediodía ET en tickers que cumplan: precio ≥ $3 (abajo de
eso el costo se come el edge y el bruto ya es flojo), evento de volumen anómalo
con rango > 40%, y **precio por debajo de la apertura** — la única señal técnica
que sobrevivió a la validación.

**Salida escalonada.** Es la mejor de las variantes probadas:
1. **50% de la posición** en el target de −20%
2. Al tomar la parcial, **mover el stop a break-even**
3. **El 50% restante corre hasta el cierre** de la sesión regular

Esa estructura captura buena parte de la media de sostener y mantiene el
resultado positivo aunque la cola no aparezca.

**Stop: 12%.** Los más ajustados rinden peor en los datos. No moverlo en contra
nunca; la única modificación permitida es a break-even tras la parcial.

**Máximo 3 trades por día.** Más entradas el mismo día no diversifican: son el
mismo evento y el mismo régimen, salen mal todas juntas.

## 4. Reglas de corte

**Corte diario.** Con 0,25% de riesgo harían falta 8 pérdidas seguidas para
tocar el límite del 2%. Igual: **después de 3 pérdidas en el día, no se opera
más**. La racha típica medida es de 5, y no hay razón para descubrir en vivo
dónde termina.

**Reducción por drawdown.** Si la cuenta cae **2% desde su máximo**, se opera a
**mitad de tamaño** (0,125% por trade) hasta recuperar el máximo anterior. Con
el drawdown máximo en 4%, esto deja margen para equivocarse dos veces.

**Corte por régimen.** Si en 20 trades consecutivos no aparece ningún ganador
de más de 20%, parar y revisar. La estrategia depende de esa cola: si dejó de
aparecer, algo cambió y no es momento de seguir pagando por descubrirlo.

## 5. Lo que este protocolo NO tiene validado

Escrito acá para que no se pierda con el tiempo:

- ~~**Independencia entre trades**~~ — **MEDIDO** (`test_correlacion.py`).
  Sí hay agrupamiento por día, pero es **chico**: la varianza de tomar k trades
  el mismo día es 7-18% mayor que lo que predice la independencia (ratios
  winsorizados 1,07-1,18, consistentes). Prueba de permutación: percentil 97,
  evidencia marginal (p≈0,03) pero con los cinco ratios apuntando igual.

  La cola tapaba el efecto: con retornos crudos (p99 = +168%, máx +672%) los
  ratios salían sin patrón. Recortando al p95 aparece.

  **Impacto:** tomar 4 trades el mismo día equivale a ~3,5 independientes. La
  simulación queda levemente optimista, pero el 0,25% tenía margen de sobra
  (0-2% de muerte) y no se mueve materialmente. Donde sí empeora es en 0,5%,
  que ya moría 20-56% de las veces. **La recomendación no cambia, se refuerza.**
- **n=124 trades** en la muestra, con reuso pesado en el remuestreo.
- **Slippage en halts.** El stop se asume ejecutado a su precio. En una acción
  que haltea, el fill real es peor. No modelado.
- **Disponibilidad de locate.** Un short que no se puede abrir tiene retorno
  cero, no negativo. El backtest los toma todos.
- **Sin fuera de muestra** sobre esta configuración específica de salida.

## 6. Cómo se vería en la práctica

Con $25.000 de buying power, 3 trades por día, 120 días hábiles:

- posición de ~$521 por trade (**2% del buying power**)
- retorno mediano en 6 meses: **+19,8%** con la cola removida, **+70,6%** con
  la distribución completa
- probabilidad de perder la cuenta: **2%**

El número honesto para planificar es el primero. El segundo es lo que pasa si
la cola aparece — y no se puede contar con eso.
