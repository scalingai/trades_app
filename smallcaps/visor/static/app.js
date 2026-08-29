/* Visor de eventos — front. Sin framework a propósito: son 300 líneas y no
   quiero un build step entre los datos y el gráfico. */

const $ = (s) => document.querySelector(s);
const LWC = window.LightweightCharts;

let TODOS = [];        // índice completo
let VISIBLES = [];     // lo que está en la tabla ahora
let SEL = null;        // {ticker, d}
let DATOS = null;      // payload del día abierto
let orden = { col: 'd', desc: true };
let abiertos = new Set();   // tickers expandidos en el panel
let MARCAS = {};            // "TICKER|fecha" -> cantidad de marcas
const ver = { anom: true, vwap: true, marcas: true, trade: true };
let TF = 1;   // temporalidad en minutos. El dato base es 1m: no hay nada más fino.

/* ------------------------------------------------ temporalidad
   Las barras del proveedor son agregados de 1 minuto. Todo lo que se ve arriba
   de eso se compone acá, en el navegador, a partir de las mismas velas — no hay
   una descarga distinta por temporalidad ni la puede haber. Bajar de 1 minuto
   necesita datos de TRADES, que es otro plan del proveedor. */

const bucket = (t) => Math.floor(t / (TF * 60)) * (TF * 60);

function agregarVelas(velas) {
  if (TF === 1) return velas;
  const out = [];
  let cur = null;
  velas.forEach((v) => {
    const k = bucket(v.time);
    if (!cur || cur.time !== k) {
      cur = { time: k, open: v.open, high: v.high, low: v.low, close: v.close };
      out.push(cur);
    } else {
      cur.high = Math.max(cur.high, v.high);
      cur.low = Math.min(cur.low, v.low);
      cur.close = v.close;
    }
  });
  return out;
}

function agregarVolumen(vol, velas) {
  if (TF === 1) return vol;
  const cierre = new Map(agregarVelas(velas).map((v) => [v.time, v.close >= v.open]));
  const m = new Map();
  vol.forEach((v) => {
    const k = bucket(v.time);
    m.set(k, (m.get(k) || 0) + v.value);
  });
  return [...m.entries()].map(([time, value]) => ({
    time, value,
    color: cierre.get(time) ? 'rgba(38,166,154,.5)' : 'rgba(239,83,80,.5)',
  }));
}

function agregarLinea(linea) {
  /* Dedupe SIEMPRE, no solo cuando se agrega: dos puntos con el mismo `time`
     dejan la serie mal formada y el eje de tiempo deja de aceptar zoom, sin
     tirar ningún error. Costó una tarde encontrarlo. */
  const m = new Map();
  linea.forEach((p) => m.set(bucket(p.time), p.value));   // gana el último del bucket
  return [...m.entries()].map(([time, value]) => ({ time, value }));
}
let modoMarcar = null;   // tipo de etiqueta activo, o null

/* ------------------------------------------------------------------ chart */

const chart = LWC.createChart($('#chart'), {
  autoSize: true,
  layout: { background: { color: '#0b0e14' }, textColor: '#7b8598', fontSize: 11 },
  grid: { vertLines: { color: '#151b26' }, horzLines: { color: '#151b26' } },
  rightPriceScale: { borderColor: '#222938', scaleMargins: { top: .08, bottom: .28 } },
  timeScale: { borderColor: '#222938', timeVisible: true, secondsVisible: false },
  crosshair: { mode: LWC.CrosshairMode.Normal },
  localization: { locale: 'es-AR' },
});

const sVelas = chart.addCandlestickSeries({
  upColor: '#26a69a', downColor: '#ef5350',
  wickUpColor: '#26a69a', wickDownColor: '#ef5350',
  borderVisible: false,
});
const sVol = chart.addHistogramSeries({
  priceFormat: { type: 'volume' }, priceScaleId: 'vol',
});
chart.priceScale('vol').applyOptions({ scaleMargins: { top: .78, bottom: 0 } });

