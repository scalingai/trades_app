/* Papeles: el mismo backtest, mirado por papel en vez de por día.

   Por qué existe y no alcanzaba con /historial ni con /bitacora: el historial
   compara estrategias entre sí ("¿cuál sirve?") y la bitácora agrupa por
   jornada ("¿qué hago un martes?"). Ninguna de las dos contesta "¿qué le pasó a
   ESTE papel cada vez que el sistema lo tocó?", que es la pregunta con la que se
   auditan las ejecuciones. En este proyecto mirar un gráfico ya encontró dos
   veces bugs que 250.000 trades simulados no habían encontrado.

   Los tres números que van al frente son el PnL en dólares, el PRECIO DE ENTRADA
   y las ACCIONES EN EL PICO de exposición simultánea. El nominal en dólares —que
   es el que se mostraba antes— quedó atrás a propósito: el locate se cobra por
   acción, así que dos papeles con el mismo nominal y distinto precio no cuestan
   lo mismo, y ret/nom es ciego al precio por construcción. */

const $ = (s) => document.querySelector(s);
const G = window.VisorGrafico;          // desfase / dibujar / pico

const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
/* null es null, no cero. El motor llegó a imprimir 0.0% donde no había dato y
   eso hacía que una estrategia con media muestra vacía pareciera perfecta. */
const cls = (v) => (v == null ? 'tenue' : v > 0 ? 'pos' : v < 0 ? 'neg' : 'tenue');
const hhmm = (h) => (h == null ? '—'
  : String(Math.floor(h)).padStart(2, '0') + ':'
    + String(Math.round((h % 1) * 60)).padStart(2, '0'));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const mas = (v) => (v >= 0 ? '+' : '');

let EST = '';
let MEDIDO = {};          // nombre de estrategia -> fecha ISO de medición
let SESION = {};          // fecha -> { pnl_R, nominal_R, tickers }
let PAPELES = [];
const GRAFICOS = new Map();   // "TICKER|fecha" -> chart, para poder destruirlos

/* --------------------------------------------------------------- el rollup */

/* Todo sale de /api/trades, que trae las 1565 filas con ticker, fecha, precio de
   entrada, acciones y PnL. No hace falta endpoint nuevo ni una llamada por día.

   Lo que NO se puede armar acá es el R por papel: `pnl_R` vive en la tabla
   `sesion`, que es por JORNADA. Los días con dos papeles lo comparten, así que
   sumarlo por ticker sería doble conteo. Por eso el R aparece sólo en la
   cabecera de una jornada abierta, y rotulado como de la sesión entera. */
function armar(filas) {
  const porTicker = new Map();
  for (const f of filas) {
    if (!porTicker.has(f.ticker)) porTicker.set(f.ticker, new Map());
    const dias = porTicker.get(f.ticker);
    if (!dias.has(f.d)) dias.set(f.d, []);
    dias.get(f.d).push(f);
  }

  const out = [];
  for (const [ticker, dias] of porTicker) {
    const jornadas = [...dias.entries()]
      .sort((a, b) => (a[0] < b[0] ? -1 : 1))
      .map(([d, ts]) => {
        const pnl = ts.reduce((a, t) => a + (t.pnl || 0), 0);
        const px = G.pico(ts);
        return {
          d, ts, pnl, px,
          /* Ponderado por acciones, no promedio simple: tres entradas de 30
             acciones y una de 300 no valen lo mismo para el costo. */
          precio: ponderado(ts),
          expansion: ts[0]?.expansion ?? null,
          stop_pct: ts[0]?.stop_pct ?? null,
          stops: ts.filter((t) => t.motivo === 'stop').length,
          mae: Math.min(...ts.map((t) => t.mae_pct ?? 0)),
          mfe: Math.max(...ts.map((t) => t.mfe_pct ?? 0)),
        };
      });
    const todos = jornadas.flatMap((j) => j.ts);
    out.push({
      ticker,
      jornadas,
      trades: todos.length,
      pnl: jornadas.reduce((a, j) => a + j.pnl, 0),
      precio: ponderado(todos),
      accPico: Math.max(...jornadas.map((j) => j.px.acciones)),
    });
  }
  return out;
}

