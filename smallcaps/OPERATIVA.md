# La operativa, como quedó

> Medido sobre 209 sesiones `reclaim` entre 2024-09-27 y 2026-08-31 (23,1 meses).
> Supersede a `GESTION-RIESGO.md`, que es de una fase anterior — hablaba de
> $25.000 de buying power y stop del 12%, y ya no describe nada de esto.
>
> **Nunca se operó en vivo.** Todo lo de abajo son mediciones sobre el censo.

## Estado al 2026-09-04

- Se opera con **cuenta propia en TradeZero**, no con fondeo (§0).
- **El corte de las 11:00 ya no se usa** en ninguna fase (§0b y §4): medido con
  el drawdown real —intradía, trepando— a $150 de riesgo, cuesta más de lo que
  protege.
- **Con $500 se mide, no se opera.** El portafolio (`/portafolio`, `propia.py`)
  proyecta la cuenta propia día por día con los costos reales del broker (§7).
- El número que falta es **el locate** de nuestros papeles el día que gapean. Se
  anota en `/vivo`, columna `loc`, y el portafolio lo toma de ahí.

Lo que sigue es la historia de cómo se llegó, en el orden en que pasó. Las
secciones marcadas *histórico* describen una fase anterior y se dejan porque
las mediciones siguen valiendo; la conclusión operativa es la de §0.

## Lo que cambió el 2026-09-01, y por qué importó (histórico)

Veníamos optimizando **plata neta** y **retorno sobre el nominal**. Ninguna de
las dos dice si la cuenta llega viva a fin de mes, y resulta que la
configuración que más plata daba **no sobrevive**: drawdown de $-3.684 contra un
tope de $1.000, incluso operando a mitad de riesgo.

Agregar un corte temprano lo arregla. Cuesta plata y es lo que hace la
diferencia entre una estrategia y una estrategia operable.

| | neto | al año | peor día | drawdown | ¿vive? |
|---|---|---|---|---|---|
| sostener al cierre | $36.495 | $18.963 | $-1.618 | $-3.684 | **NO** |
| **+ corte 11:00 si no ganó 5%** | $20.791 | **$10.803** | $-434 | **$-856** | **sí** |

Los $36.495 son plata que no se puede cobrar porque la cuenta se liquida antes.

Todo con **$150 de riesgo por papel**, simulado por día de cuenta —con todos los
papeles del día compartiendo la misma cuenta— y con el arnés verificado contra
el motor a 0,0% de diferencia.

> **Por qué esto quedó viejo.** Se midió con drawdown de CIERRE y $400 de riesgo.
> Con el drawdown como lo mide una cuenta de verdad —intradía, desde el pico— y
> con el riesgo dimensionado para eso ($150 o menos), el corte deja de proteger:
> duplica el tiempo de evaluación y, fondeado, impide cobrar. Ver §0b.

---

## 0. Dónde se opera: cuenta propia en TradeZero (fase de medición)

**La decisión (2026-09-03):** Trade The Pool no sirve para esta estrategia — la
regla de retiro de FLEX (3 días con $125 en 14) no se cumple con 2–7 sesiones
por mes, y MAX vence a los 60 días. Se opera con **cuenta propia en TradeZero
International**: sin PDT (nunca lo tuvo para no residentes de EE.UU., y FINRA lo
eliminó para todos el 2026-06-04), sin consistencia, sin días mínimos, locates
de 14 fuentes **con el precio a la vista antes de aceptar**, y los que no se
usan se revenden.

**Se arranca con $500, y con $500 NO se opera: se mide.** El único número que
decide si el negocio existe es lo que cobran por localizar NUESTROS papeles el
día que gapean, y no está en ninguna fuente pública. Medido con la estrategia
actual, el negocio muere con locate arriba de **$0,11–0,19 por acción** (según
riesgo, con el mínimo de 100 acciones por pedido). Un día normal cuesta ~$0,03;
un día caliente puede costar el 5% del nominal —$0,26 en nuestro papel
mediano—, y ese día es justamente el nuestro.

