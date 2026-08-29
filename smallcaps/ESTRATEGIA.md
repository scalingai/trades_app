# Estrategia operable — short en micro caps

> **Estado al 2026-08-29. Para papel, no para plata.**
> Cada regla lleva su evidencia y su semáforo. Las 🔴 no están validadas y están
> igual porque el sistema necesita una regla en ese lugar — no porque la
> midamos y funcione.
>
> La medición completa está en [RESEARCH.md](RESEARCH.md); el dimensionamiento,
> en [GESTION-RIESGO.md](GESTION-RIESGO.md).

## Antes que nada: qué está probado y qué no

Esto no es un trámite. Es la diferencia entre operar un edge y operar una
ilusión.

| | estado |
|---|---|
| **La dilución previa separa las distribuciones** | 🟢 gradiente monotónico en 3 baldes, n=2.421, hipótesis pre-registrada |
| **La expansión pre-market decide la dirección** | 🟢 gradiente monotónico en 5 baldes, replica en P1 y P2 |
| **El régimen mensual se diagnostica en la semana 1** | 🟢 r=+0,55 sobre 23 meses, 87.943 eventos |
| **Shortear cerca del máximo es lo peor** | 🟢 −0,310R vs −0,007R del back side, n grande |
| **El costo decide antes que la señal** | 🟢 debajo de $1 el 79% de los momentos son inoperables |
| **La ventana es 08:30–11:00 para entrada simple** | 🟢 replica en P1 y P2 |
| **Antes de 08:30 hay que ESCALONAR, no entrar** | 🟢 07:00 simple −5,5% vs escalonado +4,0%; MAE p90 240% → 142% |
| **Shelf efectivo dentro de los candidatos** | 🟢 −13,70% vs −6,41% sin shelf — el mecanismo causal, medido |
| **El radar de 5 filtros separa 15 puntos** | 🟢 n=169 sobre el universo diario · P1 −12,9% / P2 −13,4% · umbrales NO calibrados por mí · **meseta, no pico** |
| **El derrumbe sigue después del cierre** | 🟢 T+1 −9,8% · T+5 −17,4% · T+20 −31,6% (83% negativos) |
| **El historial de gaps del ticker** | 🟢 monotónico, y aporta aparte de la dilución |
| **La Chavineta mecánica** | 🔴 **−0,99% neto, 44% de aciertos.** No es un edge |
| **Ratios cortos (1:1 o menos)** | 🔴 la esperanza SUBE con el ratio en todas las celdas |
| **Front-side long** | 🟡 el balde que mejor da es el más contaminado por el sesgo |
| **Los niveles absolutos de todo lo anterior** | 🔴 **muestra sesgada** — en corrección, ver abajo |

**El sesgo que invalida los niveles absolutos.** Los 1.500 días con minutos se
sortearon de eventos con rango DIARIO > 40%, que a las 09:30 no se conoce. El
2026-08-29 se lanzó la descarga de la **población observable completa** (~2.000
eventos, gap ≥ 25% y liquidez previa ≥ $150k, criterios que sí se conocen antes
de la apertura). Cuando termine hay que **re-correr todo** y esta tabla se
reescribe.

Hasta entonces: **las comparaciones entre celdas valen, los niveles no.**

---

## 1. El universo — a qué le mirás la cara

🟢 **Precio de cierre previo entre $3 y $20.** El barrido de sensibilidad lo
respalda por los dos lados: subir el mínimo mejora levemente (−13,44% en $3) y
el máximo es **plano de $5 a $20** — ampliar hasta $20 mantiene la mediana y
suma 64% de muestra. Es la única modificación al protocolo de ellos que los
datos respaldan.

Debajo de $3 el costo fijo por acción se come más de un cuarto del riesgo en el
42% de los momentos; debajo de $1, en el 79%. Es el hallazgo más duro de todos y
va **en contra** del instinto de buscar lo barato porque "se mueve más". La
banda de $10+ fue la única con esperanza neta positiva por sí sola (+0,161R).

