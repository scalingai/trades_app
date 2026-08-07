# trades_app

Registro de trades de small caps (Streamlit) + descarga de datos históricos de
precio para hacer backtesting local.

```bash
pip install -r requirements.txt
streamlit run trades_app.py     # la app de registro de trades
```

## Descargar datos históricos

`descargar_datos.py` baja velas OHLCV a CSV. No hace falta API key ni cuenta:
usa los endpoints públicos del exchange.

```bash
# Histórico diario completo de BTC (2017 → hoy)
python descargar_datos.py --intervalo 1d

# Velas de 1 hora desde 2020
python descargar_datos.py --intervalo 1h --desde 2020-01-01

# Velas de 1 minuto de un rango concreto
python descargar_datos.py --intervalo 1m --desde 2025-01-01 --hasta 2025-06-30

# Añadir sólo las velas nuevas a un archivo ya descargado
python descargar_datos.py --intervalo 1h --actualizar

# Otro par
python descargar_datos.py --par ETHUSDT --intervalo 4h
```

Los archivos se guardan en `data/` como `PAR_INTERVALO_FUENTE.csv`, con este
esquema (una fila por vela, hora UTC):

```
timestamp,open,high,low,close,volume
2017-08-17 04:00:00+00:00,4261.48,4313.62,4261.32,4308.83,47.181009
```

Para cargarlo ya listo para analizar, con índice temporal UTC:

```python
from descargar_datos import cargar_datos

df = cargar_datos("data/BTCUSDT_1h_binance.csv")
df["sma20"] = df["close"].rolling(20).mean()
```

En el repo va incluido `data/BTCUSDT_1d_binance.csv` (histórico diario completo)
para poder empezar sin descargar nada. El resto de archivos se ignoran en git
porque pesan mucho: el histórico de 1 minuto de año y medio son ~57 MB.

### Opciones

| Opción | Para qué sirve |
|---|---|
| `--fuente` | `binance` (por defecto) o `coinbase` |
| `--par` | Par a bajar. Por defecto `BTCUSDT` en Binance, `BTC-USD` en Coinbase |
| `--intervalo` | `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `6h`, `8h`, `12h`, `1d`, `3d`, `1w` |
| `--desde` / `--hasta` | Rango en UTC, formato `YYYY-MM-DD` |
| `--actualizar` | Continúa un archivo existente en vez de rebajarlo entero |
| `--formato` | `csv` (por defecto) o `parquet` |
| `--salida` | Ruta de salida propia |
| `--sin-alinear` | Deja los timestamps tal cual los publica el exchange |

### Fuentes y cobertura

| Fuente | Par por defecto | Desde | Intervalos |
|---|---|---|---|
| Binance | `BTCUSDT` | 2017-08-17 | todos |
| Coinbase | `BTC-USD` | 2015 | `1m`, `5m`, `15m`, `1h`, `6h`, `1d` |

Binance es la fuente principal porque tiene el histórico más largo y completo.
Para rangos amplios el script no pide las velas de mil en mil por el API: se
descarga los ZIP mensuales de `data.binance.vision`, que es muchísimo más
rápido (año y medio de velas de 1 minuto, 840.000 filas, en un par de minutos).
El tramo final que aún no está archivado se completa por el API REST.

Coinbase está como respaldo: `api.binance.com` responde **HTTP 451** en varias
regiones, EE.UU. entre ellas. Si te pasa, el script cambia solo al mirror
`data-api.binance.vision`, que sirve los mismos datos sin restricción
geográfica; y si aun así falla, tienes `--fuente coinbase`.

### Sobre la calidad de los datos

Al terminar, el script revisa la serie y avisa de lo que encuentra. Merece la
pena leerlo, porque estas cosas afectan al backtest:

- **Huecos.** El histórico horario de BTC tiene 28 huecos (~127 velas) por
  paradas de mantenimiento del exchange. El mayor es de 33 horas, del 8-9 de
  febrero de 2018. No es un fallo de la descarga: esas velas no existen.
- **Velas desalineadas.** Tras esa parada de 2018, Binance reanudó publicando
  43 velas horarias desfasadas 28m14s respecto a la hora en punto. Un índice
  irregular rompe `resample()` y las medias móviles, así que por defecto se
  cuadran a su casilla (`--sin-alinear` lo desactiva).
- **Última vela incompleta.** La vela más reciente casi siempre está a medio
  formar, así que su cierre no es un cierre real. Descártala al backtestear.
  `--actualizar` la reemplaza por su versión cerrada cuando la vuelves a lanzar.
- **Microsegundos.** Los archivos de Binance posteriores a 2025-01-01 traen los
  timestamps en microsegundos en vez de milisegundos; el script lo detecta y lo
  corrige.

## Backtesting

`backtestear.py` es la puerta de entrada; `backtest/` es el paquete importable.

```bash
# Ejecutar una estrategia concreta
python backtestear.py simple --datos data/BTCUSDT_4h_binance.csv \
    --estrategia cruce_medias -p rapida=20 -p lenta=100 -p tipo=ema

# Barrer parámetros con separación in-sample / out-of-sample
python backtestear.py grid --datos data/BTCUSDT_4h_binance.csv \
    --estrategia rsi_reversion --procesos 4

# Walk-forward: reoptimiza por ventanas y mide sólo lo que no vio el ajuste
python backtestear.py walkforward --datos data/BTCUSDT_4h_binance.csv \
    --estrategia cruce_medias --dias-is 365 --dias-oos 90

# Matriz: repite el walk-forward con varios tamaños de ventana
python backtestear.py matriz --datos data/BTCUSDT_4h_binance.csv --estrategia cruce_medias