**El protocolo, dos o tres semanas:**

1. Cada mañana, pedir el locate de cada papel del scanner en TradeZero **sin
   aceptarlo**. Mirar el precio cuesta cero.
2. Anotarlo en `/vivo`, columna **loc** del scanner. Se guarda en
   `locates.jsonl`. Arriba de $0,10 se pinta ámbar.
3. Al cabo, `python test_bono_locates.py --reales` da el veredicto con la
   mediana, el p75 y el máximo anotados.

**Por qué con $500 no se opera:** TradeZero cobra $0 sólo en órdenes de 100+
acciones; debajo, 0,5¢/acción con **mínimo $0,49 por orden**. Nuestros tramos
son de 3 a 23 acciones, así que TODOS pagan $0,98 de ida y vuelta: **$726 por
año, a cualquier tamaño**. A $20 de riesgo por papel (lo que aguanta una cuenta
de $500) el bruto es $1.008/año → quedan $282 antes de locates. A $75 (cuenta de
~$2.000–2.500, 6:1) quedan **$3.053** antes de locates. Operar empieza ahí.

**La regla operativa cuando se opere:** no tocar el papel si el locate supera
**$0,10 por acción**. Convierte la incógnita en un filtro: el costo de la regla
es perderse los días caros, que son los peligrosos.

**Configuración:** modo **propia** en la app —todos los papeles, sin corte, sin
tope, riesgo por defecto $75—. Piso de precio **$2,05**: TradeZero no deja
shortear en margen bajo $2.

## 0b. Los modos de Trade The Pool: evaluación o fondeada (quedan medidos, no se usan)

La evaluación y la cuenta fondeada de Trade The Pool tienen **reglas distintas**,
así que el sistema tiene **dos configuraciones** y se elige una en la ruedita de
ajustes de `/vivo`. Medido con arranques rodantes sobre el censo (`evaluacion.py`,
`fondeada.py`), cuenta FLEX de $25.000, drawdown intradía que trepa con el pico.

| | evaluación | fondeada |
|---|---|---|
| lo que ata | **consistencia**: la mejor posición ≤ 50% del objetivo ($1.500) | **retiro**: 3 días con ≥$125 en 14 días corridos |
| tope por símbolo | **$525**: cerrar el papel al tocarlo, no volver a entrar | no hay |
| papeles por día | **todos** los del scanner | **uno** |
| corte de las 11:00 | no | no |
| riesgo por papel | $150 | $150 |
| resultado medido | pasa limpia el 82% en ~108 días esperados, 1,2 evaluaciones | cobra el 69% de las cuentas en 180 días, 10% se quema |

**El corte de las 11:00 ya no se usa en ninguna fase.** Fue "lo único que hacía
la estrategia operable", medido con $400 de riesgo contra un drawdown de cierre.
Dimensionado para el drawdown real —intradía, trepando— a $150, el corte cuesta
más de lo que protege: duplica el tiempo de evaluación y, fondeado, impide
cobrar (cierra a las 11 posiciones que al cierre habrían sido días de $125). El
mecanismo era correcto para el tamaño equivocado.

**Cómo se ejecuta el tope a mano.** El gráfico dibuja una línea ámbar
`tope $X`: es el precio al que la ganancia del día en ese símbolo toca $525,
contando lo ya cerrado. Al llegar, se cierra todo el símbolo y no se vuelve a
entrar en él ese día.

**Cuenta MAX, descartada.** No tiene la regla de los 3 días, pero da 60 días
para pasar y esta estrategia opera 2–7 veces por mes: el 60–100% de los
arranques vence sin llegar.

**Supuesto abierto (pregunta 5 para soporte):** qué pasa con el piso del drawdown
después de un retiro. Acá se asume que se vuelve a medir desde el nuevo balance.

## 1. Antes de la apertura — la watchlist

**Primero, la app.** Un comando, antes de las 09:30 NY, y Trade The Pool cerrado
(ya no se usa para nada):

