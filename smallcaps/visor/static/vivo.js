/* La sesión de hoy, mientras pasa.
 *
 * Dibuja con `VisorGrafico`, el MISMO módulo que usan la bitácora y la
 * reproducción. Que la ejecución que mirás en vivo se vea idéntica a la que vas
 * a auditar mañana no es prolijidad: si fueran dos dibujos distintos, no
 * podrías comparar lo que hiciste contra lo que el sistema decía.
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

  const charts = new Map();     // ticker -> {chart, velas, vol, vwap, primera}
  let timer = null;

  function franja(e) {
    const eq = e.equity ?? 0;
    const lim = e.limite ?? 0;
    const neto = eq - (e.comision ?? 0);
    const sEq = eq >= 0 ? 'pos' : 'neg';
    const sNe = neto >= 0 ? 'pos' : 'neg';
    return '<div class="franja">'
      + '<div class="cif"><div class="n">' + n(e.vivas, 0) + '</div>'
      + '<div class="r">acciones abiertas</div></div>'
      + '<div class="cif"><div class="n">' + n(e.pico, 0) + '</div>'
      + '<div class="r">pico · lo que hay que localizar</div></div>'
      + '<div class="cif"><div class="n ' + sEq + '">'
      + (eq >= 0 ? '+' : '') + '$' + n(eq, 2) + '</div>'
      + '<div class="r">equity · límite $' + n(lim, 0) + '</div></div>'
      + '<div class="cif"><div class="n">$' + n(e.comision, 2) + '</div>'
      + '<div class="r">comisión</div></div>'
      + '<div class="cif"><div class="n ' + sNe + '">'
      + (neto >= 0 ? '+' : '') + '$' + n(neto, 2) + '</div>'
      + '<div class="r">neto</div></div>'
      + '</div>';
  }

  function tabla(trades) {
    if (!trades.length) return '';
    const filas = trades.map(function (t, i) {
      const ab = t.motivo === 'abierta';
      const chip = ab
        ? '<span class="chip ab">abierta</span>'
        : '<span class="chip st">' + t.motivo + ' ' + hhmm(t.hora_salida) + '</span>';
      return '<tr class="' + (ab ? 'abierta' : 'cerrada') + '">'
        + '<td>' + (i + 1) + ' · ' + hhmm(t.hora_entrada) + '</td>'
        + '<td>$' + n(t.precio_entrada) + '</td>'
        + '<td>$' + n(t.precio_entrada * (1 + t.stop_pct / 100)) + '</td>'
        + '<td>' + n(t.acciones, 0) + '</td>'
        + '<td>' + chip + '</td>'
        + '<td class="' + (t.pnl >= 0 ? 'pos' : 'neg') + '">'
        + (t.pnl >= 0 ? '+' : '') + '$' + n(t.pnl) + '</td></tr>';
    }).join('');
    return '<table><thead><tr>'
      + '<th>tramo</th><th>entra</th><th>stop</th><th>acciones</th>'
      + '<th>estado</th><th>pnl</th></tr></thead><tbody>'
      + filas + '</tbody></table>';
  }

  /* Marcas de ejecución. Se separan de `grafico.js` a propósito: acá un tramo
     puede estar ABIERTO, que es un estado que el histórico no tiene. */
  function marcas(p, off) {
    const base = ((p.sesion && p.sesion.apertura) || 0) + off;
    const hAts = (h) => base + Math.round((h - 9.5) * 3600);
    const m = [];
    (p.trades_estrategia || []).forEach(function (t, i) {
      m.push({ time: hAts(t.hora_entrada), position: 'aboveBar',
               color: '#ef5350', shape: 'arrowDown',
               text: 'S' + (i + 1) + ' $' + n(t.precio_entrada) });
      if (t.motivo !== 'abierta' && t.hora_salida != null) {
        m.push({ time: hAts(t.hora_salida), position: 'belowBar',
                 color: t.pnl >= 0 ? '#26a69a' : '#ef5350', shape: 'arrowUp',
                 text: t.motivo + ' ' + (t.pnl >= 0 ? '+' : '') + '$' + n(t.pnl, 1) });
      }
    });
    m.sort((a, b) => a.time - b.time);
    return m;
  }

  function pintarPapel(p) {
    const e = p.estado || {};
    const id = 'g-' + p.ticker;
    let caja = document.getElementById('p-' + p.ticker);

    const meta = hhmm(e.hora) + ' · ' + e.barras + ' barras'
      + (e.expansion != null ? ' · expansión ' + n(e.expansion, 0) + '%' : '')
      + (e.apertura ? ' · abrió ' + e.apertura : '');
    const cab = '<div class="cab">'
      + '<span class="tk">' + p.ticker + '</span>'
      + '<span class="px">$' + n(e.precio) + '</span>'
      + '<span class="meta">' + meta + '</span></div>';

    const descartado = e.descartes && e.descartes.length;
    const cuerpo = descartado
      ? '<div class="descarte"><ul>'
        + e.descartes.map((d) => '<li>✗ ' + d + '</li>').join('')
        + '</ul></div>'
      : franja(e)
        + (e.tope ? '<div class="alerta">En el límite diario — el sistema '
                    + 'no abre más tramos</div>' : '')
        + '<div class="g" id="' + id + '"></div>'
        + tabla(p.trades_estrategia || []);

    if (!caja) {
      caja = document.createElement('section');
      caja.className = 'papel';
      caja.id = 'p-' + p.ticker;
      $('cuerpo').appendChild(caja);
    }
    /* El nodo del gráfico se PRESERVA entre refrescos: destruirlo perdería el
       zoom y el scroll, justo mientras se está mirando para mandar una orden. */
    const viejo = document.getElementById(id);
    caja.innerHTML = cab + cuerpo;
    if (viejo && charts.has(p.ticker)) {
      const nuevo = document.getElementById(id);
      if (nuevo) nuevo.replaceWith(viejo);
    }

    if (!document.getElementById(id)) return;   // día descartado: sin gráfico
    let c = charts.get(p.ticker);
    if (!c) {
      c = VisorGrafico.crear(document.getElementById(id));
      c.primera = true;
      charts.set(p.ticker, c);
    }
    const off = VisorGrafico.desfase(p);
    c.velas.setData((p.velas || []).map((v) => Object.assign({}, v, { time: v.time + off })));
    c.vol.setData((p.volumen || []).map((v) => Object.assign({}, v, { time: v.time + off })));
    c.vwap.setData((p.vwap || []).map((v) => Object.assign({}, v, { time: v.time + off })));
    c.velas.setMarkers(marcas(p, off));

    /* El stop que se dibuja es el del tramo MÁS NUEVO, y se redibuja en cada
       refresco. Cada tramo tiene el suyo —el 45% se calcula sobre su propio
       precio de entrada—, así que una sola línea fija es engañosa: la del
       primer tramo suele quedar tan arriba que se sale de la escala y no
       informa nada. El que importa mientras operás es el de la orden que estás
       por poner. */
    const ts = p.trades_estrategia || [];
    const ultimo = ts[ts.length - 1];
    if (c.lineaStop) { c.velas.removePriceLine(c.lineaStop); c.lineaStop = null; }
    if (ultimo && ultimo.motivo === 'abierta') {
      c.lineaStop = c.velas.createPriceLine({
        price: ultimo.precio_entrada * (1 + ultimo.stop_pct / 100),
        color: '#ef5350', lineWidth: 1, lineStyle: 2, axisLabelVisible: true,
        title: 'stop tramo ' + ts.length });
    }

    if (c.primera) {
      if (p.niveles && p.niveles.pm_high) {
        c.velas.createPriceLine({
          price: p.niveles.pm_high, color: '#5b8def', lineWidth: 1,
          lineStyle: 3, axisLabelVisible: true, title: 'máx premarket' });
      }
      const base = ((p.sesion && p.sesion.apertura) || 0) + off;
      try {
        c.chart.timeScale().setVisibleRange(
          { from: base - 1800, to: base + Math.round(6.67 * 3600) });
      } catch (err) {
        c.chart.timeScale().fitContent();
      }
      c.primera = false;
    }
  }

  async function tick() {
    const r = $('riesgo').value;
    const pi = $('piso').value;
    let d;
    try {
      const resp = await fetch('/api/vivo?riesgo=' + r + '&piso=' + pi);
      d = await resp.json();
    } catch (err) {
      $('reloj').textContent = 'sin conexión con el visor';
      $('tope').classList.remove('vivo');
      return;
    }
    if (d.error) {
      $('cuerpo').innerHTML = '<div class="vacio">Error: ' + d.error + '</div>';
      return;
    }
    const c = d.config || {};
    $('receta').textContent = c.apertura + ' · expansión ≥' + c.expansion
      + '% · desde ' + hhmm(c.desde) + ' · stop ' + c.stop + '%';

    if (!d.existe) {
      charts.clear();
      $('cuerpo').innerHTML = '<div class="vacio">'
        + '<p>No hay feed todavía.</p>'
        + '<p>Poné el indicador <code>TTPFeed</code> en un gráfico de 1 minuto '
        + 'por cada papel de la watchlist.</p>'
        + '<p style="margin-top:1em"><code>' + d.feed + '</code></p></div>';
      $('tope').classList.remove('vivo');
      $('pulso').classList.add('frio');
      return;
    }
    $('tope').classList.add('vivo');
    $('pulso').classList.remove('frio');

    if (!d.papeles.length) {
      charts.clear();
      $('cuerpo').innerHTML = '<div class="vacio">'
        + 'Hay feed, pero ninguna barra de hoy todavía.</div>';
    } else {
      /* Sacar los papeles que dejaron de venir, para no dejar un gráfico
         congelado que parezca vivo. */
      const hay = new Set(d.papeles.map((p) => p.ticker));
      Array.from(charts.keys()).forEach(function (tk) {
        if (!hay.has(tk)) {
          charts.get(tk).chart.remove();
          charts.delete(tk);
          const nodo = document.getElementById('p-' + tk);
          if (nodo) nodo.remove();
        }
      });
      const vacio = $('cuerpo').querySelector('.vacio');
      if (vacio) $('cuerpo').innerHTML = '';
      d.papeles.forEach(pintarPapel);
    }
    const ahora = new Date().toLocaleTimeString('es-AR');
    const con = d.papeles.filter((p) => (p.trades_estrategia || []).length).length;
    $('reloj').textContent = con + ' con señal · ' + d.papeles.length
      + ' en pantalla · ' + ahora;
  }

  function reprogramar() {
    if (timer) clearInterval(timer);
    if ($('auto').checked) timer = setInterval(tick, 20000);
  }

  ['riesgo', 'piso'].forEach((k) => $(k).addEventListener('change', tick));
  $('auto').addEventListener('change', reprogramar);
  tick();
  reprogramar();
})();
