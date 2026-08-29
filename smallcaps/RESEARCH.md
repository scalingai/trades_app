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

## 4.quinquies. Tercera ronda — qué LADO, y qué cuesta acotar la pérdida

Dos preguntas de Agus, las dos con respuesta medida. Scripts: `test_lados.py`,
`test_salidas.py`, `test_frontlong.py`. Muestra: 775 días de evento con minutos
y volumen ≥ 3× el del día previo (el filtro anti-reverse-split de §4.sexies).

### La expansión pre-market decide de qué lado estás

`expansión = máximo pre-market ÷ cierre previo`. Es observable a las 09:30 y no
usa nada del futuro. Long a las 10:00 con stop del 15%, neto de costos:

| expansión pre-market | n | mediana | media | gana | te stopean |
|---|---|---|---|---|---|
| < +25% | 173 | **+15,5%** | +24,4% | 69% | 23% |
| +25 a +50% | 55 | +3,1% | +7,6% | 55% | 38% |
| +50 a +100% | 69 | −12,2% | +2,1% | 38% | 49% |
| +100 a +200% | 31 | **−15,7%** | −8,3% | 19% | **77%** |
| > +200% | 28 | −15,3% | −3,5% | 25% | 68% |

Gradiente monotónico y **de signo invertido respecto del short**: el mismo
balde de expansión extrema donde el long muere 3 de cada 4 veces es donde el
short rinde. No son dos estrategias, es una variable que decide la dirección.

Replica en los dos períodos dentro de cada balde: `<25%` da +18,9% en P1 y
+8,6% en P2; `>100%` da −15,7% y −15,3%. La tabla total NO replicaba
(P1 +6,8% / P2 −2,1%) y eso era un efecto de mezcla: P2 tenía más días de
expansión grande.

### Front side vs back side: el riesgo es la mitad, y es del lado del long

Estado definido por el VWAP acumulado —cero parámetros, el nivel lo pone el
flujo—. MAE = cuánto se movió en contra antes del cierre:

| entrada | lado | n | long mediana | MAE p50 | MAE p90 | short mediana | MAE p50 | MAE p90 |
|---|---|---|---|---|---|---|---|---|
| 10:00 | front | 356 | **+5,7%** | 10,1% | 37,4% | −5,4% | 28,9% | 96,3% |
| 10:00 | back | 419 | −1,2% | 13,2% | 35,4% | +1,2% | 21,1% | 80,4% |
| 12:00 | front | 289 | +2,0% | 7,5% | 27,5% | −1,9% | 17,8% | 68,9% |
| 12:00 | back | 486 | −0,9% | 9,2% | 27,3% | +0,9% | 9,5% | 41,2% |

**La intuición de Agus se confirma, y por dos vías distintas.** El front-long
tiene 4× la mediana del back-short y la mitad del MAE p90 (37% vs 80%). Y no
necesita locate: es la primera cosa medida en este proyecto que se puede
ejecutar sin depender de un recurso escaso.

Con una excepción que importa: en los días de expansión > +100% el front side
se da vuelta —long mediana −13,8%, MAE p50 23,6%—. Ahí el "front side" no es
tendencia, es la punta de una parabólica.

### Salir por anomalía durante el trade: acorta la cola y se lleva el edge

Regla: salir cuando el volumen (o el rango) de un minuto supera k× la **mediana
de las 30 barras previas** y esa barra va en contra. Mediana y no promedio: con
promedio un pico previo sube la vara y esconde el siguiente.

Back-short 12:00, n=484:

| salida | mediana | media | p10 | peor | MAE p90 | minutos |
|---|---|---|---|---|---|---|
| sostener al cierre | +1,05% | **+7,77%** | −17,9% | −56,8% | 41,2% | 240 |
| stop fijo 15% | −1,86% | +6,14% | −13,0% | −13,0% | 17,5% | 240 |
| volumen anómalo k=3 | −1,02% | +0,67% | **−6,6%** | **−22,0%** | **8,7%** | **23** |
| volumen k=5 o VWAP | −1,59% | +1,36% | −7,8% | −25,4% | 10,9% | 34 |

**Funciona para lo que se pidió y no sirve para operar.** La cola izquierda se
corta a la mitad y el MAE p90 baja de 41% a 9% — la detección es real. Pero la
media cae de +7,8% a +0,7%: la regla saca del trade a los 23 minutos, y ya
sabemos desde `test_scalping.py` que a esa escala temporal la señal no predice.

**Tercera vez que aparece el mismo patrón.** Apilar filtros mejoró el trade y
empeoró el año; acortar el hold multiplicó los trades y destruyó el edge; ahora
acotar la pérdida acorta la cola y se lleva la media. En los tres casos el
instinto de controlar más empeora el resultado.

Y para el long el resultado es más duro todavía: el **stop fijo del 15% domina
a la salida por anomalía** en todo. Stop fijo: media +13,7%, p10 −15,0%.
Volumen k=3: media +1,2%, p10 −14,2%. Misma protección de cola, una décima
parte de la media. La anomalía no aporta nada que el stop no dé más barato.

Único caso donde el stop fijo mejora la media además de la cola: el
front-long. Sostener da +11,1% de media con peor caso −94,9%; con stop 15% da
**+12,4% con peor caso −18,7%**. Es la primera regla de riesgo medida en este
proyecto que no se paga.

### El sesgo de esta muestra, dicho con precisión