function ponderado(ts) {
  const acc = ts.reduce((a, t) => a + (t.acciones || 0), 0);
  if (!acc) return null;
  return ts.reduce((a, t) => a + (t.precio_entrada || 0) * (t.acciones || 0), 0) / acc;
}

/* Una barra por jornada, con signo. El R acumulado solo no alcanza para decidir
   si vale la pena abrir un papel: uno de +0,1 R puede esconder un +3 y un −2,9,
   y ese es justamente el caso que hay que poder ver desde afuera. */
function spark(vals) {
  if (!vals.length) return '';
  const max = Math.max(...vals.map((v) => Math.abs(v))) || 1;
  const w = Math.max(1, Math.min(6, Math.floor(74 / vals.length) - 1));
  const paso = w + 1, alto = 18, medio = alto / 2;
  const barras = vals.map((v, i) => {
    const h = Math.max(1, Math.round((Math.abs(v) / max) * (medio - 1)));
    const y = v >= 0 ? medio - h : medio;
    return `<rect x="${i * paso}" y="${y}" width="${w}" height="${h}" `
      + `fill="${v >= 0 ? '#2ea88f' : '#e5544f'}"/>`;
  }).join('');
  return `<svg width="${vals.length * paso}" height="${alto}" `
    + `viewBox="0 0 ${vals.length * paso} ${alto}">`
    + `<line x1="0" y1="${medio}" x2="${vals.length * paso}" y2="${medio}" `
    + `stroke="#28303c" stroke-width="1"/>${barras}</svg>`;
}

/* ---------------------------------------------------------------- pintado */

function pintar() {
  const q = $('#q').value.trim().toUpperCase();
  const modo = $('#orden').value;
  const vis = PAPELES.filter((p) => !q || p.ticker.includes(q));
  const clave = {
    abs: (p) => -Math.abs(p.pnl),
    pnl: (p) => -p.pnl,
    jornadas: (p) => -p.jornadas.length,
    precio: (p) => -(p.precio ?? 0),
    acciones: (p) => -p.accPico,
  }[modo];
  vis.sort(clave ? (a, b) => clave(a) - clave(b)
    : (a, b) => a.ticker.localeCompare(b.ticker));

  $('#resumen').textContent =
    /* "jornadas de papel" y no "jornadas" a secas: un día en que el sistema
       operó dos papeles cuenta dos veces acá, porque la unidad de esta vista
       es el par papel-jornada. El calendario tiene menos días que esto. */
    `${vis.length} papeles · ${vis.reduce((a, p) => a + p.jornadas.length, 0)}`
    + ` jornadas de papel · ${vis.reduce((a, p) => a + p.trades, 0)} trades`;

  $('#lista').innerHTML = vis.map((p) => `
    <div class="f f-papel" data-tk="${esc(p.ticker)}">
      <span class="flecha">▶</span>
      <span class="tk">${esc(p.ticker)}</span>
      <span class="meta">${p.jornadas.length} jornada${p.jornadas.length === 1 ? '' : 's'}
        · ${p.trades} trade${p.trades === 1 ? '' : 's'}</span>
      <span class="der" title="precio de entrada medio, ponderado por acciones">
        $${n(p.precio, 3)}</span>
      <span class="der tenue" title="máximo de acciones simultáneas en cualquiera de sus jornadas">
        ${n(p.accPico, 0)} acc</span>
      <span class="spark" title="una barra por jornada, con signo">${
        spark(p.jornadas.map((j) => j.pnl))}</span>
      <span class="der ${cls(p.pnl)}"><b>${mas(p.pnl)}$${n(p.pnl, 2)}</b></span>
    </div>
    <div class="jornadas" data-de="${esc(p.ticker)}" hidden>${
      p.jornadas.map((j) => `
        <div class="f f-jornada" data-tk="${esc(p.ticker)}" data-d="${j.d}">
          <span class="flecha">▶</span>
          <span class="tk">${j.d}</span>
          <span class="meta">exp ${n(j.expansion, 0)}% · ${j.ts.length} trade${
            j.ts.length === 1 ? '' : 's'}${j.stops ? ` · ${j.stops} stop` : ''}</span>
          <span class="der">$${n(j.precio, 3)}</span>
          <span class="der tenue">${n(j.px.acciones, 0)} acc</span>
          <span></span>
          <span class="der ${cls(j.pnl)}">${mas(j.pnl)}$${n(j.pnl, 2)}</span>
        </div>
        <div class="detalle" data-det="${esc(p.ticker)}|${j.d}" hidden></div>`).join('')}
    </div>`).join('') || '<div class="vacio">Ningún papel coincide.</div>';
}

