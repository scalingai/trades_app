# Small Caps — sistema semi-automático

> **Estado al 2026-08-29.** Investigación con datos propios, sin operar.
> **[ESTRATEGIA.md](ESTRATEGIA.md) — las reglas operables, con el semáforo de
> qué está validado y qué no.** Leer eso primero si venís a operar.
> **[COMO-SE-MIDE.md](COMO-SE-MIDE.md) — qué es exactamente cada número.**
> Empezar por ahí antes de creerle a una tabla: la mitad de los resultados del
> proyecto son mediciones de movimiento, no simulaciones de trade.
> La medición completa está en [RESEARCH.md](RESEARCH.md); el dimensionamiento,
> en [GESTION-RIESGO.md](GESTION-RIESGO.md).

## Qué hay construido

| script | qué hace | costo |
|---|---|---|
| `ingest.py` | ficha de estructura de papel de un ticker (EDGAR) | $0 |
| `profile_universe.py` | perfila el universo micro cap (1.459 empresas) | $0 |
| `backfill_daily.py` | barras diarias de todo el mercado US, 2 años | $0 |
| `detect_events.py` | detector de volumen anómalo → 87.943 eventos | $0 |
| `join_structure.py` | cruza cada evento con su ficha point-in-time | $0 |
| `horizons.py` | retornos a T+1/5/20 + máxima excursión adversa | $0 |
| `backfill_minutes.py` | barras de 1 minuto, muestra aleatoria de 1.500 | $0 |
| `test_out_of_sample.py` | ¿el efecto replica en dos períodos? | $0 |
| `test_signals.py` | 8 señales técnicas de cero parámetros | $0 |
| `test_ict.py` | 3 señales de estructura ICT + combinación de capas | $0 |
| `test_rr.py` | stop/target con costos, por banda de precio | $0 |
| `test_scalping.py` | ¿funcionan los trades cortos? (no) | $0 |
| `test_correlacion.py` | ¿los trades del mismo día son independientes? | $0 |
| `riesgo.py` | dimensionamiento por simulación sobre datos reales | $0 |
| `test_lados.py` | ¿front side es de menor riesgo que back side? (sí) | $0 |
| `test_salidas.py` | ¿salir por anomalía de volumen acota la pérdida? (sí, y se lleva el edge) | $0 |
| `test_frontlong.py` | el candidato: front-side long con stop fijo | $0 |
| `indicadores.py` | EMAs, RSI, perfil de volumen, estructura — todos acumulativos | $0 |
| `momentos.py` | un registro **por minuto**: estado + niveles + resultado en R | $0 |
| `test_ratios.py` | ratios fijos vs target en un nivel × volatilidad × precio | $0 |
| `etiquetas.py` | la cuota discrecional: marcas a mano desde el visor | $0 |
| `test_marcas.py` | mide las marcas a mano contra lo que pasó después | $0 |
| `test_regimen.py` | ¿la 1ª semana del mes anticipa el régimen? (sí, r=0,55) | $0 |
| `test_reciclaje.py` | escalonar a ciegas: sube el win rate y borra la media | $0 |
| `chavineta.py` | la técnica emulada de verdad: niveles, agotamiento, reclaim | $0 |
| `test_ventana.py` | perfil horario 04:00-16:00 — dónde está la plata en el día | $0 |
| `poblacion_observable.py` | descarga el **censo** seleccionado antes de la apertura | $0 |
| `test_historial.py` | ¿el historial de gaps del ticker predice el próximo? (sí, y aparte) | $0 |
| `fichas.py` | país, SIC y sector de EDGAR, en lote y cacheado | $0 |
| `radar.py` | las 3 capas del protocolo: régimen, escáner, viabilidad | $0 |
| `radar_historico.py` | el radar sobre los 61.477 eventos diarios, no solo los que tienen minutos | $0 |
| `test_sensibilidad.py` | ¿el radar es meseta o pico? (meseta) | $0 |
| `test_capas.py` | ¿las 3 capas componen? (para el trade sí, para el año no) | $0 |
| `test_ventana.py` | perfil horario del short, 04:00 a 16:00 | $0 |
| `test_construccion.py` | entrada simple vs construir la posición, por hora | $0 |
| `test_rvol_dolares.py` | el punto ciego del RVOL en acciones (existe, y está a favor) | $0 |
| `torneo.py` | **todas las estrategias contra la misma vara** | $0 |
| `recorrer.py` | re-corre TODO el análisis sobre el censo y guarda la salida | $0 |
| `visor/server.py` | **gráfico de velas local** de cualquier día descargado | $0 |