Los 1.500 eventos se sortearon de días con **rango DIARIO > 40%**, que a las
10:00 no se conoce. La consecuencia no es pareja entre baldes, y conviene
tenerlo claro antes de creerle a la tabla:

- En los días de **expansión grande**, el día calificó por el gap de
  pre-market, que **sí** es observable a las 09:30. El sesgo es menor.
- En los días de **expansión chica** —el balde donde el front-long da +15,5%—
  el día calificó porque se movió durante la sesión. Condicionar a "arriba del
  VWAP a las 10:00" dentro de una muestra pre-seleccionada por rango grande es
  casi garantizar que agarraste el runner. **Ese balde es el más contaminado y
  es justo el que mejor da.**

Traducción: el gradiente por expansión y la comparación front/back valen; el
+15,5% del balde bajo, no. Se arregla resorteando una muestra seleccionada solo
por lo observable a las 09:30.

## 4.sexies. Reverse splits: el mismo error del §4.bis, ahora en el precio

`prev_close` viene sin ajustar (decisión correcta: el ajuste del proveedor usa
la vista de HOY y mete futuro en el pasado). La consecuencia es que **un
reverse split se lee como una expansión pre-market gigante**. CETX 2024-10-03
aparece con +5.049% y operó el **57% del volumen del día previo**: no compró
nadie, cambió el denominador.

Son 11 de los 107 casos con expansión > +200%. El filtro es
`volumen del día ≥ 3× el del día previo` — un pump de verdad multiplica el
volumen por 63 en la mediana. Con el filtro el resultado no se cae, mejora.

**Y el mismo problema tiene una versión más grave, en el detector.** El RVOL de
`detect_events.py` se calcula en ACCIONES. Un reverse split 1:45 divide el
volumen por 45, así que el día del pump posterior da RVOL ≈ 1 y **no entra como
evento**. ELPW 2026-08-11 —reverse split el 8/10, +75% de expansión, $47M
operados— no está en los 87.943 eventos por eso. Toda la familia
"reverse split → float chico → pump → derrumbe" está sistemáticamente afuera
del dataset. Se arregla con RVOL en dólares.

> **CORREGIDO en §4.terdecies C.** Medido: la población que el RVOL en dólares
> destapa **sube** (+1,94% de mediana) y la que solo ve el de acciones **baja**
> (−1,96%). El punto ciego existe pero está a favor. Que arreglarlo iba a traer
> setups era una conclusión mía, y era falsa.

## 4.septies. Ratios cortos en short — el ratio no es la palanca

Pedido de Agus: **solo short, ratios 1:1 o menos, con el stop atado a la
volatilidad del día**. Se construyó `momentos.py`: **50.330 momentos** (uno cada
5 minutos de sesión, sobre 775 días), cada uno con su estado observable y el
resultado del short en **múltiplos de riesgo**, no en porcentaje.

El stop es `m × rango típico del minuto` (mediana de las últimas 30 barras). El
rango típico mediano de la muestra es **1,38%**, así que m=5 es un stop del ~7%.

### La aritmética que decide antes que cualquier tabla

| ratio | hay que acertar |
|---|---|
| 1:0,25 | **80%** |
| 1:0,5 | **67%** |
| 1:1 | 50% |
| 1:2 | 33% |
| 1:3 | 25% |

Un ratio corto no es más seguro: **es un préstamo**. Cambia riesgo de ruina por
exigencia de puntería, y el umbral sube más rápido de lo que baja el ratio.

### Lo que dicen los datos: la esperanza SUBE con el ratio, no baja

Celda más robusta por cantidad de días — precio ≥ $3, volatilidad > 2,5%/min,
debajo del VWAP, stop 8× (n=2.678 momentos en **289 días**), neto de 4 centavos
por acción:

| ratio | acierta | neto (R) | P1 | P2 |
|---|---|---|---|---|
| 1:0,5 | 54% | +0,069 | +0,112 | +0,022 |
| 1:1 | 20% | +0,130 | +0,191 | +0,063 |
| 1:2 | 3% | +0,167 | +0,224 | +0,106 |
| 1:3 | 0% | +0,172 | +0,231 | +0,107 |

**En ninguna combinación probada el ratio corto rinde más que el largo.** Y el
motivo se lee en la columna "acierta": con 1:2 el target se toca el 3% de las
veces y con 1:3 nunca. O sea que a esos ratios el target **es irrelevante** —
lo que produce el resultado es el stop más sostener hasta el cierre.

Cuarta aparición del mismo hallazgo: **el edge está en la duración**. Acortar
el ratio es otra forma de acortar el hold.

Agregado por día (que es el n honesto, porque los momentos del mismo día se
solapan): **+0,072R por día a 1:1, con el 59% de los días en positivo.**

### Dónde está y dónde no está el patrón

Esperanza BRUTA del short por corte, stop 8×, ratio 1:1:

| corte | bruto (R) | veredicto |
|---|---|---|
| precio ≥ $10 | **+0,196** | lo único neto positivo por sí solo |
| volatilidad > 2,5%/min | +0,020 | ayuda |
| expansión pre-market > +100% | +0,007 | ayuda |
| debajo del VWAP (back side) | −0,007 | neutro |
| arriba del VWAP (front side) | −0,138 | **en contra** |
| expansión < +25% | −0,143 | en contra |
| **a menos de 3% del máximo** | **−0,310** | **el peor de todos** |

