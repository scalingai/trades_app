# Cripto — Investigación previa al escáner

> **Estado al 2026-08-13.** Research. No hay escáner todavía y no hay ningún
> resultado sobre precio.
> **Todas las fuentes de §1 están verificadas con llamadas reales**, con su
> código HTTP y su cobertura. Reproducible con `python verificar_fuentes.py`.
> Las hipótesis de §6 están pre-registradas: se escriben antes de mirar un solo
> retorno, igual que en `smallcaps/RESEARCH.md` §5.

---

## 0. Por qué cripto, y qué se traslada de small caps

### 0.1 La restricción que ordena la decisión

El trabajo de small caps produjo un resultado con evidencia: la dilución previa
separa las distribuciones de retorno intradía, con gradiente monotónico y
sobreviviendo al control por precio × gap. Pero **no es operable con el capital
disponible**, y las cuentas de fondeo que cubren small caps tienen condiciones
malas.

Una ventaja que no se puede operar no es una ventaja. Binance resuelve la
ejecución: capital mínimo bajo, API pública, corto nativo, 24/7, automatizable.

La pregunta de este documento no es *si cripto es el mejor dominio en
abstracto*. Es **si el mecanismo que funcionó en acciones se traslada a un
dominio que sí podemos operar**.

### 0.2 El mecanismo, enunciado de forma general

Lo que funcionó en small caps no es "dilución". Es una clase más amplia:

> **Oferta que entra al mercado por una razón mecánica, medible antes del
> evento, en un dato público que casi nadie estructura.**

La dilución es un caso. En un token el caso equivalente es la **liberación de
supply por vesting**: tokens que pasan de bloqueados a circulantes según un
cronograma, y que llegan al mercado por una razón que no tiene nada que ver con
el precio.

### 0.3 Lo que se traslada casi sin cambios

| Small caps | Cripto perpetuos |
|---|---|
| 1.459 micro caps con float < $75M | ~500 perpetuos USDT vivos (§2) |
| `dei:EntityCommonStockSharesOutstanding` vía XBRL | supply circulante = `market_cap / price` (§1.2) |
| dilución 12m previa | crecimiento de supply 12m previo |
| ATM / 424B5 disparándose | cliff de vesting liberándose |
| shelf sin usar (capacidad) | `total_supply − circulating` (capacidad) |
| reverse split | redenominación / token swap |
| detector de volumen anómalo | **el mismo, sin cambios de lógica** |
| Polygon conserva deslistados | **data.binance.vision también** ✅ §1.1 |
| control por precio × gap | control transversal intradía contra BTC (§4) |

`detect_events.py`, `join_structure.py`, `horizons.py` y `test_correlacion.py`
se re-apuntan a otra fuente de datos. No se reescriben.

### 0.4 Dos ventajas que en acciones no existían

**Desaparece el locate.** En `smallcaps/GESTION-RIESGO.md` §5 figura como riesgo
no validado y era el que podía invalidar todo: *"un short que no se puede abrir
tiene retorno cero, no negativo. El backtest los toma todos."* En un perpetuo se
abre corto contra el contrato. Ese riesgo no se mitiga: se elimina.

**El carry cambia de signo.** En small caps el corto paga borrow, que en un
nombre caliente es caro y variable. En un perpetuo con funding positivo —el
estado normal— **el corto cobra**. Sobre BTC se midió +0,006% por corte de 8h en
la rama de bitcoin, o sea ~6,6% anual a favor del corto. En altcoins suele ser
mayor y más volátil.

La misma tesis direccional (short contra oferta entrante) es estructuralmente
más barata de expresar acá que en acciones.

### 0.5 Lo que NO se traslada, y hay que decirlo primero

**El acto discrecional se vuelve mecánico y anunciado.** Una empresa que dispara
un ATM **decide** vender contra la fuerza: es un agente con información privada
actuando de forma oportunista, cualquier mañana, sin aviso. Un unlock de token
**está publicado con meses de anticipación y ocurre igual pase lo que pase**.

Un evento fechado y conocido por todos tiene muchas más chances de estar
descontado que uno discrecional y sorpresivo. **Esta es la objeción más fuerte
al traslado y hay que tenerla presente en cada resultado.**

La salida está en el propio hallazgo de small caps (`smallcaps/RESEARCH.md`
§4.bis): *"medir comportamiento, no capacidad. Preferencia revelada sobre
declarada."* La capacidad de diluir no discriminaba porque la tenía el 54-73%
del universo; el track record de dilución realizada sí.

**Consecuencia de diseño:** el feature principal NO es "hay un unlock el
martes" —eso es capacidad, con fecha— sino **crecimiento de supply realizado en
los 12 meses previos**, que es un régimen y no un evento. Es el feature que
funcionó en acciones y además es el que esquiva el problema de la fecha
anunciada.

