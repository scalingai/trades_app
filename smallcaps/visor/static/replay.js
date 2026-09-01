/* Reproducción: un mes operativo en cámara rápida, minuto a minuto.

   Por qué no es otra tabla: todo lo que hay hoy son fotos del final. Esta vista
   contesta cómo se FORMÓ el número — a qué hora se cargó la exposición, cuánto
   tiempo estuvo puesta, y qué estaba haciendo el papel mientras tanto. Es la
   diferencia entre leer "+$243 en 4 jornadas" y ver la película.

   Tres decisiones de diseño que explican todo lo demás:

   1. LAS JORNADAS VAN ENCADENADAS, NO EN UNA LÍNEA CONTINUA. No es preferencia:
      cada jornada es un papel distinto a un precio distinto (EZRA abre en $3,19
      y los otros en cualquier otro lado), así que un eje de precios común daría
      un gráfico sin sentido. Lo continuo del mes es el TABLERO; el gráfico se
      reinicia en cada jornada.

   2. EL RELOJ ES DEL MERCADO. La velocidad se mide en milisegundos por minuto
      de rueda, no en "2×", porque lo que uno tiene en la cabeza son minutos de
      rueda. Corre de 09:30 a 16:00; el premarket se dibuja entero al arrancar,
      que es como se vive el día de verdad — llegás con la expansión premarket
      ya formada, y es justamente la señal que ya conocías.

   3. LA CURVA DEL MES SE PRECOMPUTA ENTERA AL CARGAR. Son 390 minutos por
      jornada por unas pocas jornadas: nada. A cambio, saltar a cualquier punto
      de la barra es exacto e instantáneo, en vez de tener que re-simular desde
      el principio y arriesgar que el estado quede distinto según cómo llegaste. */

const $ = (s) => document.querySelector(s);
const G = window.VisorGrafico;

const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
const cls = (v) => (v == null ? 'tenue' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'tenue');
const mas = (v) => (v >= 0 ? '+' : '');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hhmm = (h) => String(Math.floor(h)).padStart(2, '0') + ':'
  + String(Math.round((h % 1) * 60)).padStart(2, '0');

/* La rueda: de 09:30 a 16:00. Son 390 minutos de duración pero 391 posiciones
   del reloj, porque las 16:00 EN PUNTO tienen que ser una de ellas: esta
   estrategia sostiene hasta el cierre a propósito, así que TODAS las salidas
   caen exactamente ahí. Con el rango abierto en 389 el día terminaba sin que se
   dibujara una sola salida y sin sumar el resultado — que es casi todo. */
const APERTURA = 9.5;
const MINUTOS = 390;          // duración, para escalas y porcentajes
const PASOS = MINUTOS + 1;    // posiciones del reloj: 0 = 09:30 … 390 = 16:00

let EST = '';
let MEDIDO = {};
let LADO = null;          // 'short' | 'long' | null (lo informa el endpoint)
let JORNADAS = [];        // el material del mes, tal como viene
let CURVA = [];           // [jornada][minuto] -> el estado del mes en ese instante

let iJ = 0, min = 0;      // dónde está el reloj
let corriendo = false, msPorMin = 45, timer = null, enCorte = false;
let CH = null;            // { chart, velas, vol, vwap }
let dibujadas = 0;        // cuántas velas de RTH ya se pintaron en esta jornada
let REALES = [];          // las velas efectivamente ocurridas hasta el reloj

/* =============================================================== precómputo */

/* Deja cada jornada con las velas indexadas POR MINUTO de rueda, y calcula el
   estado del mes en cada uno de esos minutos. Todo lo que el reloj hace después
   es leer de acá: el tick no calcula nada, sólo pinta. */
