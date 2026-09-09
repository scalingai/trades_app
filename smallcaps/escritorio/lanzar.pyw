"""Abre small caps como una aplicación de escritorio, con todo lo que hace falta.

QUE ABRE. `smallcaps/arrancar.py --auto`, que es el supervisor: levanta el
visor (En vivo, Gráficos, Historial, Papeles, Reproducción, Cartera, Bitácora),
el feed de Yahoo que escribe las barras, y arma la watchlist según la hora de
Nueva York. No confundir con `trades_app.py`, que es una planilla de scoring
vieja y aparte.

QUE CAMBIO EL 2026-09-09. Antes esto levantaba SOLO `visor/server.py`. El visor
dibuja pero no baja datos, así que la pantalla se veía exactamente igual que un
día sin señales: vacía. Tres ruedas seguidas se leyeron como "no hubo trades"
cuando lo que no hubo fue feed. Ahora arranca el supervisor, que además se
reinicia solo cuando cambia el código — sin eso hay que matar el proceso a mano
y la terminal está minimizada.

QUE HACE. Levanta todo en segundo plano —sin ventana de consola— y abre Chrome
en modo aplicación (`--app=`), que da una ventana sin barra de direcciones ni
pestañas y con su propio botón en la barra de tareas, anclable como cualquier
app.

POR QUE `.pyw` Y NO `.py`. La extensión decide el ejecutable: `python.exe` abre
una consola negra detrás de la ventana y `pythonw.exe` no. El acceso directo
apunta igual a `pythonw.exe` explícito, para no depender de cómo estén las
asociaciones de archivos de la máquina.

SI YA ESTA CORRIENDO, NO LEVANTA OTRO. Se chequea el puerto antes de arrancar;
si contesta, se abre la ventana contra el que ya está.
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
LOG = AQUI / "app.log"

# EL SUPERVISOR NO SE PUEDE COPIAR A UNA CARPETA SUELTA: importa `motor`,
# `dias`, `chavineta` y la mitad de `smallcaps/`. Así que el acceso directo
# apunta al repo, y hay que decir cuál.
#
# Hoy el worktree es el UNICO lugar donde vive esta app: el checkout principal
# está cientos de commits atrás y no tiene ni el visor ni el puente. Cuando esto
# se mergee a main, la segunda opción pasa a ser la buena y esto sigue andando
# sin tocar nada.
CANDIDATAS = [
    Path(r"C:\Users\agust\Apps\agendai\algotrade\gracious-wing-b7a8fc\smallcaps\arrancar.py"),
    Path(r"C:\Users\agust\Apps\algotrade\smallcaps\arrancar.py"),
    AQUI.parent / "smallcaps" / "arrancar.py",
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


def supervisor() -> Path | None:
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
        # Que sobreviva a este lanzador: si muriera con él, cerrar la ventana
        # del navegador se llevaría el servidor puesto.
        banderas |= subprocess.DETACHED_PROCESS

    # LA SALIDA VA A UN ARCHIVO, NO AL VACIO. Sin consola, un error de arranque
    # —Yahoo caído, el puerto ocupado, un import roto— desaparecía sin dejar
    # rastro y el síntoma era una ventana en blanco. El log se pisa en cada
    # arranque a propósito: interesa el de ahora, no el historial.
    fh = open(LOG, "w", encoding="utf-8", errors="replace")
    subprocess.Popen(
        [str(py), "-u", str(script), "--auto",
         "--puerto", str(PUERTO), "--no-abrir"],
        cwd=str(script.parent.parent), creationflags=banderas,
        stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT)


def abrir_ventana(url: str) -> None:
    nav = navegador()
    if nav is None:
        import webbrowser
        webbrowser.open(url)
        return
    perfil = Path(os.environ.get("LOCALAPPDATA", str(AQUI))) / "SmallCaps" / "perfil"
    perfil.mkdir(parents=True, exist_ok=True)
    # Perfil propio: sin esto la ventana se abre dentro del Chrome que ya esté
    # abierto y hereda su sesión y sus extensiones. Con perfil aparte queda un
    # botón separado en la barra de tareas, que es justo lo que se busca.
    subprocess.Popen([str(nav), f"--app={url}",
                      f"--user-data-dir={perfil}",
                      "--no-first-run", "--no-default-browser-check"])


def main() -> int:
    script = supervisor()
    if script is None:
        # Sin consola no se ve un print, así que el aviso va por ventana.
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "No encontré la app (smallcaps/arrancar.py).\n\nBuscado en:\n" +
            "\n".join(str(p) for p in CANDIDATAS), "Small Caps", 0x10)
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
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "La app no levantó en 90 segundos.\n\nEl detalle está en:\n"
                   f"{LOG}", "Small Caps", 0x10)
            return 1

    abrir_ventana(f"http://127.0.0.1:{PUERTO}/vivo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
