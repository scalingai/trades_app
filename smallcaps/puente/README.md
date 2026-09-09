# El puente: datos de Trade The Pool → nuestro sistema

Una sola vía. **La plataforma manda barras, el sistema dice qué hacer, y las
órdenes las ponés vos.** No hay nada acá que pueda mandar una orden, y es a
propósito: la operativa es semiautomática.

```
  Trade The Pool                 archivo                  Python
  ┌──────────────┐            ┌───────────┐         ┌──────────────┐
  │ TTPFeedMulti │  watchlist │  .jsonl   │  vivo   │ qué shortear │
  │ en 1 gráfico │ ─────────► │ append    │ ──────► │ cuántas acc  │
  └──────────────┘   (C#)     └───────────┘         │ dónde el stop│
                                                    └──────────────┘
```

## Desde el 2026-09-04: las barras salen de Yahoo, no de la plataforma

Ya no se opera en Trade The Pool (`OPERATIVA.md` §0) y la plataforma de
TradeZero no tiene scripting, así que el indicador `TTPFeedMulti` quedó sin
dónde correr. `yahoo_feed.py` escribe **el mismo archivo, con el mismo
formato**: barras de 1 minuto con sesión extendida, al minuto, de los papeles
de la watchlist. Nada de lo que lee el archivo cambió.

La rutina de la mañana, **un solo comando**, antes de las 09:30 NY:

```bash
python smallcaps/arrancar.py                # visor (:8765/vivo) + feed de Yahoo, juntos
```

Levanta los dos procesos, mezcla sus salidas con prefijo `[visor]` / `[feed]`,
y con Ctrl+C —o si lo matan de prepo— apaga a los dos. Sueltos siguen
existiendo, para rellenar un día o reindexar:

```bash
python smallcaps/visor/server.py            # el visor → http://127.0.0.1:8765/vivo
python smallcaps/puente/yahoo_feed.py       # el feed, hasta las 20:00 NY o Ctrl+C
```

**Por qué un solo comando.** El visor abre igual sin feed, y sin feed la
pantalla se ve **exactamente como un día en el que nada califica**: vacía. La
semana del 2026-09-07 se levantó el visor solo tres ruedas seguidas y se leyó
como "no hubo trades" —IRD calificó el 9 con tres tramos y nadie lo vio—. Desde
entonces `/vivo` avisa en rojo si el mercado está abierto y el feed no tiene
ninguna barra de hoy, y **la watchlist se muestra entera** aunque un papel
todavía no tenga barras (fila ámbar "sin barras del feed").

**Trade The Pool ya no hace falta abierto.** El indicador `TTPFeedMulti` quedó
obsoleto; lo único que se necesita abierto es TradeZero, para el locate y las
órdenes.

La watchlist la arma el botón **buscar** de `/vivo` (o `python smallcaps/escaner.py`)
**con el mercado abierto**: en pre-market Yahoo no tiene el gap de los papeles
que todavía no operaron y la lista sale vacía. El feed relee la watchlist en
cada ciclo, así que se puede armar después de arrancarlo.

**El `pc` de `--dia` estaba mal, y era el denominador de un filtro (2026-09-09).**
`barras_de` leía `chartPreviousClose`, que es "el cierre anterior al COMIENZO DE
LA VENTANA": con `range=1d` es el de ayer, pero `--dia` pide `range=5d` y ahí es
el cierre de hace **seis ruedas**. FTFT escribía 1,82 cuando el cierre previo era
1,31 — 39% de error. Como `pc` es `Dia.prev_close`, y `prev_close` es el
denominador de `expansion_pct`, el filtro de pre-market decidía sobre un número
inventado sin que nada avisara. Ahora `--dia` toma el **cierre oficial** de la
sesión anterior del gráfico diario, con las velas de un minuto como red.

**Lo que no escribe:** la barra en curso. `leer_feed` se queda con la primera
línea de cada minuto, y una barra escrita a medias quedaría congelada. La
pantalla va un minuto atrás del mercado, a propósito.

Los días que el censo no tiene y el feed sí —ayer, por ejemplo— se navegan en
`/vivo` con las flechas igual que los del censo.

## Los archivos

| archivo | qué hace |
|---|---|
| `yahoo_feed.py` | **El que se usa.** Las barras de 1 minuto de la watchlist desde Yahoo, al mismo archivo. |
| `TTPFeedMulti.cs` | El indicador de la plataforma de Trade The Pool. Escribía lo mismo; queda por si se vuelve. |
| `TTPFeed.cs` | La primera versión: un gráfico por papel. Queda como respaldo. |
| `vivo.py` | La pantalla. Lee el archivo, arma un `Dia` y llama al motor. |
| `identidad.py` | Verifica que el camino vivo dé **exactamente** lo mismo que el backtest. |
| `watchlist.py` | El escáner por Polygon — **hoy no sirve en vivo**, ver abajo. |