function precomputar() {
  let realizadoPrevio = 0;
  let pico = 0;
  CURVA = [];

  JORNADAS.forEach((j) => {
    const ap = j.sesion?.apertura || 0;
    const idx = (t) => Math.round((t - ap) / 60);

    /* Las velas se parten en dos: lo previo a la apertura se dibuja de una al
       empezar la jornada, y el resto se va soltando de a un minuto. */
    j.pre = { velas: [], volumen: [], vwap: [] };
    j.rth = Array.from({ length: PASOS }, () => ({ velas: [], volumen: [], vwap: [] }));
    const repartir = (lista, campo) => (lista || []).forEach((v) => {
      const k = idx(v.time);
      if (k < 0) j.pre[campo].push(v);
      else if (k < PASOS) j.rth[k][campo].push(v);
      /* Lo posterior a las 16:00 se descarta: la rueda terminó. */
    });
    repartir(j.velas, 'velas');
    repartir(j.volumen, 'volumen');
    repartir(j.vwap, 'vwap');

    /* Un punto VACÍO (`{time}` sin valores) por cada minuto de rueda. Sirve para
       reservar el eje: sin esto `setVisibleRange` se recorta al último dato que
       hay, y como al arrancar sólo está el premarket, el gráfico abría zoomeado
       en las 09:00–09:29 en vez de mostrar el día entero esperando llenarse.
       Que la tarde se vea vacía y se vaya poblando es justamente el efecto. */
    j.blancos = Array.from({ length: PASOS }, (_, m) => ({ time: ap + m * 60 }));

    /* El último cierre conocido en cada minuto, para poder marcar a mercado.
       Si un minuto no tiene vela (papel sin operaciones en ese minuto) se
       arrastra el anterior, que es exactamente lo que vale la posición. */
    const cierres = new Array(PASOS);
    let ultimo = j.niveles?.rth_open ?? j.pre.velas.at(-1)?.close ?? null;
    for (let m = 0; m < PASOS; m++) {
      const v = j.rth[m].velas.at(-1);
      if (v) ultimo = v.close;
      cierres[m] = ultimo;
    }

    const ts = j.trades || [];
    const totalJornada = ts.reduce((a, t) => a + (t.pnl || 0), 0);

    /* Cuánto vale 1 R en dólares ESE día. Sale de despejar la propia jornada:
       `pnl_R` es el resultado en unidades de riesgo y `totalJornada` el mismo
       resultado en dólares, así que R = dólares / R. Hace falta para poder
       dibujar el piso de −1 R, que es el límite diario de riesgo con el que el
       motor decide si sigue abriendo tramos. */
    j.Rdolar = (j.pnl_R && Math.abs(j.pnl_R) > 1e-9)
      ? Math.abs(totalJornada / j.pnl_R) : null;

    const fila = [];
    for (let m = 0; m < PASOS; m++) {
      const h = APERTURA + m / 60;
      const px = cierres[m];
      let abiertos = 0, acciones = 0, noRealizado = 0, realizado = 0;
      ts.forEach((t) => {
        const sale = t.hora_salida ?? 16;
        if (t.hora_entrada <= h && h < sale) {
          abiertos += 1;
          acciones += t.acciones || 0;
          if (px != null) {
            /* Marca a mercado. El sentido sale del `lado` de la estrategia si el
               endpoint lo informa, y si no se despeja de la propia fila — ver
               `corto()` en grafico.js. Acertarle importa: 135 de las 413
               estrategias son largas, y con el signo al revés este número sería
               el espejo del real durante toda la reproducción. */
            const dir = G.corto(t, LADO) ? -1 : 1;
            noRealizado += dir * (px - t.precio_entrada) * (t.acciones || 0);
          }
        } else if (sale <= h) {
          realizado += t.pnl || 0;
        }
      });
      const realMes = realizadoPrevio + realizado;
      const equity = realMes + noRealizado;
      if (equity > pico) pico = equity;
      fila.push({
        realizado: realMes, noRealizado, equity, dd: equity - pico,
        /* La equity A MERCADO DEL DÍA, separada de la del mes: el presupuesto de
           riesgo es diario, así que el piso de −1 R se compara contra esta y no
           contra el acumulado del mes. Y esta curva no es decoración — es la
           misma que el motor consulta cada minuto para decidir si sigue
           abriendo tramos. */
        equityDia: realizado + noRealizado,
        abiertos, acciones, precio: px,
        /* Un minuto está "vivo" si hay algo puesto o si algo pasa cerca. Los
           muertos se pintan igual, pero de corrido. */
        vivo: abiertos > 0 || ts.some((t) => {
          const sale = t.hora_salida ?? 16;
          return Math.abs(t.hora_entrada - h) < 3 / 60 || Math.abs(sale - h) < 3 / 60;
        }),
      });
    }
    CURVA.push(fila);
    realizadoPrevio += totalJornada;
  });
}

/* ================================================================== gráfico */