const sVwap = chart.addLineSeries({
  color: '#e6c84a', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
});
/* El precio medio de la posición, escalonado. Es la línea que dice si construir
   mejoró la entrada o solo agrandó el problema: si sube, cada adición te dejó
   peor. */
const sMedio = chart.addLineSeries({
  color: '#ff5c8a', lineWidth: 2, lineStyle: LWC.LineStyle.Dotted,
  priceLineVisible: false, lastValueVisible: true, title: 'precio medio',
});

let lineas = [];
function limpiarLineas() {
  lineas.forEach((l) => sVelas.removePriceLine(l));
  lineas = [];
}
function nivel(precio, color, titulo) {
  if (!precio) return;
  lineas.push(sVelas.createPriceLine({
    price: precio, color, lineWidth: 1,
    lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: titulo,
  }));
}

/* Sombreado del pre-market. lightweight-charts no dibuja bandas verticales, así
   que se hace con un div encima, reposicionado cuando cambia el eje. */
function pintarSombra() {
  const el = $('#sombra');
  if (!DATOS || !DATOS.sesion.apertura) { el.style.display = 'none'; return; }
  const ts = chart.timeScale();
  const x0 = ts.timeToCoordinate(DATOS.velas[0].time);
  const x1 = ts.timeToCoordinate(DATOS.sesion.apertura);
  if (x0 == null || x1 == null) { el.style.display = 'none'; return; }
  const a = Math.max(0, Math.min(x0, x1));
  el.style.display = 'block';
  el.style.left = a + 'px';
  el.style.width = Math.max(0, x1 - a) + 'px';
}
chart.timeScale().subscribeVisibleTimeRangeChange(pintarSombra);
/* El observer SOLO reposiciona la sombra. Antes también llamaba a
   `chart.resize()` como salvavidas de cuando el contenedor medía 0 al crear el
   gráfico — pero con `autoSize: true` esa llamada pelea con el resize interno
   de la librería y deja el eje de tiempo CONGELADO: `setVisibleRange` y hasta
   `fitContent` se ignoran en silencio. El síntoma es que el zoom no responde y
   no hay ningún error en consola. */
new ResizeObserver(() => pintarSombra()).observe($('#chart'));

/* ------------------------------------------------------------------ datos */

async function cargarIndice() {
  const r = await fetch('/api/dias').then((x) => x.json());
  if (r.cargando) {
    $('#filas').innerHTML = '<tr><td colspan="4" class="tenue">indexando…</td></tr>';
    return setTimeout(cargarIndice, 1200);
  }
  TODOS = r.dias;
  try {
    MARCAS = (await fetch('/api/marcas').then((x) => x.json())).marcas || {};
  } catch (_) { MARCAS = {}; }
  render();
}

function filtrar() {
  const q = $('#q').value.trim().toUpperCase();
  const minExp = parseFloat($('#minExp').value);
  const banda = $('#banda').value;
  const limpios = $('#soloLimpios').checked;
  const soloEv = $('#soloEventos').checked;
  const soloCand = $('#soloCandidatos').checked;
  let v = TODOS.filter((r) => {
    if (q && !r.ticker.includes(q)) return false;
    if (!isNaN(minExp) && (r.expansion == null || r.expansion < minExp)) return false;
    if (soloCand && !r.candidato) return false;
    if (soloEv && !r.evento) return false;
    if (limpios && (r.ratio_vol == null || r.ratio_vol < 3)) return false;
    if (banda) {
      const [lo, hi] = banda.split(',').map(Number);
      const p = r.open || 0;
      if (!(p >= lo && p < hi)) return false;
    }
    return true;
  });
  const c = orden.col;
  v.sort((a, b) => {
    const x = a[c], y = b[c];
    if (x == null) return 1;
    if (y == null) return -1;
    const s = typeof x === 'string' ? x.localeCompare(y) : x - y;
    return orden.desc ? -s : s;
  });
  return v;
}

