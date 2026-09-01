/* Bitácora: el diario de operación, jornada por jornada.

   Por qué existe y no alcanzaba con /historial: las tablas agregadas contestan
   "¿cuánto rinde la estrategia?" y no contestan "¿qué hago un martes?". Acá cada
   renglón es un día real, con sus ejecuciones dibujadas sobre las velas — que es
   la única forma de auditar una simulación. En este proyecto el bug de las
   reducciones intrabar apareció justo así: dibujando el trade, no leyendo el
   promedio. */

const $ = (s) => document.querySelector(s);
const G = window.VisorGrafico;   // desfase / dibujar / pico
const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
const cls = (v) => (v == null ? 'tenue' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'tenue');
const hhmm = (h) => (h == null ? '—'
  : String(Math.floor(h)).padStart(2, '0') + ':'
    + String(Math.round((h % 1) * 60)).padStart(2, '0'));
const MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
  'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let DIAS = [];
let EST = '';

async function inicio() {
  const r = await fetch('/api/bitacora').then((x) => x.json());
  const es = r.estrategias || [];
  $('#est').innerHTML = es.map((e) =>
    `<option value="${esc(e)}"${e === r.estrategia ? ' selected' : ''}>${esc(e)}</option>`
  ).join('');
  EST = r.estrategia;
  pintarDiario(r.dias || []);
  $('#est').addEventListener('change', async () => {
    const q = await fetch('/api/bitacora?estrategia='
      + encodeURIComponent($('#est').value)).then((x) => x.json());
    EST = q.estrategia;
    pintarDiario(q.dias || []);
    $('#jornada').innerHTML = '<div class="vacio">Elegí una jornada.</div>';
  });
}

function pintarDiario(dias) {
  DIAS = dias;
  const tot = dias.reduce((a, x) => a + (x.pnl_R || 0), 0);
  const pos = dias.filter((x) => (x.pnl_R || 0) > 0).length;
  $('#resumen').textContent =
    `${dias.length} jornadas · ${pos} positivas (${Math.round(100 * pos / (dias.length || 1))}%)`
    + ` · acumulado ${tot >= 0 ? '+' : ''}${tot.toFixed(1)} R`;

  let html = '';
  let mesActual = '';
  for (const d of dias) {
    const [a, m] = d.d.split('-');
    const etiqueta = `${MES[+m - 1]} ${a}`;
    if (etiqueta !== mesActual) {
      mesActual = etiqueta;
      html += `<div class="mes">${etiqueta}</div>`;
    }
    const dd = d.d.slice(8);
    html += `<div class="dia" data-d="${d.d}">
      <b>${dd} · ${esc(d.tickers.join(' '))}</b>
      <span class="r ${cls(d.pnl_R)}">${d.pnl_R >= 0 ? '+' : ''}${n(d.pnl_R, 2)} R</span>
      <span class="tk">${d.trades} trade${d.trades === 1 ? '' : 's'}</span>
      <span class="n">$${n(d.pnl, 0)}</span>
    </div>`;
  }
  $('#diario').innerHTML = html || '<div class="vacio">Sin jornadas.</div>';
  $('#diario').querySelectorAll('.dia').forEach((el) => {
    el.addEventListener('click', () => abrir(el.dataset.d, el));
  });
}

async function abrir(d, el) {
  $('#diario').querySelectorAll('.dia').forEach((x) => x.classList.remove('sel'));
  if (el) el.classList.add('sel');
  $('#jornada').innerHTML = '<div class="vacio">cargando la jornada…</div>';
  const r = await fetch(`/api/bitacora/dia?d=${d}&estrategia=${encodeURIComponent(EST)}`)
    .then((x) => x.json());
  if (r.error || !r.papeles?.length) {
    $('#jornada').innerHTML = `<div class="vacio">${esc(r.error || 'sin datos del día')}</div>`;
    return;
  }

  const ts = r.trades || [];
  const pnl = ts.reduce((a, t) => a + (t.pnl || 0), 0);
  const gan = ts.filter((t) => t.pnl > 0).length;
  const stops = ts.filter((t) => t.motivo === 'stop').length;
  const dia = DIAS.find((x) => x.d === d) || {};

  /* Antes esto eran SIETE cajas identicas en fila: ninguna resaltaba y todas
     competian. Cambios: la fecha sale de la fila (es el titulo de la jornada,
     no una metrica) y el PnL del dia queda como `jefe` — el unico numero
     grande de la pantalla. Los otros cinco bajan a secundarios. */
  let html = `<div class="jornada-tope">
    <h2>${esc(d)}</h2>
    <div class="kpis">
      ${kpi(`$${n(pnl, 2)}`, 'PnL del día', cls(pnl), true)}
      ${kpi(`${dia.pnl_R >= 0 ? '+' : ''}${n(dia.pnl_R, 2)} R`, 'en unidades de riesgo', cls(dia.pnl_R))}
      ${kpi(`${ts.length}`, 'trades')}
      ${kpi(`${gan}/${ts.length}`, 'ganadores')}
      ${kpi(`${n(dia.nominal_R, 2)} R`, 'nominal reservado')}
      ${kpi(`${stops}`, 'stopeados', stops ? 'neg' : '')}
    </div>
  </div>`;

  for (const p of r.papeles) {
    const id = `g_${p.ticker}_${d.replace(/-/g, '')}`;
    html += `<div class="papel">
      <div class="cab">
        <h2>${esc(p.ticker)}</h2>
        <span class="dato">expansión premarket <b>${n(p.resumen?.expansion, 0)}%</b></span>
        <span class="dato">cierre previo <b>$${n(p.niveles?.prev_close)}</b></span>
        <span class="dato">máximo premarket <b>$${n(p.niveles?.pm_high)}</b></span>
        <span class="dato">apertura <b>$${n(p.niveles?.rth_open)}</b></span>
      </div>
      <div class="grafico" id="${id}"></div>
      ${tabla(p.trades_estrategia || [])}
      ${lectura(p, p.trades_estrategia || [])}
    </div>`;
  }
  $('#jornada').innerHTML = html;
  for (const p of r.papeles) {
    G.dibujar(`g_${p.ticker}_${d.replace(/-/g, '')}`, p);
  }
}

