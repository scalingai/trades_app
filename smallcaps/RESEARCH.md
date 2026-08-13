# Small Caps — Investigación previa al diseño

> **Estado:** research, sin código todavía. Fecha: 2026-08-13.
> **Objetivo:** decidir dónde está el edge cuantificable en small caps y qué se puede construir
> con datos verificables, antes de escribir una línea del sistema.

---

## 0. La tesis central

**En small caps el edge cuantitativo NO está en el análisis técnico. Está en la oferta de papel.**

Una small cap que corre 300% no cae por una divergencia de RSI. Cae porque **la empresa vende
acciones contra la fuerza**. El ATM que se activa, el shelf que quedó efectivo la semana pasada,
los warrants que se vuelven ejercibles arriba de $3 — eso es un shock de oferta real, con
mecanismo causal, no una correlación encontrada a fuerza de backtest.

Y acá está lo interesante: **esa capa es objetivamente medible y es gratis**. Está en los filings
de la SEC. Lo que enseñan Capelo / EduTrades es correcto pero se detiene en "fijate el
DilutionTracker antes de entrar" — un chequeo manual, cualitativo, no loggeado. Convertir eso en
un feature vector numérico y persistido es exactamente el hueco donde entra lo cuantitativo.

El análisis técnico en este dominio se queda como **capa de timing**, no como capa de edge.

---

## 1. Qué encontré, verificado

### 1.1 SEC EDGAR — gratis, sin API key, casi en tiempo real ✅ *(probado hoy)*

Corrí los tres endpoints. Los tres andan, sin key, solo exigen header `User-Agent` con contacto.
Rate limit: 10 req/s.

| Endpoint | Qué da | Latencia medida |
|---|---|---|
| `browse-edgar?action=getcurrent&type=424B5&output=atom` | Feed Atom de **los últimos filings de un form type**, todo el mercado | **~11 min** (filed 09:21 → visible 09:32) |
| `efts.sec.gov/LATEST/search-index?q="..."&forms=424B5` | Full-text search sobre todo el corpus desde 2001. Devuelve JSON con CIK, fecha, **y el ticker** (`"HeartSciences Inc. (HSCS, HSCSW)"`) | segundos |
| `data.sec.gov/submissions/CIK##########.json` | Historial completo de filings de una empresa | segundos |

Los ~11 minutos son el delay de diseminación de la SEC, no algo que se pueda comprar más barato —
los servicios pagos que "adelantan" el filing lo hacen scrapeando el sistema de aceptación, terreno
gris. Para un sistema **semi-automático** (vos apretás el gatillo) 11 min es perfectamente usable:
el uso real no es "reaccionar al filing en 200ms", es **saber antes de la apertura qué capacidad de
dilución tiene registrada cada ticker de la watchlist**.

### 1.2 Los forms que importan (y qué significa cada uno)

| Form | Qué es | Señal |
|---|---|---|
| **S-3** | Shelf registration — registra capacidad para vender después | Munición cargada. Sirve solo si `public float > $75M`, si no aplica el *baby shelf rule* (límite ⅓ del float en 12 meses) |
| **EFFECT** | Aviso de que el registro quedó efectivo | El shelf **ya se puede disparar** — antes no |
| **424B5** | Prospectus supplement — **se está pricing una oferta AHORA** | Evento de dilución en curso |
| **S-1** | Registro para las que no califican S-3 (la mayoría de micro caps) | |
| **424B3** | Registro de reventa — típicamente convertibles tóxicos | Overhang crónico |
| **8-K item 1.01 / 3.02** | Venta no registrada, PIPE, nota convertible | Dilución que no pasó por registro |
| **DEF 14A / 8-K** | Reverse split, aumento de autorizadas | Diluidor serial |
| **10-Q (cover XBRL)** | `dei:EntityCommonStockSharesOutstanding` | **Serie histórica real de share count** |