**Shortear cerca del máximo es la peor celda de la tabla.** El instinto de
"vender el techo" es exactamente lo contrario de lo que pagan los datos: paga
esperar a que el máximo tenga horas y el papel esté abajo del VWAP.

### El costo es el muro, y se puede ver dónde está

El costo fijo por acción convertido a R depende del precio y del ancho del
stop. Con 4 centavos por acción:

| banda | % de momentos donde el costo supera 0,25R | neto a 1:1 (stop 8×) |
|---|---|---|
| $0,50–1 | **79%** | −1,010 |
| $1–3 | 42% | −0,252 |
| $3–10 | 8% | −0,135 |
| **$10+** | **4%** | **+0,161** |

Debajo de $1 el costo se come más de un cuarto del riesgo en 4 de cada 5
momentos: ahí no hay trade, hay una donación. **Este es el argumento
cuantitativo más fuerte que salió hasta ahora para subir la banda de precio** —
y va en contra del instinto de buscar los papeles baratos porque "se mueven
más".

## 4.octies. Un minuto, no cinco — y el target atado a la estructura

Dos objeciones de Agus, las dos correctas.

### "¿Cada cuánto probaste?"

Cada 5 minutos, y estaba mal. Cinco minutos es una elección arbitraria y
descarta 4 de cada 5 momentos de decisión. Rehecho **cada 1 minuto**:
**233.512 momentos** sobre los mismos 775 días, 73 segundos de construcción.

Un minuto es el piso de lo que tenemos: las barras son agregados de 1 minuto.
Bajar de ahí necesita datos de **trades** (tick), que es otro plan del
proveedor. Vale la pena decir qué se ganaría: dentro del minuto está el orden
real entre stop y target, que hoy se resuelve con la convención conservadora de
que gana el stop. Con ratios cortos esa convención pesa más que con ratios
largos, porque el stop está más cerca.

### "El ratio no debe ser fijo, sino por patrón de dato"

También correcto, y es la crítica más de fondo: un target de "1:1" es un número
nuestro. Un target **en un nivel** lo pone el mercado, y el ratio sale como
consecuencia de dónde está la estructura. Es lo que hace un discrecional cuando
dice "acá tengo 1:1 y allá tengo 1:3".

Se agregaron seis niveles como candidatos a target, todos calculados
acumulativamente hacia adelante. El ratio implícito mediano, con stop de 8× la
volatilidad:

| target | disponible | ratio que impone |
|---|---|---|
| EMA20 | 49% de los minutos | 1:0,13 |
| VWAP | 37% | 1:0,51 |
| POC del perfil de volumen | 32% | 1:0,53 |
| mínimo del día | 100% | 1:2,21 |
| mínimo de pre-market | 90% | 1:2,30 |
| cierre previo | 91% | 1:2,52 |

**Los "ratios cortos" que buscaba Agus tienen nombre: son el VWAP y el POC.**
Los ratios largos son el mínimo del día y el cierre previo. Y el "disponible"
importa tanto como el ratio: un nivel sirve de target de un short solo si está
DEBAJO del precio, y el VWAP lo está apenas un tercio del tiempo.

### El resultado, incluido el que se dio vuelta

Sobre toda la población los seis niveles dan neto negativo, igual que los
ratios fijos. En la celda buena —precio ≥ $3, volatilidad > 2,5%/min, debajo
del VWAP, stop 8×— el POC parecía la mejor combinación encontrada hasta ahora:

| | n | días | ratio | acierta | neto | P1 | P2 |
|---|---|---|---|---|---|---|---|
| target = POC | 1.280 | 85 | 1:0,26 | 65% | +0,172 | **+0,321** | **−0,007** |
| fijo 1:3 | 12.534 | 302 | 1:3 | 0% | +0,168 | +0,226 | +0,104 |

**No replica.** El POC dio +0,32 en el primer período y −0,01 en el segundo, y
encima el nivel está disponible en 85 días contra 302. Agregando por día
—que es el n honesto— el POC da **−0,007R** y el ratio fijo largo **+0,082R**.

O sea: el target estructural es la idea correcta y **este** target estructural
no aguantó. Queda registrado como probado y fallado, no como pendiente.

### Indicadores agregados al estado

Cada minuto lleva ahora, además de lo anterior: distancia a EMA9 y EMA20, RSI
de 14, distancia al POC, **fracción del volumen del día operada ARRIBA del
precio actual** (el papel atrapado, que es distinto de la distancia al POC), y
cuántos tramos de 15 minutos vienen haciendo máximos decrecientes.

El perfil de volumen es el histograma verde que se ve a la izquierda en DAS:
antes lo miraba Agus a ojo y el sistema no lo tenía.

## 4.nonies. La cuota discrecional — cómo entra sin ensuciar todo

El sistema mide los features que elegí yo. Lo que ve un operador mirando el
gráfico —"esto es un short", "esto es una trampa"— no está en ninguna columna,
y **mientras no esté no se puede saber si aporta información o si es una
historia que uno se cuenta**.

La única forma honesta de meterlo es la misma regla que ya rige para el LLM en
la Capa 1: **que emita una ETIQUETA, no un número**, y después medir esa
etiqueta contra el resultado.

Implementado en el visor: se elige un tipo (`entrada_short`, `entrada_long`,
`no_va`, `salida`, `patron`), se clickea el gráfico, y queda una fila en
`etiquetas.sqlite` con `(ticker, día, hora, tipo, nota)`. La hora es la misma
clave que usa `momentos`, así que cada marca se cruza con su feature vector sin
trabajo extra.

