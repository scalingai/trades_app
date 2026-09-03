/* La sesión de hoy, mientras pasa.
 *
 * Dibuja con `VisorGrafico`, el MISMO módulo que usan la bitácora y la
 * reproducción. Que la ejecución que mirás en vivo se vea idéntica a la que vas
 * a auditar mañana no es prolijidad: si fueran dos dibujos distintos, no
 * podrías comparar lo que hiciste contra lo que el sistema decía.
 *
 * QUÉ SE DIBUJA SOBRE LAS VELAS, y por qué cada cosa:
 *   · promedio de entrada  — el número contra el que se mide todo. El stop real
 *     de la posición no es el de ningún tramo suelto, es el de este promedio.
 *   · stop del promedio    — dónde muere la posición entera.
 *   · proyección p50/p75   — hasta dónde llegó a favor la mitad (y tres cuartos)
 *     de los trades medidos. NO es un objetivo de salida: el sistema sostiene
 *     al cierre, y asegurar se midió once veces que empeora.
 *   · composición          — cómo fue variando el promedio con cada agregado.
 *     Se ve de un vistazo si cada tramo mejoró o empeoró la posición.
 *   · posiciones           — como MetaTrader: un trazo horizontal en el precio
 *     EXACTO de cada entrada, y una linea desde ahi hasta donde cierra. Las
 *     abiertas cierran en el precio de ahora, asi que todas convergen en el
 *     mismo punto y se ve de un vistazo donde esta parada la posicion.
 *
 * El gráfico se CREA una sola vez por papel y después se le cambian los datos.
 * Redibujarlo entero cada 20 segundos perdía el zoom y parpadeaba, y una
 * pantalla que parpadea mientras mandás una orden es una pantalla que no se
 * mira.
 */