# Robustez ante variaciones aleatorias
python backtestear.py montecarlo --datos data/BTCUSDT_4h_binance.csv \
    --estrategia cruce_medias -p rapida=20 -p lenta=100

# Construir estrategias desde cero por programación genética
python backtestear.py generar --datos data/BTCUSDT_4h_binance.csv \
    --poblacion 120 --generaciones 25 --guardar banco.json
```

Como módulo:

```python
import backtest as bt
from backtest import estrategias, metricas
from backtest.indicadores import Contexto

datos = bt.cargar("data/BTCUSDT_4h_binance.csv")
estrategia = estrategias.obtener("cruce_medias")
senales = estrategia.senales(Contexto(datos), rapida=20, lenta=100, tipo="ema")
resultado = bt.ejecutar(datos, senales, bt.Config())
print(metricas.formatear(metricas.calcular(resultado, datos.intervalo)))
```

### Piezas

| Módulo | Qué hace |
|---|---|
| `motor` | Ejecuta señales con comisiones, slippage, stop y objetivo |
| `metricas` | Retorno, CAGR, drawdown, Sharpe, Sortino, Return/DD, estabilidad |
| `indicadores` | SMA, EMA, WMA, RSI, ATR, Bollinger, MACD, estocástico, CCI, ROC, Donchian |
| `estrategias` | Cinco estrategias clásicas parametrizables |
| `optimizar` | Barrido de parámetros con separación in/out-of-sample |
| `walkforward` | Walk-forward analysis y matriz de ventanas |
| `montecarlo` | Seis pruebas de robustez |
| `generador` | Programación genética: construye estrategias desde cero |

### Convenciones de ejecución

Son las que separan un backtest honesto de uno que se engaña, y están fijadas
con tests en `tests/test_motor.py`:

- La señal se calcula con el cierre de la barra `t` y se ejecuta a la apertura
  de `t+1`. Nunca se opera con información de la barra que generó la señal.
- Stop y objetivo se comprueban con el máximo y el mínimo de cada barra.
- Si en la misma barra se tocan stop y objetivo, se asume el stop: no se sabe
  cuál se tocó antes, así que se toma el peor caso.
- Si la vela abre saltándose el stop, se ejecuta al precio real de apertura.
- Comisión y slippage se cobran en los dos lados (por defecto 0,04 % + 0,02 %,
  que es taker de Binance).
- En corto el resultado se mide sobre el nominal vendido, así que una caída del
  100 % gana el 100 % y no más.
- La curva de capital se marca a mercado dentro de cada operación, para que el
  drawdown recoja lo que pasó mientras la posición estaba abierta.

### El generador, y por qué el filtro importa más que el generador

El generador hace lo mismo que el Builder de StrategyQuant: combina bloques
(indicadores, comparaciones, operadores lógicos, gestión) en genomas
aleatorios, se queda con los que mejor puntúan, los cruza, los muta y repite.
Los bloques están tipados por escala, así que nunca compara un RSI con una
media móvil, y las constantes sólo aparecen donde significan algo. Todo genoma
lleva stop obligatorio: sin él la evolución descubre que no cerrar nunca las
posiciones perdedoras mejora casi cualquier métrica sobre histórico.

Genera candidatos, y generar candidatos es la parte fácil. Lo que decide si
algo vale es el filtro: la evolución sólo ve el tramo in-sample, el
out-of-sample se mira una vez al final, y encima pasa por Monte Carlo. Que no
sobreviva ninguna es el resultado más frecuente, y es información.

### Calibrar contra ruido antes de creerse nada

```bash
python validar_pipeline.py --series 10
```

Lanza el pipeline completo sobre series de precio puramente aleatorias, donde
por construcción no hay nada que encontrar. Todo lo que sobreviva ahí es un
falso positivo.

Con la configuración por defecto, el resultado medido sobre 10 series fue:

```
  series con al menos un superviviente: 5/10 (50%)
  supervivientes totales: 13
```

Conviene leerlo despacio. **La mitad de las series aleatorias producen una
estrategia que pasa el out-of-sample y el Monte Carlo.** Sobrevivir al filtro
es condición necesaria, no suficiente: si sobre bitcoin sobrevive una
estrategia, hay que compararlo contra ese 50 %, no contra cero.

Para bajar la tasa base: exigir más operaciones (`--min-operaciones`),
endurecer el drawdown admitido (`--max-drawdown`), y validar además en otro
timeframe y otro par. Este número es la referencia que ninguna plataforma
comercial te da y que cambia por completo cómo se interpretan sus resultados.

### Qué esperar de los datos que hay

- **El diario tiene 3.278 velas.** Da para estrategias de uno o dos parámetros.
  Con cuatro ya se está ajustando ruido.
- **En 5m y 1m mandan los costes.** Con 0,06 % por lado y unos cientos de
  operaciones, los costes se comen casi cualquier edge. Un backtest sin costes
  realistas miente siempre a favor.
- **Cuidado con el número de combinaciones.** Un barrido de 1.900 combinaciones
  encuentra siempre una que brilla. En la prueba sobre 4h, la ganadora
  in-sample (CAGR 104 %) conservó un −16 % de su fitness fuera de muestra.

### Tests

```bash
python -m pytest tests/ -q      # 52 pruebas
```

Cubren las convenciones de ejecución del motor, que los indicadores no miran
al futuro, que la partición in/out-of-sample no solapa, que barajar en Monte
Carlo no altera el retorno final, y que cambiar sólo el tramo out-of-sample no
altera lo que produce la evolución (es decir, que la validación no está
contaminada).