Vocabulario **cerrado** a propósito: un campo de texto libre se llena de
sinónimos en dos semanas y deja de ser agrupable. La nota libre está aparte.
Tabla **append-only**: una marca equivocada se corrige agregando otra.

Lo que esto va a poder contestar, y hoy no se puede:

1. ¿Los minutos marcados a mano rinden mejor que los que el modelo elegiría
   solo? Si sí, la discreción aporta y hay que buscar qué feature la aproxima.
   Si dan igual, no aporta — y eso también es un resultado.
2. ¿Qué features separan lo marcado de lo no marcado? Esa es la vía para
   convertir la intuición en una columna.

**Hace falta volumen de marcas antes de poder medir nada**: con veinte no
alcanza. El orden natural es marcar mientras se miran los días, no sentarse a
etiquetar.

## 4.decies. El informe de NotebookLM, contrastado contra los datos

Agus armó un informe con NotebookLM sintetizando a Espes, Vitale, Comas,
Lloret y Corrales Urrutia. Cuatro módulos: microestructura y sesgo corto,
reciclaje de posiciones, fricciones, y psicotrading. Contrastado afirmación por
afirmación con lo que hay medido.

### CONFIRMA — el régimen mensual (Módulo 3) 🟢

**La afirmación más barata de testear del documento y la que mejor salió.** Dice
que el régimen se diagnostica en la primera semana del mes. Testeado sobre las
barras diarias —**87.943 eventos**, la prueba con más muestra del proyecto—,
comparando el % de gaps que fadearon en los días 1-7 contra el resto del mes:

**r = +0,551** sobre 23 meses. Y filtrando por el diagnóstico:

| | n | mediana | % que fadea |
|---|---|---|---|
| meses diagnosticados *fading* | 2.084 | **−4,91%** | 61% |
| meses diagnosticados *reclaim* | 1.559 | −2,75% | 57% |

2,16 puntos de diferencia de mediana, en la dirección predicha. Con 23 meses el
n es chico, pero es información real y es un interruptor mensual que no depende
de nada intradía. `test_regimen.py`.

### CONFIRMA — el sesgo corto en gaps grandes y el riesgo de cola 🟢

"Gaps masivos que precipitan colapsos verticales" y el *right tail risk* del
caso Tenon (+4000%) coinciden con lo medido: expansión pre-market > +100% hace
que el long muera (77% stopeado) y el short rinda; y el peor caso individual de
la muestra diaria fue **+530%**, con MAE p90 del short entre 80% y 96%.

### CONFIRMA A MEDIAS — el reciclaje de posiciones (Módulo 2) 🟡

Es la afirmación más importante porque **contradice el modelo con el que
veníamos midiendo**: todo lo anterior asume una entrada y una salida.
Implementado en `test_reciclaje.py` (núcleo 20%, adiciones cada `paso ×
volatilidad` en contra, reducción del tramo más caro en micro-reversiones, stop
del conjunto), short a las 11:00 sobre 742 días:

| | gana | mediana | media | **desvío** | peor |
|---|---|---|---|---|---|
| simple · stop 20% | 36,9% | −7,91% | **+0,72%** | **73,67** | −32,1% |
| reciclaje 1,5× · stop 20% | **53,4%** | +0,54% | −6,87% | **14,91** | −80,2% |

**El *equity curve smoothing* es real y es enorme: el desvío cae 5×.** El win
rate sube de 37% a 53%. Las dos cosas que el informe vende, medidas.

Pero: **la media pasa de +0,72% a −6,87%**, y el peor caso empeora de −32% a
−80% —agregar contra una parabólica es exactamente el riesgo Tenon—. Replica en
los dos períodos.

Y el 77,8-80% de aciertos **no se reproduce**: da 53%. Dos explicaciones
posibles y no se puede elegir sin más información:

1. Mi versión agrega a pasos fijos de volatilidad; el humano agrega mirando
   estructura. Esto refuta "escalonar mecánicamente", no "escalonar con
   criterio".
2. **La unidad de medición.** Un win rate cambia según qué se cuente como
   trade: cada cierre parcial, o el día entero. El reciclaje genera muchos
   cierres parciales chicos ganadores y una salida grande perdedora.

### NO SE PUEDE APLICAR — el universo (Módulo 1) 🔴

El informe define el universo en **$300M a $2.000M de capitalización** (criterio
Merrill Edge / Charles Schwab) y propone como benchmark el *MSCI World Small Cap*.

**Eso no es el universo de este proyecto ni el de los operadores que cita.**
Acá el universo son micro caps con *public float* < $75M, cotizando entre $0,30
y $20, con 1.459 empresas perfiladas. La diferencia con $300M-$2.000M es de uno
a dos órdenes de magnitud.

Es una fusión de dos cosas distintas que se llaman igual: la "small cap" de la
gestión de activos y la "small cap" del day trading. Un benchmark de índice
mundial no tiene relación con shortear un gapper intradía. **La sección hay que
descartarla, no ajustarla.**

### DATO NUEVO ÚTIL — el locate al 20% 🟡

El informe afirma que los *locate fees* pueden llegar al 20% del nominal.
Sensibilidad medida sobre las celdas buenas, neto en R a 1:2:

| costo por acción | $3+ vol alta back | precio ≥ $10 |
|---|---|---|
| 2c | +0,176 | +0,241 |
| 8c | +0,136 | +0,203 |
| 30c | +0,078 | +0,163 |

Las celdas aguantan hasta 30 centavos por acción. Lo que NO aguanta nada es la
banda de menos de $3, donde el costo ya se comía el trade con 4 centavos. El
informe y los datos coinciden en la conclusión operativa aunque lleguen por
caminos distintos: **el costo decide, y decide antes de entrar.**

### SIN EVIDENCIA POSIBLE ACÁ — Módulo 4

Psicotrading, termostato financiero y protocolos de escalado (Axi Select) no se
contrastan con datos de mercado. Lo único cruzable es el criterio de invalidez
por drawdown del 10%, que es más laxo que el 4% de
[GESTION-RIESGO.md](GESTION-RIESGO.md) — pero los dos números salen de premisas
distintas y no compiten.

## 4.undecies. La Chavineta emulada de verdad — y qué queda sin explicar

Con las definiciones que trajo Agus se pudo reemplazar la caricatura de
`test_reciclaje.py` por `chavineta.py`, que emula la técnica como la describen.

### Lo que cambió respecto de la versión de juguete

| | antes | ahora |
|---|---|---|
| días operados | todos | solo los que **fallan** en la apertura |
| entrada | hora fija (11:00) | **agotamiento de volumen** |
| adiciones | pasos fijos de volatilidad | **niveles**: máx pre-market, máx día previo, VWAP, HOD |
| reducciones | pullback fijo | el precio vuelve **debajo del nivel** desde el que se agregó |
| corte | tope de pérdida | **reclaim en vivo**: cierra arriba del techo estructural |
| ejecución | cruzando el spread siempre | limitadas en el nivel, con rebate |

Confirmado además que **el win rate es plano a plano en las dos partes**, así
que el 53% de la versión anterior y el 77,8% de ellos sí eran comparables.

### El filtro de apertura descarta el 38% de los días

Clasificando cada día a las 10:00 —rompe el máximo de pre-market, lo sostiene y
hace nuevo máximo = *reclaim*; no lo rompe o se queda debajo del VWAP = *fade*—
**el 38% de los días de evento son reclaim y no se operan**. Es un filtro real y
observable, no una racionalización posterior.

### El resultado, universo $0,20–$10

| | n | gana | mediana | media | desvío | peor |
|---|---|---|---|---|---|---|
| bruto | 426 | 45,8% | −0,60% | −0,58% | 6,11 | −59,6% |
| neto, cruzando el spread siempre | 426 | 39,9% | −1,86% | −2,43% | 6,46 | −61,5% |
| **neto, adiciones pasivas + rebate** | 426 | 44,3% | −1,01% | **−0,99%** | 4,75 | −18,3% |

En el universo que declaran (≤10M acciones, n=140) da lo mismo: **−0,99% neto,
44% de aciertos**. El float bajo no lo rescata.

**La ejecución pasiva se comió la mitad del déficit** (−2,43% → −0,99%). Es la
corrección de modelado más grande de toda la ronda: cobrar spread en cada
ejecución castiga a la técnica por algo que la técnica no hace — las adiciones
son limitadas puestas EN la resistencia, que es literalmente aportar liquidez.
Queda el reparo de siempre: una limitada tiene selección adversa, te llenan
cuando el mercado sigue en contra.

### Dónde está todo el resultado

| motivo de salida | n | gana | media |
|---|---|---|---|
| llega al cierre | 254 | **72,8%** | **+1,50%** |
| cortado por reclaim | 166 | **0%** | **−5,23%** |

Los que sobreviven ganan casi 3 de cada 4 veces. Los que se cortan pierden
todos. **El resultado entero es la proporción entre esos dos baldes**, y hoy es
254 contra 166.

### El número que cierra la discusión

> **Hay que evitar el 56% de los trades que terminan cortados por reclaim para
> que la técnica empate.**

Ese es el trabajo exacto que tiene que hacer la lectura de Level 2 y Time &
Sales que ellos describen y que no está en los datos de barras. No es una
diferencia de calibración: es una capa de información que el minuto no tiene.

Con eso queda explicada la brecha entre el 44% medido y el 77,8% auditado sin
tener que acusar a nadie de nada. **Ellos no operan todos los días que pasan el
filtro: descartan con el tape.** Y ese descarte, para que los números cierren,
tiene que acertar más de la mitad de las veces sobre los que van a fallar.

### La contradicción del locate, resuelta por aritmética

El resumen dice "20% del nominal" y el ejemplo del mismo módulo dice "10% bruto
→ 8% real", que es una quita del 20% **sobre la ganancia**. Se implementaron las
dos: la quita sobre la ganancia mueve la media de −0,60% a −0,99%; la lectura
literal la manda a **−21%** y deja **cero** trades ganadores en 426. La lectura
literal no puede ser la correcta, y no hace falta discutirlo: la muestra lo
muestra.

### Lo que este resultado NO dice

No dice que la técnica no funcione. Dice que **la parte mecánica de la técnica
no alcanza**: filtro de apertura + agotamiento de volumen + adiciones en niveles
+ corte por reclaim da ~cero. Todo lo que la separa de un negocio está en la
selección discrecional, que es exactamente lo que
[etiquetas.py](etiquetas.py) existe para poder medir.