const pct = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(1) + '%');
const cls = (v) => (v == null ? 'tenue' : v > 0 ? 'pos' : 'neg');

function agrupar(filas) {
  /* Un papel es la unidad de seguimiento; los días son lo que le pasó adentro.
     Agrupar así es lo que deja ver de un vistazo que AMIX falló seis gaps
     seguidos antes del que hizo +262%.

     El filtro elige QUÉ PAPELES aparecen, no qué días se ven adentro: una vez
     que abrís un papel querés su historia completa, incluidos los días que no
     califican. Justamente los que no califican son la mitad del contexto. */
  const m = new Map();
  filas.forEach((r) => { if (!m.has(r.ticker)) m.set(r.ticker, true); });
  const porTicker = new Map();
  TODOS.forEach((r) => {
    if (!m.has(r.ticker)) return;
    if (!porTicker.has(r.ticker)) porTicker.set(r.ticker, []);
    porTicker.get(r.ticker).push(r);
  });
  return [...porTicker.entries()].map(([ticker, dias]) => {
    dias.sort((a, b) => (a.d < b.d ? 1 : -1));
    const ev = dias.filter((d) => d.evento);
    const cand = dias.filter((d) => d.candidato);
    // El resumen del papel se calcula sobre sus EVENTOS, no sobre los vecinos:
    // el intradía de un día cualquiera no dice nada del comportamiento del papel.
    const intra = ev.map((d) => d.intradia).filter((x) => x != null).sort((a, b) => a - b);
    const marcas = dias.reduce((n, d) => n + (MARCAS[`${ticker}|${d.d}`] || 0), 0);
    return {
      ticker, dias,
      n_ev: ev.length, n_cand: cand.length, marcas,
      med: intra.length ? intra[Math.floor(intra.length / 2)] : null,
      hist: (dias.find((d) => d.hist != null) || {}).hist,
      ultimo: dias[0].d,
    };
  });
}

function render() {
  VISIBLES = filtrar();
  const grupos = agrupar(VISIBLES);
  const c = orden.col;
  grupos.sort((a, b) => {
    if (c === 'ticker') return orden.desc ? b.ticker.localeCompare(a.ticker)
      : a.ticker.localeCompare(b.ticker);
    if (c === 'expansion') return b.n_cand - a.n_cand || (b.ultimo < a.ultimo ? -1 : 1);
    if (c === 'intradia') return (a.med ?? 0) - (b.med ?? 0);
    return orden.desc ? (a.ultimo < b.ultimo ? 1 : -1) : (a.ultimo > b.ultimo ? 1 : -1);
  });

  // Con un solo papel a la vista no tiene sentido pedir un clic para abrirlo.
  if (grupos.length <= 2) grupos.forEach((g) => abiertos.add(g.ticker));

  const html = [];
  grupos.slice(0, 250).forEach((g) => {
    const ab = abiertos.has(g.ticker);
    html.push(`
      <tr class="grupo" data-grupo="${g.ticker}">
        <td><span class="flecha">${ab ? '▾' : '▸'}</span> ${g.ticker}</td>
        <td class="tenue">${g.n_ev} ev${g.n_cand ? ` · <b class="pos">${g.n_cand} cand</b>` : ''}</td>
        <td class="${g.hist >= 60 ? 'neg' : 'tenue'}">${g.hist != null ? g.hist.toFixed(0) + '%' : '—'}</td>
        <td class="${cls(g.med)}">${pct(g.med)}${g.marcas ? ` <span class="marca">✋${g.marcas}</span>` : ''}</td>
      </tr>`);
    if (!ab) return;
    // Dentro del papel, primero los que califican; los vecinos van atenuados.
    g.dias.forEach((r) => {
      const sel = SEL && SEL.ticker === r.ticker && SEL.d === r.d;
      const n = MARCAS[`${r.ticker}|${r.d}`] || 0;
      html.push(`
        <tr class="dia ${sel ? 'sel' : ''} ${r.evento ? '' : 'vecino'}" data-t="${r.ticker}" data-d="${r.d}">
          <td class="tenue">${r.d}</td>
          <td>${r.candidato ? '<span class="tag">CAND</span>'
            : r.evento ? '<span class="tag ev">ev</span>' : ''}</td>
          <td class="${cls(r.expansion)}">${pct(r.expansion)}</td>
          <td class="${cls(r.intradia)}">${pct(r.intradia)}${n ? ` <span class="marca">✋${n}</span>` : ''}</td>
        </tr>`);
    });
  });
  $('#filas').innerHTML = html.join('') ||
    '<tr><td colspan="4" class="tenue">nada con esos filtros</td></tr>';
  document.querySelectorAll('.lista th').forEach((th) => {
    th.classList.toggle('orden', th.dataset.col === orden.col);
  });
  const cand = TODOS.filter((r) => r.candidato).length;
  $('#cuenta').textContent = `${grupos.length} papeles · ${VISIBLES.length} días · ${cand} candidatos`;
}