function montarJornada() {
  if (CH) { try { CH.chart.remove(); } catch (e) { /* ya estaba */ } CH = null; }
  $('#chart').innerHTML = '';
  const j = JORNADAS[iJ];
  if (!j) return;
  CH = G.crear($('#chart'));
  const off = G.desfase(j);
  j.off = off;

  /* El premarket, entero y de una: a las 09:30 ya pasó. */
  REALES = j.pre.velas.map((v) => ({ ...v, time: v.time + off }));
  CH.velas.setData(REALES.concat(j.blancos.map((b) => ({ time: b.time + off }))));
  CH.vol.setData(j.pre.volumen.map((v) => ({ ...v, time: v.time + off })));
  CH.vwap.setData(j.pre.vwap.map((v) => ({ ...v, time: v.time + off })));
  dibujadas = 0;

  /* Los niveles que ya se conocían al abrir: el stop del primer trade no, porque
     todavía no entró — eso aparece cuando entra. */
  if (j.niveles?.pm_high) {
    CH.velas.createPriceLine({
      price: j.niveles.pm_high, color: '#5b8def', lineWidth: 1, lineStyle: 3,
      axisLabelVisible: true, title: 'máx premarket',
    });
  }
  if (j.niveles?.prev_close) {
    CH.velas.createPriceLine({
      price: j.niveles.prev_close, color: '#5c6a85', lineWidth: 1, lineStyle: 2,
      axisLabelVisible: true, title: 'cierre previo',
    });
  }
  /* El encuadre es fijo, de 09:00 a 16:10: si el eje se moviera con el reloj,
     las velas quedarían siempre en el mismo lugar y no se vería avanzar el día.
     Así el día se va LLENANDO, que es lo que uno quiere mirar. */
  const base = (j.sesion?.apertura || 0) + off;
  try {
    CH.chart.timeScale().setVisibleRange({
      from: base - 30 * 60, to: base + Math.round(6.67 * 3600) });
  } catch (e) { CH.chart.timeScale().fitContent(); }
}

/* Pinta las velas desde la última dibujada hasta el minuto `hasta`. Es
   incremental a propósito: redibujar los 390 minutos en cada tick tiraría el
   navegador abajo en velocidad rápida. */
function pintarHasta(hasta) {
  const j = JORNADAS[iJ];
  if (!j || !CH) return;
  for (let m = dibujadas; m <= hasta && m < PASOS; m++) {
    j.rth[m].velas.forEach((v) => REALES.push({ ...v, time: v.time + j.off }));
    /* Volumen y VWAP van por `update()`, que sólo agrega al final y es barato.
       Las velas NO pueden: la serie tiene la cola de puntos vacíos hasta las
       16:00, así que `update()` con un minuto anterior al último sería ir para
       atrás y la librería lo rechaza. Van por `setData` con lo real más lo que
       todavía falta, que con 400 puntos no cuesta nada. */
    j.rth[m].volumen.forEach((v) => CH.vol.update({ ...v, time: v.time + j.off }));
    j.rth[m].vwap.forEach((v) => CH.vwap.update({ ...v, time: v.time + j.off }));
  }
  CH.velas.setData(REALES.concat(
    j.blancos.slice(hasta + 1).map((b) => ({ time: b.time + j.off }))));
  dibujadas = Math.max(dibujadas, hasta + 1);
  marcasHasta(hasta);
}

/* Los marcadores aparecen cuando el reloj llega a su minuto, no antes. Es el
   punto de la vista: ver la ejecución caer donde cayó. */
function marcasHasta(hasta) {
  const j = JORNADAS[iJ];
  const h = APERTURA + hasta / 60;
  const base = (j.sesion?.apertura || 0) + j.off;
  const hAts = (x) => base + Math.round((x - APERTURA) * 3600);
  const marcas = [];
  (j.trades || []).forEach((t, i) => {
    if (t.hora_entrada <= h) {
      marcas.push({
        time: hAts(t.hora_entrada), position: 'aboveBar', color: '#ef5350',
        shape: 'arrowDown', text: `${i + 1} $${n(t.precio_entrada, 2)}`,
      });
    }
    const sale = t.hora_salida ?? 16;
    if (sale <= h && t.motivo !== 'cierre') {
      marcas.push({
        time: hAts(sale), position: 'belowBar',
        color: t.pnl >= 0 ? '#26a69a' : '#ef5350', shape: 'arrowUp',
        text: `${mas(t.pnl)}$${n(t.pnl, 1)}`,
      });
    }
  });
  const cierre = (j.trades || []).filter((t) => (t.hora_salida ?? 16) === 16);
  if (cierre.length && h >= 16) {
    const suma = cierre.reduce((a, t) => a + (t.pnl || 0), 0);
    marcas.push({
      time: hAts(16), position: 'belowBar',
      color: suma >= 0 ? '#26a69a' : '#ef5350', shape: 'arrowUp',
      text: `cierra ${cierre.length} ${mas(suma)}$${n(suma, 0)}`,
    });
  }
  marcas.sort((a, b) => a.time - b.time);
  CH.velas.setMarkers(marcas);
}

