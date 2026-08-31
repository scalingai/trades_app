/* Historial de trades. Cada variante de estrategia con su curva y sus filas.
   La navegación es la del visor: clic en un trade abre el día en el gráfico. */

const $ = (s) => document.querySelector(s);
const LWC = window.LightweightCharts;

let TRADES = [];
let orden = { c: 'd', desc: false };

const chart = LWC.createChart($('#curva'), {
  autoSize: true,
  layout: { background: { color: '#0b0e14' }, textColor: '#7b8598', fontSize: 11 },
  grid: { vertLines: { color: '#151b26' }, horzLines: { color: '#151b26' } },
  rightPriceScale: { borderColor: '#222938' },
  timeScale: { borderColor: '#222938' },
  localization: { locale: 'es-AR' },
});
/* La curva es acumulada POR FECHA, no por trade: los trades del mismo día se
   solapan y sumarlos en serie daría una curva que nadie podría haber operado. */
const sAcum = chart.addAreaSeries({
  lineColor: '#26a69a', topColor: 'rgba(38,166,154,.25)',
  bottomColor: 'rgba(38,166,154,0)', lineWidth: 2, priceLineVisible: false,
});
const sDia = chart.addHistogramSeries({ priceScaleId: 'dia' });
chart.priceScale('dia').applyOptions({ scaleMargins: { top: .75, bottom: 0 } });

const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
const cls = (v) => (v == null ? 'tenue' : v > 0 ? 'pos' : 'neg');
const hhmm = (h) => (h == null ? '—'
  : String(Math.floor(h)).padStart(2, '0') + ':'
    + String(Math.round((h % 1) * 60)).padStart(2, '0'));

function kpi(v, lab, c = '') {
  return `<div class="kpi"><b class="${c}">${v}</b><span>${lab}</span></div>`;
}

async function cargarEstrategias() {
  const r = await fetch('/api/estrategias').then((x) => x.json());
  const es = r.estrategias || [];
  if (!es.length) {
    $('#comp').innerHTML =
      '<span class="tenue">No hay trades guardados. Corré <b>python backtest.py</b>.</span>';
    return;
  }
  $('#est').innerHTML = es.map((e) =>
    `<option value="${e.estrategia}">${e.estrategia}</option>`).join('');

  /* La tabla comparativa arriba: el punto de etiquetar por estrategia es poder
     verlas juntas, no de a una. */
  $('#comp').innerHTML = `<table>
    <tr><th>estrategia</th><th>n</th><th>PnL</th><th>media</th><th>gana</th>
        <th>gan medio</th><th>perd medio</th><th>profit factor</th><th>max DD</th></tr>
    ${es.map((e) => `
      <tr data-e="${e.estrategia}">
        <td>${e.estrategia}</td>
        <td>${e.n}</td>
        <td class="${cls(e.total)}">$${n(e.total, 0)}</td>
        <td class="${cls(e.media)}">$${n(e.media, 3)}</td>
        <td>${n(e.gana, 0)}%</td>
        <td class="pos">$${n(e.gan_medio)}</td>
        <td class="neg">$${n(e.per_medio)}</td>
        <td class="${e.pf >= 1 ? 'pos' : 'neg'}">${e.pf ?? '—'}</td>
        <td class="neg">$${n(e.dd, 0)}</td>
      </tr>`).join('')}
  </table>`;
  $('#comp').addEventListener('click', (ev) => {
    const tr = ev.target.closest('tr[data-e]');
    if (tr) { $('#est').value = tr.dataset.e; cargar(); }
  });
  cargar();
}

async function cargar() {
  const e = $('#est').value;
  document.querySelectorAll('#comp tr[data-e]').forEach((tr) => {
    tr.classList.toggle('sel', tr.dataset.e === e);
  });
  const raw = await fetch(`/api/trades?estrategia=${encodeURIComponent(e)}`)
    .then((x) => x.json());
  const r = raw.trades || raw;
  TRADES = r.filas || [];
  const m = r.metricas || {};
  $('#kpis').innerHTML =
    kpi(`$${n(m.total, 0)}`, 'PnL total', cls(m.total))
    + kpi(m.n, 'trades')
    + kpi(`$${n(m.media, 3)}`, 'media/trade', cls(m.media))
    + kpi(`${n(m.gana, 0)}%`, 'aciertos')
    + kpi(`$${n(m.gan_medio)}`, 'ganador medio', 'pos')
    + kpi(`$${n(m.per_medio)}`, 'perdedor medio', 'neg')
    + kpi(m.pf ?? '—', 'profit factor', m.pf >= 1 ? 'pos' : 'neg')
    + kpi(`$${n(m.dd, 0)}`, 'peor caída', 'neg');

  const curva = r.curva || [];
  const t = (d) => Math.floor(new Date(d + 'T12:00:00Z').getTime() / 1000);
  sAcum.setData(curva.map((c) => ({ time: t(c.d), value: c.acum })));
  sDia.setData(curva.map((c) => ({
    time: t(c.d), value: c.pnl,
    color: c.pnl >= 0 ? 'rgba(38,166,154,.6)' : 'rgba(239,83,80,.6)',
  })));
  chart.timeScale().fitContent();
  pintar();
}

function pintar() {
  const c = orden.c;
  const v = [...TRADES].sort((a, b) => {
    const x = a[c], y = b[c];
    if (x == null) return 1;
    if (y == null) return -1;
    const s = typeof x === 'string' ? x.localeCompare(y) : x - y;
    return orden.desc ? -s : s;
  });
  $('#filas').innerHTML = v.slice(0, 800).map((f) => `
    <tr data-t="${f.ticker}" data-d="${f.d}" title="clic para abrir el día">
      <td><b>${f.ticker}</b></td>
      <td class="tenue">${f.d}</td>
      <td class="tenue">${hhmm(f.hora_entrada)}</td>
      <td class="tenue">${hhmm(f.hora_salida)}</td>
      <td>${n(f.precio_entrada)}</td>
      <td>${n(f.precio_salida)}</td>
      <td class="tenue">${n(f.stop_pct, 1)}</td>
      <td class="tenue">${n(f.acciones, 0)}</td>
      <td class="${cls(f.ret_pct)}">${n(f.ret_pct, 1)}</td>
      <td class="${cls(f.pnl)}"><b>${n(f.pnl)}</b></td>
      <td class="neg">${n(f.mae_pct, 1)}</td>
      <td class="pos">${n(f.mfe_pct, 1)}</td>
      <td><span class="badge">${f.motivo}</span></td>
      <td class="tenue">${n(f.expansion, 0)}</td>
      <td class="tenue">${f.periodo}</td>
    </tr>`).join('');
  document.querySelectorAll('th').forEach((th) => {
    th.classList.toggle('orden', th.dataset.c === orden.c);
  });
}

document.querySelectorAll('th').forEach((th) => {
  th.addEventListener('click', () => {
    const c = th.dataset.c;
    orden = { c, desc: orden.c === c ? !orden.desc : true };
    pintar();
  });
});
$('#filas').addEventListener('click', (e) => {
  const tr = e.target.closest('tr[data-t]');
  if (tr) window.open(`/?ticker=${tr.dataset.t}&d=${tr.dataset.d}`, '_blank');
});
$('#est').addEventListener('change', cargar);

cargarEstrategias();