```
python smallcaps/arrancar.py     # visor + feed de Yahoo, juntos
```

Si el feed no está escribiendo con el mercado abierto, `/vivo` lo dice en rojo
arriba de todo. Antes no lo decía, y la semana del 2026-09-07 pasó por "no hubo
trades" cuando lo que no hubo fue feed (ver `puente/README.md`).

**El botón `buscar` del scanner, en `/vivo`.** Tarda entre veinte segundos y un
minuto y deja `watchlist.txt` escrito. Desde la terminal es lo mismo:

```
python escaner.py               # muestra qué encontró, no escribe
python escaner.py --escribir    # reemplaza watchlist.txt
```

Aplica los criterios del **censo** (`poblacion_observable.py`), que son los que
definen la población sobre la que se midió todo el proyecto:

**gap ≥ 25% · liquidez previa ≥ $150k · precio previo $0.20–$20**, más el piso
operativo de **$2**.

Sobre 472 días hábiles eso da **4,3 papeles por día**. Si un día salen 40 o
sale 0, el número lo canta y ese día no se opera hasta entender por qué.

Los datos salen de Yahoo Finance, que es lo único gratis que ve el mercado
entero en el día: Polygon free no ve el día en curso, y `TradeApi.dll` de Trade
The Pool no expone el universo —sólo da precios de símbolos que uno ya nombró—.
Yahoo elige los NOMBRES; los precios con los que se opera siguen saliendo de la
plataforma.

**Si Yahoo se cae**, que puede pasar porque es una API no oficial: `watchlist.txt`
es un archivo de texto y se escribe a mano como antes, un papel por línea con su
precio al lado. El precio no es decoración —un mismo símbolo existe en varios
mercados y sin él el sistema baja los datos del papel equivocado.

```
FLYE 2.07
BIAF 6.45
```

**Lo que se hacía hasta el 2026-09-03:** abrir `Tools → Gainers/Losers list` con
filtro `Vol>1M Price<10` y anotar "los que suban fuerte". Esa última frase era
la única parte del sistema que no estaba medida ni era reproducible: dos días
con el mismo mercado podían dar dos watchlists distintas según qué viste
primero. **Filtro extra que no está en el censo:** float ≤ 47M.

Y nada más. Se probó filtrar además por salud de la empresa —poca caja, mucha
dilución, reverse splits— y aunque esos días **sí se derrumban más** (22,9%
contra 10,8%), filtrar por ellos **no le gana a elegir la misma cantidad de días
al azar**. Separar el derrumbe y ganar plata no son la misma cosa.

## 2. A las 10:00 — qué califica

El sistema clasifica la apertura y decide solo:

- **apertura `reclaim`** (abre, cae bajo el VWAP y lo recupera). Los `fade` no
  se operan: se midió y pierden.
- **expansión ≥ 0%** contra el máximo premarket.
- sin premarket no hay expansión y **el día no califica** — la pantalla lo dice.

No se entra antes de las 10:00. La etiqueta de apertura necesita las velas hasta
esa hora, y usarla antes fue uno de los look-ahead más caros del proyecto
(inflaba el retorno 12 puntos).

## 3. Entradas — se agrega, no se acierta

- Señal: `señales_swing` desde las 10:00, precio ≥ $2.
- **Tamaño por riesgo:** `riesgo_por_tramo / (precio × 45%)`. Cada tramo
  arriesga lo mismo en dólares, no la misma cantidad de acciones.
- **Stop por tramo: 45%** sobre SU precio de entrada. Cada tramo muere solo.
- Hasta 40 tramos.
- **Presupuesto diario:** se deja de abrir cuando la equity marcada a mercado
  menos un tramo caería bajo el límite. Marcada a mercado, no con el PnL final
  — usar el final fue un look-ahead que infló todo 5 puntos.

**Un 45% de stop suena enorme y no lo es:** el movimiento en contra mediano es
10% y el p90 es 38%. El stop está más allá del percentil 90 de lo que estos
papeles se mueven en contra.