/* ================================================================== tablero */

function kpi(v, lab, c = '', jefe = false) {
  return `<div class="kpi${jefe ? ' jefe' : ''}"><b class="${c}">${v}</b>`
    + `<span>${lab}</span></div>`;
}

function pintarTablero() {
  const e = CURVA[iJ]?.[min];
  if (!e) return;
  $('#tablero').innerHTML =
    kpi(`${mas(e.equity)}$${n(e.equity, 2)}`, 'PnL del mes', cls(e.equity), true)
    + kpi(`${n(e.acciones, 0)}`, 'acciones expuestas', e.acciones ? '' : 'tenue', true)
    + '<div class="sep"></div>'
    + kpi(`${mas(e.realizado)}$${n(e.realizado, 2)}`, 'realizado', cls(e.realizado))
    + kpi(`${mas(e.noRealizado)}$${n(e.noRealizado, 2)}`, 'sin cerrar', cls(e.noRealizado))
    + kpi(`${n(e.dd, 2)}`, 'caída desde el pico', e.dd < 0 ? 'neg' : 'tenue')
    + kpi(`${e.abiertos}`, 'tramos abiertos', e.abiertos ? '' : 'tenue');

  const j = JORNADAS[iJ];
  $('#cabj').innerHTML = `
    <span class="reloj">${hhmm(APERTURA + min / 60)}</span>
    <span class="tk">${esc(j.ticker)}</span>
    <span>${j.d}</span>
    <span>jornada <b>${iJ + 1}</b>/${JORNADAS.length}</span>
    <span>expansión <b>${n(j.resumen?.expansion, 0)}%</b></span>
    <span>apertura <b>$${n(j.niveles?.rth_open)}</b></span>
    <span>máx premarket <b>$${n(j.niveles?.pm_high)}</b></span>
    <span>último <b>$${n(e.precio, 3)}</b></span>`;
}

/* ================================================================== la barra */

/* Las corridas contiguas de minutos sin acción de una jornada, como porcentajes
   para pintar sobre su segmento. */
function tramosMuertos(k) {
  const fila = CURVA[k];
  if (!fila) return '';
  const out = [];
  let ini = null;
  for (let m = 0; m <= PASOS; m++) {
    const muerto = m < PASOS && !fila[m].vivo;
    if (muerto && ini == null) ini = m;
    if (!muerto && ini != null) {
      /* Menos de 10 minutos no se marca: sería ruido visual y tampoco se nota
         al reproducir. */
      if (m - ini >= 10) {
        out.push(`<span class="muerto" style="left:${(ini / MINUTOS) * 100}%;`
          + `width:${((m - ini) / MINUTOS) * 100}%"></span>`);
      }
      ini = null;
    }
  }
  return out.join('');
}

