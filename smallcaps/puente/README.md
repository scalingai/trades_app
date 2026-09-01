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

## Los archivos

| archivo | qué hace |
|---|---|
| `TTPFeedMulti.cs` | **El que se usa.** Un solo indicador, en un solo gráfico, saca las barras de toda la watchlist. |
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