(function () {
  const $ = (id) => document.getElementById(id);
  const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
  const hhmm = (h) => (h == null ? '—'
    : String(Math.floor(h)).padStart(2, '0') + ':'
      + String(Math.round((h % 1) * 60)).padStart(2, '0'));
  const signo = (v) => (v >= 0 ? '+' : '');

  const charts = new Map();     // ticker -> {chart, series..., datos, tocado}
  let modal = null;             // el chart grande, uno solo y reusado
  let ultimo = null;            // último payload, para repintar el popup
  let abierto = null;           // ticker que está en el popup
  let timer = null;

  /* ------------------------------------------------------- temporalidad */

  /* LA TEMPORALIDAD ES SOLO VISUAL. La estrategia se mide en velas de UN
     minuto y ahi se queda: las señales, la clasificacion de apertura y el corte
     salen del servidor calculados sobre 1m. Agregar aca, en el navegador,
     garantiza que mirar el grafico en 5m no pueda cambiar ni una decision.

     Si esto se hiciera en el servidor habria un camino, por corto que sea, para
     que el timeframe se filtre al motor — y ese es exactamente el tipo de error
     que no avisa. */
  let TF = 1;
  let RIESGO = 400, PISO = 2;

  function agregar(velas, m) {
    if (m <= 1 || !velas || !velas.length) return velas || [];
    const out = [];
    let b = null;
    velas.forEach((v) => {
      const t = Math.floor(v.time / (m * 60)) * (m * 60);
      if (!b || b.time !== t) {
        b = { time: t, open: v.open, high: v.high, low: v.low, close: v.close };
        out.push(b);
      } else {
        b.high = Math.max(b.high, v.high);
        b.low = Math.min(b.low, v.low);
        b.close = v.close;
      }
    });
    return out;
  }

  function agregarVol(vol, m) {
    if (m <= 1 || !vol || !vol.length) return vol || [];
    const out = [];
    let b = null;
    vol.forEach((v) => {
      const t = Math.floor(v.time / (m * 60)) * (m * 60);
      if (!b || b.time !== t) { b = { time: t, value: v.value, color: v.color }; out.push(b); }
      else { b.value += v.value; b.color = v.color; }
    });
    return out;
  }

  function agregarLinea(pts, m) {
    if (m <= 1 || !pts || !pts.length) return pts || [];
    const out = [];
    let b = null;
    pts.forEach((v) => {
      const t = Math.floor(v.time / (m * 60)) * (m * 60);
      if (!b || b.time !== t) { b = { time: t, value: v.value }; out.push(b); }
      else { b.value = v.value; }
    });
    return out;
  }

  /* Las marcas y las lineas de posicion viven en minutos exactos. En 5m no hay
     vela en 10:03, asi que hay que llevarlas al comienzo de su bucket o la
     libreria las descarta en silencio. */
  const alBucket = (t) => (TF <= 1 ? t : Math.floor(t / (TF * 60)) * (TF * 60));

  /* ---------------------------------------------------------------- capas */

  /* Las líneas horizontales de decisión. Se borran y se rehacen en cada
     refresco porque el promedio se mueve con cada tramo nuevo. */
  function niveles(c, e, cfg) {
    (c.lineas || []).forEach((l) => { try { c.velas.removePriceLine(l); } catch (x) {} });
    c.lineas = [];
    const poner = (price, color, title, style) => {
      if (!price) return;
      c.lineas.push(c.velas.createPriceLine({
        price, color, lineWidth: 1, lineStyle: style,
        axisLabelVisible: true, title,
      }));
    };
    poner(e.precio_prom, '#e8eaed', `prom $${n(e.precio_prom)}`, 0);
    poner(e.stop_prom, '#ef5350', `stop $${n(e.stop_prom)}`, 2);
    poner(e.proy_50, '#26a69a', `p50 $${n(e.proy_50)}`, 2);
    poner(e.proy_75, '#1c6f68', `p75 $${n(e.proy_75)}`, 3);
  }

  /* La composición: el promedio de entrada minuto a minuto, en escalones.
     Escalones y no una curva a propósito — el promedio no cambia entre
     agregados, y dibujarlo interpolado sugeriría un movimiento que no existe. */
  function composicion(c, p, off) {
    const comp = p.estado?.composicion || [];
    if (!comp.length) { c.comp.setData([]); return; }
    const base = ((p.sesion && p.sesion.apertura) || 0) + off;
    const hAts = (h) => alBucket(base + Math.round((h - 9.5) * 3600));
    const fin = base + Math.round(6.6 * 3600);
    const pts = [];
    comp.forEach((x, i) => {
      const t0 = hAts(x.h);
      const t1 = i + 1 < comp.length ? hAts(comp[i + 1].h) : fin;
      pts.push({ time: t0, value: x.prom });
      if (t1 > t0) pts.push({ time: t1 - 1, value: x.prom });
    });
    // Tiempos estrictamente crecientes: la librería descarta la serie entera
    // ante un duplicado, y el síntoma es una capa que simplemente no aparece.
    const limpio = [];
    let ult = -1;
    pts.forEach((x) => { if (x.time > ult) { limpio.push(x); ult = x.time; } });
    c.comp.setData(limpio);
  }

  /* CADA POSICIÓN, COMO LA DIBUJA METATRADER: un trazo horizontal en el precio
     exacto de entrada, y una línea desde ahí hasta donde cierra. Las abiertas
     cierran en el precio de AHORA, así que todas convergen en el mismo punto —
     que es exactamente lo que se quiere ver: dónde está parada la posición.
     Verde si ese tramo va a favor, rojo si va en contra.

     Una serie POR TRAMO y no una sola con cortes. La primera versión metía
     todos los segmentos en una serie separándolos con puntos en blanco, y los
     cortes no cortaban: quedaban diagonales largas uniendo el fin de un
     segmento con el principio del siguiente, cruzando el gráfico entero. Con
     una serie por tramo el problema no puede existir, y además cada una puede
     tener su propio color, que con una sola era imposible. */
  function posiciones(c, p, off) {
    (c.pos || []).forEach((s) => { try { c.chart.removeSeries(s); } catch (e) {} });
    c.pos = [];
    const ts = p.trades_estrategia || [];
    if (!ts.length) return;

    const base = ((p.sesion && p.sesion.apertura) || 0) + off;
    const hAts = (h) => alBucket(base + Math.round((h - 9.5) * 3600));
    const velas = p.velas || [];
    const ahoraT = velas.length ? alBucket(velas[velas.length - 1].time + off) : null;
    const ahoraP = velas.length ? velas[velas.length - 1].close : null;
    const LEAD = 8 * 60;   // el trazo horizontal en el precio de entrada

    ts.forEach((t) => {
      const tEnt = hAts(t.hora_entrada);
      const abierta = t.motivo === 'abierta';
      const tSal = abierta ? ahoraT : hAts(t.hora_salida);
      const pSal = abierta ? ahoraP : t.precio_salida;
      if (tSal == null || pSal == null || tSal <= tEnt) return;

      const gana = t.pnl >= 0;
      const s = c.chart.addLineSeries({
        color: gana ? 'rgba(38,166,154,.95)' : 'rgba(239,83,80,.95)',
        // Las abiertas punteadas y las cerradas solidas: de un vistazo se
        // distingue lo que todavia se puede dar vuelta de lo que ya es plata.
        lineWidth: 2, lineStyle: abierta ? 2 : 0,
        priceLineVisible: false, lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      s.setData([
        { time: Math.max(base - 1740, tEnt - LEAD), value: t.precio_entrada },
        { time: tEnt, value: t.precio_entrada },
        { time: tSal, value: pSal },
      ]);
      c.pos.push(s);
    });
  }

  /* Entradas y cierres con su $. Se separan de `grafico.js` a propósito: acá un
     tramo puede estar ABIERTO, que es un estado que el histórico no tiene. */
  function marcas(p, off) {
    const base = ((p.sesion && p.sesion.apertura) || 0) + off;
    const hAts = (h) => alBucket(base + Math.round((h - 9.5) * 3600));
    const m = [];
    (p.trades_estrategia || []).forEach(function (t, i) {
      m.push({ time: hAts(t.hora_entrada), position: 'aboveBar',
               color: '#ef5350', shape: 'arrowDown',
               text: `${i + 1} $${n(t.precio_entrada)}` });
      if (t.motivo !== 'abierta' && t.hora_salida != null) {
        m.push({ time: hAts(t.hora_salida), position: 'belowBar',
                 color: t.pnl >= 0 ? '#26a69a' : '#ef5350', shape: 'arrowUp',
                 text: `${t.motivo} ${signo(t.pnl)}$${n(t.pnl, 1)}` });
      }
    });
    m.sort((a, b) => a.time - b.time);
    return m;
  }

  /* --------------------------------------------------------------- gráfico */

  function crearChart(el) {
    const c = VisorGrafico.crear(el);
    c.comp = c.chart.addLineSeries({
      color: '#d0d4da', lineWidth: 1, lineStyle: 2, lineType: 1,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    c.pos = [];
    c.lineas = [];
    c.datos = [];
    c.tocado = false;

    /* EL ANCHO NO ESTA LISTO CUANDO SE PINTA, Y ESE ERA TODO EL PROBLEMA.
       La tarjeta se acaba de crear, el navegador todavia no resolvio la grilla
       de dos columnas, y el chart se mide a 192px. Con ese ancho la libreria
       RECORTA EN SILENCIO el rango que se le pide: se pedia 09:00-11:55 y
       quedaba 11:01-11:55 — menos de una hora de las cinco que hay. Eso es lo
       que se veia "sumeado", y por que aparecia y desaparecia segun cuando
       llegaba el refresco.

       El parche anterior era un `requestAnimationFrame` extra, que acierta o
       no segun cuando el navegador termine el layout. Un ResizeObserver no
       adivina: reencuadra cuando el ancho de verdad aparece, y de paso cubre
       colapsar la barra lateral y agrandar la ventana. */
    if (window.ResizeObserver) {
      c.ro = new ResizeObserver(() => {
        if (c.datos.length && !c.tocado) {
          try { encuadrar(c); } catch (e) {}
        }
      });
      c.ro.observe(el);
    }

    /* Si movés el gráfico a mano, deja de reencuadrarse solo. No hay nada más
       molesto que una pantalla que cada veinte segundos te devuelve de donde
       estabas mirando. Vuelve a acomodarse al cambiar de temporalidad. */
    ['wheel', 'mousedown', 'touchstart'].forEach((ev) =>
      el.addEventListener(ev, () => { c.tocado = true; }, { passive: true }));
    return c;
  }

  function pintarChart(c, p) {
    const off = VisorGrafico.desfase(p);
    const map = (a) => (a || []).map((v) => Object.assign({}, v, { time: v.time + off }));
    /* Los datos ya agrupados se guardan: el encuadre razona en INDICES de vela
       y tiene que contar exactamente las que estan en la serie, no las que
       vinieron del server (en 5m son la quinta parte). */
    c.datos = agregar(map(p.velas), TF);
    c.velas.setData(c.datos);
    c.vol.setData(agregarVol(map(p.volumen), TF));
    c.vwap.setData(agregarLinea(map(p.vwap), TF));
    c.velas.setMarkers(marcas(p, off));
    composicion(c, p, off);
    posiciones(c, p, off);
    niveles(c, p.estado || {}, null);
    if (p.niveles && p.niveles.pm_high && !c.pm) {
      c.pm = c.velas.createPriceLine({
        price: p.niveles.pm_high, color: '#5b8def', lineWidth: 1,
        lineStyle: 3, axisLabelVisible: true, title: 'máx pm' });
    }
    if (!c.tocado) encuadrar(c);
  }

  /* DESDE LA PRIMERA VELA, y en indices de vela y no en horas.
     `setVisibleRange` trabaja con tiempos y la libreria lo recorta contra el
     espaciado de barra que tenga en ese momento — por eso fallaba sin avisar.
     `setVisibleLogicalRange` trabaja con indices: es la misma cuenta que usa
     `fitContent` por dentro y no depende del ancho que el chart crea tener. */
  function encuadrar(c) {
    const total = (c.datos || []).length;
    if (!total) return;

    /* DESDE LA PRIMERA VELA, SIEMPRE. Hubo un tope —si el pre-market pesaba
       mas que la sesion, arrancaba mas tarde— y Agus lo saco: prefiere ver el
       dia entero aunque un papel como RDAC opere tres cuartas partes antes de
       las 09:30. Es defendible: en small caps el pre-market ES parte de la
       historia del papel, y el maximo de pre-market es el nivel del que
       depende toda la estrategia.

       Media vela de aire a la izquierda y tres a la derecha, para que la
       ultima no quede pegada al eje de precios. */
    try {
      c.chart.timeScale().setVisibleLogicalRange({ from: -0.5, to: total + 2.5 });
    } catch (err) {
      try { c.chart.timeScale().fitContent(); } catch (e2) {}
    }
  }

  /* ---------------------------------------------------------------- tarjeta */

  /* EL ENCABEZADO EN DOS FILAS, no en cuatro.
     Tenia: identidad, una tira de metadatos con puntos medios, una banda con el
     motivo del descarte, y una fila de cifras con rotulos en versalitas
     espaciadas. Cuatro filas de chrome antes de llegar al grafico, que es lo
     unico que uno quiere mirar.

     Ahora: identidad y precio arriba, cifras abajo. Los rotulos van DESPUES del
     numero, en minuscula y apagados — el numero es lo que se lee, el rotulo es
     lo que se consulta. */

  function cifra(v, rotulo, cls) {
    if (v == null || v === '') return '';
    return `<span class="dato"><b class="${cls || ''}">${v}</b>${rotulo}</span>`;
  }

  function encabezado(p) {
    const e = p.estado || {};
    const nv = p.niveles || {};
    const cambio = (e.precio && nv.prev_close)
      ? 100 * (e.precio - nv.prev_close) / nv.prev_close : null;

    /* El estado del papel en una palabra. La razon completa va abajo con las
       cifras: aca solo hace falta saber de un vistazo si este papel esta en
       juego o no. */
    const estado = e.tramos && e.tramos.length ? null
      : (e.apertura || ((e.descartes || []).some((d) => d.includes('pre-market'))
          ? 'pre-market' : null));
    const rancio = (e.atraso != null && e.atraso > (ultimo?.config?.rancio ?? 3))
      ? `<span class="sello alerta-sello">sin datos ${n(e.atraso, 0)} min</span>` : '';

    const tfs = [1, 5, 15].map((m) =>
      `<button class="tf${m === TF ? ' on' : ''}" data-tf="${m}">${m}m</button>`
    ).join('');

    const fila1 = '<div class="cab">'
      + `<span class="tk">${p.ticker}</span>`
      + `<span class="px">$${n(e.precio)}</span>`
      + (cambio != null
        ? `<span class="chg ${cambio >= 0 ? 'pos' : 'neg'}">${signo(cambio)}${n(cambio, 1)}%</span>`
        : '')
      + rancio
      + (estado ? `<span class="sello">${estado}</span>` : '')
      + `<div class="tfs" role="group" aria-label="Temporalidad">${tfs}</div>`
      + `<button class="lupa" data-tk="${p.ticker}" aria-label="Ampliar ${p.ticker}">⤢</button>`
      + '</div>';

    const abierto = e.tramos && e.tramos.length;
    const fila2 = '<div class="datos">'
      + (abierto ? [
        cifra(n(e.vivas, 0), 'acciones'),
        cifra(n(e.pico, 0), 'pico a localizar'),
        cifra('$' + n(e.precio_prom), 'promedio'),
        cifra('$' + n(e.stop_prom), 'stop'),
        cifra(signo(e.pnl_cerrado ?? 0) + '$' + n(Math.abs(e.pnl_cerrado ?? 0)),
              'cerrado', (e.pnl_cerrado ?? 0) >= 0 ? 'pos' : 'neg'),
        cifra(signo(e.pnl_abierto ?? 0) + '$' + n(Math.abs(e.pnl_abierto ?? 0)),
              'abierto', (e.pnl_abierto ?? 0) >= 0 ? 'pos' : 'neg'),
      ].join('') : [
        cifra('$' + n(nv.prev_close), 'previo'),
        cifra('$' + n(nv.pm_high), 'máx pm'),
        /* Se llamaba "expansión". Es `expansion_pct` de dias.py: "máximo
           pre-market vs cierre previo" — o sea, cuánto corrió ANTES de abrir.
           El nombre viejo es el del motor y ahí se queda; el rótulo de la
           pantalla tiene que decir qué mide. */
        cifra(e.expansion != null ? signo(e.expansion) + n(e.expansion, 0) + '%' : null,
              'pre-market'),
        cifra(e.barras, 'barras'),
      ].join(''))
      + ((e.descartes || []).length
        ? `<span class="motivo">${e.descartes.join(' · ')}</span>` : '')
      + '</div>';

    return fila1 + fila2;
  }

  function tabla(trades) {
    if (!trades.length) return '';
    const filas = trades.map(function (t, i) {
      const ab = t.motivo === 'abierta';
      const chip = ab ? '<span class="chip ab">abierta</span>'
        : `<span class="chip st">${t.motivo} ${hhmm(t.hora_salida)}</span>`;
      return `<tr class="${ab ? '' : 'cerrada'}">`
        + `<td>${i + 1} · ${hhmm(t.hora_entrada)}</td>`
        + `<td>$${n(t.precio_entrada)}</td>`
        + `<td>$${n(t.precio_entrada * (1 + t.stop_pct / 100))}</td>`
        + `<td>${n(t.acciones, 0)}</td><td>${chip}</td>`
        + `<td class="${t.pnl >= 0 ? 'pos' : 'neg'}">${signo(t.pnl)}$${n(t.pnl)}</td></tr>`;
    }).join('');
    return '<details><summary>tramos</summary><table><thead><tr>'
      + '<th>tramo</th><th>entra</th><th>stop</th><th>acc</th>'
      + '<th>estado</th><th>pnl</th></tr></thead><tbody>'
      + filas + '</tbody></table></details>';
  }

  /* LA TARJETA SE ARMA UNA VEZ Y DESPUES SOLO SE ACTUALIZAN SUS PARTES.
     La version anterior reescribia `caja.innerHTML` en cada refresco y despues
     volvia a meter el nodo del grafico con `replaceWith`. Ese ida y vuelta
     DESPRENDE el nodo del DOM, el ResizeObserver de la libreria lo mide en 0x0
     y el chart se encoge a cero — y reengancharlo no lo recupera. El sintoma
     era que las velas quedaban apretadas contra el borde derecho, y se
     "arreglaba" al colapsar la barra lateral porque eso disparaba un resize.

     Con el grafico en su propio nodo, que nadie toca, el problema no existe. */
  function pintarPapel(p) {
    const e = p.estado || {};
    let caja = document.getElementById('p-' + p.ticker);
    if (!caja) {
      caja = document.createElement('section');
      caja.id = 'p-' + p.ticker;
      caja.innerHTML = '<div class="cab-wrap"></div>'
        + `<div class="g" id="g-${p.ticker}"></div>`
        + '<div class="tabla-wrap"></div>';
      $('cuerpo').querySelector('.grilla').appendChild(caja);
    }
    caja.className = 'papel' + ((p.trades_estrategia || []).length ? ' opera' : '')
      + ((e.descartes || []).length ? ' fuera' : '');
    caja.querySelector('.cab-wrap').innerHTML = encabezado(p)
      + (e.tope ? '<div class="alerta">En el límite diario — no abre más tramos</div>' : '');

    /* La tabla se reescribe, pero conserva si estaba desplegada: si no, se
       cerraria sola cada 20 segundos mientras uno la mira. */
    const cont = caja.querySelector('.tabla-wrap');
    const abiertoDet = cont.querySelector('details')?.open;
    cont.innerHTML = tabla(p.trades_estrategia || []);
    const det = cont.querySelector('details');
    if (det && abiertoDet) det.open = true;

    let c = charts.get(p.ticker);
    if (!c) {
      c = crearChart(document.getElementById('g-' + p.ticker));
      charts.set(p.ticker, c);
    }
    pintarChart(c, p);
  }

  /* --------------------------------------------------------------- mando */

  /* QUE ESTA PASANDO, EN UNA COLUMNA. Mientras la operativa se simula acá, esto
     es lo que hay que mirar: qué está operando, qué está esperando, y cómo
     viene el día. Los gráficos son el contexto de eso, no al revés. */

  /* EL EMBUDO DE LA JORNADA.

     Antes esto era un reloj: tres horas con la palabra "pasó" al costado y,
     debajo, la receta escrita en prosa. Decía CUANDO pasan las cosas y no
     QUE PASO — que es lo único que uno quiere saber a media rueda.

     Ahora es lo que realmente hace `evaluar()` en puente/vivo.py: una fila de
     filtros, en el mismo orden en que los aplica el motor, con cuántos papeles
     sobrevivieron a cada uno. Leído de arriba abajo se ve exactamente dónde se
     cae la watchlist — y hoy se cae entera en "abrió reclaim", que es la
     razón por la que no hay trades.

     El orden NO es decorativo: es el orden del motor. Un papel que muere en
     "expansión" nunca llega a que se le mire la apertura, así que no puede
     contarse en las filas de abajo. */
  const NIVELES = [
    'en la watchlist',
    'abrió el mercado',
    'con pre-market medido',
    'corrió en pre-market',
    'apertura clasificada',
    'abrió',
    'dio señal',
  ];

  /* Cuántos filtros sobrevivió un papel. Las preguntas van en el orden del
     motor y devuelven en cuál se quedó: un papel que muere temprano no tiene
     información sobre los filtros de más abajo, y eso es correcto — nunca se
     los aplicaron. */
  function nivel(p) {
    const e = p.estado || {};
    const d = (e.descartes || []).join(' · ');
    if (d.includes('todavia en pre-market')) return 0;
    if (e.sin_premarket || d.includes('no se parece')) return 1;
    if (d.includes('expansion')) return 2;
    if (d.includes('se clasifica a las 10:00')) return 3;
    if (d.includes('se opera')) return 4;
    if (!(p.trades_estrategia || []).length) return 5;
    return 6;
  }

  function embudo(ps, c) {
    const total = ps.length;
    const niveles = ps.map(nivel);
    /* La hora que habilita cada filtro, donde exista. Las dos primeras las
       fija el mercado; la de la apertura la fija la estrategia. */
    const horas = [null, 9.5, null, null, c.desde, null, null];
    /* El detalle es el UMBRAL del filtro, no una segunda descripcion: sin el,
       "corrió en pre-market" no dice contra que se compara. */
    const detalle = [null, null, null, `≥${c.expansion}%`,
                     null, c.apertura, null];
    return NIVELES.map((rot, i) => {
      const n0 = i === 0 ? total : niveles.filter((v) => v >= i).length;
      const pct = total ? Math.round(100 * n0 / total) : 0;
      return `<div class="filtro${n0 ? '' : ' seco'}">`
        + `<span class="pf" style="width:${pct}%"></span>`
        + `<b>${n0}</b><span class="q">${rot}`
        + (detalle[i] ? `<em> ${detalle[i]}</em>` : '') + '</span>'
        + (horas[i] ? `<i>${hhmm(horas[i])}</i>` : '<i></i>')
        + '</div>';
    }).join('');
  }

  /* LO QUE FALTA DEL DIA. Son las dos cosas que el sistema HACE solo, y por eso
     no son filtros: a las 11 corta lo que no está ganando, a las 16 cierra
     todo. La palabra "pasó" no decía nada — ahora dice cuántos cortó. */
  function pendientes(ps, c) {
    if (c.ahora == null) return '';
    const cortados = ps.reduce((a, p) => a + (p.trades_estrategia || [])
      .filter((t) => t.motivo === 'corte').length, 0);
    const hitos = [
      [c.corte, `corta lo que no gane ${c.corte_umbral}%`,
       cortados ? `${cortados} cortado${cortados === 1 ? '' : 's'}` : 'ninguno'],
      [c.cierre, 'cierra todo', null],
    ];
    return hitos.map(([h, que, hecho]) => {
      const falta = (h - c.ahora) * 60;
      const paso = falta < 0;
      const cuando = paso ? (hecho || 'listo')
        : falta < 60 ? `en ${Math.round(falta)} min`
        : `en ${Math.floor(falta / 60)}h ${Math.round(falta % 60)}m`;
      return `<div class="hito ${paso ? 'paso' : (falta < 30 ? 'ahora' : '')}">`
        + (paso
          ? '<svg class="tick" viewBox="0 0 16 16" fill="none" stroke="currentColor"'
            + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            + '<path d="M3.4 8.4l3.1 3.1 6.1-6.6"/></svg>'
          : '<span class="tick"></span>')
        + `<b>${hhmm(h)}</b><span>${que}</span>`
        + `<span class="cuando">${cuando}</span></div>`;
    }).join('');
  }

  function pintarMando(d) {
    const c = d.config || {};
    const ps = d.papeles || [];
    const conTramos = ps.filter((p) => (p.trades_estrategia || []).length);
    const esperando = ps.filter((p) => !(p.trades_estrategia || []).length
      && !(p.estado?.descartes || []).length);

    /* El dia simulado: lo cerrado ya es plata, lo abierto todavia se puede dar
       vuelta. Sumarlos en un solo numero esconde justo esa diferencia. */
    const cerrado = conTramos.reduce((a, p) => a + (p.estado.pnl_cerrado || 0), 0);
    const abierto = conTramos.reduce((a, p) => a + (p.estado.pnl_abierto || 0), 0);
    const com = conTramos.reduce((a, p) => a + (p.estado.comision || 0), 0);
    const tramos = conTramos.reduce((a, p) => a + p.trades_estrategia.length, 0);
    const neto = cerrado + abierto - com;

    /* Riesgo consumido: cuanto de la caja del dia esta comprometido. Es lo que
       dice si entra otro tramo, y hasta ahora no estaba en ningun lado. */
    const riesgo = RIESGO;
    const usado = Math.max(0, -Math.min(0, cerrado + abierto));
    const pct = Math.min(100, 100 * usado / riesgo);

    const bloque = (titulo, cuerpo) =>
      `<div class="bloque"><h2>${titulo}</h2>${cuerpo}</div>`;

    /* Una cifra con su rotulo debajo. El cero va en gris y no en verde: no
       ganaste nada, y pintarlo de verde lo haria parecer un resultado. */
    const par = (v, rotulo) =>
      `<div class="cifra2"><b class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">`
      + `${signo(v)}$${n(Math.abs(v))}</b><span>${rotulo}</span></div>`;

    /* La cinta: todos los eventos del dia de todos los papeles, en orden, lo
       ultimo arriba. Es "como viene la operativa" leido de un tiron. */
    const eventos = [];
    conTramos.forEach((p) => {
      (p.trades_estrategia || []).forEach((t, i) => {
        eventos.push({ h: t.hora_entrada, tk: p.ticker,
          que: `short ${n(t.acciones, 0)} acc`, m: '$' + n(t.precio_entrada) });
        if (t.motivo !== 'abierta' && t.hora_salida != null) {
          eventos.push({ h: t.hora_salida, tk: p.ticker, que: t.motivo,
            m: signo(t.pnl) + '$' + n(Math.abs(t.pnl)),
            cls: t.pnl >= 0 ? 'pos' : 'neg' });
        }
      });
    });
    eventos.sort((a, b) => b.h - a.h);

    /* EL ORDEN DE LA COLUMNA ES EL ORDEN EN QUE SE MIRA, y hasta ahora no lo
       era: arriba de todo estaban los AJUSTES —que se tocan una vez por día— y
       el número del día quedaba tercero, a media columna de scroll. Con ocho
       bloques del mismo gris y rótulos de 10px, nada saltaba.

       Ahora baja por urgencia: cuánto voy hoy, qué tengo abierto, qué falta
       para el próximo hito, qué espera, qué pasó. Los ajustes se fueron a una
       ruedita en la esquina del primer bloque: se tocan una vez por día y
       después se miran cero veces — no se ganan un renglón permanente. */
    $('mando').innerHTML = [
      /* 1. EL NUMERO DEL DIA. Uno por pantalla, y es este.

         Antes esto eran tres renglones grises del mismo peso: el numero, una
         cadena "0 tramos · cerrado +$0.00 · abierto +$0.00" con todo mezclado,
         y otra cadena con el riesgo. Cerrado y abierto son cosas DISTINTAS
         —uno ya es plata, el otro todavia se puede dar vuelta— y meterlos en
         la misma linea separados por puntos medios los hace parecer lo mismo.

         Encima, con el dia en cero, la barra de riesgo quedaba vacia y se leia
         como una linea divisoria: parecia decoracion en vez de medir algo. */
      `<div class="bloque jefe">`
      + '<button class="rueda" id="aj-abrir" type="button" aria-label="Ajustes">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
      + ' stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
      + '<circle cx="12" cy="12" r="3.1"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8'
      + 'l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5'
      + 'v.2a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1'
      + 'a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H2.2'
      + 'a2 2 0 0 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1'
      + 'a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V2.2'
      + 'a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1'
      + 'a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.2'
      + 'a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z"/></svg></button>'
      + '<div class="jefe-cab">'
      + `<span class="gran ${neto > 0 ? 'pos' : neto < 0 ? 'neg' : 'cero'}">`
      + `${signo(neto)}$${n(Math.abs(neto))}</span>`
      + '<span class="que">operado hoy</span></div>'

      /* Cerrado y abierto, cada uno con su rotulo abajo y su columna. La
         diferencia entre los dos es la unica que importa a media rueda. */
      + '<div class="jefe-desglose">'
      + par(cerrado, 'cerrado') + par(abierto, 'abierto')
      + `<div class="cifra2"><b>${tramos}</b>`
      + `<span>tramo${tramos === 1 ? '' : 's'}</span></div>`
      + '</div>'

      /* El riesgo, como medidor y no como renglon: el rotulo y el numero
         arriba, la barra abajo. Asi en cero se lee "no gastaste nada" en vez
         de parecer un separador. */
      + '<div class="riesgo"><div class="riesgo-cab"><span>riesgo del día</span>'
      + `<b>$${n(usado, 0)} <i>de $${n(riesgo, 0)}</i></b></div>`
      + `<div class="barra"><i class="${pct > 85 ? 'lleno' : ''}"`
      + ` style="width:${Math.max(pct, pct > 0 ? 2 : 0)}%"></i></div></div></div>`,

      /* 2. QUE TENGO ABIERTO. Es lo único de la pantalla sobre lo que se puede
         actuar ahora mismo, así que va pegado al número. */
      bloque(`operando · ${conTramos.length}`, conTramos.length
        ? conTramos.map((p) => {
          const e = p.estado;
          return '<div class="pos-fila">'
            + `<span class="tk2">${p.ticker}</span>`
            + `<span class="num ${(e.pnl_abierto || 0) >= 0 ? 'pos' : 'neg'}">`
            + `${signo(e.pnl_abierto || 0)}$${n(Math.abs(e.pnl_abierto || 0))}</span>`
            + `<span class="det">${n(e.vivas, 0)} acc · prom $${n(e.precio_prom)}`
            + ` · stop $${n(e.stop_prom)}</span></div>`;
        }).join('')
        : '<div class="nada">nada abierto</div>'),

      /* 3. EL EMBUDO. Antes acá había un reloj —tres horas con la palabra
         "pasó" al costado— y la receta escrita en prosa. Decía CUANDO pasan
         las cosas y no QUE PASO, que es lo único que uno quiere saber a media
         rueda. Ahora son los filtros del motor en orden, con cuántos papeles
         sobrevivió cada uno. */
      bloque('sesión · nueva york ' + hhmm(c.ahora),
        embudo(ps, c) + '<div class="pendientes">' + pendientes(ps, c) + '</div>'),

      bloque(`esperando señal · ${esperando.length}`, esperando.length
        ? '<div class="chips">' + esperando.map((p) =>
            `<span class="chip2 espera">${p.ticker}</span>`).join('') + '</div>'
        : '<div class="nada">ninguno califica</div>'),

      bloque('cinta', eventos.length
        ? '<div class="cinta">' + eventos.map((x) =>
            `<div class="ev"><span class="h">${hhmm(x.h)}</span>`
            + `<span class="q"><b>${x.tk}</b> ${x.que}</span>`
            + `<span class="m ${x.cls || ''}">${x.m}</span></div>`).join('')
          + '</div>'
        : '<div class="nada">sin movimientos</div>'),
    ].join('');
  }

  /* ----------------------------------------------------------------- popup */

  function abrirModal(tk) {
    const p = (ultimo?.papeles || []).find((x) => x.ticker === tk);
    if (!p) return;
    abierto = tk;
    $('modal').classList.add('abierto');
    if (!modal) modal = crearChart($('gmodal'));
    else modal.tocado = false;          // reencuadrar al abrir otro papel
    pintarModal(p);
  }

  function pintarModal(p) {
    const e = p.estado || {};
    $('mtk').textContent = p.ticker;
    $('mmeta').textContent =
      `$${n(e.precio)} · ${hhmm(e.hora)} · prom $${n(e.precio_prom)} · `
      + `stop $${n(e.stop_prom)} · p50 $${n(e.proy_50)} · `
      + `cerrado ${signo(e.pnl_cerrado ?? 0)}$${n(e.pnl_cerrado ?? 0)} · `
      + `abierto ${signo(e.pnl_abierto ?? 0)}$${n(e.pnl_abierto ?? 0)}`;
    pintarChart(modal, p);
    try { modal.chart.resize($('gmodal').clientWidth, $('gmodal').clientHeight); }
    catch (err) {}
  }

  function cerrarModal() {
    $('modal').classList.remove('abierto');
    abierto = null;
  }

  /* ------------------------------------------------------------------ ciclo */

  async function tick() {
    let d;
    try {
      const r = await fetch(`/api/vivo?riesgo=${RIESGO}&piso=${PISO}`);
      d = await r.json();
    } catch (err) {
      /* Sin barra donde avisar, la falta de conexion se dice donde se mira:
         en el panel, que es lo unico que queda arriba. */
      $('mando').innerHTML =
        '<div class="bloque"><h2>sin conexión</h2>'
        + '<div class="nada">el visor no responde</div></div>';
      return;
    }
    if (d.error) {
      $('cuerpo').innerHTML = `<div class="vacio">Error: ${d.error}</div>`;
      return;
    }
    ultimo = d;
    const c = d.config || {};
    if (!d.existe) {
      charts.clear();
      $('cuerpo').innerHTML = `<div class="vacio"><p>No hay feed todavía.</p>`
        + `<p>Poné el indicador <code>TTPFeedMulti</code> en un gráfico y escribí`
        + ` la watchlist.</p><p style="margin-top:1em"><code>${d.feed}</code></p></div>`;
      return;
    }
    /* El aviso global usa el papel MENOS atrasado: si hasta el más fresco está
       viejo, se cortó todo. El por-papel va en cada cabecera, porque con un
       aviso sólo global uno que sigue llegando tapa a los demás. */
    const atrasos = d.papeles.map((p) => p.estado?.atraso).filter((x) => x != null);
    const min = atrasos.length ? Math.min(...atrasos) : null;
    $('alarma').innerHTML = (min != null && min > (c.rancio ?? 3))
      /* El feed cortado NO es plata perdida: es "lo de abajo esta viejo". Iba
         en un muro rojo a todo el ancho con cuatro renglones de instrucciones
         que uno ya se sabe. Ambar, un renglon, y el dato que importa —hace
         cuanto— adelante. */
      ? '<div class="alarma"><span class="luz"></span>'
        + `<b>Feed frenado hace ${n(min, 0)} min</b>`
        + '<span class="que">— revisá que Trade The Pool diga “Connected”.'
        + ' Lo de abajo está viejo.</span></div>'
      : '';

    if (!$('cuerpo').querySelector('.grilla')) {
      $('cuerpo').innerHTML = '<div class="grilla"></div>';
    }
    if (!d.papeles.length) {
      $('cuerpo').innerHTML = '<div class="vacio">Hay feed, pero ninguna barra de hoy.</div>';
    } else {
      /* Sacar los papeles que dejaron de venir, para no dejar un gráfico
         congelado que parezca vivo. */
      const hay = new Set(d.papeles.map((p) => p.ticker));
      Array.from(charts.keys()).forEach(function (tk) {
        if (!hay.has(tk)) {
          try { charts.get(tk).chart.remove(); } catch (e) {}
          charts.delete(tk);
          document.getElementById('p-' + tk)?.remove();
        }
      });
      d.papeles.forEach(pintarPapel);
      /* Los que operan primero: en una pantalla que se mira de reojo, lo
         accionable no puede estar abajo de seis graficos descartados. */
      const grilla = $('cuerpo').querySelector('.grilla');
      d.papeles.slice().sort((a, b) =>
        (b.trades_estrategia || []).length - (a.trades_estrategia || []).length
        || (a.estado?.descartes || []).length - (b.estado?.descartes || []).length
      ).forEach((p) => {
        const el = document.getElementById('p-' + p.ticker);
        if (el) grilla.appendChild(el);
      });
      if (abierto) {
        const p = d.papeles.find((x) => x.ticker === abierto);
        if (p) pintarModal(p); else cerrarModal();
      }
    }
    pintarMando(d);
    pintarScanner(d);
    const con = d.papeles.filter((p) => (p.trades_estrategia || []).length).length;
  }

  /* El refresco es incondicional: no hay boton para apagarlo porque no hay
     razon para apagarlo. Una pantalla de operar que se puede congelar sin
     querer es una trampa. */
  function reprogramar() {
    if (timer) clearInterval(timer);
    timer = setInterval(tick, 20000);
  }

  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('.lupa');
    if (b) { abrirModal(b.dataset.tk); return; }
    const t = ev.target.closest('.tf');
    if (t) {
      TF = Number(t.dataset.tf) || 1;
      try { localStorage.setItem('visor.vivo.tf', String(TF)); } catch (e) {}
      /* Reencuadrar todos: en 5m hay una quinta parte de las velas y el rango
         que quedo de 1m mostraria una franja vacia. Cambiar de temporalidad
         tambien perdona el "lo movi a mano": es un gesto de volver a mirar el
         conjunto, no de conservar el zoom que tenias. */
      charts.forEach((c) => { c.tocado = false; });
      if (modal) modal.tocado = false;
      tick();
    }
  });
  $('mcerrar').addEventListener('click', cerrarModal);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && abierto) cerrarModal();
  });
  window.addEventListener('resize', () => {
    if (abierto && modal) {
      try { modal.chart.resize($('gmodal').clientWidth, $('gmodal').clientHeight); }
      catch (e) {}
    }
  });
  /* ------------------------------------------------------------ watchlist */

  /* LOS ESTADOS DE UN PAPEL EN EL DIA, que son SIETE y no tres. Salen de leer
     `evaluar()` en puente/vivo.py de arriba a abajo — son las salidas reales de
     esa función, no una categoría inventada para la pantalla:

       pre-market   antes de las 09:30. Todavía no empezó nada.
       abriendo     09:30 a 10:00. Abrió, pero la apertura se clasifica a las
                    10:00 y hasta entonces no se sabe si sirve. NO es
                    pre-market: el papel ya está operando en el mercado, sólo
                    que nosotros todavía no.
       no califica  quedó afuera por el filtro: expansión < 0%, o abrió fade
                    cuando operamos reclaim. El motivo completo va en el título.
       espera       CALIFICA y todavía no dio señal. Es el estado más
                    importante de los siete y el que no estaba: son los que
                    pueden disparar en cualquier momento.
       operando     tiene tramos vivos.
       cerrado      tuvo tramos y ya están todos cerrados (stop, corte o cierre).
       revisar      no es un estado del mercado sino un problema del DATO, y
                    por eso es el único en ámbar. Dos causas: el gráfico vino
                    sin sesión extendida (sin eso no hay expansión y el filtro
                    no filtra nada), o el precio no se parece al de la
                    watchlist y puede ser otro instrumento con el mismo
                    símbolo. Las dos piden ir a tocar algo en la plataforma. */
  const ESTADOS = {
    operando:   { nombre: 'operando',
                  d: '<circle cx="8" cy="8" r="3.4" fill="currentColor" stroke="none"/>'
                   + '<circle cx="8" cy="8" r="6.2"/>' },
    cerrado:    { nombre: 'cerrado',
                  d: '<path d="M3.4 8.4l3.1 3.1 6.1-6.6"/>' },
    espera:     { nombre: 'espera señal',
                  d: '<circle cx="8" cy="8" r="4.1"/><path d="M8 .9v2.4M8 12.7v2.4'
                   + 'M.9 8h2.4M12.7 8h2.4"/>' },
    abriendo:   { nombre: 'abriendo · clasifica 10:00',
                  d: '<circle cx="8" cy="8" r="6.2"/><path d="M8 4.4V8l2.5 1.6"/>' },
    premarket:  { nombre: 'pre-market',
                  d: '<path d="M13.4 9.6A5.9 5.9 0 0 1 6.1 2.4a5.9 5.9 0 1 0 7.3 7.2z"/>' },
    nocalifica: { nombre: 'no califica',
                  d: '<circle cx="8" cy="8" r="6.2"/><path d="M5.2 8h5.6"/>' },
    /* No hay un octavo icono para "puede ser otro instrumento": para quien
       mira es el MISMO problema que "falta el pre-market" —el dato no se puede
       creer y hay que ir a arreglar algo afuera de la app—, y siete formas ya
       son las que se pueden aprender. Cuál de los dos es, lo dice el título. */
    revisar:    { nombre: 'revisar el dato',
                  d: '<path d="M8 2.2 14.6 13.4H1.4z"/><path d="M8 6.6v3M8 11.4v.1"/>' },
  };

  /* El orden de las preguntas es el orden en que decide el motor. Invertirlo
     cambia el resultado: un papel con tramos abiertos TAMBIEN puede tener un
     descarte viejo colgado, y preguntar por el descarte primero lo mostraria
     como "no califica" mientras está short. */
  function estadoDe(p) {
    const e = p.estado || {};
    const d = e.descartes || [];
    const tr = p.trades_estrategia || [];
    if (tr.length) {
      return tr.some((t) => t.motivo === 'abierta') ? 'operando' : 'cerrado';
    }
    /* El orden importa y las coincidencias son EXACTAS a proposito: el texto
       de "sin premarket: prendé la sesión extendida" contiene la palabra
       premarket, asi que un `includes('premarket')` suelto lo clasificaria
       como "todavia no abrio" — el error de configuracion desaparecido
       adentro de un estado normal, que es la peor forma de perderlo. */
    if (e.sin_premarket) return 'revisar';
    if (d.some((x) => x.includes('no se parece'))) return 'revisar';
    if (d.some((x) => x.includes('todavia en pre-market'))) return 'premarket';
    if (d.some((x) => x.includes('se clasifica a las 10:00'))) return 'abriendo';
    if (d.length) return 'nocalifica';
    return 'espera';
  }

  const icono = (k) => '<svg class="ico" viewBox="0 0 16 16" fill="none"'
    + ' stroke="currentColor" stroke-width="1.5" stroke-linecap="round"'
    + ` stroke-linejoin="round">${ESTADOS[k].d}</svg>`;

  /* EL SCANNER. Cuatro columnas con encabezado, como cualquier terminal: qué
     es, a cuánto está, cuánto lleva hoy y cuánto corrió en pre-market.

     La columna `pm` es `expansion_pct` de dias.py — "máximo pre-market vs
     cierre previo". Es la variable del filtro y hasta ahora sólo se veía
     adentro de la tarjeta rotulada "expansión", que no le decía a nadie que
     estaba hablando del pre-market. */
  function pintarScanner(d) {
    const ps = d.papeles || [];
    if (!ps.length) {
      $('wl-lista').innerHTML = '<div class="wl-vacio">sin datos todavía</div>';
      return;
    }
    $('wl-lista').innerHTML =
      '<div class="wl-cols"><span></span><span>papel</span>'
      + '<span>precio</span><span>día</span><span>pm</span></div>'
      + ps.map((p) => {
        const e = p.estado || {};
        const nv = p.niveles || {};
        const k = estadoDe(p);
        const st = ESTADOS[k];
        const v = (e.precio && nv.prev_close)
          ? 100 * (e.precio - nv.prev_close) / nv.prev_close : null;
        const motivo = (e.descartes || []).length
          ? st.nombre + ' — ' + e.descartes.join(' · ') : st.nombre;
        return `<div class="wl-fila e-${k}" data-tk="${p.ticker}" title="${motivo}">`
          + icono(k)
          + `<span class="tk3">${p.ticker}</span>`
          + `<span class="p">$${n(e.precio)}</span>`
          + `<span class="v ${v >= 0 ? 'pos' : 'neg'}">`
          + `${v == null ? '—' : signo(v) + n(v, 1) + '%'}</span>`
          + `<span class="pm">${e.expansion == null ? '—'
              : signo(e.expansion) + n(e.expansion, 0) + '%'}</span>`
          + '</div>';
      }).join('');
  }

  async function cargarWatchlist() {
    try {
      const d = await (await fetch('/api/watchlist')).json();
      $('wl-txt').value = d.texto || '';
      const n = (d.texto || '').split(/\r?\n/).filter((x) => x.trim()).length;
      $('wl-n').textContent = n ? `${n} papeles` : 'vacía';
    } catch (e) {
      $('wl-n').textContent = 'no se pudo leer';
    }
  }

  async function guardarWatchlist() {
    const msg = $('wl-msg');
    msg.textContent = 'guardando…';
    msg.className = '';
    try {
      const r = await fetch('/api/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ texto: $('wl-txt').value }),
      });
      const d = await r.json();
      if (d.error) {
        msg.textContent = d.error;
        msg.className = 'neg';
        return;
      }
      msg.textContent = `guardada · ${d.papeles} papeles`
        + (d.sin_precio ? ` · ${d.sin_precio} SIN PRECIO` : '');
      msg.className = d.sin_precio ? 'neg' : 'pos';
      $('wl-n').textContent = String(d.papeles);
      /* Refrescar enseguida: el indicador relee el archivo en su proximo ciclo,
         asi que la pantalla se pone al dia sola en menos de un minuto. */
      tick();
    } catch (e) {
      msg.textContent = 'no se pudo guardar';
      msg.className = 'neg';
    }
  }

  try { TF = Number(localStorage.getItem('visor.vivo.tf')) || 1; } catch (e) {}

  $('wl-guardar').addEventListener('click', guardarWatchlist);
  $('wl-editar').addEventListener('click', () => {
    const ed = $('wl-editor');
    const abierto2 = ed.hidden;
    ed.hidden = !abierto2;
    $('wl-editar').setAttribute('aria-expanded', String(abierto2));
    $('wl-editar').textContent = abierto2 ? 'listo' : 'editar';
  });
  $('wl-lista').addEventListener('click', (ev) => {
    const f = ev.target.closest('.wl-fila');
    if (!f || !f.dataset.tk) return;
    document.getElementById('p-' + f.dataset.tk)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  /* Los inputs viven en markup fijo, pero la RUEDITA se repinta con el mando
     cada 20 segundos: por eso el listener va en el documento y no en el boton,
     que a los veinte segundos ya no es el mismo nodo. */
  $('riesgo').value = RIESGO;
  $('piso').value = PISO;
  document.addEventListener('change', (ev) => {
    if (ev.target.id === 'riesgo') { RIESGO = Number(ev.target.value) || 400; tick(); }
    if (ev.target.id === 'piso') { PISO = Number(ev.target.value) || 2; tick(); }
  });

  /* El popover se ancla a la ruedita en vez de centrarse: nace de donde lo
     abriste, que es como se sabe de que es. Se posiciona al abrir y no en CSS
     porque el boton se mueve con la columna. */
  function ajustes(abrir) {
    const caja = $('ajustes');
    if (abrir) {
      const r = $('aj-abrir').getBoundingClientRect();
      caja.hidden = false;
      $('aj-fondo').hidden = false;
      /* Si no entra abajo, se acuesta contra el borde: nunca fuera de pantalla. */
      const alto = caja.offsetHeight;
      caja.style.top = Math.min(r.bottom + 8, window.innerHeight - alto - 12) + 'px';
      caja.style.left = Math.max(12, r.right - caja.offsetWidth) + 'px';
      $('riesgo').focus();
    } else {
      caja.hidden = true;
      $('aj-fondo').hidden = true;
    }
  }
  document.addEventListener('click', (ev) => {
    if (ev.target.closest('#aj-abrir')) { ajustes($('ajustes').hidden); return; }
    if (ev.target.id === 'aj-fondo') ajustes(false);
  });
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape' && !$('ajustes').hidden) ajustes(false);
  });
  cargarWatchlist();

  tick();
  reprogramar();
})();