Y hay un dato de mercado que falta y ahora tiene nombre: **el Level 2 y el Time
& Sales**. Es lo único que puede decidir cuáles de esos 166 no tomar.

## 4.duodecies. El radar de tres capas — el resultado más fuerte del proyecto

Agus trajo el protocolo de filtrado completo de la Chavineta: régimen mensual,
escáner cuantitativo con parámetros exactos, y auditoría de viabilidad.
Implementado en `radar.py` con los umbrales **que ellos declaran**, sin tocar
ninguno.

**Eso último importa más que el resultado.** Los cinco filtros —precio $0,70–$5,
gap ≥ 70%, float ≤ 10M acciones, volumen pre-market ≥ 3M, volumen del día ≥ 3×—
vinieron de afuera y antes de medir. No los busqué yo. Es lo más parecido a una
hipótesis pre-registrada que tuvo este proyecto desde el gradiente de dilución.

### Apertura → cierre

| | n | mediana | cae |
|---|---|---|---|
| toda la población con minutos | 1.357 | **+5,41%** | 43% |
| **candidatos del radar (5 filtros)** | **39** | **−12,42%** | **74%** |
| + historial de fallo del ticker ≥ 60% | 14 | **−14,44%** | **93%** |
| + empresa china | 5 | −36,21% | 80% |

La población **sube** +5,4% de mediana; los candidatos **bajan** 12,4%. Son casi
18 puntos de separación, y salen de un filtro que no calibré.

**No es efecto de la cola.** Media −8,90%; sacando el 5% superior, −13,62%. La
cola juega EN CONTRA del short (BAOS +101,3% en un día) y aun así el agregado
aguanta.

**Replica partido al medio:** primera mitad −13,50% con 70% de caídas, segunda
mitad −10,50% con 79%.

### Capa 3: el historial del gapeador aporta aparte de la dilución

La afirmación era: si un ticker falló 7 de sus últimos 10 gaps, tenés ventaja en
*ese* activo. Testeado point-in-time —para cada evento solo los gaps
anteriores—, sobre gaps ≥ +20%, n=1.007:

| historial previo | n | mediana | falla |
|---|---|---|---|
| < 40% | 212 | −5,28% | 60% |
| 40–60% | 172 | −5,76% | 61% |
| 60–80% | 352 | −8,96% | 66% |
| ≥ 80% | 271 | −8,96% | **70%** |

Y el control que hacía falta —si es la dilución con otro nombre—:

| | dil ≤ 100% | dil > 100% |
|---|---|---|
| historial < 60% | −3,21% | −8,64% |
| historial ≥ 60% | −7,77% | −10,83% |

**Las dos dimensiones se mueven por separado.** Dentro de cada columna el
historial suma 2 a 5 puntos; dentro de cada fila la dilución suma 3 a 5. Son
features distintos y apilan.

### Origen y sector, gratis y no los teníamos

De EDGAR: `countryCode` del domicilio comercial (F4 = China) y el SIC
(2834/2836/8731 = biotech). NAMI y ELPW resultan chinas incorporadas en Caimán,
que es exactamente el perfil que el protocolo marca como hiper-volátil. Cacheado
en disco, cero costo.

### Los tres reparos, sin los cuales esto no se puede usar

1. **n = 39, y 14 en la mejor celda.** Es poco. La descarga del censo lo va a
   multiplicar, y hasta que corra eso el número es indicativo.
2. **Sigue el sesgo de la muestra vieja** (rango diario > 40%). La separación
   entre población y candidatos es una comparación DENTRO de la misma muestra,
   que es lo más robusto al sesgo — pero el nivel no.
3. **No hay dato de borrow.** El propio protocolo pone el locate como criterio
   de descarte. Un candidato del radar puede ser inoperable y el radar no se
   entera. Es la frontera del sistema.

### Un conflicto que no se resuelve a favor de nadie

Ellos filtran **$0,70–$5**. Mi medición dice que debajo de $3 el costo se come
más de un cuarto del riesgo en el 42% de los momentos, y que la única banda con
esperanza neta positiva por sí sola fue **$10+**.

Los defaults de `radar.py` son los de ellos; la banda de
[ESTRATEGIA.md](ESTRATEGIA.md) sigue siendo ≥ $3. **Se decide con el re-corrido
sobre el censo, no antes** — y es la clase de desacuerdo que conviene tener
anotado en vez de zanjado por autoridad.

## 4.terdecies. Tres experimentos mientras bajaba el censo

Ninguno depende de la descarga. Uno confirma, uno agranda el hallazgo y **uno me
desmiente a mí**.

### A. El radar está en una MESETA, no en un pico (`test_sensibilidad.py`)

El reparo que faltaba: los umbrales del protocolo no los calibré yo, pero eso no
dice nada sobre si el resultado es robusto. Un resultado sano vive en una
meseta; uno de suerte, en un pico. Se mueve un parámetro por vez y se mira la
superficie entera.

**Gap mínimo** — monotónico, sin pico:

| gap ≥ | n | mediana | cae |
|---|---|---|---|
| 40% | 364 | −10,74% | 68% |
| 70% ← el del protocolo | 169 | −13,10% | 73% |
| 100% | 100 | −18,14% | 75% |
| 130% | 74 | −19,50% | 74% |

**Float máximo** — la banda de 10-30M es claramente peor, así que el corte en
10M sí discrimina:

