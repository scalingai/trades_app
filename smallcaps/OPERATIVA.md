# La operativa, como quedó

> Medido sobre 209 sesiones `reclaim` entre 2024-09-27 y 2026-08-31 (23,1 meses).
> Supersede a `GESTION-RIESGO.md`, que es de una fase anterior — hablaba de
> $25.000 de buying power y stop del 12%, y ya no describe nada de esto.
>
> **Nunca se operó en vivo.** Todo lo de abajo son mediciones sobre el censo.

## Lo que cambió hoy, y por qué importa más que todo lo anterior

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

Todo con **$250 de riesgo por papel**, simulado por día de cuenta —con todos los
papeles del día compartiendo la misma cuenta— y con el arnés verificado contra
el motor a 0,0% de diferencia. Ver §7 para el detalle y para un número que este
documento daba mal.

---

## 1. Antes de la apertura — la watchlist

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

## 4. A las 11:00 — el corte (esto es lo nuevo)

> **Si la posición no está al menos 5% a favor, se cierra todo y ese papel no
> se opera más en el día.**

Es la regla que hace la diferencia entre sobrevivir y no. Tres cosas que hay que
saber de ella:

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

## 7. Cuánta plata

Simulado por DIA DE CUENTA —todos los papeles juntos, no cada uno por su lado—
con el arnés verificado contra el motor a 0,0% de diferencia:

| config | al año | drawdown | ¿entra en $1.000? |
|---|---|---|---|
| sin corte (lo que había) | $18.963 | $-3.684 | **NO** |
| **$400/papel + corte 11:00** | **$10.803** | **$-856** | **sí** |
| $300/papel + corte | $7.908 | $-654 | sí |
| $200/papel + corte | $5.013 | $-487 | sí |

**Va $400 por papel.** Una versión anterior de este documento decía $200 y
$5.983 al año: salía de una simulación que agregaba el PnL por fecha pero no
modelaba el día de cuenta. Con el modelo correcto el drawdown a $400 es $-856 y
entra con margen.

Queda un día del censo que perfora el límite diario por $34. Eso bloquea la
operativa ese día, no liquida la cuenta — el que liquida es el drawdown.

⚠️ **Los límites del plan nunca se confirmaron con soporte.** El tope de $1.000
de drawdown y los $400 de pérdida diaria salen de leer la web, no de una
respuesta. Está en `MAIL-SOPORTE.md` y sigue sin mandarse. Si el drawdown real
fuera más chico, todo esto se redimensiona.

## 8. Lo que falta y se sabe que falta

**El locate sigue sin confirmarse.** Tres fuentes independientes dicen que Trade
The Pool no cobra, ninguna es la empresa.

**Nada de esto se operó en vivo.** Son 209 sesiones de censo con ~450
estrategias probadas encima. El corte de las 11:00 aguantó las dos mitades del
tiempo, que es el mínimo, no una garantía.