🟢 **Biotech sí, chinas con cuidado.** Sobre los candidatos del radar, biotech
da mediana −18,89% Y media −18,10% (n=55): consistente, sin cola. Las chinas dan
mediana −12,42% pero **media +3,88%** (n=30) — buena mediana y cola derecha
letal, que es exactamente lo que el protocolo advierte cuando dice que atrapan
cortos de forma irracional. **La china es un papel para bajar tamaño, no para
subirlo.**

🟡 **Float bajo ayuda pero no rescata.** Con ≤10M acciones el resultado no
mejoró. Se sigue registrando porque el mecanismo es real (float chico = spread
agresivo = movimientos parabólicos), pero no es un filtro que salve un setup
malo.

🟢 **Dilución 12m previa > 100%** o **≥1 reverse split en 12m**. Son los dos
features de estructura de papel que discriminan, y no son redundantes entre sí
(Jaccard 0,23). Salen gratis de EDGAR, point-in-time.

🔴 **Shelf efectivo, runway corto, cadencia de ofertas.** Los cumple más de la
mitad del universo: describen al asset class, no seleccionan. No los uses de
filtro.

## 2. El mes — para DIMENSIONAR, no para descartar

> **Corregido el 2026-08-29.** Esta sección decía "no operar corto" en los meses
> *reclaim*. Medido: apilar el filtro de régimen sobre el escáner mejora el trade
> (−13,27% → −15,87%) y **empeora el año 1,8 veces**, porque se lleva puesta la
> mitad de la frecuencia. El régimen es una perilla de tamaño, no un interruptor.

🟢 **Diagnóstico en la primera semana.** Contá qué fracción de los gaps de los
días 1–7 cerró por debajo de su apertura.

| semana 1 | qué hacer el resto del mes |
|---|---|
| **fadea ≥ 60%** | mes de *fading*: tamaño normal |
| fadea 50–60% | tamaño mitad |
| **fadea < 50%** | mes de *reclaims*: **cuarto de tamaño** (no cero) |

Los meses diagnosticados *fading* dieron mediana −4,91% contra −2,75% de los
*reclaim*. Son 2,16 puntos, no es enorme, pero es gratis y no depende de nada
que pase durante el día.

## 3. El día — el filtro de apertura, a las 10:00

🟢 **Descarta el 38% de los días y es observable.**

**Reclaim → no se opera.** El papel rompió el máximo de pre-market, cerró arriba
5 minutos seguidos, y después hizo un nuevo máximo del día. Ahí los cortos
atrapados tienen que cubrir y eso es un *squeeze*, no un fade.

**Fade → se activa el protocolo.** No logró romper el máximo de pre-market, o
está debajo del VWAP a las 10:00.

## 4. La dirección — la decide la expansión pre-market

🟢 `expansión = máximo de pre-market ÷ cierre previo − 1`

| expansión | qué es | dirección |
|---|---|---|
| **> +100%** | parabólica agotada | **short** (el long muere: 77% stopeado) |
| +50 a +100% | tierra de nadie | no operar |
| < +25% | todavía tiene recorrido | short **NO** — acá el short es el que pierde |

Y un control de sanidad que no es opcional: **volumen del día ≥ 3× el del día
previo.** Sin eso, un reverse split se lee como una expansión de +5.000% (CETX,
+5.049% con el 57% del volumen del día anterior). Pasó, está medido, y envenena
justo la cola que interesa.

## 5. La hora — el hallazgo que corrige todo lo anterior

🟢 **La ventana es 08:30–11:00 ET, y el mejor momento es la apertura.**

Short en días de expansión ≥ +100%, retorno a la campana:

| entrada | mediana | gana | P1 | P2 | MAE p90 |
|---|---|---|---|---|---|
| 07:00 | **−5,15%** | 45% | +2,55% | **−9,12%** | **310%** |
| 08:00 | −0,03% | 49% | +8,14% | −4,03% | 253% |
| 08:30 | +6,03% | 55% | +8,49% | +1,73% | 156% |
| **09:30** | **+8,97%** | 61% | +13,23% | +2,34% | 99% |
| 10:00 | +8,14% | 64% | +10,19% | +6,06% | 71% |
| 11:00 | +3,97% | 56% | +5,07% | +2,36% | 50% |