/* --------------------------------------------------------------- plegado */

/* El gráfico se crea al abrir la jornada y se DESTRUYE al cerrarla. Con 227
   papeles y 223 jornadas, dejarlos vivos sería tener cientos de lienzos de
   lightweight-charts en memoria a la vez. */
$('#lista').addEventListener('click', async (ev) => {
  const fp = ev.target.closest('.f-papel');
  if (fp) {
    const caja = $(`.jornadas[data-de="${CSS.escape(fp.dataset.tk)}"]`);
    const abrir = caja.hidden;
    caja.hidden = !abrir;
    fp.classList.toggle('abierto', abrir);
    if (!abrir) caja.querySelectorAll('.f-jornada.abierto').forEach(cerrarJornada);
    return;
  }
  const fj = ev.target.closest('.f-jornada');
  if (!fj) return;
  if (fj.classList.contains('abierto')) { cerrarJornada(fj); return; }
  await abrirJornada(fj);
});

function detalleDe(fj) {
  return $(`.detalle[data-det="${CSS.escape(fj.dataset.tk + '|' + fj.dataset.d)}"]`);
}

function cerrarJornada(fj) {
  fj.classList.remove('abierto');
  const det = detalleDe(fj);
  if (det) { det.hidden = true; det.innerHTML = ''; }
  const k = `${fj.dataset.tk}|${fj.dataset.d}`;
  const ch = GRAFICOS.get(k);
  if (ch) { try { ch.remove(); } catch (e) { /* ya estaba desmontado */ } GRAFICOS.delete(k); }
}

async function abrirJornada(fj) {
  const { tk, d } = fj.dataset;
  const det = detalleDe(fj);
  fj.classList.add('abierto');
  det.hidden = false;
  det.innerHTML = '<div class="cargando">cargando la jornada…</div>';

  const r = await fetch(`/api/bitacora/dia?d=${d}&estrategia=${encodeURIComponent(EST)}`)
    .then((x) => x.json()).catch(() => ({ error: 'no se pudo pedir el día' }));
  if (r.error || !r.papeles?.length) {
    det.innerHTML = `<div class="cargando">${esc(r.error || 'sin datos del día')}</div>`;
    return;
  }
  const p = r.papeles.find((x) => x.ticker === tk);
  if (!p) {
    det.innerHTML = '<div class="cargando">ese papel no está en el día.</div>';
    return;
  }

  const ts = p.trades_estrategia || [];
  const pnl = ts.reduce((a, t) => a + (t.pnl || 0), 0);
  const px = G.pico(ts);
  const precio = ponderado(ts);
  const ses = SESION[d] || {};
  const id = `g_${tk}_${d.replace(/-/g, '')}`;

  det.innerHTML = `
    <div class="kpis">
      ${kpi(`${mas(pnl)}$${n(pnl, 2)}`, 'PnL del papel', cls(pnl), true)}
      ${kpi(`$${n(precio, 3)}`, 'precio de entrada', '', true)}
      ${kpi(`${n(px.acciones, 0)}`, 'acciones en el pico', '')}
      ${kpi(hhmm(px.horaAcciones), 'hora del pico', 'tenue')}
      ${kpi(`${px.tramosAcciones}`, 'tramos a la vez', 'tenue')}
    </div>
    ${contexto(p, ts, px, ses, d)}
    <div class="grafico" id="${id}"></div>
    ${tabla(ts)}`;

  const ch = G.dibujar(id, p);
  if (ch) GRAFICOS.set(`${tk}|${d}`, ch);
}

