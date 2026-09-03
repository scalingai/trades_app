/* chrome.js — la barra lateral, montada desde un solo lugar.

   Antes la navegacion estaba escrita cuatro veces a mano, y ya habia divergido:
   /cartera listaba tres destinos, /bitacora cuatro, / tenia un link suelto
   adentro del subtitulo y /historial no tenia navegacion en absoluto — desde el
   historial no habia forma de llegar a /cartera sin escribir la URL.

   No hace falta un sistema de plantillas para esto: una funcion que escupe el
   markup y marca el activo alcanza, y se puede leer entera de una sentada.

   POR QUE COLAPSA. La barra es chrome, no contenido. En /vivo el cuerpo es una
   grilla de graficos a dos columnas, y cada pixel que se lleva la barra es
   ancho de vela que se pierde. Colapsada quedan 56px: los iconos siguen
   leyendose y el grafico gana 100px de aire.

   COMO COLAPSA. El ancho vive en `--nav`, y el `body` lo descuenta con
   `padding-left`. Redefinir la variable en `<html>` mueve las dos cosas a la
   vez, asi que la barra y el contenido se corren juntos sin JavaScript de
   layout. La preferencia se recuerda: si trabajas colapsado, no hay que
   volver a decirlo cada vez que se abre una pagina. */

(function () {
  /* Los iconos van inline y no como fuente ni emoji: colapsada, el icono ES el
     destino, asi que tiene que verse nitido a 18px y tomar el color del estado
     (apagado, hover, activo) sin trucos. */
  const ICONO = {
    vivo: '<path d="M3 12h4l2.5-7 4 14 2.5-7h5"/>',
    graficos: '<rect x="4.5" y="8" width="5" height="9" rx="1.2"/>'
      + '<path d="M7 4.5v3.5M7 17v2.5"/>'
      + '<rect x="14.5" y="6" width="5" height="7" rx="1.2"/>'
      + '<path d="M17 3v3M17 13v5"/>',
    historial: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3.2 2"/>',
    papeles: '<path d="M12 3.2l8.6 4.6L12 12.4 3.4 7.8z"/>'
      + '<path d="M3.4 12.6 12 17.2l8.6-4.6"/>',
    replay: '<path d="M8.2 5.4 18.4 12 8.2 18.6z"/>',
    cartera: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5v8.5h8.5"/>',
    bitacora: '<rect x="5" y="3.5" width="14" height="17" rx="2"/>'
      + '<path d="M9.2 3.5v17M12.4 9h4M12.4 13h4"/>',
  };

  const PAGINAS = [
    { href: '/vivo', label: 'En vivo', icono: 'vivo', alias: ['/vivo.html'] },
    { href: '/', label: 'Gráficos', icono: 'graficos', alias: ['/index.html'] },
    { href: '/historial', label: 'Historial', icono: 'historial', alias: ['/historial.html'] },
    { href: '/papeles', label: 'Papeles', icono: 'papeles', alias: ['/papeles.html'] },
    { href: '/replay', label: 'Reproducción', icono: 'replay', alias: ['/replay.html'] },
    { href: '/cartera', label: 'Cartera', icono: 'cartera', alias: ['/cartera.html'] },
    { href: '/bitacora', label: 'Bitácora', icono: 'bitacora', alias: ['/bitacora.html'] },
  ];

  const CLAVE = 'visor.nav.corta';
  const aqui = location.pathname;
  const activa = (p) => p.href === aqui || p.alias.includes(aqui);

  const svg = (d) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    + ' stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"'
    + ' aria-hidden="true">' + d + '</svg>';

  const html = `
    <nav class="nav" aria-label="Secciones">
      <div class="nav-marca">
        <span class="nav-punto" aria-hidden="true"></span>
        <span class="nav-nombre">small caps</span>
      </div>
      <div class="nav-lista">
        ${PAGINAS.map((p) => `
          <a href="${p.href}"${activa(p) ? ' class="sel" aria-current="page"' : ''}>
            ${svg(ICONO[p.icono])}<span>${p.label}</span>
          </a>`).join('')}
      </div>
      <button class="nav-toggle" type="button" aria-expanded="true"
              aria-label="Contraer la barra lateral">
        ${svg('<path d="M14.5 7 9.5 12l5 5"/>')}<span>Contraer</span>
      </button>
    </nav>`;

  function montar() {
    document.body.insertAdjacentHTML('afterbegin', html);
    const raiz = document.documentElement;
    const boton = document.querySelector('.nav-toggle');

    /* La preferencia se lee ANTES de la primera pintura, mas abajo. Aca solo se
       refleja en el boton, que todavia no existia en ese momento. */
    const pintar = () => {
      const corta = raiz.classList.contains('nav-corta');
      boton.setAttribute('aria-expanded', String(!corta));
      boton.setAttribute('aria-label',
        corta ? 'Expandir la barra lateral' : 'Contraer la barra lateral');
    };
    pintar();

    boton.addEventListener('click', () => {
      raiz.classList.toggle('nav-corta');
      try { localStorage.setItem(CLAVE, raiz.classList.contains('nav-corta') ? '1' : ''); }
      catch (e) { /* modo privado: se pierde la preferencia, no la funcion */ }
      pintar();
      /* Los graficos miden su contenedor al crearse y no se enteran solos de
         que la ventana cambio de ancho. Sin esto, colapsar deja las velas
         cortadas hasta el proximo refresco. */
      window.dispatchEvent(new Event('resize'));
    });
  }

  /* Se aplica la clase apenas se puede, para que la barra no aparezca ancha y
     salte a angosta en el primer cuadro. */
  try {
    if (localStorage.getItem(CLAVE)) {
      document.documentElement.classList.add('nav-corta');
    }
  } catch (e) { /* sin localStorage arranca expandida, que es el default */ }

  if (document.body) montar();
  else document.addEventListener('DOMContentLoaded', montar);
})();