## La rutina de la mañana

**1. Armar la watchlist.** En la plataforma: `Tools → Gainers/Losers list`,
filtro `Vol>1M Price<10`. Los que suben fuerte con precio ≥ $2 van al archivo,
con su precio al lado:

```
C:\Users\agust\Apps\algotrade-data\smallcaps\watchlist.txt

FLYE 2.07
BIAF 6.45
RDAC 6.56
```

**El precio no es decoración.** Un mismo símbolo existe en más de un mercado:
`SSM` resolvió a un instrumento de $59 con 116 acciones de volumen cuando el
SSM que buscábamos estaba a $3,85 subiendo 43%. El precio es lo único que los
distingue, y se chequea en los dos lados —el indicador elige con él, y `vivo.py`
lo vuelve a verificar—. Repetido a propósito: una verificación que vive sólo del
lado que manda los datos no verifica nada.

El archivo se relee solo. Agregar un ticker a mitad de rueda lo mete sin tocar
la plataforma.

**2. El indicador, una sola vez.** `TTPFeedMulti` en **cualquier** gráfico. No
importa qué papel muestre ese gráfico ni su timeframe: el indicador pide la
historia de cada ticker por su cuenta, en 1 minuto y **con sesión extendida**,
que es lo que garantiza el premarket sin depender de cómo esté configurado nada.

El título del indicador dice el estado: `TTPFeedMulti 5/7` son cinco papeles con
datos de siete pedidos. Si ves `0/7` algo se rompió — los errores se tragan para
no romper el gráfico, así que ése es el único síntoma.

**3. La pantalla.**

```bash
python smallcaps/puente/vivo.py --riesgo 400 --piso 2
```

o el visor, con gráficos: `python smallcaps/visor/server.py` → **En vivo**.

## Lo que la pantalla te dice

Por papel: si el día califica —y **por qué no**, si no—, los tramos con precio
de entrada y stop, cuáles siguen abiertas y cuáles ya saltaron, y las dos cifras
que deciden:

- **acciones en el pico del día** — eso es lo que hay que tener localizado. No
  es la suma de los tramos: el locate se reserva una vez por papel y por día
  para el máximo simultáneo.
- **equity contra el límite diario** — cuando se acerca, el sistema deja de
  abrir tramos, igual que en el backtest.

## La regla que sostiene todo esto

`vivo.evaluar` **no tiene lógica de estrategia**: llama a `motor.jornada`, la
misma función que produjo cada número medido.

Por eso, **antes de operar**:

```bash
python smallcaps/puente/identidad.py
```

Compara cinco días reales —incluido uno perdedor y el de 20 tramos— pasando los
datos por el mismo archivo JSONL que escribe la plataforma. Si dice
`HAY DIVERGENCIA`, no se opera.

Ese test ya se ganó el sueldo dos veces: encontró el huso horario hardcodeado
que iba a romper en noviembre, y se puso en rojo cuando metí el chequeo de
identidad del papel adentro de `evaluar` —donde no va, porque es sobre la
procedencia del dato y no sobre la estrategia—.

## Mantenimiento

El indicador vuelca la historia entera cuando arranca, así que el archivo crece.
Con el **mercado cerrado**:

```bash
python smallcaps/puente/vivo.py --limpiar
```

Se corre cerrado a propósito: reescribir el archivo mientras el indicador
escribe puede perder la barra de ese minuto, y una barra perdida cambia el día.

## Por qué `watchlist.py` no sirve todavía

El plan de datos de Polygon entrega el día **siguiente**: pedirle hoy devuelve
`NOT_AUTHORIZED` y ayer funciona. Sirve para revisar a posteriori, no para armar
la lista de la mañana. Por eso la watchlist sale hoy del `Gainers/Losers list`
de la plataforma, que sí tiene datos en tiempo real y viene incluido con la
cuenta.

## Lo verificado

Todo lo de arriba corrió contra datos reales el 2026-09-01: el indicador cargó
en la plataforma, bajó los siete papeles de la watchlist, y el sistema decidió
solo —dos con señal (BIAF y DAIC, ambos *reclaim*), tres rechazados por abrir
*fade*, uno por precio que no cuadraba—.