De esos se derivan features numéricos duros: *capacidad de shelf sin usar en USD*, *tasa de dilución
histórica trimestre a trimestre*, *warrants vivos arriba del precio actual*, *cash runway* (caja del
10-Q ÷ burn) → probabilidad de que la empresa **tenga** que levantar plata.

### 1.3 Float — el dato más sucio del stack ⚠️

Float es el denominador de casi todo (rotación de float, % de float en volumen) y es donde los
proveedores mienten más. FMP lo tiene y tiene free tier; Polygon da `share_class_shares_outstanding`
(que **no es float** — no descuenta insiders/restringidas). Ninguno es confiable en micro caps sin
validar.

**Consecuencia de diseño:** el float no se toma de un proveedor y listo. Se reconstruye del cover
page del 10-Q vía XBRL y se lo compara contra el proveedor. Cuando discrepan, se marca
`data_quality: 'conflict'` en vez de elegir uno en silencio.

### 1.4 Halts, SSR, short interest — gratis

- **Halts LULD**: `nasdaqtrader.com` publica RSS de trade halts, gratis. Las small caps halten 5–10
  veces en un día de squeeze; el patrón de halts es un feature en sí mismo.
- **SSR (Rule 201)**: se dispara con −10% vs cierre previo y dura ese día + el siguiente. Derivable
  del cierre previo, no hace falta comprarlo.
- **Short interest**: FINRA lo publica bimensual, gratis. Con lag, pero sirve.
- **FTDs (fails to deliver)**: SEC, gratis, quincenal.

### 1.5 Data de precio

Los proveedores que usa el mundo small cap en 2026: **Polygon.io, Alpaca, Finnhub, Tradier,
Databento**. El punto crítico: **feed SIP vs feed IEX**. IEX es ~2–4% del volumen de una small cap —
para escanear pre-market con feed IEX estás mirando un ruido. Hay que pagar SIP.

Polygon: ~$29/mo delayed 15min, ~$199/mo realtime. **Polygon mantiene tickers deslistados**, que
es la diferencia entre un backtest honesto y uno de fantasía (§3.1).

### 1.6 Dilución como producto pago

DilutionTracker ($74/mo) es el estándar de facto de la industria retail. Aparecieron competidores
con **API** (DilutionWatch ~$80/mo, Dilutracker) que exponen un `DilutionScore` programático.

**Mi lectura sobre comprar vs construir:** construir la ingesta determinística de EDGAR, y usar
DilutionTracker los primeros meses como *ground truth para validar tu parser*. Razón: el score de
ellos es una caja negra que no podés backtestear ni recalibrar; el dataset propio sí, y **el dataset
es el activo**. Pero validar contra ellos te ahorra descubrir en producción que tu parser de
warrants está roto.

### 1.7 Ejecución — dónde se rompe la automatización

| Broker | API | Locates para short |
|---|---|---|
| **DAS Trader (CMD API)** | Sí — incluso **automatiza el pedido de locates** | Depende del broker atrás |
| **Cobra Trading** | Vía DAS | Múltiples fuentes, rápido |
| **CenterPoint** | Vía DAS | Mesa propia de lending, la mejor en micro caps |
| **IBKR** | API buena, Python nativo | **Débil en hard-to-borrow** |
| **Alpaca** | API excelente | Prácticamente no sirve para shortear micro caps |

Hecho incómodo: **el lado short de small caps es el que tiene el edge más citado y el que peor se
automatiza**, porque depende de conseguir locate, que es un recurso escaso, con precio, y que no
existe en ningún backtest.

---

## 2. La arquitectura que propongo

Es el mismo esqueleto que ya funciona en la consola pre-market de ES/MES — Capa 0 determinística,
Capa 1 interpretativa, dataset append-only, vistas point-in-time. Reusar eso es la decisión de
diseño más barata que hay acá.

