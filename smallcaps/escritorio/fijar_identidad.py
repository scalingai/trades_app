#!/usr/bin/env python3
"""Le pone al acceso directo la identidad de app (AppUserModelID) y el icono.

    python fijar_identidad.py

POR QUE HACE FALTA. Anclar a la barra de tareas una ventana hecha por Python
ancla *python.exe*: Windows agrupa las ventanas por `AppUserModelID`, y si el
proceso no declara uno propio hereda el del ejecutable. Por eso el ícono que
quedaba fijado no era el de small caps.

Son DOS lados y tienen que coincidir:

  · el PROCESO lo declara al arrancar  -> `lanzar.pyw`, con
    `SetCurrentProcessExplicitAppUserModelID`
  · el ACCESO DIRECTO lo lleva escrito -> este script, con la propiedad
    `System.AppUserModel.ID` del .lnk

Si coinciden, Windows entiende que la ventana ES ese acceso directo: la agrupa
abajo de su ícono y al anclarla ancla la app, no Python.

Esto no lo hace `WScript.Shell`, que es el camino corto para crear .lnk: esa
propiedad se escribe por `IPropertyStore`, o sea COM. De ahí que sea un script
aparte y no dos líneas en PowerShell.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "Agus.SmallCaps.Visor"        # el mismo que declara lanzar.pyw
AQUI = Path(__file__).resolve().parent
ICONO = AQUI / "trades.ico"
LANZADOR = AQUI / "lanzar.pyw"


def escritorio() -> Path:
    return Path(os.environ["USERPROFILE"]) / "Desktop"


def pythonw() -> str:
    p = Path(sys.executable)
    w = p.with_name("pythonw.exe")
    return str(w if w.exists() else p)


def crear_o_actualizar(destino: Path) -> None:
    """El .lnk apuntando al lanzador, con su ícono."""
    import pythoncom
    from win32com.client import Dispatch
    sh = Dispatch("WScript.Shell")
    lnk = sh.CreateShortcut(str(destino))
    lnk.TargetPath = pythonw()
    lnk.Arguments = f'"{LANZADOR}"'
    lnk.WorkingDirectory = str(AQUI)
    lnk.Description = "Small Caps - visor en vivo"
    if ICONO.exists():
        lnk.IconLocation = f"{ICONO},0"
    lnk.Save()
    del pythoncom


def poner_appid(destino: Path) -> None:
    """La propiedad que WScript.Shell no sabe escribir."""
    from win32com.propsys import propsys, pscon
    from win32com.shell import shellcon
    import pythoncom

    store = propsys.SHGetPropertyStoreFromParsingName(
        str(destino), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID,
                   propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()


def leer(destino: Path) -> str | None:
    from win32com.propsys import propsys, pscon
    from win32com.shell import shellcon
    try:
        store = propsys.SHGetPropertyStoreFromParsingName(
            str(destino), None, shellcon.GPS_DEFAULT, propsys.IID_IPropertyStore)
        return store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()
    except Exception:
        return None


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    if sys.platform != "win32":
        print("Esto es sólo para Windows.")
        return 1
    if not LANZADOR.exists():
        print(f"No encuentro el lanzador: {LANZADOR}")
        return 1

    destino = escritorio() / "Small Caps.lnk"
    crear_o_actualizar(destino)
    poner_appid(destino)
    leído = leer(destino)

    print(f"Acceso directo: {destino}")
    print(f"  apunta a : {pythonw()} \"{LANZADOR}\"")
    print(f"  ícono    : {ICONO if ICONO.exists() else '(falta trades.ico)'}")
    print(f"  app id   : {leído or '(no se pudo leer)'}")
    if leído != APP_ID:
        print("\n  ! El AppUserModelID no quedó escrito. La ventana va a abrir "
              "igual,\n    pero al anclarla puede volver a aparecer como Python.")
        return 1
    print("\nListo. Para que Windows tome la identidad nueva:")
    print("  1. Cerrá la ventana de la app si está abierta.")
    print("  2. Si ya tenías algo anclado, desanclalo (botón derecho > Desanclar).")
    print("  3. Abrí el acceso directo del escritorio.")
    print("  4. Botón derecho en su ícono de la barra > Anclar a la barra de tareas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