Todo corre sobre datos locales. Lo único que necesita API key es la descarga
de precio (Massive/Polygon, plan gratis).

## Estado de la descarga

`python backfill_minutes.py --stats` para ver dónde quedó. Es resumable: la
muestra está fija con semilla en la base, así que relanzar continúa con los
mismos eventos.

## Mirar los días

```bash
python visor/server.py
```

Velas de 1 minuto, VWAP, niveles y la ficha de dilución de cada día, en el
navegador. Detalle en [visor/README.md](visor/README.md).

## Lo que sigue

1. **Terminar `poblacion_observable.py`** (~6 h con el tier free) y después
   `python recorrer.py`, que corre todo sobre el censo con `SMALLCAPS_CENSO=1`. Es lo único que vuelve creíbles los niveles absolutos:
   la muestra vieja se sorteó por rango del día completo, que a las 09:30 no se
   conoce. Si el gradiente de expansión sobrevive sin ese sesgo, el edge existe.
2. **40 días marcados a mano** en el visor, incluidos los que descartás. La
   pregunta concreta está en §8 de [ESTRATEGIA.md](ESTRATEGIA.md).
3. ~~**RVOL en dólares** en `detect_events.py`~~ — **medido y descartado**:
   la población que destapa sube, no baja (§4.terdecies C).
4. **Datos de borrow.** Un short sin locate rinde cero, no negativo.
5. Medir el slippage real en los eventos con halt detectado

---

# Fase 0: estructura de papel

Ingesta determinística de SEC EDGAR. **Sin LLM, sin scoring, sin decisiones.**
Emite hechos con fecha de publicación conocida; el juicio viene después y sobre
el dataset acumulado, no sobre umbrales inventados hoy.

Ver [RESEARCH.md](RESEARCH.md) para la tesis y los límites del enfoque.

## Uso

```bash
python ingest.py HSCS
```

```bash
python ingest.py --file universe.txt --out data/structures.jsonl
```

Reconstruir el pasado (point-in-time, sin look-ahead):

```bash
python ingest.py HSCS --as-of 2025-06-01
```

## Qué produce

```
  ESTRUCTURA DE PAPEL
    acciones en circulación   3,899,491
    medido al                 2026-07-20   (público desde 2026-07-23, 21d)
    dilución 12m              +101.6%
    reverse splits            1 detectados
        ~1:77  entre 2024-03-14 y 2024-07-29

  CAJA
    caja                      $1.7M
    burn mensual              $653,412   [quarterly]
    runway                    2.5 meses

  CADENCIA DE OFERTAS
    pricings (424B*) 12m      0
    shelf disparable          SÍ — registro efectivo
    8-K dilutivos 12m         8
```

## La regla que sostiene todo: `filed`, no `end`

```
end   = a qué fecha corresponde la medición   (acciones al 2026-03-16)
filed = cuándo se hizo pública                (presentado el 2026-03-16)
```

Un backtest indexado por `end` tiene look-ahead metido en el feature central:
al 2026-01-15 el mercado no sabía el share count del 2026-03-16. **Todo acceso
point-in-time filtra por `filed`.** Está testeado en
`tests/test_structure.py::TestPointInTime`.

## Reverse splits

Se infieren de un drop de share count >1.5× entre reportes consecutivos —
ninguna micro cap recompra un tercio de sus acciones en un trimestre. Sin este
ajuste, **un 1:20 se lee como −95% de dilución** y el signo del feature central
queda invertido justo en las empresas que más importan.