```
CAPA 0 — INGESTA DETERMINÍSTICA (sin LLM)          CAPA 1 — INTERPRETACIÓN (LLM)
┌──────────────────────────────────┐               ┌──────────────────────────────┐
│ scanner: gappers del día         │               │ clasifica el FILING:         │
│   gap%, RVOL, vol premarket,     │               │   ¿ATM? ¿registered direct?  │
│   precio, float, rotación        │               │   ¿tamaño vs market cap?     │
│                                  │               │                              │
│ estructura de papel (EDGAR):     │──────────────▶│ clasifica el CATALIZADOR:    │
│   shelf sin usar (USD)           │   snapshot    │   sustantivo / promocional / │
│   warrants vivos + strike        │               │   reciclado / sin noticia    │
│   tasa dilución histórica        │               │                              │
│   cash runway (10-Q)             │               │ emite: tesis + etiqueta      │
│   historial reverse splits       │               │ NUNCA emite un número        │
│                                  │               └──────────────┬───────────────┘
│ tape: halts, SSR, short int, FTD │                              │
└──────────────────────────────────┘                              ▼
                                                   ┌──────────────────────────────┐
                                                   │ DATASET append-only          │
                                                   │ 1 fila por candidato/día     │
                                                   │ features + etiquetas + qué   │
                                                   │ pasó después (outcome)       │
                                                   └──────────────┬───────────────┘
                                                                  ▼
                                                   ┌──────────────────────────────┐
                                                   │ backtest / calibración       │
                                                   │ point-in-time, sin look-ahead│
                                                   └──────────────────────────────┘
```