async function abrir(ticker, d) {
  SEL = { ticker, d };
  abiertos.add(ticker);
  render();
  const r = await fetch(`/api/dia?ticker=${ticker}&d=${d}`).then((x) => x.json());
  if (r.error) { $('#detalle').textContent = r.error; return; }
  DATOS = r;
  $('#vacio').style.display = 'none';

  redibujar();
  limpiarLineas();
  nivel(r.niveles.prev_close, '#5c6a85', 'cierre previo');
  nivel(r.niveles.pm_high, '#8e6bd8', 'máx pre-market');
  requestAnimationFrame(() => { encuadrar(); pintarSombra(); });
  pintarBarra();
  pintarTrade();
  pintarPie();
}

const ICONO_TRADE = {
  entrada:   { shape: 'arrowDown', color: '#ff5c8a', pos: 'aboveBar', txt: 'ENTRA' },
  adicion:   { shape: 'arrowDown', color: '#d98a4a', pos: 'aboveBar', txt: '+' },
  reduccion: { shape: 'arrowUp',   color: '#4ade80', pos: 'belowBar', txt: '−' },
  salida:    { shape: 'square',    color: '#e6c84a', pos: 'belowBar', txt: 'SALE' },
};

const COLOR_ET = {
  entrada_short: '#ff5c8a', entrada_long: '#4ade80', no_va: '#8892a6',
  salida: '#e6c84a', patron: '#a78bfa',
};

function redibujar() {
  if (!DATOS) return;
  sVelas.setData(agregarVelas(DATOS.velas));
  sVol.setData(agregarVolumen(DATOS.volumen, DATOS.velas));
  sVwap.setData(ver.vwap ? agregarLinea(DATOS.vwap) : []);
  sMedio.setData(ver.trade && DATOS.trade && DATOS.trade.operado
    ? agregarLinea(DATOS.trade.medio) : []);
  pintarMarcas();
}

/* El encuadre por defecto: pre-market tardío + sesión completa. `fitContent`
   mostraba de 04:00 a 20:00 y dejaba el día aplastado contra el medio; lo que
   interesa mirar es cómo se armó el setup y cómo terminó, no las cuatro horas
   de after hours sin volumen. */
function encuadrar(todo = false) {
  if (!DATOS || !DATOS.velas.length) return;
  const v = DATOS.velas;
  if (todo) return chart.timeScale().fitContent();
  const ap = DATOS.sesion.apertura, ci = DATOS.sesion.cierre;
  let from = ap ? ap - 90 * 60 : v[0].time;
  let to = ci ? ci + 10 * 60 : v[v.length - 1].time;
  const t = DATOS.trade;
  if (t && t.operado && t.pasos.length) {
    from = Math.min(from, t.pasos[0].time - 20 * 60);
    to = Math.max(to, t.pasos[t.pasos.length - 1].time + 20 * 60);
  }
  chart.timeScale().setVisibleRange({
    from: Math.max(from, v[0].time),
    to: Math.min(to, v[v.length - 1].time),
  });
}

