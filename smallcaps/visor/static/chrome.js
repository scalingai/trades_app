/* chrome.js — la barra lateral, montada desde un solo lugar.

   Antes la navegacion estaba escrita cuatro veces a mano, y ya habia divergido:
   /cartera listaba tres destinos, /bitacora cuatro, / tenia un link suelto
   adentro del subtitulo y /historial no tenia navegacion en absoluto — desde el
   historial no habia forma de llegar a /cartera sin escribir la URL.

   No hace falta un sistema de plantillas para esto: una funcion que escupe el
   markup y marca el activo alcanza, y se puede leer entera de una sentada.
   Se inserta con `afterbegin` y la barra es `position:fixed`, asi que sale del
   flujo y no se convierte en una columna de la grilla de las paginas que usan
   grilla (/ y /bitacora). */

(function () {
  const PAGINAS = [
    { href: '/vivo', label: 'En vivo', alias: ['/vivo.html'] },
    { href: '/', label: 'Gráficos', alias: ['/index.html'] },
    { href: '/historial', label: 'Historial', alias: ['/historial.html'] },
    { href: '/papeles', label: 'Papeles', alias: ['/papeles.html'] },
    { href: '/replay', label: 'Reproducción', alias: ['/replay.html'] },
    { href: '/cartera', label: 'Cartera', alias: ['/cartera.html'] },
    { href: '/bitacora', label: 'Bitácora', alias: ['/bitacora.html'] },
  ];

  const aqui = location.pathname;
  const activa = (p) => p.href === aqui || p.alias.includes(aqui);

  const html = `
    <nav class="nav">
      <div class="nav-marca">small caps<span>visor</span></div>
      ${PAGINAS.map((p) =>
        `<a href="${p.href}"${activa(p) ? ' class="sel"' : ''}>${p.label}</a>`
      ).join('')}
      <div class="nav-pie">local · sin internet</div>
    </nav>`;

  const montar = () => document.body.insertAdjacentHTML('afterbegin', html);
  if (document.body) montar();
  else document.addEventListener('DOMContentLoaded', montar);
})();
