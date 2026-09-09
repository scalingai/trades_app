/* grafico.js — el gráfico de una jornada: velas, volumen, VWAP y las ejecuciones
   dibujadas encima.

   Sale tal cual de `bitacora.js`, donde vivía. Se movió acá porque ahora lo usan
   dos páginas (/bitacora y /papeles) y copiarlo habría repetido exactamente el
   problema que acabamos de terminar de arreglar en el CSS: dos copias que
   divergen y nadie se entera hasta que una queda mal.

   El comportamiento NO cambió. La corrección de huso horario sobre todo es
   sutil y está verificada contra el gráfico: se toca sólo si algo se rompe.

   Se expone en `window.VisorGrafico` en vez de usar módulos ES a propósito —
   el visor no tiene build step y los `<script>` clásicos se ejecutan en orden,
   que es todo lo que hace falta acá. */

window.VisorGrafico = (function () {
  const LWC = window.LightweightCharts;
  const n = (v, d = 2) => (v == null ? '—' : Number(v).toFixed(d));

  /* El desfase horario de Nueva York en ese día, para que el eje muestre ET y no
     la hora local del navegador. Se deriva del propio dato: la apertura del RTH
     es siempre 09:30 ET, así que la diferencia contra el timestamp de la primera
     barra de la rueda da el corrimiento exacto, incluido el horario de verano. */
  function desfase(p) {
    const t = p?.sesion?.apertura;
    if (!t) return 0;
    const d = new Date(t * 1000);
    const local = d.getUTCHours() + d.getUTCMinutes() / 60;
    return Math.round((9.5 - local) * 3600);
  }

  /* El armazón: el gráfico vacío con las tres series, exactamente con la config
     que ya estaba afinada. Se separó de `dibujar()` porque la reproducción
     necesita el mismo gráfico pero alimentado vela por vela en vez de de una,
     y tener dos configuraciones distintas era garantía de que se separaran.
     Ninguna opción cambió al extraerlo. */
  function crear(el) {
    const chart = LWC.createChart(el, {
      autoSize: true,
      layout: { background: { color: '#131922' }, textColor: '#7b8598', fontSize: 11 },
      grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
      rightPriceScale: { borderColor: '#222938', scaleMargins: { top: .1, bottom: .28 } },
      timeScale: { borderColor: '#222938', timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
      localization: { locale: 'es-AR' },
    });
    const velas = chart.addCandlestickSeries({
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
      wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    const vol = chart.addHistogramSeries({
      priceScaleId: 'vol', priceLineVisible: false, lastValueVisible: false,
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: .78, bottom: 0 } });
    const vwap = chart.addLineSeries({
      color: '#d4a11e', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
    });
    return { chart, velas, vol, vwap };
  }

  /* Dibuja la jornada entera de una. Devuelve el `chart` para que quien lo creó
     pueda destruirlo con `.remove()` — es lo único que se agregó al mover la
     función acá: /papeles crea el gráfico al desplegar una jornada y lo tiene
     que soltar al plegarla, o con cien abiertas el navegador se queda sin
     memoria. /bitacora ignora el retorno y se comporta igual que antes. */
  function dibujar(id, p) {
    const el = document.getElementById(id);
    if (!el) return null;
    const off = desfase(p);
    const { chart, velas, vol, vwap } = crear(el);
    velas.setData((p.velas || []).map((v) => ({ ...v, time: v.time + off })));
    vol.setData((p.volumen || []).map((v) => ({ ...v, time: v.time + off })));
    vwap.setData((p.vwap || []).map((v) => ({ ...v, time: v.time + off })));

    /* Las ejecuciones. Entrada y salida de cada trade como marcador, más una línea
       horizontal en el stop: sin ver dónde estaba el stop no se puede juzgar si el
       trade fue razonable o si zafó de casualidad. */
    const ts = p.trades_estrategia || [];
    const base = (p.sesion?.apertura || 0) + off;
    const hAts = (h) => base + Math.round((h - 9.5) * 3600);
    const marcas = [];
    /* ENTRADA Y SALIDA DICEN COSAS DISTINTAS Y POR ESO SE VEN DISTINTAS.
       La entrada es un hecho sin resultado todavia: cuantas acciones entraron,
       y nada mas. Llevaba el numero de tramo y el precio, que ya estan en la
       tabla y en el eje — cinco entradas seguidas tapaban las velas justo donde
       hay que mirar. Va en gris: una entrada no es buena ni mala.
       La salida SI tiene resultado, y es lo unico que se pinta verde o rojo. */
    const GRIS = '#8f9bb3', VERDE = '#26a69a', ROJO = '#ef5350';
    const plata = (v) => `${v >= 0 ? '+' : '−'}$${n(Math.abs(v), 2)}`;
    ts.forEach((t) => {
      marcas.push({
        time: hAts(t.hora_entrada), position: 'aboveBar', color: GRIS,
        shape: 'arrowDown', text: `${n(t.acciones, 0)}`,
      });
      /* Las salidas al cierre se apilan todas en el mismo minuto y tapan las
         velas. Se agrupan mas abajo; las individuales viven en la tabla. */
      if (t.hora_salida != null && t.motivo !== 'cierre') {
        marcas.push({
          time: hAts(t.hora_salida), position: 'belowBar',
          color: t.pnl >= 0 ? VERDE : ROJO, shape: 'arrowUp',
          text: `${t.motivo} ${plata(t.pnl)}`,
        });
      }
    });
    const alCierre = ts.filter((t) => t.motivo === 'cierre');
    if (alCierre.length) {
      const suma = alCierre.reduce((a, t) => a + (t.pnl || 0), 0);
      /* Uno solo: se dice su PnL. Varios: no se pueden separar en el mismo
         minuto sin taparse, asi que va el total y cuantos son. */
      marcas.push({
        time: hAts(alCierre[0].hora_salida), position: 'belowBar',
        color: suma >= 0 ? VERDE : ROJO, shape: 'arrowUp',
        text: alCierre.length === 1 ? `cierre ${plata(suma)}`
          : `cierre ×${alCierre.length} ${plata(suma)}`,
      });
    }
    marcas.sort((a, b) => a.time - b.time);
    velas.setMarkers(marcas);

    if (ts.length) {
      const t = ts[0];
      velas.createPriceLine({
        price: t.precio_entrada * (1 + (t.stop_pct || 0) / 100),
        color: '#ef5350', lineWidth: 1, lineStyle: 2,
        axisLabelVisible: true, title: `stop ${n(t.stop_pct, 0)}%`,
      });
    }
    if (p.niveles?.pm_high) {
      velas.createPriceLine({
        price: p.niveles.pm_high, color: '#5b8def', lineWidth: 1, lineStyle: 3,
        axisLabelVisible: true, title: 'máx premarket',
      });
    }

    /* Encuadre: de 09:00 a 16:10 ET. Mirar la rueda entera y no lo que la
       librería decida por su cuenta. */
    const desde = base - 30 * 60, hasta = base + Math.round(6.67 * 3600);
    try { chart.timeScale().setVisibleRange({ from: desde, to: hasta }); }
    catch (e) { chart.timeScale().fitContent(); }
    return chart;
  }

  /* ¿La posición es corta o larga? Se despeja de la propia fila:

         largo:  pnl = (salida − entrada) × acciones
         corto:  pnl = (entrada − salida) × acciones

     así que `sign(pnl) × sign(entrada − salida) > 0` ⟺ corto. No es una
     adivinanza — es álgebra sobre datos que ya están en la fila, y resuelve el
     99,1% de los trades de la base. El resto son los que tienen pnl 0 o precio
     que no se movió, donde el sentido es indistinguible y la marca a mercado
     da ~0 igual, así que no cambia ningún número.

     Si el endpoint informa el `lado` de la estrategia, ESE manda: esto es el
     respaldo. Importa acertarle porque 135 de las 413 estrategias son largas,
     y con el signo al revés el PnL de la reproducción sería espejo del real. */
  function corto(t, lado) {
    if (lado === 'short') return true;
    if (lado === 'long') return false;
    const d = (t.precio_entrada - t.precio_salida) * t.pnl;
    return d === 0 ? true : d > 0;
  }

  /* El barrido de exposición SIMULTÁNEA, por eventos de apertura y cierre.
     Vive acá porque lo usan las dos páginas y porque es el cálculo que este
     proyecto ya tuvo mal una vez: durante un tiempo se tomaba el trade más
     grande en vez de la suma, y con eso el costo de locate salía hasta nueve
     veces más barato de lo real.

     Los dos picos se siguen POR SEPARADO, cada uno con su hora. No son el mismo
     instante: si dos entradas tienen precios distintos, el momento de máximas
     acciones no tiene por qué ser el de máximo nominal. Colapsarlos en uno solo
     daría un número que no corresponde a ningún minuto real de la rueda.

     El de acciones es el que ahora manda —el locate se cobra POR ACCIÓN, así que
     dos papeles con el mismo nominal en dólares pero distinto precio no cuestan
     lo mismo— pero el de dólares se conserva porque es el que narra /bitacora. */
  function pico(ts) {
    const ev = [];
    ts.forEach((t) => {
      const acc = t.acciones || 0;
      const nom = acc * (t.precio_entrada || 0);
      ev.push([t.hora_entrada, +acc, +nom]);
      ev.push([t.hora_salida ?? 24, -acc, -nom]);
    });
    /* A igual hora, las aperturas antes que los cierres: es lo que hay que tener
       localizado en el peor instante del minuto, no el neto al final. */
    ev.sort((a, b) => (a[0] - b[0]) || (b[1] - a[1]));
    let vAcc = 0, vNom = 0, pAcc = 0, pNom = 0, hAcc = null, hNom = null;
    ev.forEach(([h, dAcc, dNom]) => {
      vAcc += dAcc; vNom += dNom;
      if (vAcc > pAcc) { pAcc = vAcc; hAcc = h; }
      if (vNom > pNom) { pNom = vNom; hNom = h; }
    });
    const tramosEn = (h) => ts.filter((t) =>
      t.hora_entrada <= h && (t.hora_salida ?? 24) > h).length;
    return {
      acciones: pAcc, horaAcciones: hAcc, tramosAcciones: tramosEn(hAcc),
      nominal: pNom, hora: hNom, tramos: tramosEn(hNom),
    };
  }

  return { desfase, crear, dibujar, pico, corto };
})();
