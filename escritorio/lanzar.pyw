"""Abre el visor de small caps como una aplicación de escritorio.

QUE ABRE. `smallcaps/visor/server.py` — la app que tiene En vivo, Gráficos,
Historial, Papeles, Reproducción, Cartera y Bitácora. No confundir con
`trades_app.py`, que es una planilla de scoring vieja y aparte.

QUE HACE. Levanta el servidor en segundo plano —sin ventana de consola— y abre
Chrome en modo aplicacion (`--app=`), que da una ventana sin barra de
direcciones ni pestañas y con su propio boton en la barra de tareas.

POR QUE `.pyw` Y NO `.py`. La extension decide el ejecutable: `python.exe` abre
una consola negra detras de la ventana y `pythonw.exe` no. El acceso directo
apunta igual a `pythonw.exe` explicito, para no depender de como esten las
asociaciones de archivos de la maquina.

SI YA ESTA CORRIENDO, NO LEVANTA OTRO. Se chequea el puerto antes de arrancar;
si contesta, se abre la ventana contra el que ya esta.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PUERTO = 8765          # el default de visor/server.py
AQUI = Path(__file__).resolve().parent

# EL VISOR NO SE PUEDE COPIAR A UNA CARPETA SUELTA: es un paquete que importa
# `motor`, `dias`, `chavineta` y la mitad de `smallcaps/`. Asi que el acceso
# directo apunta al repo, y hay que decir cual.
#
# Hoy el worktree es el UNICO lugar donde vive esta app: el checkout principal
# esta cientos de commits atras y no tiene ni el visor ni el puente. Cuando esto
# se mergee a main, la segunda opcion pasa a ser la buena y esto sigue andando
# sin tocar nada.
CANDIDATAS = [
    Path(r"C:\Users\agust\Apps\agendai\algotrade\gracious-wing-b7a8fc\smallcaps\visor\server.py"),
    Path(r"C:\Users\agust\Apps\algotrade\smallcaps\visor\server.py"),
    AQUI.parent / "smallcaps" / "visor" / "server.py",
]

CHROMES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def contesta(puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", puerto)) == 0


def servidor() -> Path | None:
    for p in CANDIDATAS:
        if p.exists():
            return p
    return None


def navegador() -> Path | None:
    for p in CHROMES:
        if p.exists():
            return p
    return None


def arrancar(script: Path) -> None:
    """El visor en segundo plano, sin consola y sin que abra el navegador solo."""
    pyw = Path(sys.executable)
    # `sys.executable` es pythonw.exe cuando esto corre por el acceso directo.
    # El servidor imprime su banner al arrancar y con pythonw no hay stdout, asi
    # que se usa python.exe con la salida al vacio.
    py = pyw.with_name("python.exe")
    if not py.exists():
        py = pyw

    banderas = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        banderas |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        # Que sobreviva a este lanzador: si muriera con el, cerrar la ventana
        # del navegador se llevaria el servidor puesto.
        banderas |= subprocess.DETACHED_PROCESS

    subprocess.Popen(
        [str(py), str(script), "--puerto", str(PUERTO), "--no-abrir"],
        cwd=str(script.parent.parent), creationflags=banderas,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)


def abrir_ventana(url: str) -> None:
    nav = navegador()
    if nav is None:
        import webbrowser
        webbrowser.open(url)
        return
    perfil = Path(os.environ.get("LOCALAPPDATA", str(AQUI))) / "SmallCaps" / "perfil"
    perfil.mkdir(parents=True, exist_ok=True)
    # Perfil propio: sin esto la ventana se abre dentro del Chrome que ya este
    # abierto y hereda su sesion y sus extensiones. Con perfil aparte queda un
    # boton separado en la barra de tareas, que es justo lo que se busca.
    subprocess.Popen([str(nav), f"--app={url}",
                      f"--user-data-dir={perfil}",
                      "--no-first-run", "--no-default-browser-check"])


def main() -> int:
    script = servidor()
    if script is None:
        # Sin consola no se ve un print, asi que el aviso va por ventana.
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "No encontre el visor (visor/server.py).\n\nBuscado en:\n" +
            "\n".join(str(p) for p in CANDIDATAS), "Small Caps", 0x10)
        return 1

    if not contesta(PUERTO):
        arrancar(script)
        # El visor construye su indice al arrancar y puede tardar. Se espera al
        # puerto en vez de dormir un rato fijo: con un sleep corto la ventana se
        # abre contra un servidor que todavia no existe y se ve un error.
        limite = time.monotonic() + 60
        while time.monotonic() < limite and not contesta(PUERTO):
            time.sleep(0.4)

    abrir_ventana(f"http://127.0.0.1:{PUERTO}/vivo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