| banda de acciones | n | mediana | media |
|---|---|---|---|
| < 3M | 72 | −12,71% | −5,14% |
| 3–10M | 96 | −13,41% | −6,90% |
| **10–30M** | 122 | **−6,97%** | −2,27% |
| > 100M | 43 | −2,52% | −0,90% |

**Precio máximo** — plano de $5 a $20: −13,10% con n=169 contra −13,27% con
n=277. **Ampliar la banda hasta $20 mantiene la mediana y suma 64% de muestra**,
y de paso resuelve la objeción de costos: más precio, menos costo en R. Es la
única modificación al protocolo que los datos respaldan.

**Estabilidad trimestral** — funciona en los 7 trimestres con muestra
suficiente, y sacando el que más aporta el agregado casi no se mueve
(−13,10% → −12,64%). No depende de un período.

### B. El derrumbe NO termina en el cierre

Desde el cierre del día del evento, sobre los mismos 169 candidatos:

| horizonte | mediana | media | negativos |
|---|---|---|---|
| T+1 | **−9,82%** | −8,55% | 73% |
| T+5 | **−17,41%** | −10,14% | 77% |
| T+20 | **−31,58%** | −7,76% | **83%** |

Contra la población entera: T+1 −1,28%, T+5 −3,16%.

Encadenado con el intradía (−13,10% de apertura a cierre), un candidato típico
pierde **~28% de la apertura al cierre de T+5**. Es coherente con la tesis
central del proyecto: estas empresas diluyen DESPUÉS del pump, y por eso la caída
continúa.

**El precio de sostener:** el MAE del short a T+5 tiene mediana +7,74% pero
media **+32,96%** — un tercio se te va en contra fuerte antes de darte la razón.
Y el borrow se paga todos los días. Es un swing, no una extensión gratis del
intradía.

### C. El RVOL en dólares: yo estaba equivocado (`test_rvol_dolares.py`)

Vengo diciendo desde §4.sexies que arreglar el RVOL —que se calcula en acciones
y por eso se rompe con los reverse splits— iba a "destapar una familia entera de
setups". **Lo medí y es falso.**

| población | n | mediana | cae |
|---|---|---|---|
| las ve las dos versiones | 60.711 | +0,07% | 44% |
| **solo el RVOL en dólares** (el punto ciego) | 7.788 | **+1,94%** | 39% |
| solo el RVOL en acciones | 3.680 | **−1,96%** | 62% |

El punto ciego existe —3.076 de esos días no están en `events`— pero **esos días
SUBEN**. Y al revés: los que solo ve el RVOL en acciones son los mejores para el
short de las tres poblaciones. El detector no tiene un bug que nos cuesta plata:
tiene un sesgo que resulta estar a favor.

Ni siquiera la firma del reverse split rescata el argumento: filtrando a los que
tienen RVOL en acciones < 0,5× —los que operaron MENOS acciones que lo normal,
que es la marca del split— quedan 195 días con mediana −1,10%. Nada.

**Queda como corrección, no como pendiente.** ELPW 2026-08-11 sigue afuera del
dataset y sigue siendo cierto que el RVOL en acciones no lo ve; lo que era falso
es mi conclusión de que eso importara.

Un detalle de calidad de dato que salió de paso: VIDA 2026-05-29 da un RVOL en
dólares de **11.009.692×** porque la mediana de volumen en dólares de sus 20
días previos es prácticamente cero. Cualquier umbral sobre un ratio necesita un
piso absoluto en el denominador, o la cola se llena de divisiones por casi cero.

## 4.quaterdecies. Las capas componen para el trade y destruyen el año

El protocolo asume que las tres capas se apilan. Medido en las dos monedas a la
vez —por trade y por año—, apilarlas hace lo de siempre:

| | n | por trade | frecuencia | **por año** |
|---|---|---|---|---|
| capa 2 sola (el escáner) | 277 | −13,27% | 147,6/año | **−1.959%** |
| + capa 1 (meses *fading*) | 128 | −15,87% | 68,2/año | −1.082% |
| + capa 3 (historial ≥ 60%) | 100 | −13,39% | 53,3/año | −713% |
| **las tres juntas** | 39 | **−20,28%** | 20,8/año | **−421%** |
| las tres + dilución > 100% | 18 | −19,84% | 9,6/año | −190% |

El trade mejora un 53% (−13,27 → −20,28). El año empeora **4,6 veces**.

**Cuarta aparición del mismo hallazgo.** Ya había pasado con los filtros
técnicos, con la duración del hold, y con el control de pérdida. Ahora con las
capas del protocolo. En los cuatro casos el instinto de seleccionar más produce
un trade más lindo y un negocio peor.

La lectura operativa no es "no filtres": es que **la capa 2 es el filtro, y las
capas 1 y 3 son para dimensionar, no para descartar.** Un mes *reclaim* o un
ticker sin historial de fallo son razones para ir con medio tamaño, no para
mirar de afuera.

*(Caveat de la cuenta: `mediana × frecuencia` no es una suma de medianas y no
pretende ser el P&L. Sirve como comparación entre filas, que es para lo que está.
Con 148 eventos al año el capital no es la restricción, así que la frecuencia se
puede tomar como aprovechable.)*

### El otro número que sale de acá: 148 candidatos por año

Menos de uno cada dos semanas. Los operadores del informe hacen **12 a 30 trades
por día** sobre 2 a 4 tickers.

