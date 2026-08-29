# Visor de eventos

Gráfico de velas de 1 minuto sobre los días que ya están descargados, con la
ficha de dilución y el estado de cada señal al lado. Local, sin internet.

```bash
python visor/server.py
```

Abre `http://127.0.0.1:8765` solo. Escucha en **127.0.0.1**, no en `0.0.0.0`:
no se ve desde la red.

## Qué muestra

| | |
|---|---|
| zona sombreada | pre-market (04:00–09:30 ET) |
| línea ámbar | VWAP acumulado desde las 04:00 — el que define front / back |
| raya gris | cierre del día previo |
| raya violeta | máximo de pre-market — el denominador de la "expansión" |
| flecha verde ↑ / roja ↓ | estado a las 10:00 y 12:00 (front / back) |
| círculos | minutos con volumen o rango ≥5× la mediana de las 30 barras previas |

La barra de arriba trae la expansión pre-market, el volumen contra el día
previo, RVOL, volumen en dólares, y de la ficha de EDGAR: dilución 12m, reverse
splits, runway y si el shelf estaba efectivo **a esa fecha** (point-in-time, sin
look-ahead).

## Atajos

`j` / `k` siguiente y anterior de la lista · `v` anomalías · `w` VWAP ·
`m` marcas de estado.

## La lista

Por defecto muestra **solo los días de evento** — los 1.114 que se sortearon y
sobre los que se mide. Destildando "solo eventos" aparecen también los ~2.900
días vecinos: cada descarga trae el día del evento y los 4 siguientes, así que
el día 2 de una parabólica está bajado aunque nadie lo haya sorteado.

**Los vecinos sirven para MIRAR, no para medir.** Meterlos en una muestra la
agranda con días que no salieron del sorteo, y ahí se pierde la propiedad que
hace válido todo lo demás. Se distinguen con un `·` al lado de la fecha.

El filtro "vol ≥ 3× el día previo" saca los reverse splits disfrazados de
expansión (§4.sexies de RESEARCH.md).

## Bajar un día que no está

El campo de abajo a la izquierda baja los minutos de un `(ticker, fecha)`
cualquiera: **una llamada** a la API, y trae el día pedido más los 4 siguientes.
Con el tier free son 5 por minuto.

## Por qué así

- **lightweight-charts de TradingView** (Apache 2.0, 160 KB) vendorizado en
  `static/`. Velas, volumen, zoom y crosshair ya resueltos; escribir eso a mano
  eran dos días para llegar a algo peor.
- **Sin build step y sin framework.** Son ~300 líneas de JS: `npm` acá sería más
  infraestructura que producto.
- **Servidor de stdlib.** Los datos viven en dos SQLite de cientos de MB;
  servirlos por HTTP evita duplicarlos a JSON y deja pedir un día a la vez.
- El índice se cachea en `visor_indice.json` dentro del directorio de datos.
  Rehacerlo: `python visor/server.py --reindexar` (tarda ~2 min).

## Detalle de implementación que se ve raro

`server.ts()` le suma el offset de Nueva York al epoch antes de mandarlo.
lightweight-charts dibuja el eje en UTC y no acepta zona horaria; sumarle el
offset hace que las 09:30 ET se dibujen como 09:30. Es el precio de no arrastrar
una librería de fechas al front.