## 4. A las 11:00 — el corte (histórico: ya no se usa)

> **Hoy no hay corte.** Se sostiene al cierre. Lo de abajo es cómo se midió y
> por qué se adoptó; §0b dice por qué se sacó: dimensionado para el drawdown
> real —intradía, trepando— a $150 de riesgo, cuesta más de lo que protege. Se
> probaron además las 11:05, 11:10 y 11:15 (`test_corte_minuto.py`), la salida
> por rango seco (`test_salida_rango_seco.py`) y el corte condicionado a que el
> movimiento siga vivo (`test_corte_condicionado.py`): ninguna mejora el
> drawdown en las dos mitades del tiempo.

La regla era: *si la posición no está al menos 5% a favor, se cierra todo y ese
papel no se opera más en el día.* Tres cosas que se sabían de ella:

**No gana más plata.** Sostener al cierre deja $175 por sesión y esto $110. Lo
que compra es que el peor día pase de $-1.618 a $-505.

**La condición importa, no el horario.** Cerrar a las 11:00 *siempre* deja $23
por sesión; cerrar *sólo lo que no funciona* deja $110; cerrar *sólo lo que sí
funciona* deja $74. No es salir antes: es a cuáles.

**Tiene que ser temprano.** A las 12:00 y 13:00 el beneficio de riesgo se
evapora y el drawdown vuelve a $-2.520 y $-4.348. Cortar tarde ya es tarde.

Aguanta partido en las dos mitades del tiempo: el drawdown mejora en las dos, y
el retorno queda en 8,39% y 8,46% —más estable que la base, que oscila entre
8,30% y 11,57%.

## 5. El resto del día

- Stop por tramo al 45%, cada uno por su cuenta.
- Todo lo que quede vivo **se cierra a las 16:00**.
- **No hay take profit, y no es un olvido.** Se midió catorce veces: objetivo
  fijo, trailing, breakeven, stop-profit, cerrar por rango que se seca. Todas
  empeoran. La razón es mecánica: la estrategia vive de la cola —los pocos días
  que se derrumban en serio— y cualquier regla que corte ganadores corta
  exactamente eso.
- La pantalla dibuja hasta dónde llegó a favor la mitad (18,3%) y tres cuartos
  (29,5%) de los trades. **Es referencia, no un objetivo de salida.**

## 6. El riesgo es POR ACTIVO, y no hace falta techo

Un día de tres papeles arriesga más que uno de un papel, y está bien. Lo que no
puede pasar es perforar el límite diario de la cuenta.

**Se probó ponerle un techo duro a la cuenta —cerrar todo cuando la pérdida
junta toca el límite— y NO sirve.** Medido:

| | neto | drawdown | peor día |
|---|---|---|---|
| $200/papel + corte, **sin techo** | **$9.647** | $-487 | **$-221** |
| $200/papel + corte, con techo $400 | $9.217 | $-487 | $-447 |

Mismo drawdown, pero sin techo gana más y con mejor peor día. Y el techo SOLO
—sin el corte— empeora las cosas: el drawdown pasa de $-3.684 a $-3.788.

**Por qué.** El techo cierra en el peor momento del día, que es justo cuando la
pérdida es máxima. Convierte caídas que se hubieran recuperado en pérdidas
realizadas. Protege del desastre y cobra en el día promedio, y con el corte de
las 11:00 puesto el desastre ya no llega.

El control diario real es el riesgo por activo bien dimensionado más el corte.

**Sin el corte la conclusión se sostiene** (`test_tope_intradia.py`, 2026-09-03):
un tope duro de pérdida diaria empeora el drawdown en todos los umbrales
probados, por el mismo mecanismo. El control es el tamaño, no un techo.

## 7. Cuánta plata