function pintarMarcas() {
  if (!DATOS) return;
  const m = [];
  (DATOS.etiquetas || []).forEach((e) => m.push({
    time: e.time,
    position: e.tipo === 'entrada_long' ? 'belowBar' : 'aboveBar',
    color: COLOR_ET[e.tipo] || '#fff',
    shape: e.tipo === 'no_va' ? 'circle' : 'square',
    text: '✋ ' + e.tipo.replace('entrada_', '') + (e.nota ? ' · ' + e.nota : ''),
  }));
  if (ver.marcas) m.push(...DATOS.marcas);
  const tr = DATOS.trade;
  if (ver.trade && tr && tr.operado) {
    tr.pasos.forEach((p) => {
      const ic = ICONO_TRADE[p.tipo] || ICONO_TRADE.salida;
      m.push({
        time: p.time, position: ic.pos, color: ic.color, shape: ic.shape,
        text: `${ic.txt}${p.tipo === 'adicion' || p.tipo === 'reduccion'
          ? ' ' + p.tramos + '/5' : ''} $${p.precio.toFixed(2)}`,
      });
    });
  }
  if (ver.anom) {
    DATOS.anomalias.forEach((a) => m.push({
      time: a.time,
      position: a.subio ? 'belowBar' : 'aboveBar',
      color: a.subio ? '#4a90d9' : '#d98a4a',
      shape: 'circle',
      text: a.texto,
    }));
  }
  m.forEach((x) => { x.time = bucket(x.time); });
  m.sort((a, b) => a.time - b.time);
  sVelas.setMarkers(m);
}

function kpi(valor, etiqueta, clase) {
  return `<div class="kpi"><b class="${clase || ''}">${valor}</b><span>${etiqueta}</span></div>`;
}

function pintarBarra() {
  const r = DATOS.resumen, f = DATOS.ficha || {};
  const ev = f.evento || {}, st = f.estructura || {};
  const n = (v, d = 1, suf = '') => (v == null ? '—' : v.toFixed(d) + suf);
  const partes = [
    `<div class="tit">${r.ticker} <span class="tenue" style="font-size:12px">${r.d}</span></div>`,
    '<div class="sep"></div>',
    kpi(pct(r.expansion), 'expansión pre-mkt', cls(r.expansion)),
    kpi(n(r.ratio_vol, 1, '×'), 'vol vs día previo'),
    kpi(pct(r.intradia), 'apertura→cierre', cls(r.intradia)),
    kpi(r.estado10 || '—', 'estado 10:00',
      r.estado10 === 'front' ? 'pos' : r.estado10 ? 'neg' : ''),
    kpi(r.estado12 || '—', 'estado 12:00',
      r.estado12 === 'front' ? 'pos' : r.estado12 ? 'neg' : ''),
    '<div class="sep"></div>',
    kpi(n(ev.rvol, 0, '×'), 'rvol'),
    kpi(ev.dollar_volume ? '$' + (ev.dollar_volume / 1e6).toFixed(1) + 'M' : '—', 'vol en $'),
    '<div class="sep"></div>',
    kpi(pct(st.dilution_12m_pct), 'dilución 12m',
      st.dilution_12m_pct > 100 ? 'neg' : ''),
    kpi(st.reverse_splits_12m == null ? '—' : st.reverse_splits_12m, 'rev splits 12m',
      st.reverse_splits_12m > 0 ? 'neg' : ''),
    kpi(n(st.runway_months, 1, ' m'), 'runway'),
    kpi(st.shelf_effective == null ? '—' : (st.shelf_effective ? 'sí' : 'no'), 'shelf efectivo'),
  ];
  $('#barra').innerHTML = partes.join('');
  const PASOS = [['ok_censo', 'en el censo'], ['ok_precio', 'precio ≥ $3'],
    ['ok_volumen', 'vol ≥ 3×'], ['ok_expansion', 'expansión ≥ 100%'],
    ['ok_fade', 'abrió fade']];
  $('#embudo').innerHTML =
    `<span class="tenue" style="font-size:10px">EMBUDO</span><div class="embudo">` +
    PASOS.map(([k, lab]) =>
      `<span class="paso ${r[k] ? 'si' : 'no'}">${r[k] ? '✓' : '✗'} ${lab}</span>`).join('') +
    `<span class="paso ${r.candidato ? 'si' : 'no'}" style="font-weight:700">` +
    `${r.candidato ? 'CANDIDATO' : 'no candidato'}</span>` +
    (r.apertura ? `<span class="paso">apertura: ${r.apertura}</span>` : '') +
    `</div>`;
  $('#detalle').innerHTML =
    `${DATOS.velas.length} barras · ${DATOS.anomalias.length} anomalías (≥5× la mediana ` +
    'de las 30 previas)';
}

