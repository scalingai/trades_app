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

  const charts = new Map();     // ticker -> {chart, series..., primera}
  let modal = null;             // el chart grande, uno solo y reusado
  let ultimo = null;            // último payload, para repintar el popup
  let abierto = null;           // ticker que está en el popup
  let timer = null;

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
    const hAts = (h) => base + Math.round((h - 9.5) * 3600);
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
    const hAts = (h) => base + Math.round((h - 9.5) * 3600);
    const velas = p.velas || [];
    const ahoraT = velas.length ? velas[velas.length - 1].time + off : null;
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
    const hAts = (h) => base + Math.round((h - 9.5) * 3600);
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
    c.primera = true;
    c.lineas = [];
    return c;
  }

  function pintarChart(c, p) {
    const off = VisorGrafico.desfase(p);
    const map = (a) => (a || []).map((v) => Object.assign({}, v, { time: v.time + off }));
    c.velas.setData(map(p.velas));
    c.vol.setData(map(p.volumen));
    c.vwap.setData(map(p.vwap));
    c.velas.setMarkers(marcas(p, off));
    composicion(c, p, off);
    posiciones(c, p, off);
    niveles(c, p.estado || {}, null);
    if (p.niveles && p.niveles.pm_high && !c.pm) {
      c.pm = c.velas.createPriceLine({
        price: p.niveles.pm_high, color: '#5b8def', lineWidth: 1,
        lineStyle: 3, axisLabelVisible: true, title: 'máx pm' });
    }
    if (c.primera) {
      /* Encuadre: desde las 09:00 hasta AHORA, no hasta las 16:10.
         Pedir un `to` más allá del último dato hace que la librería rechace el
         rango entero y caiga en `fitContent()`, que muestra desde las 04:00 —
         y el premarket de un gapper es tan alto que aplasta toda la rueda
         contra el piso del gráfico. En vivo el día todavía no terminó, así que
         el borde derecho es el último minuto que llegó. */
      const base = ((p.sesion && p.sesion.apertura) || 0) + off;
      const velas = p.velas || [];
      const fin = velas.length ? velas[velas.length - 1].time + off : base;
      try {
        c.chart.timeScale().applyOptions({ rightOffset: 6 });
        c.chart.timeScale().setVisibleRange({ from: base - 1800, to: fin });
      } catch (err) { c.chart.timeScale().fitContent(); }
      c.primera = false;
    }
  }

  /* ---------------------------------------------------------------- tarjeta */

  function franja(e) {
    const cer = e.pnl_cerrado ?? 0, ab = e.pnl_abierto ?? 0;
    const neto = (e.equity ?? 0) - (e.comision ?? 0);
    const cif = (v, r, cls) =>
      `<div class="cif"><div class="n ${cls || ''}">${v}</div><div class="r">${r}</div></div>`;
    return '<div class="franja">'
      + cif(n(e.vivas, 0), 'acciones abiertas')
      + cif(n(e.pico, 0), 'pico · a localizar')
      + cif('$' + n(e.precio_prom), 'promedio')
      + cif(`${signo(cer)}$${n(cer)}`, 'pnl cerrado', cer >= 0 ? 'pos' : 'neg')
      + cif(`${signo(ab)}$${n(ab)}`, 'pnl abierto', ab >= 0 ? 'pos' : 'neg')
      + cif(`${signo(neto)}$${n(neto)}`, 'neto · lím $' + n(e.limite, 0),
            neto >= 0 ? 'pos' : 'neg')
      + '</div>';
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

  function cabecera(p) {
    const e = p.estado || {};
    const meta = `${hhmm(e.hora)} · ${e.barras} barras`
      + (e.expansion != null ? ` · exp ${n(e.expansion, 0)}%` : '')
      + (e.apertura ? ` · ${e.apertura}` : '');
    const rancio = (e.atraso != null && e.atraso > (ultimo?.config?.rancio ?? 3))
      ? `<span class="rancio">SIN DATOS HACE ${n(e.atraso, 0)} MIN</span>` : '';
    return '<div class="cab">'
      + `<span class="tk">${p.ticker}</span>`
      + `<span class="px">$${n(e.precio)}</span>`
      + `<span class="meta">${meta}</span>${rancio}`
      + `<button class="lupa" data-tk="${p.ticker}">⤢ ampliar</button></div>`;
  }

  function pintarPapel(p) {
    const e = p.estado || {};
    const id = 'g-' + p.ticker;
    let caja = document.getElementById('p-' + p.ticker);
    const descartado = e.descartes && e.descartes.length;
    const cuerpo = descartado
      ? '<div class="descarte"><ul>'
        + e.descartes.map((d) => `<li>✗ ${d}</li>`).join('') + '</ul></div>'
      : franja(e)
        + (e.tope ? '<div class="alerta">En el límite diario — no abre más tramos</div>' : '')
        + `<div class="g" id="${id}"></div>`
        + tabla(p.trades_estrategia || []);

    if (!caja) {
      caja = document.createElement('section');
      caja.id = 'p-' + p.ticker;
      $('cuerpo').querySelector('.grilla').appendChild(caja);
    }
    caja.className = 'papel' + ((p.trades_estrategia || []).length ? ' opera' : '');

    /* El nodo del gráfico se PRESERVA entre refrescos: destruirlo perdería el
       zoom y el scroll, justo mientras se está mirando para mandar una orden.
       Lo mismo con <details>, o se cerraría sola cada 20 segundos. */
    const viejo = document.getElementById(id);
    const abiertoDet = caja.querySelector('details')?.open;
    caja.innerHTML = cabecera(p) + cuerpo;
    if (viejo && charts.has(p.ticker)) {
      const nuevo = document.getElementById(id);
      if (nuevo) nuevo.replaceWith(viejo);
    }
    const det = caja.querySelector('details');
    if (det && abiertoDet) det.open = true;

    if (!document.getElementById(id)) return;
    let c = charts.get(p.ticker);
    if (!c) { c = crearChart(document.getElementById(id)); charts.set(p.ticker, c); }
    pintarChart(c, p);
  }

  /* ----------------------------------------------------------------- popup */

  function abrirModal(tk) {
    const p = (ultimo?.papeles || []).find((x) => x.ticker === tk);
    if (!p) return;
    abierto = tk;
    $('modal').classList.add('abierto');
    if (!modal) modal = crearChart($('gmodal'));
    else modal.primera = true;          // reencuadrar al abrir otro papel
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
      const r = await fetch(`/api/vivo?riesgo=${$('riesgo').value}&piso=${$('piso').value}`);
      d = await r.json();
    } catch (err) {
      $('reloj').textContent = 'sin conexión con el visor';
      $('tope').classList.remove('vivo');
      return;
    }
    if (d.error) {
      $('cuerpo').innerHTML = `<div class="vacio">Error: ${d.error}</div>`;
      return;
    }
    ultimo = d;
    const c = d.config || {};
    $('receta').textContent = `${c.apertura} · exp ≥${c.expansion}% · desde `
      + `${hhmm(c.desde)} · stop ${c.stop}%`
      + (c.corte ? ` · corte ${hhmm(c.corte)} si no gana ${c.corte_umbral}%` : '')
      + ` · p50 ${n(c.mfe50, 1)}%`;

    if (!d.existe) {
      charts.clear();
      $('cuerpo').innerHTML = `<div class="vacio"><p>No hay feed todavía.</p>`
        + `<p>Poné el indicador <code>TTPFeedMulti</code> en un gráfico y escribí`
        + ` la watchlist.</p><p style="margin-top:1em"><code>${d.feed}</code></p></div>`;
      $('tope').classList.remove('vivo');
      $('pulso').classList.add('frio');
      return;
    }
    $('tope').classList.add('vivo');
    $('pulso').classList.remove('frio');

    /* El aviso global usa el papel MENOS atrasado: si hasta el más fresco está
       viejo, se cortó todo. El por-papel va en cada cabecera, porque con un
       aviso sólo global uno que sigue llegando tapa a los demás. */
    const atrasos = d.papeles.map((p) => p.estado?.atraso).filter((x) => x != null);
    const min = atrasos.length ? Math.min(...atrasos) : null;
    $('alarma').innerHTML = (min != null && min > (c.rancio ?? 3))
      ? `<div class="alarma"><b>EL FEED ESTÁ FRENADO</b> — ningún papel recibió `
        + `una barra en ${n(min, 0)} minutos. Revisá que Trade The Pool diga `
        + `"Connected" y que TTPFeedMulti siga en el gráfico. Lo de abajo está viejo.</div>`
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
      if (abierto) {
        const p = d.papeles.find((x) => x.ticker === abierto);
        if (p) pintarModal(p); else cerrarModal();
      }
    }
    const con = d.papeles.filter((p) => (p.trades_estrategia || []).length).length;
    $('reloj').textContent = `${con} con señal · ${d.papeles.length} en pantalla · `
      + new Date().toLocaleTimeString('es-AR');
  }

  function reprogramar() {
    if (timer) clearInterval(timer);
    if ($('auto').checked) timer = setInterval(tick, 20000);
  }

  document.addEventListener('click', (ev) => {
    const b = ev.target.closest('.lupa');
    if (b) abrirModal(b.dataset.tk);
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
  ['riesgo', 'piso'].forEach((k) => $(k).addEventListener('change', tick));
  $('auto').addEventListener('change', reprogramar);
  tick();
  reprogramar();
})();