---

## 1. Fuentes — verificado, no supuesto

Todo lo de esta sección se probó con llamadas reales el 2026-08-13. El código
HTTP está anotado. Lo que devolvió error también está anotado, porque saber qué
NO se puede consumir vale igual que lo contrario.

### 1.1 El archivo público de Binance — la columna vertebral

`https://data.binance.vision` sirve archivos históricos comprimidos, **sin API
key y sin cuenta**.

| Recurso | Ruta | HTTP | Cobertura | Granularidad |
|---|---|---|---|---|
| klines futuros UM | `data/futures/um/{monthly,daily}/klines/` | **200** | 2019-09+ según símbolo | 1m … 1M |
| funding rate | `data/futures/um/monthly/fundingRate/` | **200** | 2020-01+ | cada 8h |
| metrics (OI + ratios) | `data/futures/um/daily/metrics/` | **200** | **2020-09+** | **cada 5 min** |
| bookDepth | `data/futures/um/daily/bookDepth/` | **200** | 2023-01+ | intradía |
| klines contado | `data/spot/monthly/klines/` | **200** | 2017-08+ | 1m … 1M |

Contenido verificado de `metrics` (BTCUSDT, 2024-06-03: 289 filas, una cada
5 min):

```
create_time,symbol,sum_open_interest,sum_open_interest_value,
count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,
count_long_short_ratio,sum_taker_long_short_vol_ratio

2024-06-03 00:00:00,BTCUSDT,76155.768,5159979653.83,1.91673877,1.55748,1.9209649,0.624167
```

Eso es **open interest cada 5 minutos con historia desde 2020-09, gratis**, más
tres ratios de posicionamiento incluido el de los traders grandes. No hay
equivalente gratis de esto en acciones.

#### El hallazgo que decide la viabilidad: el archivo conserva los deslistados ✅

`smallcaps/RESEARCH.md` §3.1 llama al sesgo de supervivencia *"el asesino
silencioso"*, y en cripto es peor que en acciones: Binance deslista perpetuos
con frecuencia y los que mueren son justo los que más diluyeron.

Probado con cuatro perpetuos deslistados hace años, pidiendo datos de 2022-10:

| Símbolo | Estado | klines | funding |
|---|---|---|---|
| `SRMUSDT` | deslistado tras el colapso de FTX | **200** | **200** |
| `TOMOUSDT` | deslistado | **200** | — |
| `FTTUSDT` | deslistado | **200** | — |
| `BTCSTUSDT` | deslistado | **200** | — |

**El archivo no borra la historia de lo que murió.** Esto es lo mismo que hace
Polygon en acciones y es requisito, no preferencia. Sin esto no había estudio.

#### Enumeración del universo histórico completo

El bucket responde al listado estilo S3, lo que permite reconstruir **el
universo incluyendo lo deslistado** sin depender del endpoint REST:

```
https://s3-ap-northeast-1.amazonaws.com/data.binance.vision
    ?delimiter=/&prefix=data/futures/um/monthly/klines/
```

→ **HTTP 200, 986 símbolos, `IsTruncated=false`** (no hace falta paginar).
Los cuatro deslistados de arriba aparecen en la lista.

#### El bloqueo geográfico, y por qué no importa

`https://fapi.binance.com/fapi/v1/exchangeInfo` → **HTTP 451**. Es la
restricción por región ya documentada en la rama de bitcoin.

**No es un problema para el research**, porque todo lo histórico sale del
archivo y del mirror `data-api.binance.vision`. Sí lo es para el bot en vivo:
la ejecución necesita `fapi` accesible desde donde corra. **Verificar antes de
escribir una línea del bot**, no después.

### 1.2 La capa de supply — el cuello de botella real

Acá está el problema de este proyecto, y conviene verlo sin adornos.

#### Lo que sí funciona, gratis

CoinGecko `market_chart` con `days=365` → **HTTP 200**. Devuelve `prices`,
`market_caps` y `total_volumes` diarios. La supply circulante **no viene como
campo**, pero se deriva:

```
supply_circulante(t) = market_cap(t) / price(t)
```

**Verificado sobre ARB, 366 puntos diarios:**

```
2025-08-14   5.153.477.728 tokens
2025-11-13   5.501.810.377
2026-02-13   5.826.785.045
2026-05-15   6.150.718.438
2026-08-13   6.614.056.381        →  +28,3% en 12 meses

13 días con salto > 0,8%, en cadencia mensual:
  2025-08-19 +2,65%   2025-11-09 +0,87%   2026-01-17 +1,88%
  2025-09-20 +2,11%   2025-11-20 +2,04%   2026-02-28 +1,93%
  2025-10-18 +2,10%   2025-12-18 +1,78%
```