Aun multiplicando por las re-entradas —4 ciclos por evento serían ~600 al año—
queda lejos de los ~3.000 anuales que implica su frecuencia. **O su filtro real
es bastante más laxo que el que describe el informe, o operan muchos setups que
no cumplen las cinco condiciones.** Es una pregunta abierta y vale la pena
hacerla: no cambia lo medido, cambia cuánto de su operativa cubre este radar.

### Reincidentes vs primerizos: no es lo mismo que el historial

Con 185 tickers distintos para 277 candidatos, el 34% repite. Pero repetir no
paga por sí solo: reincidentes −13,43% contra primerizos −12,99%, o sea nada.

Lo que paga es **haber fallado antes**, no haber aparecido antes. Son dos cosas
distintas y conviene no confundirlas: la capa 3 mide la primera.

## 4.quindecies. La entrada temprana NECESITA el escalonado — y ahí se reconcilia todo

Quedaba pendiente el reparo más grande contra el informe: ellos dicen que operan
desde las 06:30 y que ahí sale el 85% del profit, y yo había medido que shortear
a las 07:00 pierde −5,15% con un MAE p90 del 310%.

La hipótesis de reconciliación era que **ellos no entran, construyen**: núcleo
del 20% temprano y adiciones contra la suba hasta la apertura. Medido sobre 316
días de expansión ≥ 100%, salida a las 11:30:

| entrada | método | n | mediana | media | gana | MAE p90 |
|---|---|---|---|---|---|---|
| **07:00** | entrada simple | 264 | **−5,49%** | −6,37% | 45% | **240,6%** |
| **07:00** | **escalonado** | 264 | **+4,03%** | +1,94% | **66%** | **141,7%** |
| 08:00 | simple | 300 | +0,10% | −0,45% | 50% | 193,0% |
| 08:00 | escalonado | 300 | +4,55% | +4,30% | 69% | 94,7% |
| 09:00 | simple | 316 | **+8,44%** | +8,12% | 67% | 93,8% |
| 09:00 | escalonado | 316 | +4,00% | +6,38% | **78%** | **33,1%** |

**El escalonado da vuelta la entrada temprana.** A las 07:00 pasa de −5,49% a
+4,03% y el MAE p90 baja de 240% a 142%. Yo estaba midiendo una entrada sola
donde ellos construyen una posición, y por eso el resultado no cerraba.

**Y a las 09:00 pasa lo contrario.** La entrada simple da +8,44% y el escalonado
+4,00%: cuando entrás tarde el papel ya no hace máximos nuevos, así que no se
agregan tramos y quedás con el 20% del nominal puesto. El escalonado no
"funciona mejor" — funciona **cuando hay contra qué escalonar**.

La regla que sale de acá, y es la primera que reconcilia las dos operativas:

> **Temprano se construye, tarde se entra.** Antes de las 08:30 no se abre
> posición completa: núcleo del 20% y adiciones contra los máximos. Después de
> las 09:00 el escalonado ya no aporta y sí cuesta mediana.

*(Cómo está contabilizado: el resultado del escalonado se escala por el nominal
efectivamente usado —`tramos abiertos / 5`—, así que un día donde solo se abrió
el núcleo cuenta como un quinto del movimiento. Es la contabilidad honesta y
explica parte de por qué la mediana del escalonado a las 09:00 es menor: se
desplegó menos capital. La comparación de win rate y de MAE sí es directa,
porque el riesgo máximo comprometido es el mismo en las dos.)*

## 4.sexdecies. Estructura de papel DENTRO de los candidatos

Sobre los 277 candidatos del radar (precio hasta $20), retorno apertura→cierre:

| | n | mediana | cae |
|---|---|---|---|
| todos los candidatos | 277 | −13,27% | 73% |
| **shelf efectivo** | 212 | **−13,70%** | 75% |
| shelf NO efectivo | 65 | **−6,41%** | 65% |
| ≥ 1 pricing en 12m | 213 | −14,45% | 76% |
| **pricing hace < 90 días** | 96 | **−15,50%** | 74% |
| runway < 6 meses | 126 | −12,48% | 75% |
| reverse split en 12m | 186 | −13,26% | 73% |

**El shelf efectivo vuelve a aparecer, y confirma la corrección de §4.quater.**
Descartado en la Etapa A por no discriminar *qué empresas son micro caps* (lo
cumple el 54% del universo), acá separa 7 puntos: **con el registro efectivo la
empresa puede vender contra la fuerza, y lo hace.** Es el mecanismo causal de la
tesis del proyecto, medido dentro de la población que importa.

**Un pricing reciente (< 90 días) suma otro punto y medio.** También
mecanismo-consistente: la empresa ya demostró en el trimestre que está vendiendo
papel.

Runway y reverse split, en cambio, **no separan dentro de los candidatos**
—−12,48% y −13,26% contra −13,27% de base—. Siguen siendo buenos para describir
al asset class y no aportan al día del evento.

### Un feature que NO se puede usar y conviene decir por qué

`close_pos` —dónde cerró dentro de su rango— separa brutalmente: los que
cerraron en el cuarto bajo dan −24,32% con 93% de caídas, y los que cerraron
arriba dan **+16,57%**.

**Es circular y no es un hallazgo.** Cerrar abajo del rango *es* haber caído: el
feature y el resultado son la misma medición con dos nombres. Se anota
únicamente para que nadie lo redescubra dentro de tres semanas y lo confunda con
una señal.

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
