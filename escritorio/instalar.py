#!/usr/bin/env python3
"""Deja el visor de small caps como un programa del escritorio.

QUE HACE
  1. Copia el lanzador y el icono a una carpeta ESTABLE, fuera del worktree.
  2. Crea el acceso directo en el Escritorio y en el menu Inicio.

POR QUE NO APUNTA AL WORKTREE. Los worktrees son descartables —se borran y se
llevan todo lo que no este commiteado— asi que un acceso directo que apunte a
uno deja de funcionar el dia que se limpia, y el sintoma es un error de Windows
que no dice nada util. La copia vive junto a la data durable del proyecto.

POR QUE APUNTA A `pythonw.exe` Y NO AL `.pyw`. Que un `.pyw` se abra sin consola
depende de como esten las asociaciones de archivos de la maquina, que es
justamente lo que no conviene asumir. El acceso directo nombra el ejecutable.

    python escritorio/instalar.py
    python escritorio/instalar.py --quitar
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
DESTINO = Path.home() / "Apps" / "algotrade-data" / "escritorio"
NOMBRE = "Small Caps"


def pythonw() -> Path:
    p = Path(sys.executable)
    w = p.with_name("pythonw.exe")
    return w if w.exists() else p


def carpetas_de_windows() -> list[Path]:
    """Escritorio y menu Inicio. El menu Inicio es el que deja anclar."""
    salida = []
    perfil = Path.home()
    for cand in (perfil / "Desktop", perfil / "Escritorio",
                 perfil / "OneDrive" / "Desktop",
                 perfil / "OneDrive" / "Escritorio"):
        if cand.is_dir():
            salida.append(cand)
            break
    inicio = Path(os.environ.get("APPDATA", "")) / \
        "Microsoft" / "Windows" / "Start Menu" / "Programs"
    if inicio.is_dir():
        salida.append(inicio)
    return salida


def crear_acceso(destino_lnk: Path, exe: Path, script: Path, icono: Path) -> None:
    """El .lnk se crea por COM, que es la unica via sin dependencias."""
    ps = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{destino_lnk}')
$s.TargetPath = '{exe}'
$s.Arguments = '"{script}"'
$s.WorkingDirectory = '{script.parent}'
$s.IconLocation = '{icono},0'
$s.Description = 'Visor de small caps — en vivo, bitacora y reproduccion'
$s.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   check=True, capture_output=True)


def instalar() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre in ("lanzar.pyw", "trades.ico"):
        origen = AQUI / nombre
        if not origen.exists():
            print(f"  falta {origen} — corré primero: python escritorio/icono.py")
            return 1
        shutil.copy2(origen, DESTINO / nombre)

    # El visor NO se copia: es un paquete que importa media `smallcaps/`. El
    # lanzador apunta al repo y resuelve el camino solo (ver `CANDIDATAS`).
    print(f"  copiado a {DESTINO}")

    exe, script, icono = pythonw(), DESTINO / "lanzar.pyw", DESTINO / "trades.ico"
    for carpeta in carpetas_de_windows():
        lnk = carpeta / f"{NOMBRE}.lnk"
        crear_acceso(lnk, exe, script, icono)
        print(f"  acceso directo: {lnk}")

    print()
    print("  Para tenerlo en la barra de abajo: boton derecho sobre el acceso")
    print("  del Escritorio -> 'Anclar a la barra de tareas'.")
    return 0


def quitar() -> int:
    for carpeta in carpetas_de_windows():
        lnk = carpeta / f"{NOMBRE}.lnk"
        if lnk.exists():
            lnk.unlink()
            print(f"  borrado {lnk}")
    if DESTINO.exists():
        shutil.rmtree(DESTINO, ignore_errors=True)
        print(f"  borrado {DESTINO}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Instala la app en el escritorio")
    ap.add_argument("--quitar", action="store_true")
    args = ap.parse_args(argv)
    return quitar() if args.quitar else instalar()


if __name__ == "__main__":
    raise SystemExit(main())
