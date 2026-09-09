"""Small caps como aplicación de escritorio de verdad: ventana propia, sin Chrome.

QUE ABRE. `smallcaps/arrancar.py --auto`, el supervisor: levanta el visor (En
vivo, Gráficos, Historial, Papeles, Reproducción, Cartera, Bitácora), el feed de
Yahoo que escribe las barras, y arma la watchlist según la hora de Nueva York.
No confundir con `trades_app.py`, que es una planilla de scoring vieja y aparte.

POR QUE YA NO ES CHROME (2026-09-09). Antes esto abría Chrome con `--app=`, que
da una ventana sin barra de direcciones pero SIGUE SIENDO CHROME: en la barra de
tareas aparece con el logo de Chrome y anclarla ancla a Chrome. Ahora la ventana
la hace **WebView2**, el motor que ya viene con Windows 11, a través de
`pywebview`. Es una ventana nativa, con su propio ícono y su propia identidad en
la barra de tareas.

EL ICONO EN LA BARRA DE TAREAS son dos cosas distintas y hacen falta las dos:

  1. El ícono de la VENTANA — lo pone `webview.start(icon=...)`.
  2. La IDENTIDAD de la app — el `AppUserModelID`. Sin eso Windows agrupa la
     ventana con "Python" y al anclarla ancla python.exe. Se fija acá con
     `SetCurrentProcessExplicitAppUserModelID` y tiene que coincidir con el que
     lleva el acceso directo (lo pone `fijar_identidad.py`).

QUE HACE SI YA ESTA CORRIENDO. Se chequea el puerto antes de arrancar; si
contesta, la ventana se abre contra el servidor que ya está. Cerrar la ventana
NO apaga el servidor: sigue juntando barras, que es lo que uno quiere.

POR QUE `.pyw` Y NO `.py`. La extensión decide el ejecutable: `python.exe` abre
una consola negra detrás de la ventana y `pythonw.exe` no.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

PUERTO = 8765          # el default de visor/server.py
AQUI = Path(__file__).resolve().parent
LOG = AQUI / "app.log"
ICONO = AQUI / "trades.ico"
APP_ID = "Agus.SmallCaps.Visor"     # el mismo que fija el acceso directo

# EL SUPERVISOR NO SE PUEDE COPIAR A UNA CARPETA SUELTA: importa `motor`,
# `dias`, `chavineta` y la mitad de `smallcaps/`. Así que esto apunta al repo,
# y hay que decir cuál. Cuando se mergee a main, la segunda pasa a ser la buena
# y esto sigue andando sin tocar nada.
CANDIDATAS = [
    Path(r"C:\Users\agust\Apps\agendai\algotrade\gracious-wing-b7a8fc\smallcaps\arrancar.py"),
    Path(r"C:\Users\agust\Apps\algotrade\smallcaps\arrancar.py"),
    AQUI.parent / "smallcaps" / "arrancar.py",
]


def aviso(texto: str) -> None:
    """Sin consola no se ve un print: el error va por ventana o no existe."""
    import ctypes
    ctypes.windll.user32.MessageBoxW(0, texto, "Small Caps", 0x10)


def identidad() -> None:
    """Que Windows trate esto como una app y no como 'Python'."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass    # sin esto la ventana igual abre; solo se agrupa peor


def contesta(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def supervisor() -> Path | None:
    for p in CANDIDATAS:
        if p.exists():
            return p
    return None


def arrancar(script: Path) -> None:
    """Visor + feed en segundo plano, sin consola, con la salida a un archivo."""
    pyw = Path(sys.executable)
    # `sys.executable` es pythonw.exe cuando esto corre por el acceso directo.
    # El supervisor imprime lo que hacen sus hijos y con pythonw no hay stdout,
    # así que se usa python.exe y la salida va al log.
    py = pyw.with_name("python.exe")
    if not py.exists():
        py = pyw

    banderas = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        banderas |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        # Que sobreviva a esta ventana: cerrar la app no tiene por qué apagar el
        # feed, que es justamente lo que uno quiere que siga juntando barras.
        banderas |= subprocess.DETACHED_PROCESS

    # LA SALIDA VA A UN ARCHIVO, NO AL VACIO. Sin consola, un error de arranque
    # —Yahoo caído, el puerto ocupado, un import roto— desaparecía sin rastro y
    # el síntoma era una ventana en blanco. Se pisa en cada arranque a
    # propósito: interesa el de ahora, no el historial.
    fh = open(LOG, "w", encoding="utf-8", errors="replace")
    subprocess.Popen(
        [str(py), "-u", str(script), "--auto",
         "--puerto", str(PUERTO), "--no-abrir"],
        cwd=str(script.parent.parent), creationflags=banderas,
        stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT)


def ventana(url: str) -> bool:
    """La ventana nativa. Devuelve False si no se pudo (falta pywebview)."""
    try:
        import webview
    except ImportError:
        return False
    webview.create_window("Small Caps", url, width=1500, height=950,
                          min_size=(900, 600), confirm_close=False)
    # `gui="edgechromium"` explícito: es el motor que ya viene con Windows 11 y
    # el que da una ventana sin nada de Chrome. Dejarlo en automático puede
    # caer a otro backend según lo que haya instalado.
    webview.start(gui="edgechromium", icon=str(ICONO) if ICONO.exists() else None)
    return True


def chrome(url: str) -> None:
    """Plan B, si no hay pywebview: Chrome en modo app. Se ve con su logo."""
    import os
    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if Path(c).exists():
            perfil = Path(os.environ.get("LOCALAPPDATA", str(AQUI))) / "SmallCaps" / "perfil"
            perfil.mkdir(parents=True, exist_ok=True)
            subprocess.Popen([c, f"--app={url}", f"--user-data-dir={perfil}",
                              "--no-first-run", "--no-default-browser-check"])
            return
    import webbrowser
    webbrowser.open(url)


def main() -> int:
    identidad()
    script = supervisor()
    if script is None:
        aviso("No encontré la app (smallcaps/arrancar.py).\n\nBuscado en:\n"
              + "\n".join(str(p) for p in CANDIDATAS))
        return 1

    if not contesta(PUERTO):
        arrancar(script)
        # El visor construye su índice al arrancar y puede tardar. Se espera al
        # puerto en vez de dormir un rato fijo: con un sleep corto la ventana se
        # abre contra un servidor que todavía no existe y se ve un error.
        limite = time.monotonic() + 90
        while time.monotonic() < limite and not contesta(PUERTO):
            time.sleep(0.4)
        if not contesta(PUERTO):
            aviso(f"La app no levantó en 90 segundos.\n\nEl detalle está en:\n{LOG}")
            return 1

    url = f"http://127.0.0.1:{PUERTO}/vivo"
    if not ventana(url):
        chrome(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