Ese escalonado mensual **es el calendario de vesting apareciendo solo en el
dato**, sin pedirle el cronograma a ningún proveedor. Es la misma serie que
salía de XBRL en acciones, por otra vía. Para referencia, +28,3% en 12m ubica a
ARB alrededor del percentil 60-70 de la distribución de dilución de micro caps
(mediana 10,4%, p75 73%).

#### Lo que NO funciona: todo lo que pase de 365 días

| Fuente | Llamada | HTTP | Lectura |
|---|---|---|---|
| CoinGecko | `market_chart?days=max` | **401** | free tier tope 365d |
| CoinGecko | `/coins/{id}/history?date=…` | **401** | snapshot por fecha, de pago |
| CoinPaprika | `/tickers/{id}/historical` | **402** | de pago |
| CryptoCompare | `/data/v2/histoday` | **401** | exige key |
| DefiLlama | `/emissions` | **402** | **los unlocks son de pago** |
| DefiLlama | `/emission/{proto}`, `/emissionsBreakdown` | **402** | ídem |

DefiLlama sigue teniendo endpoints libres (`/protocols`, `/v2/chains`,
`stablecoins` → 200), pero **la parte de emisiones y unlocks, que es justo la
que sirve, pasó a pago.**

**Conclusión honesta: la capa de supply cuesta plata o cuesta tiempo.** Es la
única pieza del stack que no es gratis, y es justo la que sostiene la tesis.

#### Las tres salidas, con su costo real

| Opción | Ventana | Costo | Qué se pierde |
|---|---|---|---|
| **A. Free tier, 365 días** | 12m | **$0** | un solo régimen, sin fuera de muestra temporal |
| **B. Tier pago con historia completa** | 3-4 años | mensualidad (**verificar precio**) | nada; es la buena |
| **C. Snapshot hacia adelante** | desde hoy | **$0** | no hay backtest, hay que esperar meses |

**Recomendación: arrancar con A y montar C en paralelo desde el día uno.** A
permite testear ya; C garantiza que dentro de seis meses haya una serie
point-in-time propia, no dependiente de que un proveedor no restatee. B solo si
A muestra señal — no se paga por datos para averiguar si vale la pena mirarlos.

Y hay un alineamiento afortunado: la ventana de 12m que permite el free tier es
**aproximadamente la misma ventana donde el universo de perpetuos es ancho**
(§2). Ir más atrás en el tiempo compraría historia a cambio de perder la mitad
del corte transversal, que es justo lo que hace funcionar el método.

#### El point-in-time es más débil que EDGAR, y no se puede arreglar del todo

La regla que sostiene todo el trabajo de acciones es `filed`, no `end`: la SEC
garantiza **cuándo se hizo público** cada dato, y por eso
`tests/test_structure.py::TestPointInTime` puede probar que no hay look-ahead.

**CoinGecko no da esa garantía.** Puede recalcular supply hacia atrás —por
corregir un error, por reclasificar tokens de tesorería— y no avisa. Una serie
descargada hoy no es necesariamente la que se habría visto entonces.

Mitigaciones, ninguna perfecta:

1. **Doble snapshot.** Guardar la serie hoy con fecha de descarga y volver a
   bajarla en 60-90 días. Comparar. Eso **mide** cuánto se mueve el pasado en
   vez de suponerlo. Es barato y hay que hacerlo desde el principio.
2. **Segunda fuente.** Contrastar contra CMC o Messari en una muestra. Donde
   discrepen, marcar `data_quality: 'conflict'` en vez de elegir en silencio —
   la misma regla de `smallcaps/RESEARCH.md` §1.3.
3. **Snapshot propio hacia adelante** (opción C). Es la única que da garantía
   real, y solo a futuro.

**Esto es una degradación respecto de acciones y queda anotada como tal.** No
invalida el estudio; obliga a que cualquier resultado lleve la advertencia.

#### El mapeo símbolo → moneda: una trampa concreta

CoinGecko lista **18.402 monedas**, y **el 16,1% de los símbolos está
duplicado**:

```
'pepe' → 20 ids   ['baby-pepe-5', 'based-pepe', 'el-sapo-pepe', 'next-gen-pepe', …]
'sol'  → 11 ids   ['binance-peg-sol', 'base-bridged-sol-base', …]
'arb'  →  2 ids   ['arbitrage-loop', 'arbitrum']
'op'   →  2 ids   ['one-path', 'optimism']
```

Resolver por símbolo a ciegas mete supply de una moneda distinta en las filas.
Y como sería un error silencioso que solo afecta a algunas filas, llegaría al
resultado disfrazado de ruido — exactamente el mismo tipo de error que el share
count corrupto de KPTI (`smallcaps/RESEARCH.md` §4.bis).

