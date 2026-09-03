/* portafolio.js — el ciclo de vida de las cuentas de fondeo.

   Los números NO se calculan acá. Salen de `cuentas.simular()`, que es la
   misma función que imprime el informe de terminal. Es la misma regla que en
   /vivo: dos caminos que calculan lo mismo se separan solos, y en una
   proyección de plata eso no se puede permitir. */

(function () {
  const $ = (id) => document.getElementById(id);
  const n = (v, d = 0) => Number(v || 0).toLocaleString('es-AR',
    { minimumFractionDigits: d, maximumFractionDigits: d });
  const signo = (v) => (v >= 0 ? '+' : '−');
  const plata = (v, d = 0) => `${signo(v)}$${n(Math.abs(v), d)}`;
  const clase = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'tenue');

  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  /* Partida a mano: `new Date('2026-02-25')` se lee como UTC y en Argentina
     muestra un día antes. Ya nos mordió en el feed y en /vivo. */
  const fecha = (iso) => {
    const [a, m, d] = iso.split('-').map(Number);
    return `${d} ${MESES[m - 1]} ${String(a).slice(2)}`;
  };

  /* Los estados abiertos se recuerdan entre refrescos: si desplegaste la
     cuenta #2 para mirarla, cambiar el riesgo no te la tiene que cerrar. */
  const abiertas = new Set();

  function resumen(d) {
    const cs = d.cuentas;
    const ret = cs.reduce((a, c) => a + c.retirado, 0);
    const gas = cs.reduce((a, c) => a + c.gastado, 0);
    const bal = cs.reduce((a, c) => a + c.balance, 0);
    const fond = cs.filter((c) => c.estado === 'fondeada').length;
    const quem = cs.reduce((a, c) => a + c.quemadas, 0);
    const bolsillo = ret - gas;
    const gestionado = fond * d.plan.poder;
    return [
      ['bolsillo', plata(bolsillo), clase(bolsillo)],
      ['retirado', `$${n(ret)}`, ''],
      ['en las cuentas', `$${n(bal)}`, ''],
      ['gastado en evaluaciones', `$${n(gas)}`, 'neg'],
      ['fondeadas', String(fond), fond ? 'pos' : ''],
      ['quemadas', String(quem), quem ? 'neg' : 'tenue'],
      ['poder gestionado', `$${n(gestionado)}`, ''],
    ].map(([rot, val, cls]) =>
      `<div><b class="${cls}">${val}</b><span>${rot}</span></div>`).join('');
  }

  /* EL HITO DEL DIA. Un día en que la cuenta cambió de vida importa más que su
     PnL: es cuándo empezó a producir, o cuándo se murió. La historia guarda el
     estado al cierre de cada día, así que el cambio se detecta comparando con
     el día anterior. */
  function hito(hoy, ayer) {
    if (!ayer) return null;
    if (ayer.estado === 'evaluacion' && hoy.estado === 'fondeada') return 'pasó a fondeada';
    if (ayer.estado === 'fondeada' && hoy.estado === 'evaluacion') return 'se quemó';
    if (hoy.retirado > ayer.retirado) {
      return `retiró ${plata(hoy.retirado - ayer.retirado)}`;
    }
    return null;
  }

  function dias(c, plan) {
    const filas = c.historia.map((h, i) => {
      const ev = hito(h, c.historia[i - 1]);
      const quema = ev === 'se quemó';
      /* EL DIA QUE HABRIA REVENTADO LA CUENTA Y NO FIGURA COMO QUEMADA.
         El simulador mide el drawdown sobre el balance de CIERRE de cada día;
         el plan lo mide sobre la equity, minuto a minuto. Un día que cierra en
         +$2.882 después de haber ido -$1.048 no deja rastro en el balance
         diario y sin embargo perfora un tope de $800. Se marca en ámbar
         porque es el supuesto más optimista que queda en toda la proyección. */
      const revienta = Math.abs(h.dd) > plan.tope_dd;
      return `<div class="dia${ev ? (quema ? ' hito quema' : ' hito') : ''}`
        + `${revienta ? ' revienta' : ''}">`
        + `<span class="f">${fecha(h.f)}</span>`
        + `<span class="tk">${h.tk || '—'}</span>`
        + `<span class="hito-txt">${ev || ''}</span>`
        + `<span class="n ${clase(h.pnl)}">${plata(h.pnl, 2)}</span>`
        + `<span class="n ${revienta ? 'dd-mal' : 'tenue'}"`
        + `${revienta ? ' title="intradía perforó el tope de drawdown"' : ''}>`
        + `${h.dd ? plata(h.dd, 2) : '—'}</span>`
        + `<span class="n tenue">${h.tramos}</span>`
        + '</div>';
    }).reverse().join('');
    return '<div class="cols"><span>día</span><span>papel</span><span></span>'
      + '<span>resultado</span><span>drawdown</span><span>tramos</span></div>'
      + `<div class="dias">${filas}</div>`;
  }

  function trabas(c, plan) {
    const m = c.motivos || {};
    const claves = Object.keys(m);
    if (!claves.length) return '';
    const partes = claves.sort((a, b) => m[b] - m[a])
      .map((k) => `<b>${m[k]}</b> por ${k}`).join(' · ');
    return `<div class="trabas">Días en que quiso retirar y el plan no dejó: `
      + `${partes}.<br>Las reglas: mínimo <b>$${n(plan.min_retiro)}</b> · `
      + `<b>${plan.dias_entre}</b> días calendario entre retiros`
      + (plan.buenos_pedidos
        ? ` · <b>${plan.buenos_pedidos}</b> días de <b>$${n(plan.dia_bueno)}</b>`
          + ` en <b>${plan.ventana_buenos}</b> días`
        : '') + '.</div>';
  }

  function tarjeta(c, plan) {
    /* El margen contra el tope: lo que decide si la cuenta sigue viva. Un 0%
       significa que lo perforó, no que estuvo cerca. */
    const usado = Math.min(1, Math.abs(c.peor_dd) / plan.tope_dd);
    const margen = Math.round(100 * (1 - usado));
    const cls = margen <= 0 ? 'perforado' : margen < 30 ? 'apretado' : '';
    const abierta = abiertas.has(c.n);
    const revientan = c.historia.filter((h) => Math.abs(h.dd) > plan.tope_dd).length;
    return `<section class="cuenta${c.quemadas ? ' quemada' : ''}" data-n="${c.n}">`
      + '<div class="cab">'
      + `<span class="id">Cuenta ${c.n}</span>`
      + `<span class="estado ${c.estado}">${c.estado}</span>`
      + `<span class="m"><b class="${clase(c.balance)}">${plata(c.balance)}</b>`
      + '<span>balance</span></span>'
      + `<span class="m"><b class="${c.retirado ? 'pos' : ''}">$${n(c.retirado)}</b>`
      + '<span>retirado</span></span>'
      + `<span class="m"><b class="${clase(c.peor_dd)}">${plata(c.peor_dd)}</b>`
      + `<span>peor drawdown · ${margen}% de margen</span></span>`
      + `<span class="m"><b>${c.historia.length}</b><span>días operados</span></span>`
      + (revientan
        ? `<div class="aviso-dd">⚠ ${revientan} día${revientan === 1 ? '' : 's'}`
          + ` con drawdown <b>intradía</b> mayor al tope de $${n(plan.tope_dd)}.`
          + ' El simulador mide el drawdown al cierre de cada día; si el plan lo'
          + ' mide minuto a minuto, esa cuenta ya estaba liquidada.</div>'
        : '')
      + `<div class="margen"><i class="${cls}" style="width:${Math.max(0, margen)}%"></i></div>`
      + '</div>'
      + (abierta ? dias(c, plan) + trabas(c, plan) : '')
      + '</section>';
  }

  let ultimo = null;

  function pintar(d) {
    ultimo = d;
    if (d.error) {
      $('lista').innerHTML = `<div class="vacio">${d.error}</div>`;
      return;
    }
    const p = d.plan;
    $('titulo').textContent = `${d.cuentas.length} cuentas · desde ${fecha(d.desde)}`
      + ` · ${d.fechas.length} días con sesión · $${n(d.riesgo)} de riesgo por papel`;
    $('caja').innerHTML = resumen(d);
    $('lista').innerHTML = d.cuentas.map((c) => tarjeta(c, p)).join('');
    $('plan').innerHTML = `Plan <b>${p.nombre.toUpperCase()}</b> sobre `
      + `<b>$${n(p.poder)}</b> de poder de compra: objetivo <b>$${n(p.objetivo)}</b>`
      + ` · drawdown máximo <b>$${n(p.tope_dd)}</b> · pérdida diaria `
      + `<b>$${n(p.lim_dia)}</b> · evaluación <b>$${n(p.eval, 0)}</b> · reparto `
      + `<b>${Math.round(p.split * 100)}%</b> · consistencia `
      + `<b>${Math.round(p.consistencia * 100)}%</b> en evaluación.<br>`
      + 'Los porcentajes son del producto, verificados contra tradethepool.com. '
      + 'Lo que sigue <b>sin confirmar</b> es qué poder de compra compra la '
      + 'evaluación de $97 — y de ahí sale todo lo demás.';
  }

  let pidiendo = 0;
  async function cargar() {
    const id = ++pidiendo;
    $('cargando').textContent = 'calculando…';
    const q = `cuentas=${$('m-cuentas').value}&desde=${$('m-desde').value}`
      + `&riesgo=${$('m-riesgo').value}`;
    try {
      const d = await (await fetch(`/api/portafolio?${q}`)).json();
      /* Si mientras tanto se pidió otra cosa, este resultado ya no sirve. Sin
         esto, tocar el riesgo dos veces seguidas puede dejar en pantalla el
         resultado del PRIMER pedido, que es el que tarda más. */
      if (id !== pidiendo) return;
      pintar(d);
    } catch (e) {
      $('lista').innerHTML = '<div class="vacio">no se pudo calcular</div>';
    } finally {
      if (id === pidiendo) $('cargando').textContent = '';
    }
  }

  $('m-cuentas').value = 3;
  $('m-desde').value = '2026-01-01';
  $('m-riesgo').value = 250;
  ['m-cuentas', 'm-desde', 'm-riesgo'].forEach((id) =>
    $(id).addEventListener('change', cargar));

  /* Delegado: las tarjetas se rehacen enteras en cada refresco. */
  document.addEventListener('click', (ev) => {
    const c = ev.target.closest('.cuenta');
    if (!c || !ev.target.closest('.cab')) return;
    const k = Number(c.dataset.n);
    if (abiertas.has(k)) abiertas.delete(k); else abiertas.add(k);
    if (ultimo) pintar(ultimo);
  });

  cargar();
})();