function pintarBarra() {
  $('#barra').innerHTML = JORNADAS.map((j, k) => {
    const tot = (j.trades || []).reduce((a, t) => a + (t.pnl || 0), 0);
    const marcas = (j.trades || []).map((t) => {
      const e = ((t.hora_entrada - APERTURA) / (MINUTOS / 60)) * 100;
      const s = (((t.hora_salida ?? 16) - APERTURA) / (MINUTOS / 60)) * 100;
      return `<span class="ev ent" style="left:${e}%"></span>`
        + (t.motivo !== 'cierre' ? `<span class="ev sal" style="left:${s}%"></span>` : '');
    }).join('');
    /* Los tramos que el modo "sólo con acción" acelera, pintados. Sin esto la
       barra haría creer que el día fue más corto de lo que fue: el tiempo se
       comprime, pero tiene que verse DÓNDE se comprimió. */
    const muertos = $('#soloAccion').checked ? tramosMuertos(k) : '';
    return `<div class="seg${k === iJ ? ' actual' : ''}" data-j="${k}"
      title="${esc(j.ticker)} · ${j.d} · ${(j.trades || []).length} trades">
      <span class="lleno" style="width:${k < iJ ? 100 : k > iJ ? 0 : (min / MINUTOS) * 100}%"></span>
      ${muertos}
      ${marcas}
      ${k === iJ ? `<span class="aguja" style="left:${(min / MINUTOS) * 100}%"></span>` : ''}
      <span class="rot">${esc(j.ticker)}<span class="${cls(tot)}">${mas(tot)}$${n(tot, 0)}</span></span>
    </div>`;
  }).join('');
}

function refrescarBarra() {
  const seg = $(`.seg[data-j="${iJ}"]`);
  if (!seg) return pintarBarra();
  seg.querySelector('.lleno').style.width = `${(min / MINUTOS) * 100}%`;
  const ag = seg.querySelector('.aguja');
  if (ag) ag.style.left = `${(min / MINUTOS) * 100}%`;
}

/* ============================================================ panel de curvas */

/* Dos carriles dibujados a mano en un canvas, no otro lightweight-charts: son
   390 puntos y se redibujan enteros en cada tick, así que una librería de
   gráficos financieros acá sería peso muerto.

   Arriba: la equity a mercado del día, con el piso de −1 R. Abajo: las acciones
   en exposición simultánea. De las dos, la de abajo es la que nunca se había
   visto moverse en el tiempo — sólo su máximo — y es la que decide el costo de
   todo el sistema, porque el locate se cobra por acción y por el rato que la
   tenés puesta. */
function dibujarPanel() {
  const cv = $('#panel');
  const fila = CURVA[iJ];
  if (!cv || !fila) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== W * dpr || cv.height !== H * dpr) {
    cv.width = W * dpr; cv.height = H * dpr;
  }
  const c = cv.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.clearRect(0, 0, W, H);

  const pad = 4, gap = 10;
  const hA = Math.round((H - gap) * 0.58), hB = H - gap - hA;
  const topB = hA + gap;
  const x = (m) => (m / MINUTOS) * (W - 1);

  const j = JORNADAS[iJ];
  const piso = j.Rdolar ? -j.Rdolar : null;

  /* ---- carril A: equity a mercado del día ---- */
  const eq = fila.map((f) => f.equityDia);
  let lo = Math.min(...eq, piso ?? 0, 0);
  let hi = Math.max(...eq, 0);
  if (hi - lo < 1e-9) { hi = lo + 1; }
  const mA = 6;
  const yA = (v) => pad + mA + (1 - (v - lo) / (hi - lo)) * (hA - 2 * mA - pad);

  // el cero
  c.strokeStyle = '#28303c'; c.lineWidth = 1;
  c.beginPath(); c.moveTo(0, Math.round(yA(0)) + .5); c.lineTo(W, Math.round(yA(0)) + .5); c.stroke();

  // el piso de −1 R: de lo que el sistema se está escapando
  if (piso != null) {
    c.save();
    c.strokeStyle = '#d4a11e'; c.setLineDash([4, 3]); c.lineWidth = 1;
    c.beginPath(); c.moveTo(0, Math.round(yA(piso)) + .5);
    c.lineTo(W, Math.round(yA(piso)) + .5); c.stroke();
    c.restore();
    c.fillStyle = '#d4a11e'; c.font = '10px ui-monospace,Consolas,monospace';
    c.fillText(`−1 R  $${n(piso, 0)}`, 4, yA(piso) - 3);
  }

  c.strokeStyle = eq[min] >= 0 ? '#2ea88f' : '#e5544f';
  c.lineWidth = 1.5; c.beginPath();
  for (let m = 0; m <= min; m++) {
    const px = x(m), py = yA(eq[m]);
    if (m === 0) c.moveTo(px, py); else c.lineTo(px, py);
  }
  c.stroke();

  c.fillStyle = '#5f6979'; c.font = '10px ui-sans-serif,system-ui,sans-serif';
  c.fillText('equity a mercado del día', 4, pad + 9);

  /* ---- carril B: acciones en exposición simultánea ---- */
  const acc = fila.map((f) => f.acciones);
  const maxA = Math.max(...acc, 1);
  const yB = (v) => topB + (1 - v / maxA) * (hB - 12) + 12;

  c.fillStyle = 'rgba(91,141,239,.22)';
  c.beginPath(); c.moveTo(x(0), yB(0));
  for (let m = 0; m <= min; m++) c.lineTo(x(m), yB(acc[m]));
  c.lineTo(x(min), yB(0)); c.closePath(); c.fill();

  c.strokeStyle = '#5b8def'; c.lineWidth = 1.2; c.beginPath();
  for (let m = 0; m <= min; m++) {
    const px = x(m), py = yB(acc[m]);
    if (m === 0) c.moveTo(px, py); else c.lineTo(px, py);
  }
  c.stroke();

  c.fillStyle = '#5f6979'; c.font = '10px ui-sans-serif,system-ui,sans-serif';
  c.fillText(`acciones expuestas · máx ${n(maxA, 0)}`, 4, topB + 9);

  /* ---- la aguja del reloj, cruzando los dos carriles ---- */
  c.strokeStyle = 'rgba(220,226,235,.45)'; c.lineWidth = 1;
  c.beginPath(); c.moveTo(Math.round(x(min)) + .5, 0);
  c.lineTo(Math.round(x(min)) + .5, H); c.stroke();
}