function kpi(v, lab, c = '', jefe = false) {
  return `<div class="kpi${jefe ? ' jefe' : ''}"><b class="${c}">${v}</b>`
    + `<span>${lab}</span></div>`;
}

/* Todo lo que no es uno de los números grandes, en prosa. La exposición
   simultánea se explica en vez de mostrarse pelada porque es el número que este
   proyecto ya tuvo mal: durante un tiempo se tomaba el trade más grande en vez
   de la suma, y el costo de locate salía nueve veces más barato de lo real. */
function contexto(p, ts, px, ses, d) {
  const partes = [];
  const mayor = Math.max(...ts.map((t) => t.acciones || 0));
  partes.push(`Expansión premarket <b>${n(p.resumen?.expansion, 0)}%</b>,
    apertura <b>$${n(p.niveles?.rth_open)}</b>, máximo premarket
    <b>$${n(p.niveles?.pm_high)}</b>, stop <b>${n(ts[0]?.stop_pct, 0)}%</b>.`);
  partes.push(`Primera entrada <b>${hhmm(ts[0]?.hora_entrada)}</b>, última
    <b>${hhmm(ts[ts.length - 1]?.hora_entrada)}</b>. La entrada más grande fue de
    <b>${n(mayor, 0)}</b> acciones, pero a las <b>${hhmm(px.horaAcciones)}</b>
    había <b>${n(px.acciones, 0)}</b> simultáneas${
    px.tramosAcciones > 1
      ? ` en <b>${px.tramosAcciones}</b> tramos — ${(px.acciones / (mayor || 1)).toFixed(1)}× la entrada más grande`
      : ''}. Eso es lo que hay que tener localizado, y es lo que se paga
    (<b>$${n(px.nominal, 0)}</b> de nominal en el pico de dólares, a las
    <b>${hhmm(px.hora)}</b>).`);
  const stops = ts.filter((t) => t.motivo === 'stop').length;
  partes.push(stops === 0
    ? `Ningún stop: los ${ts.length} cerraron al cierre de la rueda.`
    : stops === ts.length
      ? `<b>Los ${stops} salieron por stop.</b> Día en que el papel no cedió.`
      : `<b>${stops}</b> de ${ts.length} salieron por stop.`);
  const mae = Math.min(...ts.map((t) => t.mae_pct ?? 0));
  const mfe = Math.max(...ts.map((t) => t.mfe_pct ?? 0));
  partes.push(`Peor excursión en contra <b>${n(mae, 1)}%</b>, mejor a favor
    <b>${n(mfe, 1)}%</b>.`);
  /* El R es de la SESIÓN, no del papel: la tabla `sesion` es por jornada, así
     que en un día de dos papeles este número los incluye a los dos. Decirlo es
     la diferencia entre un dato y un dato mal atribuido. */
  if (ses.pnl_R != null) {
    const otros = (ses.tickers || []).filter((x) => x && x !== p.ticker);
    partes.push(`La sesión del ${d} cerró en
      <b class="${cls(ses.pnl_R)}">${mas(ses.pnl_R)}${n(ses.pnl_R, 2)} R</b>${
      otros.length
        ? ` — pero ese R es de la <b>sesión entera</b>, que también operó ${esc(otros.join(', '))}.`
        : ', y ese día este fue el único papel operado.'}`);
  }
  return `<div class="contexto">${partes.join(' ')}</div>`;
}

