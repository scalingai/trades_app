# El puente: datos de Trade The Pool → nuestro sistema

Una sola vía. **La plataforma manda barras, el sistema dice qué hacer, y las
órdenes las ponés vos.** No hay nada acá que pueda mandar una orden, y es a
propósito: la operativa es semiautomática.

```
  Trade The Pool                 archivo                  Python
  ┌──────────────┐            ┌───────────┐         ┌──────────────┐
  │  gráfico 1m  │  TTPFeed   │  .jsonl   │  vivo   │  qué shortear│
  │  por papel   │ ─────────► │ append    │ ──────► │  cuántas acc │
  └──────────────┘   (C#)     └───────────┘         │  dónde el stop│
                                                    └──────────────┘
```

## Los cuatro archivos

| archivo | qué hace |
|---|---|
| `TTPFeed.cs` | Indicador de la plataforma. Escribe cada barra **cerrada** al archivo. No decide nada. |
| `vivo.py` | La pantalla. Lee el archivo, arma un `Dia` y llama al motor. |
| `identidad.py` | Verifica que el camino vivo dé **exactamente** lo mismo que el backtest. |
| `prueba.py` | Lo mismo a nivel señales: mismas horas, mismos precios de entrada. |

## Instalación

1. Copiar `TTPFeed.cs` a `%AppData%\Trade The Pool\Scripts\Indicators\`
2. En la plataforma: un gráfico de **1 minuto** por cada papel de la watchlist,
   y a cada uno agregarle el indicador **TTPFeed**.
3. Los gráficos escriben todos al **mismo** archivo, con el símbolo en cada
   línea. Python los separa solo.
4. En una terminal:

```bash
python smallcaps/puente/vivo.py --riesgo 400 --piso 2
```

Se refresca cada 20 segundos. `--una-vez` imprime una foto y sale.

## Lo que la pantalla te dice

Por papel: si el día califica (y **por qué no**, si no), los tramos con precio
de entrada y stop, cuántas acciones, cuáles siguen abiertas y cuáles ya
saltaron, y abajo las dos cifras que deciden:

- **acciones en el pico del día** — eso es lo que hay que tener localizado.
  No es la suma de los tramos: el locate se reserva una vez por papel y por día
  para el máximo simultáneo. Confundirlos sobreestimaba el costo hasta 9×.
- **equity contra el límite diario** — cuando se acerca, el sistema deja de
  abrir tramos, igual que en el backtest.

## La regla que sostiene todo esto

`vivo.py` **no tiene lógica de estrategia**. Llama a `motor.jornada`, la misma
función que produjo cada número medido. Si en vivo decidiera con código propio,
los ocho meses de mediciones no significarían nada y no habría forma de
enterarse hasta perder plata.

Ya pasó una vez, acá: la primera versión de `evaluar` copiaba a mano la regla
de presupuesto y divergía — mostraba 14 tramos donde el motor abría menos, y
valuaba a mercado tramos que ya habían saltado por stop. Un tramo de más en la
pantalla es una orden de más en el mercado.

Por eso, **antes de operar, correr esto**:

```bash
python smallcaps/puente/identidad.py
```

Compara cinco días reales —incluido uno perdedor y el de 20 tramos— pasando los
datos por el mismo archivo JSONL que escribe la plataforma. Tienen que dar
idénticos a cuatro decimales. Si dice `HAY DIVERGENCIA`, no se opera.

## Lo que todavía no está verificado

**El lado C# no se compiló nunca dentro de la plataforma.** Todo lo probado es
el lado Python, alimentado con un archivo escrito por nosotros con el formato
que el indicador debería producir. En la primera compilación pueden fallar dos
cosas concretas:

- el cast `HistoryDataSeries as BarData` para leer el volumen
- el acceso `HistoricalRequest.Instrument.DayInfo.PrevClose` para el cierre previo

Si `pc` sale en 0, la expansión y el gap salen mal y **el día no va a
calificar**: se nota enseguida porque la pantalla descarta todo. El volumen no
lo usa la configuración candidata (`min_ratio_vol=0`), así que si falla el cast
no rompe nada.

## Configuración, congelada

Las constantes arriba de `vivo.py` son la variante medida y no se tocan sin
volver a medir:

```
reclaim · expansión ≥0% · entradas desde las 10:00 · precio ≥$2
stop 45% · hasta 40 tramos · sostener al cierre
```