Peor: **15 perpetuos llevan prefijo multiplicador** (`1000PEPEUSDT`,
`1000BONKUSDT`, `1000000MOGUSDT`…). Ahí el precio del contrato es 1.000 o
1.000.000 veces el del token. Si eso se ignora, la supply derivada como
`mcap/price` sale mal por tres o seis órdenes de magnitud.

**Decisión de diseño:** el mapeo de los ~500 perpetuos vivos se resuelve **una
vez, a mano, y se versiona en el repo** como `mapeo.csv` con una columna
`multiplicador`. Son 500 filas, es trabajo acotado, y es la diferencia entre un
dataset limpio y uno envenenado. Nada de resolución automática por símbolo.

### 1.3 Lo que se descarta, y por qué

| Fuente | Por qué no |
|---|---|
| Liquidaciones históricas de Binance | La carpeta existe pero está **vacía**; discontinuado. Solo websocket en vivo. Sustituto: caída brusca de OI (ya documentado en `descargar_futuros.py`) |
| Glassnode / CryptoQuant (netflows a exchange) | De pago y caro. Sería el mejor análogo de "oferta entrante", pero no entra en el presupuesto de la Etapa 0 |
| Cronogramas de vesting (TokenUnlocks, CryptoRank) | De pago, y **look-ahead severo**: el cronograma publicado hoy no es el que se conocía hace 18 meses; se enmiendan. La supply realizada no tiene ese problema |
| Datos on-chain directos | Reconstruir supply desde el nodo es correcto y point-in-time real, pero es un proyecto en sí mismo |
| Sentimiento / social | Sin mecanismo causal. Fuera del criterio de §0.2 |

### 1.4 Resumen: qué cuesta cada capa

| Capa | Fuente | Costo | Cobertura verificada |
|---|---|---|---|
| Precio (perp + contado) | archivo Binance | **$0** | 2019-09+, incluye deslistados |
| Funding | archivo Binance | **$0** | 2020-01+ |
| Open interest + ratios | archivo Binance | **$0** | 2020-09+, cada 5 min |
| Profundidad de libro | archivo Binance | **$0** | 2023-01+ |
| Universo histórico | listado S3 | **$0** | 986 símbolos, sin truncar |
| Edad de listado | derivada del archivo | **$0** | completa |
| **Supply / dilución** | **CoinGecko** | **$0 (365d) / pago (completa)** | **el cuello de botella** |

---

## 2. El universo — cuántos, y desde cuándo

Del listado del archivo, 986 símbolos alguna vez existieron:

| Denominación | Símbolos | Nota |
|---|---|---|
| USDT | **832** | el universo de trabajo |
| USDC | 40 | mayormente duplicados de pares USDT |
| BUSD | 41 | **todos muertos** — BUSD fue discontinuada |
| con prefijo `1000x` | 15 | trampa de mapeo (§1.2) |

### Cuántos estaban vivos en cada momento

Muestreo aleatorio de 60 símbolos USDT, verificando existencia de klines
mensuales (semilla fija, reproducible):

| Fecha | De la muestra | Estimado sobre 832 |
|---|---|---|
| 2022-06 | 9/60 | **~125** |
| 2023-06 | 11/60 | **~153** |
| 2024-06 | 14/60 | **~194** |
| 2025-06 | 37/60 | **~513** |

Dos lecturas, las dos importantes:

**El sesgo de supervivencia es enorme y ahora es medible.** 832 perpetuos
existieron alguna vez y ~513 estaban vivos a mediados de 2025. Un estudio que
solo mire los que cotizan hoy pierde cientos de instrumentos, y los que murieron
no murieron al azar. El archivo permite no cometer ese error.

**El corte transversal se angosta rápido hacia atrás.** Ir a 2022 deja ~125
instrumentos: menos de una cuarta parte del ancho actual, y el método depende
del ancho.

**Ventana de estudio elegida: los últimos 12 meses**, donde conviven el universo
más ancho (~500) y la supply gratis (365 días). Que las dos restricciones caigan
en la misma ventana es suerte, pero conviene aprovecharla.

**Costo:** 12 meses es **un solo régimen de mercado**. No hay fuera de muestra
temporal de verdad. Anotado en §7 y en los criterios de refutación de §6.

---

## 3. Los escenarios fundamentales — qué busca el escáner

Tres capas, igual que en acciones: el evento dice *cuándo mirar*, el feature
estructural dice *qué distingue*, y el control dice *contra qué se compara*.

### Capa 1 — El detector de evento (cuándo dispara)

Traslado directo de `smallcaps/detect_events.py`. Un símbolo-día entra como
evento si:

| Condición | Umbral inicial | Nota |
|---|---|---|
| RVOL | ≥ 5 | volumen contra su propia mediana de 20 días |
| volumen en dólares | ≥ $2M | **por VWAP, no por cierre** — ver abajo |
| rango del día | ≥ 15% | |
| antigüedad | ≥ 30 días desde listado | evita el caos de los primeros días |

**El volumen se calcula por VWAP, no por cierre.** No es un detalle: en acciones
usar el cierre invirtió el signo del agregado (media +2,76% → −1,01%), porque un
solo evento mal medido dominaba la cola. El bug ya está corregido en el código
que se reusa; no hay que reintroducirlo.

Los umbrales son **placeholders a calibrar contra la frecuencia observada**, no
verdades. El objetivo es una tasa de eventos que deje muestra suficiente sin
inundar de ruido.

### Capa 2 — Los features estructurales (qué distingue)

Ordenados por cercanía al mecanismo que ya funcionó:

| # | Feature | Fuente | Costo | Análogo en acciones |
|---|---|---|---|---|
| **S1** | **crecimiento de supply 12m previo** | CoinGecko | $0 (365d) | **dilución 12m — el que funcionó** |
| S2 | `(total − circulante) / circulante` | CoinGecko | $0 | shelf sin usar (capacidad) |
| S3 | funding acumulado 7d / 30d y su extremo | Binance | $0 | — (no tiene análogo) |
| S4 | subida de OI previa, y caída brusca | Binance | $0 | — (rastro de liquidación) |
| S5 | **días desde el listado** | **derivado del archivo** | **$0** | antigüedad del papel |
| S6 | profundidad de libro a ±1% / mcap | Binance | $0 | float / liquidez real |

**S1 es la hipótesis principal.** Es el traslado literal de lo único que
demostró información en acciones. Todo lo demás es secundario y se mide para
control, no porque se espere que funcione.

**S5 merece atención: es gratis y nadie lo mira.** La fecha de listado sale del
propio archivo (primer mes con klines). Un token listado hace 90 días está, casi
por definición, en la parte empinada de su curva de vesting: los cliffs de
equipo e inversores caen en los primeros 12-24 meses. **Es un proxy de presión
de supply futura que no cuesta nada y no requiere CoinGecko.** Si S5 replica lo
que hace S1, tenemos el feature gratis y el problema del cuello de botella se
alivia mucho.

**S3 y S4 son los que todo el mundo mira.** El funding rate está en el dashboard
de cualquier mesa de cripto y Coinglass lo publica gratis. Precisamente por eso
se miden como **control**, no como esperanza: si S3 no separa nada, es evidencia
de que el mercado descuenta lo que es fácil de ver, y refuerza el argumento de
que la ventaja está en lo tedioso (S1) y no en lo visible.

### Capa 3 — El control (contra qué se compara) → §4

---

## 4. El arrastre de BTC — cómo se neutraliza

Esta es la sección que decide si el estudio mide algo o mide beta.

### 4.1 El problema, dimensionado

En acciones, `test_correlacion.py` midió que tomar 4 trades el mismo día
equivale a ~3,5 independientes: agrupamiento real pero chico, y por eso el
dimensionamiento no se movió.

**En altcoins va a ser mucho peor.** El día que BTC cae 8%, caen las 500. Un
dataset de 3.000 eventos puede valer, en información, como 300.

Las dos formas de arruinar el estudio con esto:

1. **Falso positivo.** Si los tokens que más diluyeron son además los de beta
   más alta —plausible: más nuevos, más chicos, más especulativos— entonces
   "diluyen más y caen más" sería **beta a BTC con otro nombre**, y aparecería
   con gradiente monotónico perfecto.
2. **Intervalos de confianza mentirosos.** Con n nominal de 3.000 y n efectivo
   de 300, cualquier test da significativo. El error estándar estaría subestimado
   por un factor de ~3.

### 4.2 La solución: ranking transversal dentro del día

De las tres opciones, la recomendada:

| Método | Cómo | Problema |
|---|---|---|
| Restar el retorno de BTC | `r_alt − r_btc` | asume beta = 1 para todos; es falso |
| Residuo por beta | `r_alt − β·r_btc`, β rodante | hay que **estimar** β: ruidoso, inestable, y un parámetro más |
| **Rango transversal intradía** | **percentil de `r_alt` entre todos los alts vivos ESE día** | **ninguno de los dos** |

**El rango transversal es el que hay que usar como medida primaria.** Razones:

- **Elimina el factor común por construcción**, sin estimar nada. Si BTC arrastra
  todo, arrastra también al percentil 50, y el percentil de cada token queda
  limpio.
- **No introduce parámetros.** Coherente con la disciplina de `analisis_ventanas`
  y del generador: cada parámetro es una oportunidad de sobreajuste.