/* ================================================================== el reloj */

function irA(j, m, repintar = true) {
  const cambioJornada = j !== iJ;
  iJ = Math.max(0, Math.min(JORNADAS.length - 1, j));
  min = Math.max(0, Math.min(PASOS - 1, m));
  if (cambioJornada || repintar) montarJornada();
  pintarHasta(min);
  pintarTablero();
  pintarBarra();
  dibujarPanel();
}

/* El reloj corre sobre `requestAnimationFrame` y no sobre `setTimeout` en
   cadena, por tres razones concretas:

   - A velocidad rápida (14 ms por minuto de rueda) `setTimeout` no llega: el
     navegador redondea a su granularidad y el reloj queda más lento que lo
     pedido. Con rAF se avanzan TODOS los minutos que entraron en el cuadro y se
     dibuja una sola vez, así que la velocidad es la que dice el botón.
   - En una pestaña de fondo el navegador estrangula los temporizadores. El tope
     de `dt` hace que volver a la pestaña siga la reproducción donde estaba en
     vez de disparar media rueda de golpe.
   - La deuda acumulada corrige el error de redondeo, en vez de arrastrarlo.

   Un avance completo cuesta ~4 ms medidos, así que el cuello nunca es el
   dibujo. */
let ultimoCuadro = 0, deuda = 0;

function bucle(ts) {
  if (!corriendo || enCorte) return;
  if (!ultimoCuadro) ultimoCuadro = ts;
  deuda += Math.min(ts - ultimoCuadro, 250);
  ultimoCuadro = ts;

  let avanzo = false;
  /* Tope por cuadro: sin él, un salteo largo de minutos muertos se comería la
     jornada entera en un solo cuadro y no se vería pasar nada. */
  for (let k = 0; k < 60 && deuda >= msPorMin; k++) {
    if (min >= PASOS - 1) { render(); finJornada(); return; }
    min += 1; avanzo = true;
    /* El salteo de minutos muertos no deja de dibujarlos — los dibuja SIN
       consumir tiempo del reloj. Si se los omitiera, el gráfico quedaría con
       agujeros y la forma del día mentiría. Se comprime el tiempo, no el dato. */
    const vivo = CURVA[iJ][min].vivo || !$('#soloAccion').checked;
    if (vivo) deuda -= msPorMin;
  }
  if (avanzo) render();
  timer = requestAnimationFrame(bucle);
}

function render() {
  pintarHasta(min);
  pintarTablero();
  refrescarBarra();
  dibujarPanel();
}

function correr(v) {
  corriendo = v;
  $('#play').textContent = v ? '❚❚ pausa' : '▶ correr';
  cancelAnimationFrame(timer);
  ultimoCuadro = 0; deuda = 0;
  if (v && !enCorte) timer = requestAnimationFrame(bucle);
}

/* Entre jornadas la película se detiene y muestra el resultado del día. Es el
   único corte, y se puede saltear — pero existe porque si el mes pasara de
   largo no se registraría dónde terminó una jornada y empezó otra. */
