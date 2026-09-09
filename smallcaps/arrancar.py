#!/usr/bin/env python3
"""La rutina de la mañana en un solo comando: el feed y el visor, juntos.

    python smallcaps/arrancar.py                # visor en :8765 + feed de Yahoo
    python smallcaps/arrancar.py --puerto 9000  # otro puerto para el visor
    python smallcaps/arrancar.py --no-abrir     # sin abrir el navegador

POR QUE EXISTE. La pantalla en vivo son DOS procesos: `visor/server.py`
dibuja y `puente/yahoo_feed.py` escribe las barras. El visor solo abre
igual, y con el feed apagado se ve exactamente como un día en el que ningún
papel califica: vacío. La semana del 2026-09-07 se levantó el visor solo tres
ruedas seguidas y se leyó como "no hubo trades". Los hubo —IRD calificó el 9
con tres tramos— pero nadie los vio.

Dos procesos que siempre van juntos tienen que arrancar juntos. Esto los
lanza, mezcla sus salidas con un prefijo para saber quién habla, y con Ctrl+C
mata a los dos. Si el feed termina solo —a las 20:00 NY cierra el post-market
y sale— el visor sigue, porque mirar el día ya cerrado es parte del trabajo.

NO reemplaza a los scripts: cada uno sigue corriendo suelto para rellenar un
día (`yahoo_feed.py --dia`) o reindexar el visor (`server.py --reindexar`).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VISOR = AQUI / "visor" / "server.py"
FEED = AQUI / "puente" / "yahoo_feed.py"


def _atar_a_este_proceso() -> object | None:
    """En Windows, un Job Object que mata a los hijos cuando muere el padre.

    Con Ctrl+C el `finally` de abajo los apaga. Pero si a este proceso lo
    matan de prepo —cerrar la ventana desde el administrador de tareas, un
    `Stop-Process`—, el `finally` no corre y quedan un visor y un feed
    huérfanos, escribiendo. Probado el 2026-09-09: los dos siguieron vivos.
    Un feed huérfano es peor que ninguno: mañana alguien levanta otro, los
    dos escriben el mismo archivo, y el visor lee líneas de dos procesos que
    no se conocen.

    KILL_ON_JOB_CLOSE: cuando se cierra el último handle del job —o sea, cuando
    este proceso muere por lo que sea— el sistema mata a todo lo que esté
    adentro. Devuelve el handle para que viva hasta el final.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32

        class _Limits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in
                        ("ReadOperationCount", "WriteOperationCount",
                         "OtherOperationCount", "ReadTransferCount",
                         "WriteTransferCount", "OtherTransferCount")]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Limits),
                        ("IoInfo", _IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        # Sin esto ctypes devuelve el HANDLE como int de 32 bits y en 64 bits
        # llega truncado: todo lo que sigue falla con ERROR_INVALID_HANDLE (6)
        # y el job no se arma. Medido: los hijos sobrevivían al kill.
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                wintypes.LPVOID, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation,
                                           ctypes.byref(info), ctypes.sizeof(info)):
            return None
        if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
            return None
        return job
    except Exception:
        # Sin job se sigue igual: Ctrl+C sigue apagando a los dos. Solo se
        # pierde la red para el kill de prepo.
        return None


def _volcar(nombre: str, proc: subprocess.Popen) -> None:
    """Copia la salida de un hijo a la nuestra, línea por línea, con prefijo."""
    assert proc.stdout is not None
    for linea in proc.stdout:
        sys.stdout.write(f"[{nombre}] {linea}")
        sys.stdout.flush()


def _lanzar(nombre: str, args: list[str]) -> tuple[subprocess.Popen, threading.Thread]:
    # `-u`: sin buffer, para que lo que imprime el hijo se vea al momento y no
    # cuando se le llena el buffer. Con el feed eso serían minutos de silencio.
    proc = subprocess.Popen(
        [sys.executable, "-u", *args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", cwd=str(AQUI.parent),
    )
    hilo = threading.Thread(target=_volcar, args=(nombre, proc), daemon=True)
    hilo.start()
    return proc, hilo


def _apagar(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Visor + feed de Yahoo, juntos")
    ap.add_argument("--puerto", type=int, default=8765, help="puerto del visor")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    a = ap.parse_args(argv)

    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    visor_args = [str(VISOR), "--puerto", str(a.puerto)]
    if a.no_abrir:
        visor_args.append("--no-abrir")

    print(f"  visor  -> http://127.0.0.1:{a.puerto}/vivo")
    print(f"  feed   -> {FEED.name}  (Yahoo, hasta las 20:00 NY)")
    print("  Ctrl+C apaga los dos.\n", flush=True)

    _job = _atar_a_este_proceso()  # vive hasta que salgamos, a propósito
    visor, _ = _lanzar("visor", visor_args)
    feed, _ = _lanzar("feed", [str(FEED)])
    procs = [visor, feed]
    try:
        while True:
            # El visor es el que manda: si se cae, no hay nada que mirar y se
            # apaga todo. El feed puede terminar solo al cierre del post-market
            # y eso no es un error.
            if visor.poll() is not None:
                print(f"\n  el visor terminó (código {visor.returncode}); apago el feed.")
                break
            if feed is not None and feed.poll() is not None and feed.returncode != 0:
                print(f"\n  ! el feed terminó con código {feed.returncode}. "
                      "El visor sigue, pero SIN barras nuevas: relanzá "
                      "`python smallcaps/puente/yahoo_feed.py` aparte.", flush=True)
                feed = None  # no volver a avisar
                procs = [visor]
            try:
                visor.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print("\n  Ctrl+C: apago visor y feed.")
    finally:
        _apagar([p for p in procs if p is not None])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
