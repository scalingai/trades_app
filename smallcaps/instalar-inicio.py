#!/usr/bin/env python3
"""Que la app arranque sola al prender la máquina.

    python smallcaps/instalar-inicio.py           # instala
    python smallcaps/instalar-inicio.py --quitar  # desinstala
    python smallcaps/instalar-inicio.py --ver     # dice si está puesto

QUE HACE. Deja un `.cmd` en la carpeta Inicio de Windows del usuario. Al
iniciar sesión, Windows lo corre y eso levanta `arrancar.py --auto`: visor,
feed, y la watchlist armada sola a la hora que corresponda.

POR QUE LA CARPETA INICIO Y NO UNA TAREA PROGRAMADA. La carpeta es un archivo
en un directorio: se ve, se borra a mano, no pide permisos de administrador y
no queda nada escondido en el registro. Una tarea programada es más potente
—puede correr sin sesión iniciada— y acá eso no sirve para nada: la máquina
está apagada hasta que Agus la prende, y lo que se quiere es exactamente
"cuando la prenda".

A QUE CHECKOUT APUNTA. Por defecto, a aquel desde donde se lo corre. Eso está
bien para el checkout de trabajo y MAL para un worktree de sesión, que es
descartable: el día que se limpia, el arranque queda roto. Por eso existe
`--desde`, para instalarlo apuntando al checkout durable.

QUE NO HACE. No opera. No manda una sola orden. Levanta la pantalla y junta
los datos, que es lo que se venía olvidando.

SI HOY NO HAY RUEDA —fin de semana o feriado— `arrancar.py --auto` se da cuenta
solo (le pregunta a las barras de SPY) y no levanta nada. No hace falta apagar
esto los sábados.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent
NOMBRE = "smallcaps-arrancar.cmd"


def carpeta_inicio() -> Path:
    """La carpeta Inicio de ESTE usuario."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("no encuentro %APPDATA% - esto es solo para Windows")
    return (Path(appdata) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup")


def contenido(raiz: Path) -> str:
    """El .cmd, apuntando a `raiz`.

    TODO EN ASCII, a propósito: cmd.exe lee el archivo con la codepage OEM y no
    con UTF-8, así que un acento se ve como basura justo en el mensaje de error
    que hay que poder leer.

    Y la ruta queda escrita, no se resuelve al arrancar: si mañana ese checkout
    se mueve o se borra, esto tiene que fallar RUIDOSAMENTE, no encontrar otra
    copia del proyecto y levantar una rama vieja sin que nadie se entere.
    """
    arrancar = raiz / "smallcaps" / "arrancar.py"
    py = sys.executable
    return (
        "@echo off\r\n"
        "rem Generado por smallcaps/instalar-inicio.py - borrable a mano.\r\n"
        f'cd /d "{raiz}"\r\n'
        f'if not exist "{arrancar}" (\r\n'
        "  echo No encuentro el proyecto: se movio o se borro el checkout.\r\n"
        f"  echo Esperaba: {arrancar}\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        f'"{py}" "{arrancar}" --auto\r\n'
        "rem Si algo falla, que la ventana no se cierre y se pueda leer.\r\n"
        "if errorlevel 1 pause\r\n"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Arranque automático de la app")
    ap.add_argument("--quitar", action="store_true", help="sacarlo del inicio")
    ap.add_argument("--ver", action="store_true", help="sólo decir cómo está")
    ap.add_argument("--desde", metavar="RUTA",
                    help="instalar apuntando a OTRO checkout (por defecto, este)")
    a = ap.parse_args(argv)

    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    if sys.platform != "win32":
        print("Esto es sólo para Windows.")
        return 1

    destino = carpeta_inicio() / NOMBRE

    if a.ver:
        if destino.exists():
            print(f"PUESTO · {destino}\n")
            print("--- lo que corre al prender la máquina:")
            print(destino.read_text(encoding="ascii", errors="replace"))
        else:
            print(f"NO está puesto (no existe {destino})")
        return 0

    if a.quitar:
        if destino.exists():
            destino.unlink()
            print(f"Sacado: {destino}")
        else:
            print("No estaba puesto, no hice nada.")
        return 0

    raiz = Path(a.desde).resolve() if a.desde else RAIZ
    if not (raiz / "smallcaps" / "arrancar.py").exists():
        print(f"No hay un checkout del proyecto en {raiz}")
        return 1

    destino.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""` para que Python no traduzca los \r\n que ya escribimos y
    # queden \r\r\n.
    destino.write_text(contenido(raiz), encoding="ascii", newline="")
    print(f"Puesto en el inicio de Windows:\n  {destino}")
    print(f"  apunta a: {raiz}\n")
    print("Al prender la máquina va a levantar, en una ventana:")
    print("  · el visor      http://127.0.0.1:8765/vivo")
    print("  · el feed de Yahoo")
    print("  · la watchlist, a la hora que corresponda\n")
    print("Para sacarlo:")
    print("  python smallcaps/instalar-inicio.py --quitar")
    print("o borrar ese archivo a mano, que es lo mismo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
