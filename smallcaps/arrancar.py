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
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AQUI = Path(__file__).resolve().parent
VISOR = AQUI / "visor" / "server.py"
FEED = AQUI / "puente" / "yahoo_feed.py"
ESCANER = AQUI / "escaner.py"
RECONSTRUIR = AQUI / "reconstruir.py"

NY = ZoneInfo("America/New_York")
APERTURA_H = 9.5
# Hasta esta hora el "cambio de hoy" de Yahoo todavia es el gap de la apertura
# y `escaner.py` acepta escribir. Despues hay que MEDIR el gap sobre las velas,
# que es lo que hace `reconstruir.py`.
LIMITE_ESCANER_H = 10.5
CIERRE_H = 16.0
FIN_FEED_H = 20.0


def ahora_ny() -> datetime:
    return datetime.now(NY)


def h_de(t: datetime) -> float:
    return t.hour + t.minute / 60.0


def hay_rueda(t: datetime) -> tuple[bool, str]:
    """¿Hoy opera el mercado? Se pregunta al mercado, no a una lista.

    Un calendario de feriados hay que mantenerlo, y el año que nadie lo
    actualiza falla en silencio. SPY opera todos los dias habiles desde las
    04:00 en pre-market: si hoy no tiene NI UNA barra, no hay rueda. El dato
    sale de la misma fuente que el feed, asi que si Yahoo esta caido esto
    tambien lo detecta — y quedarse quieto ante Yahoo caido es correcto.
    """
    if t.weekday() >= 5:
        return False, "fin de semana"
    sys.path.insert(0, str(AQUI))
    sys.path.insert(0, str(AQUI / "puente"))
    try:
        import yahoo_feed as yf
        r = yf.pedir("SPY", rango="1d")
        barras, _ = yf.barras_de(r or {}, solo_dia=t.date().isoformat())
        if barras:
            return True, f"rueda normal ({len(barras)} barras de SPY)"
        return False, "SPY no tiene ni una barra hoy — feriado, o Yahoo caido"
    except Exception as e:
        # Ante la duda, SEGUIR. Un falso "no hay rueda" cuesta el dia entero;
        # un falso "si hay" cuesta un feed girando en el vacio.
        return True, f"no se pudo verificar ({type(e).__name__}), sigo igual"


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


def _correr(nombre: str, args: list[str], timeout: float = 600) -> int:
    """Un script de una sola pasada, con su salida prefijada. Devuelve el código."""
    proc, hilo = _lanzar(nombre, args)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"[{nombre}] se colgó, lo corté.")
        return 1
    hilo.join(timeout=5)
    return proc.returncode or 0


def _plan(t: datetime) -> tuple[str, float | None, str]:
    """Qué hacer con la lista, según la hora de Nueva York.

    Devuelve (qué, a qué hora esperar, por qué). Las tres opciones:

      escaner      el campo de gap de Yahoo TODAVIA es el de la apertura
      reconstruir  ya no: hay que medir el gap sobre las velas
      esperar      falta para las 09:31; se espera y después se escanea

    Agus prende la máquina cerca de las 10:00 de Argentina, que son las 09:00
    de Nueva York: el camino normal es esperar media hora con el feed ya
    juntando el pre-market, y escanear apenas abre.
    """
    h = h_de(t)
    if h < APERTURA_H:
        return ("esperar", APERTURA_H + 1 / 60.0,
                f"son las {t:%H:%M} NY: falta para la apertura. El feed ya "
                "junta el pre-market; la lista se arma a las 09:31.")
    if h <= LIMITE_ESCANER_H:
        return ("escaner", None,
                f"son las {t:%H:%M} NY: el cambio de hoy todavía ES el gap de "
                "la apertura, la lista sale del escáner.")
    if h < FIN_FEED_H:
        return ("reconstruir", None,
                f"son las {t:%H:%M} NY y el día ya corrió: el gap se MIDE sobre "
                "las velas, no se lee de Yahoo.")
    return ("reconstruir", None,
            f"son las {t:%H:%M} NY, terminó hasta el post-market: se reconstruye "
            "el día para ver qué habría hecho el sistema.")


def _lista_del_dia(puerto: int) -> None:
    """Deja `watchlist.txt` con la población del censo, sea la hora que sea.

    Corre en su propio hilo para no frenar al visor ni al feed: mientras se
    espera la apertura, la pantalla ya está arriba y el feed ya escribe.
    """
    qué, esperar_h, por_qué = _plan(ahora_ny())
    print(f"[lista] {por_qué}", flush=True)
    if esperar_h is not None:
        while True:
            t = ahora_ny()
            faltan = (esperar_h - h_de(t)) * 3600
            if faltan <= 0:
                break
            # Dormir de a poco para que Ctrl+C no tenga que esperar media hora.
            time.sleep(min(30.0, faltan))
        qué = "escaner"
        print(f"[lista] {ahora_ny():%H:%M} NY: abrió, armo la lista.", flush=True)

    if qué == "escaner":
        rc = _correr("lista", [str(ESCANER), "--escribir"], timeout=300)
        if rc != 0:
            print("[lista] el escáner no quiso escribir; reconstruyo midiendo "
                  "el gap sobre las velas.", flush=True)
            _correr("lista", [str(RECONSTRUIR), "--escribir"], timeout=600)
    else:
        _correr("lista", [str(RECONSTRUIR), "--escribir"], timeout=600)
        # RECONSTRUIR ESCRIBE LA LISTA, NO LAS VELAS. Durante la rueda el feed
        # relee la watchlist en cada ciclo y las trae solo; despues de las 20:00
        # el feed ya salio y la pantalla quedaria con papeles sin barras — la
        # fila ambar de "sin barras del feed", para siempre. El relleno explicito
        # cierra ese hueco y no molesta si el feed ya las trajo: `leer_feed`
        # deduplica por (simbolo, minuto).
        hoy = ahora_ny().date().isoformat()
        print(f"[lista] traigo las velas del {hoy} de esos papeles.", flush=True)
        _correr("velas", [str(FEED), "--dia", hoy], timeout=600)
    print(f"[lista] listo. La pantalla la toma sola: "
          f"http://127.0.0.1:{puerto}/vivo", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Visor + feed de Yahoo, juntos")
    ap.add_argument("--puerto", type=int, default=8765, help="puerto del visor")
    ap.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    ap.add_argument("--auto", action="store_true",
                    help="además arma la watchlist sola, según la hora de NY")
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

    if a.auto:
        t = ahora_ny()
        abierto, por_qué = hay_rueda(t)
        print(f"  {t:%a %d/%m %H:%M} Nueva York · {por_qué}")
        if not abierto:
            print("  Hoy no hay rueda. No levanto nada.")
            return 0

    _job = _atar_a_este_proceso()  # vive hasta que salgamos, a propósito
    visor, _ = _lanzar("visor", visor_args)
    feed, _ = _lanzar("feed", [str(FEED)])
    procs = [visor, feed]
    if a.auto:
        threading.Thread(target=_lista_del_dia, args=(a.puerto,),
                         daemon=True).start()
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
