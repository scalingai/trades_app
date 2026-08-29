# Cómo se mide cada número

> Pregunta de Agus, 2026-08-29: *"¿con qué criterio decidís acá se hubiera
> entrado, acá se hubiera acumulado, acá se hubiera salido?"*
>
> La respuesta corta es incómoda: **depende de qué número**, y **la mitad de los
> números del proyecto no son trades**. Este documento dice exactamente qué es
> cada uno.

## Lo primero, porque cambia cómo se lee todo lo demás

Hay dos clases de resultado en este proyecto y **se parecen en la tabla pero no
significan lo mismo**:

| | qué es | ejemplo |
|---|---|---|
| **Medición de movimiento** | ¿el papel cayó? | el −13,27% del radar |
| **Simulación de trade** | ¿esta regla ganaba plata? | el −0,99% de la Chavineta |

El número más citado del proyecto —**el −13,27% del radar**— es del primer tipo.
Es `(cierre ÷ apertura − 1)`: **el papel se movió eso**. No hay entrada, ni
stop, ni salida, ni costos, ni locate.

Eso **no** lo vuelve inútil: es la pregunta correcta para "¿este filtro
selecciona días que caen?", que es lo que un filtro tiene que contestar. Pero
**no es** la respuesta a "¿cuánto ganaba?", y no hay que leerlo así. Un día que
cae 13% de apertura a cierre puede haber subido 40% en el medio y haberte
sacado tres veces.

---

## Tipo A — Mediciones de movimiento (NO son trades)

**Qué calculan:** `(cierre ÷ apertura − 1) × 100` del día del evento. En la base
es el campo `intraday_pct`.

**Reglas de entrada/salida:** ninguna. No hay stop, ni target, ni costos.

**Qué contestan:** si un filtro selecciona días que caen.

**Scripts:** `radar.py`, `radar_historico.py`, `test_historial.py`,
`test_regimen.py`, `test_capas.py`, `test_sensibilidad.py`.

**Cómo leerlos:** la comparación entre filas vale (los candidatos caen 13% y la
población sube 1,8%). El número **no** es un retorno esperado.

---

## Tipo B — Entrada a hora fija con stop

**Entrada:** se vende el nominal completo al precio de cierre del minuto de la
hora indicada (10:00, 12:00, según el test). Sin condición extra: si el día está
en la muestra, se entra.

**Adiciones:** ninguna. Es una entrada y una salida.

**Stop:** un porcentaje fijo desde la entrada. Se dispara con el **máximo** de
cualquier minuto posterior, y se asume ejecutado a su precio exacto — que es
optimista en un papel que haltea.

**Salida:** lo que pase primero, el stop o el cierre de la sesión regular
(16:00).

**Costos:** spread en centavos + comisión × 2 + locate, todo por acción,
convertido a % dividiendo por el precio de entrada.

**Scripts:** `test_lados.py`, `test_frontlong.py`, `test_signals.py`,
`test_ict.py`.

---

## Tipo C — Grilla de stop y target en múltiplos de riesgo

**Entrada:** cada minuto de 09:45 a 15:30 es una entrada candidata. Son 233.512
observaciones, no 233.512 trades: los momentos del mismo día se solapan.

**Stop:** `m × volatilidad del momento`, donde la volatilidad es la **mediana**
del rango `(máximo−mínimo)/cierre` de las 30 barras previas. Con la mediana de
1,38% de la muestra, `m=8` es un stop del ~11%.

**Target:** `R × la distancia del stop`, o un nivel estructural (VWAP, POC,
mínimo del día…) — en ese caso el ratio sale de dónde está el nivel.

**Empate:** si en el mismo minuto se tocan stop y target, **gana el stop**. No se
sabe el orden dentro de la barra y asumir lo favorable sería inventar plata.

**Salida:** stop, target, o cierre de la sesión, lo que pase primero.

**Costos:** en R, no en %. `costo por acción ÷ precio ÷ ancho del stop`. Los
momentos donde el costo supera 0,25R se descartan como inoperables, y se reporta
cuántos son.

**Scripts:** `momentos.py` (construye), `test_ratios.py` (evalúa).

---

## Tipo D — La Chavineta (construcción de posición)

Este es el único que se parece a operar. `chavineta.py`.

**1. Filtro del día.** A las 10:00 se clasifica la apertura:
- *reclaim* — rompió el máximo de pre-market, **cerró arriba 5 minutos
  seguidos**, y después hizo un máximo nuevo → **no se opera el día**.