function kpi(v, lab, c = '', jefe = false) {
  return `<div class="kpi${jefe ? ' jefe' : ''}"><b class="${c}">${v}</b>`
    + `<span>${lab}</span></div>`;
}

function tabla(ts) {
  if (!ts.length) return '';
  return `<table>
    <tr><th>#</th><th>entra</th><th>sale</th><th>precio</th><th>salida</th>
        <th>stop %</th><th>acciones</th><th>nominal</th><th>PnL</th>
        <th>MAE</th><th>MFE</th><th>motivo</th></tr>
    ${ts.map((t, i) => `<tr>
      <td>${i + 1}</td>
      <td>${hhmm(t.hora_entrada)}</td>
      <td class="tenue">${hhmm(t.hora_salida)}</td>
      <td>$${n(t.precio_entrada, 3)}</td>
      <td>$${n(t.precio_salida, 3)}</td>
      <td class="tenue">${n(t.stop_pct, 0)}</td>
      <td class="tenue">${n(t.acciones, 0)}</td>
      <td class="tenue">$${n((t.acciones || 0) * (t.precio_entrada || 0), 0)}</td>
      <td class="${cls(t.pnl)}"><b>$${n(t.pnl, 2)}</b></td>
      <td class="neg">${n(t.mae_pct, 1)}%</td>
      <td class="pos">${n(t.mfe_pct, 1)}%</td>
      <td><span class="badge">${esc(t.motivo)}</span></td>
    </tr>`).join('')}
  </table>`;
}

/* La lectura del día en prosa. No es decoración: obliga a mirar el trade contra
   lo que el sistema decía que iba a pasar, que es donde aparecen los errores. */
function lectura(p, ts) {
  if (!ts.length) return '';
  const pnl = ts.reduce((a, t) => a + (t.pnl || 0), 0);
  const stops = ts.filter((t) => t.motivo === 'stop').length;
  const peorMAE = Math.min(...ts.map((t) => t.mae_pct ?? 0));
  const mejorMFE = Math.max(...ts.map((t) => t.mfe_pct ?? 0));
  const primera = ts[0], ultima = ts[ts.length - 1];
  const mayor = Math.max(...ts.map((t) => (t.acciones || 0) * (t.precio_entrada || 0)));

  /* La exposición SIMULTÁNEA, barriendo el día por eventos de apertura y cierre.
     Es lo que hay que tener localizado, y por lo tanto lo que se paga. Durante
     un tiempo este proyecto tomó el trade más grande en vez de la suma, y con
     eso el costo de locate salía hasta nueve veces más barato de lo real.
     El barrido vive en grafico.js porque /papeles lo necesita igual; el número
     que se narra acá sigue siendo el pico en DÓLARES, como antes. */
  const px = G.pico(ts);
  const pico = px.nominal, hPico = px.hora, tramos = px.tramos;

  const partes = [];
  partes.push(`Primera entrada <b>${hhmm(primera.hora_entrada)}</b>, última
    <b>${hhmm(ultima.hora_entrada)}</b>. El trade más grande fue de
    $${n(mayor, 0)}, pero a las <b>${hhmm(hPico)}</b> había <b>${tramos}</b>
    tramo${tramos === 1 ? '' : 's'} abierto${tramos === 1 ? '' : 's'} a la vez:
    <b>$${n(pico, 0)}</b> de exposición simultánea. <b>Eso</b> es lo que hay que
    tener localizado, y es lo que se paga${
    tramos > 1 ? ` — ${(pico / mayor).toFixed(1)}× el trade más grande` : ''}.`);
  if (stops === 0) {
    partes.push(`Ningún stop: los ${ts.length} cerraron al cierre de la rueda.`);
  } else if (stops === ts.length) {
    partes.push(`<b>Los ${stops} salieron por stop.</b> Día en que el papel no cedió.`);
  } else {
    partes.push(`<b>${stops}</b> de ${ts.length} salieron por stop.`);
  }
  partes.push(`La peor excursión en contra fue <b>${n(peorMAE, 1)}%</b> y la mejor
    a favor <b>${n(mejorMFE, 1)}%</b>${
    mejorMFE > Math.abs(peorMAE) * 2
      ? ' — la cola derecha fue mucho más grande que la izquierda, que es exactamente por lo que no se toma ganancia temprano.'
      : '.'}`);
  partes.push(`Resultado del papel: <b class="${cls(pnl)}">$${n(pnl, 2)}</b>.`);
  return `<div class="lectura">${partes.join(' ')}</div>`;
}

inicio();
