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
