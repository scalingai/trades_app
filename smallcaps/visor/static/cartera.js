/* Cartera: qué estrategias hay, cuánto se parecen entre sí, y qué combinación
   llega antes a los $20.000.

   La decisión de diseño que importa: la matriz colorea por CORRELACIÓN pero
   también marca el solape de fechas, porque dos estrategias que no operan los
   mismos días están decorrelacionadas por construcción y eso vale más que una
   correlación baja medida sobre retornos. El gris no es "sin dato" — es el
   mejor caso. */

const $ = (s) => document.querySelector(s);
const LWC = window.LightweightCharts;
const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
const cls = (v) => (v == null ? 'tenue' : v > 0 ? 'pos' : 'neg');

const PALETA = ['#26a69a', '#5b8def', '#ef5350', '#d4a11e', '#a06bd6',
  '#3fb6c8', '#e07a3f', '#8bbf4d'];

function colorCorr(c, s) {
  if (c == null || s < 0.05) return '#1a1f2b';       // casi sin días en común
  if (c > 0.6) return '#e5544f';
  if (c > 0.3) return '#7a4a4a';
  if (c > -0.3) return '#2b3444';
  return '#2ea88f';
}

async function cargar() {
  const r = await fetch('/api/cartera').then((x) => x.json());
  if (r.error) {
    $('#tabla').innerHTML = `<tr><td class="vacio">${r.error}</td></tr>`;
    return;
  }
  const es = r.estrategias || [];
  $('#resumen').textContent =
    `${es.length} estrategias · ${(r.ranking || []).length} combinaciones evaluadas`;

  if (!es.length) {
    $('#tabla').innerHTML =
      '<tr><td class="vacio">No hay estrategias todavía. Corré <b>python motor.py</b> '
      + 'o las familias <b>fam_*.py</b>.</td></tr>';
    return;
  }

  /* --- tabla de estrategias --- */
  const ord = [...es].sort((a, b) => (b.ret_nom || 0) - (a.ret_nom || 0));
  $('#tabla').innerHTML = `
    <thead><tr>
      <th>estrategia</th><th>familia</th><th>lado</th><th>ses/mes</th>
      <th>bruto R</th><th>nominal R</th><th>ret/nom</th>
      <th>P1</th><th>P2</th><th>brecha</th>
    </tr></thead><tbody>
    ${ord.map((e) => {
      const mala = e.replica != null && e.replica > 15;
      return `<tr data-e="${e.nombre}" title="clic para abrirla en el historial">
        <td><b>${e.nombre}</b></td>
        <td class="tenue">${e.familia || '—'}</td>
        <td><span class="badge">${e.lado}</span></td>
        <td>${n(e.ses_mes, 1)}</td>
        <td class="${cls(e.bruto_R)}">${n(e.bruto_R, 3)}</td>
        <td class="tenue">${n(e.nom_R, 2)}</td>
        <td class="${(e.ret_nom || 0) > 20 ? 'pos' : 'neg'}"><b>${n(e.ret_nom, 1)}%</b></td>
        <td class="tenue">${n(e.p1_ret_nom ?? null, 1)}</td>
        <td class="tenue">${n(e.p2_ret_nom ?? null, 1)}</td>
        <td class="${mala ? 'neg' : 'tenue'}">${n(e.replica, 1)}p${mala ? ' ⚠' : ''}</td>
      </tr>`;
    }).join('')}</tbody>`;
  $('#tabla').addEventListener('click', (ev) => {
    const tr = ev.target.closest('tr[data-e]');
    if (tr) window.open('/historial', '_blank');
  });

  /* --- matriz ---
     Se dibujan las MAX_MAT de mayor ret/nom, no las 390 que trae el endpoint.
     No es una decision estetica: 390 x 390 son 152.100 celdas, y con eso la
     pagina tarda medio minuto en pintar y el navegador queda sin responder
     (medido: el screenshot del renderer se cae por timeout). Ademas una matriz
     de ese tamano no se lee — la pregunta que contesta es "cuales de las que me
     importan se pisan", y las que importan son las de arriba de la tabla.
     El endpoint sigue devolviendo todo; si hace falta mas, se sube el numero. */
  const MAX_MAT = 40;
  const nn = r.nombres || [];
  const corto = (s) => s.replace(/^[^·]+·/, '').slice(0, 18);
  const donde = new Map(nn.map((x, i) => [x, i]));
  /* Los indices se toman del orden por ret/nom pero se resuelven contra `nn`:
     `r.matriz` esta indexada por la posicion original, no por la del ranking. */
  const sel = ord.map((e) => e.nombre).filter((x) => donde.has(x)).slice(0, MAX_MAT);
  const ix = sel.map((x) => donde.get(x));
  $('#matAlcance').innerHTML = nn.length > sel.length
    ? `Se muestran las <b>${sel.length}</b> de mayor ret/nom, de ${nn.length} medidas.`
    : '';
  $('#matriz').innerHTML = `
    <thead><tr><th></th>${sel.map((x) =>
      `<th class="rot">${corto(x)}</th>`).join('')}</tr></thead>
    <tbody>${sel.map((a, ai) => `<tr><th>${corto(a)}</th>${
      sel.map((b, bj) => {
        const i = ix[ai], j = ix[bj];
        const c = r.matriz[i][j];
        if (i === j) return '<td style="background:#0d1117"></td>';
        const col = colorCorr(c.c, c.s);
        const txt = c.c == null ? '·' : (c.c >= 0 ? '+' : '') + c.c.toFixed(2);
        return `<td style="background:${col}" title="${a} vs ${b}
correlación ${c.c == null ? 'no medible (pocos días en común)' : c.c.toFixed(3)}
fechas compartidas ${(c.s * 100).toFixed(0)}%">${txt}<br>
        <span style="opacity:.55">${(c.s * 100).toFixed(0)}%</span></td>`;
      }).join('')}</tr>`).join('')}</tbody>`;

  /* --- curvas --- */
  const chart = LWC.createChart($('#curvas'), {
    autoSize: true,
    layout: { background: { color: '#131922' }, textColor: '#7b8598', fontSize: 11 },
    grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
    rightPriceScale: { borderColor: '#222938' },
    timeScale: { borderColor: '#222938' },
    localization: { locale: 'es-AR' },
  });
  const t = (d) => Math.floor(new Date(d + 'T12:00:00Z').getTime() / 1000);
  ord.slice(0, 8).forEach((e, k) => {
    const s = chart.addLineSeries({
      color: PALETA[k % PALETA.length], lineWidth: 2,
      priceLineVisible: false, title: corto(e.nombre),
    });
    let acum = 0;
    /* Dedup por fecha: dos puntos con el mismo timestamp dejan la serie
       malformada y la librería no avisa — ya pasó una vez en este visor. */
    const vistos = new Set();
    const datos = [];
    (e.serie || []).forEach(([d, v]) => {
      acum += v;
      if (vistos.has(d)) return;
      vistos.add(d);
      datos.push({ time: t(d), value: Number(acum.toFixed(4)) });
    });
    s.setData(datos);
  });
  chart.timeScale().fitContent();

  /* --- ranking --- */
  const rk = r.ranking || [];
  $('#ranking').innerHTML = rk.length ? `
    <thead><tr>
      <th>#</th><th>meses (mediana)</th><th>p90</th><th>llega</th>
      <th>caja 48m</th><th>peor 10%</th><th>corr</th><th>solape</th>
      <th>estrategias</th>
    </tr></thead><tbody>
    ${rk.map((x, i) => `<tr>
      <td>${i + 1}</td>
      <td class="${x.meses_med && x.meses_med < 18 ? 'pos' : ''}">
        <b>${x.meses_med ? n(x.meses_med, 1) : '—'}</b></td>
      <td class="tenue">${x.meses_p90 ? n(x.meses_p90, 0) : '—'}</td>
      <td>${n(x.p_llega, 0)}%</td>
      <td class="${cls(x.caja_med)}">$${n(x.caja_med, 0)}</td>
      <td class="${cls(x.caja_p10)}">$${n(x.caja_p10, 0)}</td>
      <td class="${x.cor > 0.6 ? 'neg' : 'pos'}">${x.cor == null ? '—' : n(x.cor, 2)}</td>
      <td class="${x.solape > 0.5 ? 'neg' : 'pos'}">${n(x.solape * 100, 0)}%</td>
      <td class="tenue">${(x.combo || []).join(' + ')}</td>
    </tr>`).join('')}</tbody>` : `
    <tr><td class="vacio">Sin ranking todavía. Corré
    <b>python cartera.py</b> para generarlo.</td></tr>`;
}

cargar();