Dos correcciones de una:

**A lo que veníamos haciendo.** Todas las mediciones previas entraban a las
10:00 o al mediodía. El pico está en la apertura y se decae toda la tarde: a las
13:00 ya no queda nada.

**A la ventana del informe.** Dicen 06:30–11:30. La mitad temprana de esa
ventana **pierde**: shortear a las 07:00 da −5,15% de mediana, no replica
(P1 +2,55 / P2 −9,12) y tiene un MAE p90 del **310%**. Ahí no se está fadeando
un colapso, se está adelante de la parabólica.

La reconciliación probable: ellos entran temprano **y escalonan** contra la
suba, que es justamente la Chavineta. Una entrada sola a las 07:00 no es lo
mismo que un núcleo del 20% a las 07:00 con adiciones hasta las 09:30. Pero
medido como entrada simple, temprano es peor y es mucho más peligroso.

**La regla operable, corregida el 2026-08-29: temprano se CONSTRUYE, tarde se
ENTRA.** Antes de las 08:30 no se abre posición completa — núcleo del 20% y
adiciones contra los máximos. Medido a las 07:00: entrada simple −5,49% con MAE
p90 del 240%; escalonado **+4,03% con MAE p90 del 142%**. El escalonado da
vuelta la entrada temprana. A las 09:00 pasa lo contrario (simple +8,44% contra
escalonado +4,00%): ya no hay máximos nuevos contra los cuales agregar.

**Lo que decía antes:** Y el mejor momento del día
es entre 09:15 y 10:00, que además es cuando aparece el volumen ($40M por día en
la franja de 09:30 contra $2,7M a las 06:30).

## 6. La entrada

🟡 **Esperá a que el máximo tenga horas.** Shortear a menos del 3% del máximo
corriente es la peor celda de toda la tabla: −0,310R contra −0,007R del back
side general. El instinto de "vender el techo" es exactamente lo contrario de lo
que pagan los datos.

🟡 **Precio debajo del VWAP acumulado** (back side). Con el precio arriba del
VWAP el short pierde: −0,138R.

🟡 **Volatilidad del minuto > 2,5%** (mediana del rango de las últimas 30
barras). Es la única celda además de $10+ con bruto positivo, y encima es donde
el costo pesa menos.

🔴 **Agotamiento de volumen como gatillo.** Definido como el volumen de los
últimos 5 minutos cayendo por debajo de la mitad del clímax mientras el precio
no hace máximos. Implementado en `chavineta.py` y **no alcanzó para dar
positivo**. Está acá porque hace falta un gatillo y este es el que describen los
operadores, no porque esté validado.

## 7. Después del cierre — el trade no termina en la campana

🟢 Desde el cierre del día del evento, sobre los candidatos del radar:

| horizonte | mediana | media | negativos |
|---|---|---|---|
| T+1 | −9,82% | −8,55% | 73% |
| T+5 | **−17,41%** | −10,14% | 77% |
| T+20 | −31,58% | −7,76% | **83%** |

La población entera da −1,28% a T+1. Encadenado con el intradía, un candidato
típico pierde **~28% de la apertura al cierre de T+5**.

**Y lo que cuesta.** El MAE del short a T+5 tiene mediana +7,74% pero media
**+32,96%**: a un tercio se le va en contra fuerte antes de darte la razón. Más
el borrow, que se paga todos los días. Es un swing con su propio
dimensionamiento, no una extensión gratis del intradía — y hasta que no esté
medido con costos de overnight, **no se opera**.

## 8. La gestión

🟢 **Stop entre 8× y 12× la volatilidad del minuto** (≈11% a 16% en un papel
típico). Stops más ajustados rinden peor: con 3× salta el 72% de las veces.

