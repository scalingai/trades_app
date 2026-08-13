# Small Caps — Fase 0: estructura de papel

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