Es una *inferencia*, no un dato: el campo se llama `approx_ratio` a propósito.

**Los forward splits NO se ajustan, a propósito.** Un salto de 4× hacia arriba es
indistinguible de una dilución del 300% mirando solo el share count — y en micro
caps la dilución del 300% es el caso normal. Auto-detectarlos generaría falsos
positivos justo en la población objetivo. En vez de eso se emite una advertencia
y `dilution_since_inception_pct` queda marcado como no confiable para esos names.
Las ventanas de 3m y 12m —las que importan— no se ven afectadas.

## Costo y límites

- **$0.** EDGAR no pide API key. Solo exige `User-Agent` con contacto y ≤10 req/s;
  ambas cosas están centralizadas en `edgar/client.py` con cache en disco.
- Configurable: `export SEC_USER_AGENT="tu-app (tu@email.com)"`.
- **El share count se actualiza solo con los reportes.** Una small cap puede diluir
  40% entre un 10-Q y el siguiente: el dato es correcto pero viejo. Por eso el
  snapshot lleva `shares_stale_days` y advierte arriba de 120 días — no lo esconde.
- **Todavía no hay precio.** Sin market cap no se puede evaluar el *baby shelf rule*
  (S-3 limitado a ⅓ del float si el public float < $75M). Entra en Fase 1.

## Dónde vive cada cosa (leer antes de retomar)

**Todo es local, en tu PC. Nada sale a ninguna nube.** Pero está partido en dos
lugares a propósito:

| | Ruta | Sobrevive si se borra el worktree |
|---|---|---|
| **Código** | `…/gracious-wing-b7a8fc/smallcaps/` | **Sí** — commiteado en la rama `claude/small-caps-trading-system-df39e8`, que vive en el `.git` real de `C:\Users\agust\Apps\algotrade` |
| **Datos** | `C:\Users\agust\Apps\algotrade-data\smallcaps\` | **Sí** — está afuera del worktree |
| **`.env`** | worktree + respaldo en el dir de datos | **Sí** — por el respaldo |

**Por qué separados.** El código corre en un *worktree* de git, que es
descartable. Los datos no van en git (son cientos de MB y son reproducibles),
pero si vivieran adentro del worktree se perderían al borrarlo. El `.env` tenía
el mismo problema con la key adentro, por eso `config.py` lo busca primero en el
worktree y después en el respaldo.

El directorio de datos está **fuera de todo repo git**, así que la key no puede
commitearse por accidente ni siquiera equivocándose de comando.

Se mueve con `SMALLCAPS_DATA_DIR` en el `.env`.

**Presupuesto de disco:**

| Qué | Tamaño | Costo de recuperarlo |
|---|---|---|
| cache de EDGAR | ~170 MB | ~25 min |
| perfiles JSONL | ~2 MB | ~25 min |
| barras diarias (2 años) | ~700 MB | ~100 min |

Todo es reproducible; lo que se pierde al borrarlo es tiempo, no información.

## Para retomar más adelante

```bash
cd C:/Users/agust/Apps/algotrade && git checkout claude/small-caps-trading-system-df39e8
```

Los datos ya están en `C:\Users\agust\Apps\algotrade-data\smallcaps\`. Si el
`.env` del worktree no está, `config.py` levanta el respaldo solo.

## Estructura

```
smallcaps/
  edgar/
    client.py      throttle + User-Agent + cache   (único punto que toca la SEC)
    tickers.py     ticker <-> CIK
    facts.py       XBRL como series point-in-time
    filings.py     timeline + taxonomía de forms dilutivos
    structure.py   derivación: dilución, splits, runway, cadencia de ofertas
  ingest.py        CLI
  tests/           18 tests, sin red
```

## Siguiente

Fase 1 — scanner pre-market + consola, espejo de la de ES/MES. Recién ahí entra
data de precio paga y el LLM como capa de **clasificación de texto** (leer un
424B5 y decir "ATM de $50M, capacidad remanente $31M"), nunca de números.
