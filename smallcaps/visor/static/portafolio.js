/* portafolio.js — la cuenta propia en TradeZero, día por día.

   Los números NO se calculan acá. Salen de `propia.simular()`, que es la
   misma función que imprime el informe de terminal. Es la misma regla que en
   /vivo: dos caminos que calculan lo mismo se separan solos, y en una
   proyección de plata eso no se puede permitir. */

(function () {
  const $ = (id) => document.getElementById(id);
  const n = (v, d = 0) => Number(v || 0).toLocaleString('es-AR',
    { minimumFractionDigits: d, maximumFractionDigits: d });
  const signo = (v) => (v >= 0 ? '+' : '−');
  const plata = (v, d = 0) => `${signo(v)}$${n(Math.abs(v), d)}`;
  /* Rojo es plata PERDIDA, nada más. Un costo se escribe en gris con su
     signo: es plata que salió, no un resultado. */
  const clase = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : 'tenue');
  const costo = (v, d = 0) => (v ? `−$${n(Math.abs(v), d)}` : '—');

  const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun',
                 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  /* Partida a mano: `new Date('2026-02-25')` se lee como UTC y en Argentina
     muestra un día antes. Ya nos mordió en el feed y en /vivo. */
  const fecha = (iso) => {
    const [a, m, d] = iso.split('-').map(Number);
    return `${d} ${MESES[m - 1]} ${String(a).slice(2)}`;
  };

  /* Los días desplegados se recuerdan entre refrescos: si abriste el 21 de
     julio para mirar VIVK, cambiar el locate no te lo tiene que cerrar. */
  const abiertos = new Set();

  const LOCATE_CARO = 0.10;   // OPERATIVA.md §0: arriba de esto no se toca

  function escenarios(d) {
    const p = d.params;
    return d.escenarios.map((e) => {
      const activo = e.deposito === p.deposito && e.riesgo === p.riesgo;
      return `<div class="esc${activo ? ' activo' : ''}" data-dep="${e.deposito}"`
        + ` data-riesgo="${e.riesgo}">`
        + `<span class="t">$${n(e.deposito)} · $${n(e.riesgo)} por papel`
        + `<small>${e.estado === 'parada' ? 'se paró' : 'operando'} · `
        + `${e.dias} días</small></span><span></span>`
        + `<span class="m"><b class="${clase(e.anual)}">${plata(e.anual)}</b>`
        + '<span>al año, neto</span></span>'
        + `<span class="m"><b class="${clase(e.peor_dd)}">${Math.round(e.peor_dd_pct)}%</b>`
        + '<span>peor drawdown</span></span>'
        + '</div>';
    }).join('');
  }

  function resumen(d) {
    const c = d.cuenta;
    const costos = c.comision + c.locates + c.plataforma;
    const loc = c.locates_reales + c.locates_supuestos;
    return [
      ['equity hoy', `$${n(c.equity)}`, '', `de $${n(c.deposito)} depositados`],
      ['resultado neto', plata(c.neto), clase(c.neto), `${plata(c.anual)} al año`],
      /* POR DIA OPERADO, los dos: es lo que explica por que la cuenta chica
         sangra y la grande no. El costo por dia es FIJO —$0,49 por orden y
         100 acciones de locate no achican con el riesgo— y el bruto por dia
         escala con el riesgo. Cuando el segundo no cubre al primero, la
         cuenta baja aunque la estrategia gane. */
      ['bruto', plata(c.bruto), clase(c.bruto),
        `${plata(c.bruto / Math.max(1, c.dias), 1)} por día operado`],
      ['costos', costo(costos), '',
        `${costo(costos / Math.max(1, c.dias), 1)} por día operado · ${Math.round(100 * costos / Math.max(1, Math.abs(c.bruto)))}% del bruto`],
      ['comisiones', costo(c.comision), '', 'mínimo $0,49 por orden'],
      ['locates', costo(c.locates), '',
        c.locates_reales
          ? `${c.locates_reales} de ${loc} anotados`
          : `${loc} papeles-día, todos supuestos`],
      ['peor drawdown', plata(c.peor_dd), clase(c.peor_dd),
        `${Math.round(c.peor_dd_pct)}% del depósito, intradía`],
      ['días operados', String(c.dias), '', `en ${d.meses} meses`],
    ].map(([rot, val, cls, det]) =>
      `<div><b class="${cls}">${val}</b><span>${rot}</span><small>${det}</small></div>`)
      .join('');
  }

  function papeles(h) {
    const filas = h.papeles.map((p) => {
      const mot = Object.entries(p.motivos || {})
        .map(([k, v]) => `${v} ${k}`).join(' · ');
      const locCls = p.locate_acc > LOCATE_CARO ? 'caro' : p.locate_real ? 'real' : '';
      return '<div class="papel">'
        + '<span></span>'
        + `<span class="tk">${p.tk}<small>$${n(p.precio, 2)} · ${p.pico_acciones} acc</small></span>`
        + `<span class="n ${clase(p.bruto)}">${plata(p.bruto, 2)}</span>`
        + `<span class="n tenue" title="${p.ordenes} órdenes">${costo(p.comision, 2)}</span>`
        + `<span class="n loc ${locCls}" title="${p.locate_acciones} acciones a `
        + `$${n(p.locate_acc, 3)} · ${p.locate_real ? 'anotado en /vivo' : 'supuesto'}">`
        + `${costo(p.locate, 2)}${p.locate_real ? '' : '<small> ?</small>'}</span>`
        + `<span class="n ${clase(p.neto)}">${plata(p.neto, 2)}</span>`
        + `<span class="n tenue">${p.dd ? plata(p.dd, 2) : '—'}</span>`
        + `<span class="n tenue" title="${mot}">${p.tramos}</span>`
        + '</div>';
    }).join('');
    return '<div class="papeles"><div class="cols"><span></span><span>papel</span>'
      + '<span>bruto</span><span>comisión</span><span>locate</span><span>neto</span>'
      + '<span>drawdown</span><span>tramos</span></div>' + filas + '</div>';
  }

  function dias(c) {
    const filas = c.historia.map((h) => {
      const costos = h.comision + h.locates + h.plataforma;
      const abierto = abiertos.has(h.f);
      const tks = h.papeles.map((p) => p.tk).join(' ');
      const nota = h.parada ? '<i>se paró acá</i>'
        : h.factor < 1 ? `<i>riesgo recortado al ${Math.round(100 * h.factor)}%: `
          + `$${n(h.nominal)} de nominal contra $${n(h.poder)} de poder</i>`
        : '';
      return `<div class="dia${h.parada ? ' parada' : h.factor < 1 ? ' recortado' : ''}`
        + `${abierto ? ' abierto' : ''}" data-f="${h.f}">`
        + `<span class="f">${fecha(h.f)}</span>`
        + `<span class="tks">${tks}${nota}</span>`
        + `<span class="n ${clase(h.bruto)}">${plata(h.bruto, 2)}</span>`
        + `<span class="n tenue">${costo(costos, 2)}</span>`
        + `<span class="n ${clase(h.neto)}">${plata(h.neto, 2)}</span>`
        + `<span class="n tenue">${h.dd ? plata(h.dd, 2) : '—'}</span>`
        + `<span class="n">$${n(h.equity)}</span>`
        + '</div>' + (abierto ? papeles(h) : '');
    }).reverse().join('');
    return '<div class="cols"><span>día</span><span>papeles</span><span>bruto</span>'
      + '<span>costos</span><span>neto</span><span>drawdown</span><span>equity</span></div>'
      + `<div class="dias">${filas}</div>`;
  }

  function tarjeta(d) {
    const c = d.cuenta;
    const p = d.params;
    /* El colchón hasta el stop-out: qué tan cerca estuvo la cuenta de parar.
       100% es que nunca bajó del depósito; 0% es que lo tocó. */
    const stop = c.deposito * p.parar_en;
    const minimo = c.historia.length
      ? Math.min(c.deposito, ...c.historia.map((h) => h.equity)) : c.deposito;
    const margen = c.deposito > stop
      ? Math.round(100 * (minimo - stop) / (c.deposito - stop)) : 100;
    const cls = margen <= 0 ? 'perforado' : margen < 30 ? 'apretado' : '';
    const sup = c.locates_supuestos;
    return `<section class="cuenta${c.estado === 'parada' ? ' parada' : ''}">`
      + '<div class="cab">'
      + '<span class="id">Cuenta propia</span>'
      + `<span class="estado ${c.estado}">${c.estado === 'parada' ? 'parada' : 'operando'}</span>`
      + `<span class="m"><b>$${n(c.equity)}</b><span>equity</span></span>`
      + `<span class="m"><b class="${c.retirable ? 'pos' : ''}">$${n(c.retirable)}</b>`
      + '<span>retirable sin bajar del depósito</span></span>'
      + `<span class="m"><b class="${clase(c.peor_dd)}">${plata(c.peor_dd)}</b>`
      + `<span>peor drawdown · ${Math.max(0, margen)}% de colchón</span></span>`
      + `<span class="m"><b>${c.dias}</b><span>días operados</span></span>`
      + `<div class="margen"><i class="${cls}" style="width:${Math.max(0, margen)}%"></i></div>`
      + (sup
        ? `<div class="aviso">⚠ <b>${sup}</b> papel${sup === 1 ? '' : 'es'}-día con el locate`
          + ` <b>supuesto</b> a $${n(p.locate, 2)}/acción. Es el costo que decide y no está`
          + ' medido: se anota cada mañana en /vivo, columna <b>loc</b>, y esta proyección'
          + ' lo toma de ahí en cuanto exista.</div>'
        : '')
      + (c.recortados
        ? `<div class="aviso">⚠ <b>${c.recortados}</b> día${c.recortados === 1 ? '' : 's'}`
          + ' con el riesgo <b>recortado</b>: el nominal que pedía la estrategia superaba'
          + ' el poder de compra. Marcados en ámbar.</div>'
        : '')
      + '</div>'
      + dias(c)
      + '</section>';
  }

  /* LA CURVA. Lightweight Charts, la misma librería que dibuja las velas en
     /vivo. Cada barra de cada día es un punto; la librería los pone a
     distancia fija —no deja huecos por los días sin sesión—, así que la curva
     se lee corrida y el eje dice la fecha. El tiempo se pasa como si la hora
     de Nueva York fuera UTC: la librería dibuja en UTC y así el eje muestra el
     reloj del mercado, no el de la máquina. */
  let chart = null;
  let serie = null;
  let lineas = [];
  let curvaDe = null;   // el payload que ya está dibujado, para no redibujar
  let tocado = false;   // si el usuario hizo zoom o arrastró, no se lo pisa

  /* ENCUADRAR TODO. `fitContent` recién después de `setData` mide un chart que
     todavía no tiene ancho —autoSize lo mide asincrónicamente— y deja a la
     vista los últimos dos días. Ya pasó en /vivo con `setVisibleRange`. Se
     encuadra en el próximo frame y otra vez cada vez que el contenedor cambia
     de tamaño, salvo que el usuario ya haya tocado el zoom. */
  function encuadrar() {
    if (!chart || tocado) return;
    requestAnimationFrame(() => chart && !tocado && chart.timeScale().fitContent());
  }

  function curva(d) {
    if (curvaDe === d || typeof LightweightCharts === 'undefined') return;
    curvaDe = d;
    const c = d.cuenta;
    const p = d.params;
    if (!chart) {
      chart = LightweightCharts.createChart($('curva'), {
        autoSize: true,
        layout: { background: { color: '#131922' }, textColor: '#7b8598', fontSize: 11 },
        grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
        rightPriceScale: { borderColor: '#222938' },
        /* `minBarSpacing` por defecto es medio píxel por barra: con 22.000
           barras en 330px la librería se niega a mostrar más de dos días,
           aunque se le pida encuadrar todo. */
        timeScale: { borderColor: '#222938', timeVisible: true, secondsVisible: false,
                     minBarSpacing: 0.001 },
        crosshair: { mode: 0 },
        localization: { locale: 'es-AR', priceFormatter: (v) => `$${n(v)}` },
      });
      serie = chart.addBaselineSeries({
        topLineColor: '#2ea88f', topFillColor1: 'rgba(46,168,143,.28)',
        topFillColor2: 'rgba(46,168,143,.03)',
        bottomLineColor: '#e5544f', bottomFillColor1: 'rgba(229,84,79,.03)',
        bottomFillColor2: 'rgba(229,84,79,.28)',
        lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
      });
      const cont = $('curva');
      ['wheel', 'mousedown', 'touchstart'].forEach((ev) =>
        cont.addEventListener(ev, () => { tocado = true; }, { passive: true }));
      new ResizeObserver(encuadrar).observe(cont);
    }
    lineas.forEach((l) => serie.removePriceLine(l));
    lineas = [];
    const datos = [];
    let ultimoT = -1;
    c.historia.forEach((h) => {
      const [a, m, dd] = h.f.split('-').map(Number);
      const base = Date.UTC(a, m - 1, dd) / 1000;
      (h.curva || []).forEach(([hora, eq]) => {
        const t = Math.round(base + hora * 3600);
        if (t <= ultimoT) return;   // dos puntos con el mismo tiempo rompen la serie
        ultimoT = t;
        datos.push({ time: t, value: eq });
      });
    });
    serie.applyOptions({ baseValue: { type: 'price', price: c.deposito } });
    serie.setData(datos);
    lineas.push(serie.createPriceLine({
      price: c.deposito, color: '#6d7788', lineWidth: 1, lineStyle: 2,
      axisLabelVisible: true, title: 'depósito',
    }));
    const stop = c.deposito * p.parar_en;
    if (stop > 0) {
      lineas.push(serie.createPriceLine({
        price: stop, color: '#e5544f', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: 'stop-out',
      }));
    }
    tocado = false;
    encuadrar();
  }

  let ultimo = null;

  function pintar(d) {
    ultimo = d;
    if (d.error) {
      $('lista').innerHTML = `<div class="vacio">${d.error}</div>`;
      return;
    }
    curva(d);
    const p = d.params;
    const b = d.broker;
    $('titulo').textContent = `$${n(p.deposito)} depositados · desde ${fecha(d.desde)}`
      + ` · ${d.fechas.length} días con sesión · $${n(p.riesgo)} de riesgo por papel`;
    $('escenarios').innerHTML = escenarios(d);
    $('caja').innerHTML = resumen(d);
    $('lista').innerHTML = tarjeta(d);
    const apal = b.apalancamiento.map(([u, v]) =>
      `${v}:1 ${u ? `desde $${n(u)}` : 'debajo'}`).join(', ');
    $('plan').innerHTML = '<b>TradeZero International</b>, leído el 3 de septiembre de 2026: '
      + `comisión <b>$0</b> en órdenes de ${b.orden_gratis}+ acciones a más de $1, si no `
      + `<b>${n(b.comision_acc * 100, 1)}¢</b> por acción con mínimo <b>$${n(b.comision_min, 2)}</b>`
      + ` por orden · poder de compra <b>${apal}</b> · sin PDT · shorts en margen sólo desde`
      + ` <b>$${n(b.piso, 2)}</b> (el piso de la estrategia).<br>`
      + `<b>Supuestos</b>: el locate se pide por <b>${b.locate_min}</b> acciones como mínimo,`
      + ' una vez por papel por día, sobre el pico de exposición; se cobra a la mañana. La'
      + ' plataforma se cobra el primer día operado del mes. La cuenta se para por una regla'
      + ` <b>nuestra</b> —equity bajo el ${Math.round(100 * p.parar_en)}% del depósito—, no del`
      + ' broker. El drawdown es intradía y trepa con el pico, sumando las curvas de todos los'
      + ' papeles minuto a minuto.';
  }

  let pidiendo = 0;
  async function cargar() {
    const id = ++pidiendo;
    $('cargando').textContent = 'calculando…';
    const q = `deposito=${$('m-deposito').value}&riesgo=${$('m-riesgo').value}`
      + `&desde=${$('m-desde').value}&locate=${$('m-locate').value}`
      + `&plataforma=${$('m-plataforma').value}`
      + `&parar=${Number($('m-parar').value) / 100}`;
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

  $('m-deposito').value = 500;
  $('m-riesgo').value = 20;
  $('m-desde').value = '2026-01-01';
  $('m-locate').value = 0.05;
  $('m-plataforma').value = 0;
  $('m-parar').value = 20;
  ['m-deposito', 'm-riesgo', 'm-desde', 'm-locate', 'm-plataforma', 'm-parar']
    .forEach((id) => $(id).addEventListener('change', cargar));

  /* Delegado: las filas se rehacen enteras en cada refresco. */
  document.addEventListener('click', (ev) => {
    const e = ev.target.closest('.esc');
    if (e) {
      $('m-deposito').value = e.dataset.dep;
      $('m-riesgo').value = e.dataset.riesgo;
      cargar();
      return;
    }
    const dia = ev.target.closest('.dia');
    if (!dia) return;
    const f = dia.dataset.f;
    if (abiertos.has(f)) abiertos.delete(f); else abiertos.add(f);
    if (ultimo) pintar(ultimo);
  });

  cargar();
})();
