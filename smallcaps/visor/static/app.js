/* Visor de eventos — front. Sin framework a propósito: son 300 líneas y no
   quiero un build step entre los datos y el gráfico. */

const $ = (s) => document.querySelector(s);
const LWC = window.LightweightCharts;

let TODOS = [];        // índice completo
let VISIBLES = [];     // lo que está en la tabla ahora
let SEL = null;        // {ticker, d}
let DATOS = null;      // payload del día abierto
let orden = { col: 'd', desc: true };
const ver = { anom: true, vwap: true, marcas: true };

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
/* `autoSize` cubre el caso normal, pero si el contenedor todavía medía 0 al
   crear el gráfico las canvas quedan en 0×2 y no se recuperan solas. */
new ResizeObserver(() => {
  const el = $('#chart');
  if (el.clientWidth && el.clientHeight) chart.resize(el.clientWidth, el.clientHeight);
  pintarSombra();
}).observe($('#chart'));

/* ------------------------------------------------------------------ datos */

async function cargarIndice() {
  const r = await fetch('/api/dias').then((x) => x.json());
  if (r.cargando) {
    $('#filas').innerHTML = '<tr><td colspan="4" class="tenue">indexando…</td></tr>';
    return setTimeout(cargarIndice, 1200);
  }
  TODOS = r.dias;
  render();
}

function filtrar() {
  const q = $('#q').value.trim().toUpperCase();
  const minExp = parseFloat($('#minExp').value);
  const banda = $('#banda').value;
  const limpios = $('#soloLimpios').checked;
  const soloEv = $('#soloEventos').checked;
  let v = TODOS.filter((r) => {
    if (q && !r.ticker.includes(q)) return false;
    if (!isNaN(minExp) && (r.expansion == null || r.expansion < minExp)) return false;
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

function render() {
  VISIBLES = filtrar();
  $('#filas').innerHTML = VISIBLES.slice(0, 600).map((r) => `
    <tr data-t="${r.ticker}" data-d="${r.d}"
        class="${SEL && SEL.ticker === r.ticker && SEL.d === r.d ? 'sel' : ''}">
      <td>${r.ticker}</td>
      <td class="tenue">${r.d.slice(5)}${r.evento ? '' : ' ·'}</td>
      <td class="${cls(r.expansion)}">${pct(r.expansion)}</td>
      <td class="${cls(r.intradia)}">${pct(r.intradia)}</td>
    </tr>`).join('') ||
    '<tr><td colspan="4" class="tenue">nada con esos filtros</td></tr>';
  document.querySelectorAll('.lista th').forEach((th) => {
    th.classList.toggle('orden', th.dataset.col === orden.col);
  });
}

async function abrir(ticker, d) {
  SEL = { ticker, d };
  render();
  const r = await fetch(`/api/dia?ticker=${ticker}&d=${d}`).then((x) => x.json());
  if (r.error) { $('#detalle').textContent = r.error; return; }
  DATOS = r;
  $('#vacio').style.display = 'none';

  sVelas.setData(r.velas);
  sVol.setData(r.volumen);
  sVwap.setData(ver.vwap ? r.vwap : []);
  limpiarLineas();
  nivel(r.niveles.prev_close, '#5c6a85', 'cierre previo');
  nivel(r.niveles.pm_high, '#8e6bd8', 'máx pre-market');
  pintarMarcas();
  chart.timeScale().fitContent();
  setTimeout(pintarSombra, 0);
  pintarBarra();
}

function pintarMarcas() {
  if (!DATOS) return;
  const m = [];
  if (ver.marcas) m.push(...DATOS.marcas);
  if (ver.anom) {
    DATOS.anomalias.forEach((a) => m.push({
      time: a.time,
      position: a.subio ? 'belowBar' : 'aboveBar',
      color: a.subio ? '#4a90d9' : '#d98a4a',
      shape: 'circle',
      text: a.texto,
    }));
  }
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
  $('#detalle').innerHTML =
    `${DATOS.velas.length} barras · ${DATOS.anomalias.length} anomalías (≥5× la mediana ` +
    'de las 30 previas)';
}

/* ------------------------------------------------------------------ eventos */

$('#filas').addEventListener('click', (e) => {
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
['q', 'minExp', 'banda', 'soloLimpios', 'soloEventos'].forEach((id) =>
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

const chips = { tgAnom: 'anom', tgVwap: 'vwap', tgMarcas: 'marcas' };
Object.entries(chips).forEach(([id, k]) => {
  $('#' + id).addEventListener('click', () => alternar(k));
});
function alternar(k) {
  ver[k] = !ver[k];
  const id = Object.keys(chips).find((x) => chips[x] === k);
  $('#' + id).classList.toggle('on', ver[k]);
  if (!DATOS) return;
  if (k === 'vwap') sVwap.setData(ver.vwap ? DATOS.vwap : []);
  else pintarMarcas();
}
document.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key === 'v') alternar('anom');
  if (e.key === 'w') alternar('vwap');
  if (e.key === 'm') alternar('marcas');
  if (e.key === 'j' || e.key === 'k') {
    const i = VISIBLES.findIndex((r) => SEL && r.ticker === SEL.ticker && r.d === SEL.d);
    const n = VISIBLES[Math.max(0, Math.min(VISIBLES.length - 1, i + (e.key === 'j' ? 1 : -1)))];
    if (n) abrir(n.ticker, n.d);
  }
});

cargarIndice();