/* ------------------------------------------------------------------ eventos */

$('#filas').addEventListener('click', (e) => {
  const g = e.target.closest('tr[data-grupo]');
  if (g) {
    const t = g.dataset.grupo;
    if (abiertos.has(t)) abiertos.delete(t); else abiertos.add(t);
    return render();
  }
  const tr = e.target.closest('tr[data-t]');
  if (tr) abrir(tr.dataset.t, tr.dataset.d);
});
document.querySelectorAll('.lista th').forEach((th) => {
  th.addEventListener('click', () => {
    const c = th.dataset.col;
    orden = { col: c, desc: orden.col === c ? !orden.desc : true };
    $('#orden').value = ['d', 'expansion', 'intradia', 'ratio_vol'].includes(c)
      ? c : $('#orden').value;
    render();
  });
});
['q', 'minExp', 'banda', 'soloLimpios', 'soloEventos', 'soloCandidatos'].forEach((id) =>
  $('#' + id).addEventListener('input', render));
$('#orden').addEventListener('change', () => {
  orden = { col: $('#orden').value, desc: true };
  render();
});

$('#bajar').addEventListener('click', async () => {
  const t = $('#nvTicker').value.trim().toUpperCase();
  const d = $('#nvFecha').value.trim();
  if (!t || !/^\d{4}-\d{2}-\d{2}$/.test(d)) { alert('ticker y fecha AAAA-MM-DD'); return; }
  $('#bajar').textContent = '…';
  const r = await fetch(`/api/bajar?ticker=${t}&d=${d}`).then((x) => x.json());
  $('#bajar').textContent = 'bajar';
  if (r.error) return alert(r.error);
  if (r.estado !== 'ok') return alert('sin barras para ese día (' + r.estado + ')');
  await cargarIndice();
  abrir(t, d);
});

const chips = { tgAnom: 'anom', tgVwap: 'vwap', tgMarcas: 'marcas', tgTrade: 'trade' };
Object.entries(chips).forEach(([id, k]) => {
  $('#' + id).addEventListener('click', () => alternar(k));
});
function alternar(k) {
  ver[k] = !ver[k];
  const id = Object.keys(chips).find((x) => chips[x] === k);
  $('#' + id).classList.toggle('on', ver[k]);
  if (!DATOS) return;
  redibujar();
}
/* ---- la cuota discrecional: marcar sobre el gráfico ---- */

function horaDesdeTs(t) {
  /* El servidor manda los ts corridos al huso de Nueva York (ver server.ts),
     así que la hora ET sale de leerlos como UTC. */
  const d = new Date(t * 1000);
  return d.getUTCHours() + d.getUTCMinutes() / 60;
}

chart.subscribeClick(async (param) => {
  if (!modoMarcar || !DATOS || !param.time) return;
  const nota = prompt(`Nota para "${modoMarcar}" (opcional):`, '');
  if (nota === null) return;
  const h = horaDesdeTs(param.time);
  const u = `/api/etiquetar?ticker=${DATOS.ticker}&d=${DATOS.d}` +
    `&hora=${h.toFixed(5)}&tipo=${modoMarcar}&nota=${encodeURIComponent(nota)}`;
  const r = await fetch(u).then((x) => x.json());
  if (r.error) return alert(r.error);
  DATOS.etiquetas.push({ id: r.id, time: param.time, hora: h, tipo: modoMarcar, nota });
  MARCAS[`${DATOS.ticker}|${DATOS.d}`] = (MARCAS[`${DATOS.ticker}|${DATOS.d}`] || 0) + 1;
  pintarMarcas();
  pintarPie();
  render();
});