**La frontera dura (la misma regla que ya tenés):** el LLM nunca produce un número. Float, gap%,
capacidad de shelf en dólares, runway — todo determinístico y con `source` + `verified`. El LLM
aporta **clasificación de texto** (leer un 424B5 de 80 páginas y decir "ATM de $50M, precio de
mercado, con capacidad remanente de $31M") — que es genuinamente difícil por regex y natural para
un modelo. Y como emite una *etiqueta*, esa etiqueta se loggea y después se valida contra el
resultado.

**Por qué esto importa:** el snapshot crudo de Capa 0 se guarda verbatim. Si en tres meses cambiás
los pesos del scoring, **re-puntuás la historia entera sin re-fetchear y sin re-correr el agente**.

---

## 3. Los límites — lo que va a salir mal si no se cuida

Esto es la parte que ningún curso cuenta y la que decide si el sistema sirve.

### 3.1 Sesgo de supervivencia — el asesino silencioso
La mayoría de las small caps que corrieron en 2023 hoy no cotizan: deslistadas, reverse-splitteadas,
quebradas. Si backtesteás con un proveedor que borra deslistados (yfinance, casi todos los free
tiers), **tu universo histórico son solo las sobrevivientes** y cualquier estrategia long va a
brillar. Polygon mantiene deslistados; es requisito, no preferencia.

### 3.2 Look-ahead en los datos de estructura — el trap específico de este dominio
El float de hoy **no es** el float de hace 6 meses. Ese es literalmente el punto del sistema.
Si backtesteás usando el share count actual, tenés look-ahead metido en el feature central.
Hay que reconstruir la serie de share count desde los filings históricos, con la fecha de
*conocimiento público*, no la fecha del período reportado.

### 3.3 Slippage domina el resultado
Un backtest sobre una acción de $2 con spread de 3 centavos que haltea 4 veces no te dice nada si
asumís fills al mid. En este dominio los costos de ejecución **no son un ajuste al margen, son la
variable principal**. Cualquier resultado sin modelo de slippage explícito y pesimista es ficción.

### 3.4 Locate inexistente
Un backtest que shortea cada parabólica asume borrow que no existía. Es la brecha más grande entre
backtest y realidad en small caps.

### 3.5 Tamaño de muestra
Setups reales: quizás 1–3 por día. Un año ≈ 400–600 observaciones. **Eso no alcanza para un modelo
de muchos features** — se sobreajusta solo. Disciplina: pocos features, elegidos por mecanismo
causal, no por búsqueda.

---

## 4. Plan por fases

| Fase | Qué | Entregable | Riesgo de plata |
|---|---|---|---|
| **0** | Ingesta EDGAR + parser de estructura de papel sobre un universo chico (~200 tickers) | Serie histórica de share count, shelfs, warrants por ticker | $0 |
| **1** | Scanner pre-market + consola de small caps (espejo de la de ES/MES): gappers del día con su ficha de dilución | Consola local, veredicto por ticker | ~$30/mo data |
| **2** | Loggear **todo candidato** con feature vector completo + outcome a T+1/T+5 | El dataset. Sin operar. | igual |
| **3** | Backtest / calibración: recién acá se contestan las hipótesis con datos propios | Umbrales reales en vez de placeholders | igual |
| **4** | Ejecución semi-automática (DAS CMD API / IBKR) | Sistema completo | broker + realtime |

**Fase 2 es la fase importante y es la que todos se saltean.** Sin ella los umbrales son opinión.
Es la misma lógica que ya venís aplicando: las reglas son placeholders, el dato es el valor.

---

## 4.bis. Resultado de Etapa A — capacidad vs comportamiento

Perfilamos **el universo completo**: 1.459 micro caps con public float < $75M,
definido por `dei:EntityPublicFloat` vía el frames API (8 requests, gratis).
Corre con `python profile_universe.py --sample 0`.

| Feature | % del universo que lo cumple | Veredicto |
|---|---|---|
| runway < 12 meses | 73% | no discrimina |
| runway < 6 meses | **58%** | no discrimina |
| shelf efectivo | **54%** | moneda al aire |
| ≥3 8-K dilutivos 12m | 44% | débil |
| ≥1 pricing en 12m | 42% | débil |
| dilución 12m > 25% | 41% | moderado |
| **dilución 12m > 100%** | **22%** | discrimina |
| **≥1 reverse split 12m** | **17%** | discrimina |

Distribución de dilución 12m: mediana **10,4%**, p75 **73%**, p90 **366%**.
Brutalmente sesgada — la empresa mediana diluye modestamente, la cola diluye 3,6×
por año.

**Los dos features útiles NO son redundantes.** `dil>100%` × `revsplit` da
Jaccard 0,23 con lift 2,04: se solapan el doble de lo esperable por azar pero
siguen siendo mayormente empresas distintas. Solo el **6,9% (101 empresas)**
cumple ambos — ese sí es un filtro angosto.

En cambio `shelf_efectivo` × `pricing≥1` da Jaccard **0,53**: además de no
discriminar, son casi la misma medición.

**Corrección a §1 de este documento.** Le dimos peso a la *capacidad* de diluir
(shelf efectivo, runway corto) y los datos no lo sostienen: casi todas las micro
caps tienen ambas cosas. Es una descripción del asset class, no un criterio de
selección.

**El reencuadre:** medir **comportamiento**, no capacidad. Shelf y runway dicen
lo que la empresa *podría* hacer; dilución realizada y reverse splits dicen lo
que *ya hizo repetidamente*. Preferencia revelada sobre declarada. La tesis de
§0 sigue en pie — el eje es la dilución — pero el feature útil es el track
record, no el permiso.

**Cobertura:** 21% del universo no tiene runway calculable (falta cash flow
operativo en XBRL). Tenerlo en cuenta antes de apoyar decisiones en ese campo.

**Calidad del dato de origen.** El perfilado destapó que la SEC contiene valores
corruptos: KPTI reportó `17.050.876.000` acciones en un 10-Q y `18.343.968` en
el siguiente — factor 1000 de más en el tag XBRL. Sin filtro, el retorno al
valor correcto se leía como un reverse split 1:929, que dividía toda la historia
y daba **+243.032%** de dilución.

Afecta al **1,3% del universo (19 empresas)**. Los agregados casi no se mueven
(p90 pasó de 367,4 a 366,3), pero las filas individuales sí — y como la tesis
vive en la cola, las filas envenenadas eran justo las de la cola. Habría llegado
al backtest disfrazado de señal.

El filtro distingue basura de patología real por la **forma**: el error es un
pico que revierte (>50× ambos vecinos), la dilución real es monótona. FOXO pasó
de 45M → 526M → 3.732M acciones y se preserva intacta en +128.208%: es una
espiral de muerte genuina, no un error.

Aparte, **111 empresas (7,6%)** tienen reverse splits inferidos de ratio >100.
No se asumen erróneos — una micro cap que hizo 1:200 es un diluidor serial
extremo, o sea la población objetivo. Quedan marcadas para verificar.

---

## 4.ter. Etapa C — primer contacto con precio (2 años, mercado completo)

Backfill: **7.694.236 barras**, 493 días, **32.582 tickers distintos**, 1.022 MB,
101 min con el tier free. Contra ~15.000 tickers en un día cualquiera: más del
doble de rotación en 2 años. El sesgo de supervivencia en su forma más cruda.

Detector: 87.943 eventos con umbrales permisivos (186/día). Apretando a
RVOL≥10, $1M, movimiento≥20%, precio $0,30-$20 quedan **35,6/día** — dentro del
rango 20-40 que se había estimado.

### El resultado que importa

Short en la apertura, cubrir al cierre, sobre los 1.658 gaps >+50% con volumen
> $1M:

| métrica | valor |
|---|---|
| gana el short | **65%** de las veces |
| mediana | **−8,64%** |
| media (todo) | −1,01% |
| media sin el 1% superior | −3,87% |
| media sin el 5% superior | −8,74% |
| peor caso individual | **+530,7%** |

**Win rate alto y expectativa cerca de cero.** Casi todo el resultado agregado
lo define el 1-5% de casos extremos. Es el perfil de juntar monedas delante de
una aplanadora — y confirma con datos la advertencia del arranque: probabilidad
≠ expectativa.

**Esto NO es una estrategia y no está descontado de costos.** Falta borrow,
slippage (grande en estos nombres) y disponibilidad de locate — los tres restan.
Shortear todo gapper grande no es un edge. La tesis es que los features de
dilución seleccionan el subconjunto donde SÍ lo es. Eso sigue sin testear.

### Un error de medición dio vuelta el signo

El volumen en dólares se calculaba como `volumen × cierre`. El cierre es un
proxy y se desvía justo en los eventos que corren hacia el cierre: MCLE operó
**$0,34M reales** (VWAP) y aparecía como $1,57M — 4,65×. Con el umbral de $1M
tendría que haber quedado afuera, y era el outlier de +6075% que dominaba la
media.

| | con cierre | con VWAP |
|---|---|---|
| media | **+2,76%** | **−1,01%** |

Un solo evento mal medido invertía el signo del agregado. En agregado el sesgo
es chico (−4,1% en gaps >50%, y en la dirección contraria a la esperada), pero
en la cola es 2-4×. Y la cola es donde vive todo.

---

## 4.quater. PRIMER RESULTADO — la dilución previa separa las distribuciones

Cruce completo: 65.697 eventos con ficha de papel point-in-time (75%), 46 min.
43.886 con dilución 12m calculable.

**Gaps >+20% con volumen >$1M (n=2.421), retorno intradía apertura→cierre:**

| dilución 12m previa | n | mediana | media | % que baja |
|---|---|---|---|---|
| **>100%** | 704 | **−9,62%** | −5,14% | 69% |
| 25-100% | 512 | −5,69% | −0,91% | 60% |
| **<25%** | 1.205 | **−1,00%** | +2,43% | 53% |

Gradiente **monotónico en tres baldes**, en la dirección que predice el
mecanismo. Mucho más difícil de obtener por azar que un corte binario.

**La hipótesis estaba pre-registrada** en §5 de este documento antes de tener
un solo dato de precio. No se encontró revolviendo.

### El control (que la hipótesis pre-registrada exigía)

El confusor era real: las diluidoras cotizan a $1,85 de mediana contra $4,63
las limpias, y gapean más (40,7% vs 31,2%). Dentro de bandas de precio × gap:

| banda | dil >100% | dil <25% | Δ |
|---|---|---|---|
| $0,30-3 · gap 20-50% | −9,61% (n=287) | −2,41% (n=310) | −7,20pp |
| $0,30-3 · gap >50% | −15,64% (n=182) | −7,46% (n=141) | −8,18pp |
| $3-10 · gap 20-50% | −2,46% (n=99) | +1,63% (n=278) | −4,09pp |
| $3-10 · gap >50% | −13,17% (n=80) | −4,90% (n=129) | −8,27pp |
| $10-50 · gap 20-50% | +2,42% (n=35) | +0,31% (n=291) | **+2,11pp** |

**4 de 5 bandas mantienen la separación.** La dilución aporta información
propia, no es un proxy del precio. La banda de $10-50 se da vuelta, pero con
n=35 es ruido; se registra igual.

### Corrección a §4.bis

`shelf_efectivo` fue descartado en Etapa A por no discriminar (54% del
universo). Acá **sí separa** (−6,05% vs −1,41% de mediana). No es contradicción:
no sirve para elegir *qué empresas son micro caps*, sí discrimina *qué pasa el
día del evento*. Son preguntas distintas.

### Lo que NO está probado

- Sin costos: ni borrow, ni locate, ni slippage. En una acción de $2 el
  slippage solo puede comerse varios de esos puntos.
- Sin MAE (máxima excursión adversa) — lo que decide la supervivencia bajo un
  límite de pérdida diaria.
- n de 80-180 en las bandas. La mediana es estable, la media no.
- 5 comparaciones, 1 se da vuelta. Esperable por azar.
- Sin fuera de muestra: se usaron los 2 años completos.

**No es una estrategia. Es un feature con información demostrada.**

---

## 5. Hipótesis a testear (no conclusiones)

Nada de esto está probado — son las preguntas que el dataset de Fase 2 tiene que poder contestar:

1. ¿Los gappers **con** capacidad de shelf sin usar se comportan distinto a los que no tienen, a
   igualdad de gap% y RVOL?
2. ¿Un EFFECT reciente (shelf recién habilitado) cambia la distribución de retornos intradía?
3. ¿La rotación de float predice algo más allá de lo que ya predice el RVOL, o es el mismo dato
   con otro nombre?
4. ¿El patrón de halts LULD tiene información, o es solo un proxy de volatilidad realizada?
5. ¿La clasificación LLM del catalizador (sustantivo vs promocional) separa las distribuciones?
   — esta es la que valida si la Capa 1 aporta algo o es decoración cara.

---

## Fuentes

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) · [EDGAR full-text search](https://efts.sec.gov/LATEST/search-index) · [Trade Halt RSS — Nasdaq Trader](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS)
- [Dilution, ATM, PIPE & Reverse Splits: Small-Cap Guide — Merlin Trader](https://www.merlintrader.com/dilution-atm-pipe-guide/) · [DilutionTracker](https://dilutiontracker.com/) · [DilutionWatch API](https://dilutionwatch.com/api) · [Dilutracker API](https://www.dilutracker.com/dilution-tracker-api)
- [Best Stock Market Data APIs for Small-Cap Traders 2026 — BullAlert](https://bullalert.ai/blog/best-stock-market-data-apis-2026/) · [FMP All Shares Float API](https://site.financialmodelingprep.com/developer/docs/stable/all-shares-float) · [edgartools (Python, MIT)](https://github.com/dgunning/edgartools)
- [Automating short locates — Elite Trader](https://www.elitetrader.com/et/threads/automating-getting-short-locates.381255/) · [Best Brokers for Short Selling 2026 — Alphanume](https://www.alphanume.com/blog/best-brokers-for-short-selling-strategies) · [IBKR API](https://www.interactivebrokers.com/en/trading/ib-api.php)
- [Capelo Trading](https://capelotrading.com/) · [2025: un año de trading real en Small Caps](https://capelotrading.substack.com/p/2025-un-ano-de-trading-real-en-small)
- [NASDAQ SSR Tracker](https://ssrlist.com/) · [Price gap anomaly in the US stock market](https://www.researchgate.net/publication/339811620_Price_gap_anomaly_in_the_US_stock_market_The_whole_story)