- **Es robusto a la cola**, que en cripto es peor que en acciones. En small caps
  un solo evento mal medido daba vuelta la media; un rango no se puede
  desestabilizar así.

**Especificación concreta.** Para cada evento, el resultado se registra como:

```
rango_dia = percentil del retorno del token entre TODOS los perps vivos ese día
z_dia     = (r_token − mediana_del_dia) / MAD_del_dia
r_bruto   = el retorno crudo, guardado para referencia
```

**La medida primaria es `rango_dia`.** `r_bruto` se reporta siempre al lado, para
que se vea cuánto del resultado era mercado y cuánto era el token — pero no es lo
que decide.

### 4.3 El n efectivo hay que medirlo, no suponerlo

`test_correlacion.py` se re-apunta **antes** de creerle a cualquier resultado, no
después. Mide la varianza de tomar k eventos el mismo día contra lo que predice
la independencia. El factor que salga corrige los intervalos de confianza de
todo lo demás.

**Criterio duro: ningún resultado se reporta con su n nominal.** Si el estudio
tiene 3.000 eventos y el factor de agrupamiento es 3, se reporta n efectivo
1.000 y los intervalos se ensanchan en consecuencia.

### 4.4 El control adicional que exige la hipótesis

En acciones el confusor era el precio: las diluidoras cotizaban a $1,85 contra
$4,63 las limpias, y el efecto tuvo que demostrarse **dentro** de bandas de
precio × gap (4 de 5 bandas lo mantuvieron).

El confusor equivalente acá es el **market cap** y la **antigüedad**. Los tokens
que más diluyen son más chicos y más nuevos. El contraste tiene que correrse
**dentro de bandas de market cap × antigüedad**, no solo en agregado. Si el
gradiente solo existe en agregado y desaparece dentro de las bandas, lo que se
midió fue tamaño, no dilución.

---

## 5. Especificación del escáner v1

### Entrada

- universo: los ~832 símbolos USDT del archivo, filtrados a los vivos en la
  ventana, con `mapeo.csv` resuelto a mano
- klines diarias y de 1h por símbolo (archivo Binance)
- funding y metrics por símbolo (archivo Binance)
- supply diaria por token (CoinGecko, 365d)

### Salida: una fila por evento

```
simbolo, fecha, coingecko_id, multiplicador
  # capa 1 — evento
  rvol, vol_usd_vwap, rango_pct, gap_pct, precio
  # capa 2 — estructura, todo point-in-time
  supply_growth_12m, supply_growth_3m, capacidad_no_circulante
  dias_desde_listado, funding_acum_7d, funding_acum_30d
  oi_cambio_previo_7d, profundidad_1pct_sobre_mcap
  # capa 3 — resultado, neutralizado
  rango_dia_t1, rango_dia_t5, z_dia_t1, r_bruto_t1, r_bruto_t5, mae_t1
  # calidad
  supply_fuente, supply_fecha_descarga, data_quality
```

`data_quality` marca conflicto entre fuentes en vez de elegir en silencio.
`supply_fecha_descarga` existe para poder medir el restatement de §1.2.

### Reuso desde `smallcaps/`

| Módulo nuevo | De dónde sale | Cambio |
|---|---|---|
| `detectar_eventos.py` | `detect_events.py` | fuente de datos |
| `cruzar_supply.py` | `join_structure.py` | EDGAR → CoinGecko |
| `horizontes.py` | `horizons.py` | agregar rango transversal |
| `test_correlacion.py` | idéntico | ninguno |
| `descargar.py` | `descargar_futuros.py` (rama bitcoin) | multi-símbolo |
| `barreras.py` | rama bitcoin | ninguno — tamiz agnóstico |

---

## 6. Hipótesis pre-registradas

Escritas antes de mirar un solo retorno. Lo que las hace valer es que los
criterios de refutación están fijados **ahora**.

**H1 — principal.** El crecimiento de supply en los 12 meses previos separa las
distribuciones de retorno post-evento, en el sentido de que **más supply nueva →
peor desempeño relativo**. Tres baldes por percentil (alto / medio / bajo), medido
en `rango_dia`.

**H2 — capacidad, control negativo esperado.** La capacidad no circulante
(`total − circulante`) **no** discrimina, por la misma razón que el shelf
efectivo no discriminaba en acciones: la tiene casi todo el universo.

**H3 — antigüedad.** Los tokens listados hace menos de ~12 meses tienen peor
desempeño relativo post-evento, por estar en la parte empinada de su vesting.
**Si H3 replica H1, el feature gratis reemplaza al de pago.**

**H4 — lo visible, control.** El funding acumulado **no** aporta información
más allá de lo que aporta S1. Si aporta, es un hallazgo genuino y hay que
revisar el supuesto de §3 sobre lo visible estando descontado.