function tabla(ts) {
  if (!ts.length) return '';
  return `<table>
    <thead><tr><th>#</th><th>entra</th><th>sale</th><th>precio</th><th>salida</th>
      <th>stop %</th><th>acciones</th><th>nominal</th><th>PnL</th>
      <th>MAE</th><th>MFE</th><th>motivo</th></tr></thead>
    <tbody>${ts.map((t, i) => `<tr>
      <td>${i + 1}</td>
      <td>${hhmm(t.hora_entrada)}</td>
      <td class="tenue">${hhmm(t.hora_salida)}</td>
      <td>$${n(t.precio_entrada, 3)}</td>
      <td>$${n(t.precio_salida, 3)}</td>
      <td class="tenue">${n(t.stop_pct, 0)}</td>
      <td>${n(t.acciones, 0)}</td>
      <td class="tenue">$${n((t.acciones || 0) * (t.precio_entrada || 0), 0)}</td>
      <td class="${cls(t.pnl)}"><b>$${n(t.pnl, 2)}</b></td>
      <td class="neg">${n(t.mae_pct, 1)}%</td>
      <td class="pos">${n(t.mfe_pct, 1)}%</td>
      <td><span class="badge">${esc(t.motivo)}</span></td>
    </tr>`).join('')}</tbody>
  </table>`;
}

/* ----------------------------------------------------- fecha de medición */

/* 337 de las 408 estrategias son de una era anterior del motor, así que pintar
   de ámbar "no es la más nueva" marcaría el 83% de la lista y el color dejaría
   de querer decir algo. Se muestra entonces el dato —cuándo se midió ESTA— y el
   ámbar aparece sólo como aclaración de que hay medidas más nuevas con las que
   no se puede comparar. Y no se infiere por prefijo: `limpio·reclaim·todo` es
   de la era vieja y `limpio·reclaim·exp150` de la nueva. */
function pintarMedicion() {
  const el = $('#medicion');
  const mio = MEDIDO[EST];
  if (!mio) { el.textContent = ''; el.className = 'medicion'; return; }
  const todas = Object.values(MEDIDO).filter(Boolean);
  const ultima = todas.length ? todas.reduce((a, b) => (a > b ? a : b)) : mio;
  const dia = (s) => String(s).slice(0, 10);
  const vieja = dia(mio) < dia(ultima);
  el.className = 'medicion' + (vieja ? ' vieja' : '');
  el.textContent = vieja
    ? `medida ${dia(mio)} · hay medidas del ${dia(ultima)}`
    : `medida ${dia(mio)}`;
  el.title = vieja
    ? 'Esta estrategia se midió con una corrida anterior del motor. '
      + 'Sus números no son comparables con los de las medidas después.'
    : 'Medida con la corrida más reciente del motor.';
}

/* -------------------------------------------------------------- arranque */

async function cargar(estrategia) {
  $('#lista').innerHTML = '<div class="vacio">cargando…</div>';
  const b = await fetch('/api/bitacora'
    + (estrategia ? `?estrategia=${encodeURIComponent(estrategia)}` : ''))
    .then((x) => x.json());
  EST = b.estrategia || '';
  MEDIDO = b.medido || {};
  SESION = {};
  (b.dias || []).forEach((x) => { SESION[x.d] = x; });

  if (!$('#est').options.length) {
    $('#est').innerHTML = (b.estrategias || []).map((e) =>
      `<option value="${esc(e)}"${e === EST ? ' selected' : ''}>${esc(e)}</option>`).join('');
  }
  $('#est').value = EST;
  pintarMedicion();

  const t = await fetch(`/api/trades?estrategia=${encodeURIComponent(EST)}`)
    .then((x) => x.json());
  PAPELES = armar((t.trades || t).filas || []);
  GRAFICOS.forEach((ch) => { try { ch.remove(); } catch (e) { /* nada */ } });
  GRAFICOS.clear();
  pintar();
}

$('#est').addEventListener('change', () => cargar($('#est').value));
$('#orden').addEventListener('change', pintar);
$('#q').addEventListener('input', pintar);

cargar();