function finJornada() {
  const j = JORNADAS[iJ];
  const e = CURVA[iJ][PASOS - 1];
  const ts = j.trades || [];
  const tot = ts.reduce((a, t) => a + (t.pnl || 0), 0);
  const px = G.pico(ts);
  const stops = ts.filter((t) => t.motivo === 'stop').length;
  const ultima = iJ >= JORNADAS.length - 1;
  /* El acumulado del mes CON este día ya cerrado. `CURVA[...][PASOS-1]` sirve
     ahora que las 16:00 son una posición del reloj, pero sumar las jornadas
     directo es más claro y no depende de dónde quedó parado el reloj. */
  const mesHasta = JORNADAS.slice(0, iJ + 1).reduce((a, x) =>
    a + (x.trades || []).reduce((b, t) => b + (t.pnl || 0), 0), 0);
  enCorte = true;
  cancelAnimationFrame(timer);

  $('#corte').hidden = false;
  $('#corte').innerHTML = `<div>
    <h2 class="${cls(tot)}">${esc(j.ticker)} · ${j.d} · ${mas(tot)}$${n(tot, 2)}</h2>
    <p>${ts.length} trade${ts.length === 1 ? '' : 's'}${
      stops ? `, <b>${stops}</b> por stop` : ', ninguno por stop'}.
      El pico de exposición fue de <b>${n(px.acciones, 0)}</b> acciones a las
      <b>${hhmm(px.horaAcciones)}</b>, en ${px.tramosAcciones} tramo${
      px.tramosAcciones === 1 ? '' : 's'}.
      El mes va ${mas(mesHasta)}$${n(mesHasta, 2)}.</p>
    <button id="seguir">${ultima ? 'volver al principio' : 'seguir con la próxima jornada'}</button>
    <div class="cuenta" id="cuenta"></div>
  </div>`;

  let resta = 4;
  $('#cuenta').textContent = corriendo ? `sigue solo en ${resta}s` : '';
  const seguir = () => {
    clearInterval(reloj);
    $('#corte').hidden = true;
    enCorte = false;
    if (ultima) { irA(0, 0); correr(false); }
    else { irA(iJ + 1, 0); if (corriendo) correr(true); }
  };
  const reloj = corriendo ? setInterval(() => {
    resta -= 1;
    if (resta <= 0) seguir();
    else $('#cuenta').textContent = `sigue solo en ${resta}s`;
  }, 1000) : null;
  $('#seguir').addEventListener('click', seguir);
}

/* ================================================================== arranque */

function pintarMedicion() {
  const el = $('#medicion');
  const mio = MEDIDO[EST];
  if (!mio) { el.textContent = ''; el.className = 'medicion'; return; }
  const todas = Object.values(MEDIDO).filter(Boolean);
  const ultima = todas.reduce((a, b) => (a > b ? a : b), mio);
  const dia = (s) => String(s).slice(0, 10);
  const vieja = dia(mio) < dia(ultima);
  el.className = 'medicion' + (vieja ? ' vieja' : '');
  el.textContent = vieja ? `medida ${dia(mio)} · hay del ${dia(ultima)}` : `medida ${dia(mio)}`;
}

async function cargarMeses() {
  const r = await fetch(`/api/replay/meses?estrategia=${encodeURIComponent(EST)}`)
    .then((x) => x.json()).catch(() => ({ meses: [] }));
  const ms = r.meses || [];
  /* Sólo se ofrecen los meses que tienen material: un rango vacío daría una
     pantalla en negro sin explicar por qué. */
  $('#mes').innerHTML = ms.length
    ? ms.slice().reverse().map((m) =>
      `<option value="${m.mes}">${m.mes} · ${m.jornadas}j · ${mas(m.pnl)}$${n(m.pnl, 0)}</option>`
    ).join('')
    : '<option value="">sin meses con trades</option>';
  return ms;
}