🔴 **Ratio: sostener hasta el cierre, no poner target corto.** En todas las
celdas medidas la esperanza SUBE con el ratio, y a 1:2 el target se toca el 3%
de las veces —o sea que a esa altura el target no participa: lo que produce el
resultado es el stop más la duración. **Esto contradice lo que querías hacer** y
es el punto donde más conviene que traigas evidencia en contra.

🟡 **Si escalonás, las adiciones van contra niveles** —máximo de pre-market,
máximo del día previo, VWAP— y son **órdenes limitadas puestas en el nivel**,
nunca cruzando el spread. Modelar el cruce en cada ejecución se comía la mitad
del resultado: −2,43% contra −0,99%.

🟢 **Cortar en el reclaim en vivo.** Si cierra arriba de la resistencia más alta
dos minutos seguidos, se cierra todo. En la simulación el 100% de los trades que
llegan a ese punto pierden, promedio −5,23%.

🔴 **Salir por anomalía de volumen durante el trade.** Funciona para lo que se
pidió —corta la cola izquierda a la mitad, el MAE p90 baja de 41% a 9%— pero se
lleva la esperanza entera. **Un stop fijo hace lo mismo y deja diez veces la
media.** No la uses.

## 9. El tamaño

🟢 De [GESTION-RIESGO.md](GESTION-RIESGO.md), derivado por simulación sobre la
distribución medida:

- **0,25% del buying power por trade.** De 0,25% a 0,50% la probabilidad de
  perder la cuenta se multiplica por diez.
- **Máximo 3 trades por día.** No diversifican: son el mismo evento y el mismo
  régimen.
- **Después de 3 pérdidas en el día, se cierra la jornada.**
- **Si la cuenta cae 2% desde su máximo, mitad de tamaño** hasta recuperarlo.
- **Si en 20 trades no aparece un ganador de más de 20%, parar y revisar.** La
  estrategia depende de esa cola; si dejó de aparecer, cambió algo.

## 10. Lo que hay que registrar — esta es la parte que no se saltea

**El dataset es el activo, no las reglas.** Las reglas de arriba son
placeholders con distintos grados de evidencia; lo que las va a corregir es el
registro de lo que pasó.

Por cada candidato que **mirás** —lo tomes o no—:

- ticker, fecha, hora de la decisión
- el feature vector completo (sale solo de `momentos.py`)
- la ficha de papel point-in-time (sale de `join_structure.py`)
- **qué decidiste y por qué** — con `etiquetas.py`, desde el visor
- qué pasó después

El campo que más vale es **el de los que NO tomaste**. Hoy la brecha entre lo
medido (44% de aciertos) y lo que auditan los operadores (77,8%) se explica
entera por lo que ellos descartan y yo no puedo ver. El número exacto está
medido:

> **Hay que evitar el 56% de los trades que terminan cortados por reclaim para
> que la técnica empate.**

Esa es la pregunta que tus marcas tienen que contestar. No hace falta que
aciertes siempre: más de la mitad alcanza.

## 11. Cómo se pasa de papel a plata

No por convicción. Por estas cuatro, en orden:

1. **Termina la descarga de la población observable y se re-corre todo.** Si el
   gradiente de expansión sobrevive sin el sesgo de muestreo, el edge existe. Si
   no sobrevive, no existe y esto se archiva.
2. **40 días marcados a mano en el visor**, con los que descartaste. Si tus
   marcas separan los dos baldes, la capa discrecional aporta y se puede
   automatizar. Si no los separan, no aporta.
3. **Datos de borrow.** Un short que no consigue locate rinde cero, no
   negativo, y hoy el backtest los toma todos. Sin esto cualquier resultado del
   lado corto es optimista por construcción.
4. **20 trades en papel con esperanza positiva**, y recién ahí el tamaño mínimo.

Mientras tanto lo que se hace es **mirar días, marcarlos y registrar**. Es
aburrido y es la fase que todos se saltean.