- *fade* — no lo rompió, o está debajo del VWAP → se activa el protocolo.

Descarta el 38% de los días.

**2. Entrada — agotamiento de volumen.** El primer minuto entre 09:45 y 14:00
donde pasan **las dos cosas**:
- el volumen promedio de los últimos 5 minutos cae por debajo de **la mitad del
  clímax de volumen del día hasta ese momento**, y
- el máximo corriente del día tiene **más de 10 minutos** de antigüedad.

Ahí se abre el **20% del nominal**.

**3. Adiciones — contra niveles, nunca a pasos fijos.** Se arma una escalera con
los niveles que estén ARRIBA del precio de entrada: máximo de pre-market, máximo
del día previo, VWAP, y máximo corriente del día. Cada vez que el precio toca el
siguiente nivel de la escalera se agrega **otro 20%**, hasta cinco tramos.

Si arriba del precio no hay estructura, **no hay adición**. Eso es lo que
separa esto de promediar a ciegas.

**4. Reducciones.** Cuando el precio vuelve a caer por **debajo del nivel desde
el que se agregó**, ese tramo se cierra. El núcleo no se toca.

**5. Salida por reclaim en vivo.** Si el precio cierra **dos minutos seguidos**
por encima de la resistencia más alta de la escalera, se cierra todo. Con
`--gradual` se cubre el 40% al toque y el resto contra los mínimos que mejoren
el precio, con 30 minutos de plazo.

**6. Tope de pérdida.** Si la pérdida no realizada supera el 20% del nominal
completo, se cierra todo.

**7. Salida final.** Lo que quede se cubre al cierre de la sesión regular.

**Costos:** comisión por ejecución —y son varias por trade, mediana 4—. Con
`--pasivo` las adiciones y reducciones se tratan como órdenes limitadas puestas
en el nivel (aportan liquidez, no cruzan el spread) y solo la salida de
emergencia cruza. El locate se aplica como quita del 20% sobre la ganancia
bruta.

---

## Tipo E — Construcción vs entrada simple (`test_construccion.py`)

**simple:** se vende el nominal completo a la hora de arranque, se cubre todo a
la hora de salida. Sin stop, sin target, sin costos.

**escalonado:** 20% a la hora de arranque, otro 20% **cada vez que el papel hace
un máximo nuevo del día**, hasta cinco tramos. No se reduce nada. Se cubre todo
a la hora de salida.

**El ajuste que hay que entender:** el resultado del escalonado se multiplica por
`tramos abiertos ÷ 5`. Un día donde solo se abrió el núcleo cuenta como **un
quinto** del movimiento, porque se puso un quinto del capital.

Por eso **las medianas de los dos no son directamente comparables**: cuando el
papel no hace máximos, el escalonado despliega menos capital y su mediana baja
por eso, no porque el método falle. La columna `tramos` está en la tabla
justamente para verlo.

**Lo que sí es comparable directo:** el win rate y el MAE, porque el riesgo
máximo comprometido es el mismo en las dos — cinco tramos de 20%.

---

## Lo que NINGUNA de las simulaciones tiene

Y conviene tenerlo junto en un solo lugar:

1. **Disponibilidad de borrow.** Todas asumen que el short se puede abrir. Un
   short sin locate rinde **cero**, no negativo, y no está modelado en ninguna.
2. **Slippage en halts.** El stop se asume ejecutado a su precio exacto. En un
   papel que haltea el fill real es peor, y con stops chicos eso pesa el doble.
3. **El orden dentro del minuto.** Las barras son agregados; cuando stop y
   target caen en el mismo minuto se asume lo desfavorable, que es conservador
   pero no es el dato real. Se arregla con datos de trades (plan pago).
4. **La decisión discrecional.** Ninguna simula lo que un operador NO toma. Es
   la brecha medida entre el 44% de la Chavineta mecánica y el 77,8% auditado, y
   es lo que `etiquetas.py` existe para poder medir.

## Y el reparo que va arriba de todo

Salvo `radar_historico.py`, `test_historial.py`, `test_regimen.py`,
`test_capas.py` y `test_sensibilidad.py` —que corren sobre las barras diarias de
los 87.943 eventos— **todo lo demás usa la muestra de minutos sesgada**: 1.500
días sorteados de eventos con rango DIARIO > 40%, que a las 09:30 no se conoce.

Las comparaciones entre celdas de esa muestra valen. Los niveles absolutos, no.
Está bajando el censo observable para arreglarlo.