async function cargarMes(mes) {
  correr(false);
  enCorte = false; $('#corte').hidden = true;
  if (!mes) {
    $('#barra').innerHTML = ''; $('#tablero').innerHTML = '';
    $('#cabj').innerHTML = '<span class="tenue">Esta estrategia no tiene jornadas.</span>';
    $('#chart').innerHTML = ''; JORNADAS = []; return;
  }
  const [a, m] = mes.split('-').map(Number);
  const desde = `${mes}-01`;
  const hasta = `${mes}-${String(new Date(a, m, 0).getDate()).padStart(2, '0')}`;
  $('#cabj').innerHTML = '<span class="tenue">cargando el mes…</span>';

  const r = await fetch(`/api/replay?estrategia=${encodeURIComponent(EST)}`
    + `&desde=${desde}&hasta=${hasta}`).then((x) => x.json())
    .catch(() => ({ jornadas: [] }));
  LADO = r.lado || r.jornadas?.[0]?.lado || null;
  JORNADAS = r.jornadas || [];
  if (!JORNADAS.length) {
    $('#cabj').innerHTML = '<span class="tenue">Sin jornadas en ese mes.</span>';
    $('#chart').innerHTML = ''; $('#barra').innerHTML = ''; $('#tablero').innerHTML = '';
    return;
  }
  precomputar();
  const tot = JORNADAS.reduce((a2, j) =>
    a2 + (j.trades || []).reduce((b, t) => b + (t.pnl || 0), 0), 0);
  const dias = new Set(JORNADAS.map((j) => j.d)).size;
  $('#resumen').textContent = `${dias} día${dias === 1 ? '' : 's'} · `
    + `${JORNADAS.length} papel-jornada${JORNADAS.length === 1 ? '' : 's'} · `
    + `${JORNADAS.reduce((a2, j) => a2 + (j.trades || []).length, 0)} trades · `
    + `${mas(tot)}$${n(tot, 2)}`;
  $('#aviso').textContent = LADO ? `lado: ${LADO}` : 'lado deducido de cada trade';
  irA(0, 0);
}

async function cargarEstrategia(nombre) {
  const b = await fetch('/api/bitacora'
    + (nombre ? `?estrategia=${encodeURIComponent(nombre)}` : '')).then((x) => x.json());
  EST = b.estrategia || '';
  MEDIDO = b.medido || {};
  if (!$('#est').options.length) {
    $('#est').innerHTML = (b.estrategias || []).map((e) =>
      `<option value="${esc(e)}">${esc(e)}</option>`).join('');
  }
  $('#est').value = EST;
  pintarMedicion();
  const ms = await cargarMeses();
  await cargarMes(ms.length ? ms[ms.length - 1].mes : '');
}

/* ------------------------------------------------------------------ eventos */

$('#play').addEventListener('click', () => correr(!corriendo));
$('#reiniciar').addEventListener('click', () => { correr(false); irA(0, 0); });
$('#saltar').addEventListener('click', () => {
  if (enCorte) return;
  const sigue = corriendo;
  correr(false);
  if (iJ < JORNADAS.length - 1) { irA(iJ + 1, 0); if (sigue) correr(true); }
  else irA(iJ, PASOS - 1);
});
$('#velocidad').addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-ms]');
  if (!b) return;
  msPorMin = Number(b.dataset.ms);
  $('#velocidad').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
});
/* Clic en la barra: saltar a ese minuto de esa jornada. Es exacto porque el
   estado sale del precómputo y no de haber simulado hasta ahí. */
$('#barra').addEventListener('click', (ev) => {
  const seg = ev.target.closest('.seg');
  if (!seg || !JORNADAS.length) return;
  const r = seg.getBoundingClientRect();
  const p = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
  const sigue = corriendo;
  correr(false);
  enCorte = false; $('#corte').hidden = true;
  irA(Number(seg.dataset.j), Math.round(p * (PASOS - 1)));
  if (sigue) correr(true);
});
$('#est').addEventListener('change', async () => {
  correr(false);
  EST = $('#est').value;
  pintarMedicion();
  const ms = await cargarMeses();
  await cargarMes(ms.length ? ms[ms.length - 1].mes : '');
});
$('#mes').addEventListener('change', () => cargarMes($('#mes').value));
window.addEventListener('resize', dibujarPanel);
$('#soloAccion').addEventListener('change', pintarBarra);
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.code === 'Space') { e.preventDefault(); correr(!corriendo); }
  if (e.key === 'ArrowRight') { correr(false); irA(iJ, min + 5, false); }
  if (e.key === 'ArrowLeft') { correr(false); irA(iJ, min - 5); }
});

cargarEstrategia();