**H5 — control negativo obligatorio.** Un feature aleatorio, con la misma
distribución que S1 pero barajado entre símbolos, **no** produce gradiente. Si lo
produce, el pipeline está roto y todo lo demás se descarta.

### Criterios de refutación — fijados antes de medir

Para que H1 se considere confirmada tiene que cumplir **las cuatro**:

1. **Monotonía** en los tres baldes, no solo diferencia entre extremos.
2. **Sobrevivir la neutralización**: el gradiente existe en `rango_dia`, no solo
   en `r_bruto`.
3. **Sobrevivir el control por bandas** de market cap × antigüedad, en al menos
   **3 de 4** bandas con n ≥ 100.
4. **Sobrevivir el n efectivo**: significativa con los intervalos corregidos por
   el factor de agrupamiento de §4.3.

**Si cumple 2 o menos, se descarta y se escribe por qué.** Un resultado negativo
documentado vale: en small caps, descartar la capacidad de diluir es lo que
llevó a medir comportamiento, que es lo que funcionó.

Sin fuera de muestra temporal (ventana de 12m, §2), el sustituto es **partir el
universo en dos mitades por símbolo** y exigir que el efecto aparezca en las
dos. Es más débil que partir por tiempo. Queda anotado como tal.

---

## 6.bis. Correcciones al implementar — antes de ver ningún resultado

Tres cosas cambiaron al construir el pipeline. Se anotan acá, con fecha, para
que quede claro que son decisiones previas al contraste y no ajustes hechos
después de ver un número que no gustaba.

### 6.bis.1 El lookback baja de 12 meses a 90 días — obligado por el dato

Se probó una tercera vía además de las dos de §1.2: `market_chart/range` con
ventana antigua. También 401, con el mensaje explícito
*"Public API users are limited to querying historical data within the past 365
days"*.

Eso rompe el plan original, y la aritmética es simple: con 365 días de supply y
lookback **L**, los eventos utilizables van de `hoy − 365 + L` a `hoy`. O sea
que la ventana de eventos es `365 − L`.

| L | Ventana de eventos |
|---|---|
| 365 días (12m) | **0 días — inútil** |
| 180 días | 185 días |
| **90 días** | **275 días** ← elegido |

**Con lookback de 12 meses el estudio tendría cero eventos.** Se usa 90 días,
que es un trimestre y se corresponde con el `dilution_3m` que ya existía en el
trabajo de acciones. No es el feature que funcionó allá —aquel era de 12m— y eso
**debilita el traslado**: se está midiendo un primo del feature, no el mismo.
Queda como limitación explícita.

### 6.bis.2 El mapeo tenía dos errores del tipo que envenena en silencio

Los dos aparecieron recién al correr el mapeo sobre los 832 símbolos:

**Multiplicadores mal parseados.** `1000000BOBUSDT` quedaba como ticker
`000BOB` y no matcheaba con nada, porque el código sacaba de a cuatro
caracteres y `1000000` tiene siete. Binance usa además la convención `1M`
(`1MBABYDOGEUSDT`). Corregido con expresión regular; verificado sobre los cinco
casos.

**"El de mayor mcap gana" falla cuando el token real no está en el ranking
descargado.** `MEMEUSDT` resolvía a `memetoon` (rank 10.274) y `AAPLUSDT` a
`apple-robinhood-tokenized-stock`. Un match a una moneda de rank muy profundo
es sospechoso por construcción: Binance no lista perpetuos de la moneda número
10.000.

**Y el universo contiene acciones tokenizadas** (AAPL, ADBE, AAOI), que no son
tokens con dinámica de supply y no pertenecen al estudio.

Solución: marca `dudoso` para todo match sin ranking o con rank >2000, y esos
quedan **fuera del análisis primario** en vez de elegirse en silencio. Resultado
sobre 832 perpetuos: **642 resueltos, 262 dudosos excluidos, 570 usables.** Los
79 ambiguos que sí entran se testean aparte con `--incluir-ambiguos` como
análisis de sensibilidad.

### 6.bis.3 El agrupamiento es mucho menor de lo previsto — y la neutralización funciona

§4.1 anticipaba que el n efectivo podía ser 3-5× peor que el nominal. **Medido,
no lo es.** Sobre 9.807 eventos en 405 días (24,2 por día):

| Medida | Factor de agrupamiento | n efectivo |
|---|---|---|
| retorno crudo `r_t1` | **1,38** (sube a 1,88 con k=5-6) | 7.092 |
| percentil `pct_t1` | **1,15** | 8.555 |

Dos lecturas. La primera es que la advertencia estaba exagerada: el
agrupamiento existe pero es moderado, no catastrófico. La segunda es que **la
diferencia entre las dos filas es la neutralización funcionando**: el percentil
transversal reduce el agrupamiento de forma medible, que es exactamente lo que
§4.2 predecía que haría.