function pintarTrade() {
  const t = DATOS && DATOS.trade;
  const el = $('#trade');
  if (!t) { el.innerHTML = ''; return; }
  if (!t.operado) {
    el.innerHTML = `<span class="tenue">sin trade — descartado por `
      + `<b>${t.motivo}</b></span>`;
    return;
  }
  const cls = t.neto > 0 ? 'pos' : 'neg';
  el.innerHTML =
    `<span class="paso ${cls}" style="font-weight:700">${t.neto > 0 ? '+' : ''}`
    + `${t.neto.toFixed(2)}% neto</span>`
    + `<span class="paso">bruto ${t.bruto > 0 ? '+' : ''}${t.bruto.toFixed(2)}%</span>`
    + `<span class="paso">salió por ${t.motivo}</span>`
    + `<span class="paso">MAE ${t.peor.toFixed(1)}%</span>`
    + `<span class="paso">${t.ejecuciones} ejecuciones</span>`
    + t.pasos.map((p) => {
      const h = new Date(p.time * 1000);
      const hh = String(h.getUTCHours()).padStart(2, '0') + ':'
        + String(h.getUTCMinutes()).padStart(2, '0');
      return `<span class="paso" title="${p.nota}">${hh} ${p.tipo} `
        + `$${p.precio.toFixed(2)} · ${p.tramos}/5</span>`;
    }).join('');
}

function pintarPie() {
  const n = (DATOS && DATOS.etiquetas || []).length;
  $('#etiquetas').textContent = n ? `${n} marcas en este día` : 'sin marcas';
}

function elegirModo(tipo) {
  modoMarcar = modoMarcar === tipo ? null : tipo;
  document.querySelectorAll('[data-tipo]').forEach((el) => {
    el.classList.toggle('on', el.dataset.tipo === modoMarcar);
  });
  $('#chart').style.cursor = modoMarcar ? 'crosshair' : '';
}
document.querySelectorAll('[data-tipo]').forEach((el) => {
  el.addEventListener('click', () => elegirModo(el.dataset.tipo));
});

$('#tf').addEventListener('change', () => {
  TF = parseInt($('#tf').value, 10) || 1;
  redibujar();
  encuadrar();
});
$('#verTodo').addEventListener('click', () => encuadrar(true));

document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'v') alternar('anom');
  if (e.key === 'w') alternar('vwap');
  if (e.key === 'm') alternar('marcas');
  if (e.key === 't') alternar('trade');
  if (e.key === 'z') encuadrar();
  if (e.key === 'Z') encuadrar(true);
  if (e.key >= '1' && e.key <= '4') {
    TF = [1, 2, 5, 15][+e.key - 1];
    $('#tf').value = String(TF);
    redibujar(); encuadrar();
  }
  if (e.key === 's') elegirModo('entrada_short');
  if (e.key === 'l') elegirModo('entrada_long');
  if (e.key === 'n') elegirModo('no_va');
  if (e.key === 'Escape') elegirModo(null);
  if (e.key === 'j' || e.key === 'k') {
    const vis = [...document.querySelectorAll('#filas tr[data-t]')]
      .map((el) => ({ ticker: el.dataset.t, d: el.dataset.d }));
    const i = vis.findIndex((r) => SEL && r.ticker === SEL.ticker && r.d === SEL.d);
    const n = vis[Math.max(0, Math.min(vis.length - 1, i + (e.key === 'j' ? 1 : -1)))];
    if (n) abrir(n.ticker, n.d);
  }
});

cargarIndice();
