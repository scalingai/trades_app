# Cripto — perpetuos de Binance

> **Estado al 2026-08-13.** Investigación con datos propios, sin operar.
> La tesis, las fuentes verificadas y las hipótesis pre-registradas están en
> [RESEARCH.md](RESEARCH.md). Las correcciones hechas al implementar, en §6.bis.

Traslado de la tesis de oferta de [`../smallcaps/`](../smallcaps/) a un dominio
que sí se puede operar con capital chico: sin locate, con corto nativo y con el
funding a favor del corto.

## Qué hay construido

| script | qué hace | costo |
|---|---|---|
| `verificar_fuentes.py` | vuelve a preguntarle a cada fuente si sigue abierta | $0 |
| `archivo.py` | cliente del archivo público de Binance (único punto que toca la red) | $0 |
| `descargar.py` | universo + barras diarias de todos los perpetuos, vivos y muertos | $0 |
| `supply.py` | mapeo símbolo→moneda y serie de supply circulante | $0 |
| `eventos.py` | detector de volumen anómalo + retornos neutralizados | $0 |
| `test_correlacion.py` | cuántos eventos independientes hay de verdad | $0 |
| `contraste.py` | el contraste de H1-H5 con sus controles | $0 |

## Orden de ejecución

```bash
python verificar_fuentes.py     # ¿siguen abiertas las fuentes?
python descargar.py             # ~10 min, 832 símbolos
python supply.py --mapeo        # construye mapeo.csv
python supply.py --bajar        # lento: el free tier tira 429
python eventos.py               # detector + neutralización
python test_correlacion.py      # ANTES del contraste, a propósito
python contraste.py             # H1-H5
```

Todo es resumable: los meses ya bajados quedan en cache, los huecos quedan
marcados y las series de supply ya descargadas se saltean.

## Las tres decisiones que sostienen el resultado

**El universo incluye los muertos.** `data.binance.vision` conserva la historia
de los perpetuos deslistados — verificado sobre SRMUSDT, TOMOUSDT, FTTUSDT y
BTCSTUSDT. Los que Binance saca del listado no son una muestra al azar: son los
que peor terminaron. Un estudio que solo mire lo que cotiza hoy los pierde.

**La medida primaria es el percentil, no el retorno.** El día que BTC cae 8%
caen las 500. El percentil de cada token entre todos los perpetuos vivos ese día
elimina el factor común por construcción, sin estimar betas y sin agregar
parámetros. Medido: el agrupamiento baja de 1,38 en retorno crudo a 1,15 en
percentil. El retorno crudo se reporta al lado pero no decide.

**El horizonte no es el intradía.** El detector necesita el volumen del día
completo, así que recién al cierre de D se sabe que D fue un evento. Medir
apertura→cierre de D sería mirar el futuro. Lo operable es `cierre[D+1]` y
`cierre[D+5]`.

## Dónde vive cada cosa

| | Ruta | Se puede borrar |
|---|---|---|
| **Código** | este directorio | no — está en git |
| **`mapeo.csv`** | este directorio | **no** — se corrige a mano y se versiona |
| **Datos** | `CRIPTO_DATA_DIR`, default `~/Apps/algotrade-data/cripto/` | sí, se rebaja |

Los datos son reproducibles desde el archivo público: lo que se pierde al
borrarlos es tiempo, no información. `mapeo.csv` no — ese lleva trabajo manual
de desambiguación y es la pieza que evita meter la supply de la moneda
equivocada en las filas.

## El límite que condiciona todo

**CoinGecko free corta en 365 días.** Probado `days=max`, `/history` y
`market_chart/range` con ventana antigua: los tres devuelven 401.

Con lookback L, la ventana de eventos es `365 − L`. Con 12 meses el estudio
tendría cero eventos, así que **el lookback es de 90 días**. Es un primo del
feature que funcionó en acciones, no el mismo, y eso debilita el traslado.
Está anotado en RESEARCH.md §6.bis.1 y no se esconde.

## Lo que sigue

1. Correr el contraste completo cuando termine la descarga de supply
2. Doble snapshot de supply en 60-90 días para medir el restatement
3. Si H1 sobrevive: costos, MAE y punto de entrada — recién ahí se habla de
   operar