Los intervalos de confianza se ensanchan ×1,07 sobre el percentil. Se aplica
igual, aunque sea chico.

---

## 7. Los límites — lo que puede salir mal

**7.1 Un solo régimen.** 12 meses de cripto es un régimen. Todo lo que se
encuentre podría ser propio de este mercado y no del mecanismo. Es la limitación
más seria y solo se resuelve pagando historia o esperando.

**7.2 Point-in-time degradado.** §1.2. CoinGecko puede restatear el pasado. Se
mide con doble snapshot; no se elimina.

**7.3 n efectivo.** §4.3. Puede ser 3-5× peor que el nominal. Si el factor sale
muy alto, la conclusión honesta puede ser que 12 meses de altcoins **no alcanzan
para decidir nada**, y eso hay que estar dispuesto a escribirlo.

**7.4 El evento anunciado.** §0.5. Los unlocks son públicos y fechados. Si el
mercado los descuenta —que es lo que debería pasar en un mercado razonablemente
eficiente— H1 falla y el traslado no funciona. Es el riesgo conceptual central.

**7.5 Cripto es lo más mirado del planeta.** A diferencia de un 10-Q de una micro
cap, que no lee nadie, acá hay cientos de equipos con más datos y más velocidad.
El argumento a favor sigue siendo que estructurar supply cruzando 500 tokens es
tedioso y poco glamoroso — pero es un argumento más débil que en acciones.

**7.6 Costos, todavía sin modelar.** Nada de este documento incluye comisión,
slippage ni funding. La rama de bitcoin ya dejó la lección: *"el peaje decide, no
la señal"*, y ahí el costo mataba resultados que se veían bien en bruto. En
perpetuos el peaje es bajo (0,02% maker / 0,05% taker) pero **no es cero, y el
slippage en una altcoin ilíquida no es el de BTC**. S6 (profundidad de libro)
existe para poder estimarlo por token en vez de asumir un número plano.

**7.7 El generador ya avisó.** `validar_pipeline.py` midió que **el 50% de las
series aleatorias produce un superviviente** que pasa out-of-sample y Monte
Carlo. Cualquier cosa que aparezca acá se compara contra esa tasa base, no
contra cero. H5 es la versión de ese control para este estudio.

---

## 8. Plan por etapas

| Etapa | Qué | Entregable | Costo |
|---|---|---|---|
| **0** | Universo + `mapeo.csv` a mano + descarga de klines/funding/metrics | dataset de precio y posicionamiento, con deslistados | **$0** |
| **1** | Supply 365d de CoinGecko + doble snapshot montado | serie de dilución por token, con fecha de descarga | **$0** |
| **2** | Detector de eventos re-apuntado + calibración de umbrales | tabla de eventos, con su frecuencia | **$0** |
| **3** | `test_correlacion` → **factor de n efectivo** | el número que corrige todo lo demás | **$0** |
| **4** | Cruce + contraste de H1-H5 con los controles de §6 | confirmación o refutación documentada | **$0** |
| **5** | Solo si H1 sobrevive: costos, MAE, punto de entrada | recién acá se habla de operar | **$0** |

**La Etapa 3 va antes que la 4 a propósito.** Saber el n efectivo antes de mirar
resultados evita el sesgo de aceptar un factor generoso porque el resultado
gustó.

**Nada de esto requiere pagar datos.** La decisión de pagar historia completa se
toma en la Etapa 5, y solo si hay algo que valga la pena extender.

---

## Fuentes

**Verificadas el 2026-08-13** — reproducible con `python verificar_fuentes.py`:

- [Binance public data archive](https://data.binance.vision) · [repositorio y esquemas](https://github.com/binance/binance-public-data) · listado S3: `https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/`
- [CoinGecko API v3](https://docs.coingecko.com/reference/introduction) — `market_chart` (365d, gratis), `coins/list` (18.402 monedas)
- [DefiLlama API](https://defillama.com/docs/api) — `/protocols`, `/v2/chains`, `stablecoins` libres; `/emissions` de pago

**Consultadas y descartadas:** CoinPaprika (`/historical` → 402), CryptoCompare
(`histoday` → 401), TokenUnlocks y CryptoRank (de pago + look-ahead de
cronograma), Glassnode y CryptoQuant (netflows, de pago).

**Trabajo previo de este repo, del que sale casi todo el método:**
`smallcaps/RESEARCH.md` (tesis de oferta, controles, la corrección de capacidad
vs comportamiento) · `smallcaps/GESTION-RIESGO.md` (dimensionamiento por
simulación) · rama `claude/bitcoin-historical-data-backtest-0pabgi`
(`validar_pipeline.py` y la tasa base del 50%, `barreras.py`, el peaje).