**Cuenta propia en TradeZero, proyectada desde el 2 de enero de 2026** con la
estrategia en modo propia (todos los papeles, sin corte, sin tope) y los costos
del broker: comisión con mínimo $0,49 por orden, locate por papel-día sobre 100
acciones como mínimo, sin plataforma (TZ1 web). Es lo que muestra `/portafolio`
y calcula `propia.py`; los dos leen la misma función.

| depósito | riesgo/papel | bruto | comisiones | locates* | neto | al año | peor drawdown |
|---|---|---|---|---|---|---|---|
| **$500** | $20 | +$839 | −$283 | −$396 | **+$160** | +$243 | −$316 (**−63%** del depósito) |
| **$2.000** | $75 | +$3.147 | −$276 | −$471 | **+$2.400** | +$3.638 | −$449 (−22%) |

\* Locates a **$0,05 por acción supuestos** en los 79 papeles-día: no hay
ninguno anotado todavía. Es el costo que decide y es el que se está midiendo.

Tres cosas que la tabla dice:

- **Los costos se comen el 81% del bruto a $500.** La comisión es casi la misma
  en las dos cuentas —$0,49 por orden no escala— y el locate tampoco, porque el
  mínimo de 100 acciones es más de lo que la cuenta chica necesita. A $2.000 los
  mismos costos son el 24%.
- **Con $500, el drawdown es del 63% del depósito.** No es que el broker no
  deje —el poder de compra alcanza—: es que a mitad de año la cuenta habría
  estado en $316. Con $2.000 y $75 el mismo camino es −22%.
- **Por eso $500 mide y $2.000 opera.** El drawdown intradía se mide sumando las
  curvas de todos los papeles minuto a minuto, contra el pico histórico.

La cuenta se para por una regla **nuestra**: equity por debajo del 20% del
depósito (era 50%; Agus lo bajó el 2026-09-04: la sangría de costos de la
cuenta chica no es motivo para cerrar la operativa). El broker no liquida por perder plata propia; uno se queda sin poder
de compra y sigue. La regla está a la vista en la página como parámetro.

**Histórico — lo que decía este documento para Trade The Pool**, medido con
drawdown de cierre y corte de las 11:00:

| config | al año | drawdown | ¿entra en $1.000? |
|---|---|---|---|
| sin corte | $18.963 | $-3.684 | NO |
| $400/papel + corte 11:00 | $10.803 | $-856 | sí |
| $200/papel + corte | $5.013 | $-487 | sí |

Los $18.963 anuales del "sin corte" son a $400 de riesgo con la comisión de
Trade The Pool y sin locate; a $75 y con los costos de TradeZero son los $3.638
de arriba. El mecanismo es el mismo, el tamaño y los costos no.

## 8. Lo que falta y se sabe que falta

**El locate de TradeZero no está medido.** Es la fase actual (§0): dos o tres
semanas anotando el precio de cada papel del scanner sin aceptar. Hasta que la
mayoría de los papeles-día del portafolio sean anotados y no supuestos, el neto
que muestra es una hipótesis con forma de número.

**El pedido mínimo de 100 acciones por locate es un supuesto** de la industria,
no confirmado con TradeZero. Si cobran sobre las acciones reales, el punto de
muerte es más holgado ($0,22–0,28 en vez de $0,11–0,19 por acción).

**El long de pre-market no se puede medir con el censo** (`test_premarket_long.py`,
2026-09-04). El censo elige por gap ≥ 25% a la apertura, así que los papeles que
se derrumban antes de las 09:30 no están: cualquier long medido ahí es un techo.
Con ese sesgo a favor, las rupturas del máximo de pre-market son peores que
entrar al azar, y lo único positivo —comprar la primera barra con gap y aguantar
sin stop— saca el 99% de su resultado del 5% de los trades. No se implementa.
Medirlo de verdad exige una población elegida a las 07:00, prospectiva.

**Nada de esto se operó en vivo.** Son 209 sesiones de censo con ~450
estrategias probadas encima. Sostener al cierre sin corte aguantó las dos
mitades del tiempo, que es el mínimo, no una garantía.
