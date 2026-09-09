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
import os
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
DIARIAS = AQUI / "backfill_daily.py"
EVENTOS = AQUI / "detect_events.py"

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


# QUE ARCHIVOS HACEN QUE LA PANTALLA DIGA OTRA COSA.
#
# El .py del visor y del puente calculan los numeros; el .js y el .html los
# dibujan. Si cambia cualquiera de esos, lo que esta corriendo dejo de ser lo
# que dice el repo. Los datos NO se vigilan: el feed escribe el .jsonl cada
# quince segundos y reiniciar por eso seria un loop infinito.
VIGILADOS = ("*.py", "visor/static/*.js", "visor/static/*.html")
CADA_S = 4.0


def huella() -> dict:
    """Ruta -> fecha de modificacion de todo lo que puede cambiar un numero."""
    out = {}
    for patron in VIGILADOS:
        for f in AQUI.glob(patron):
            try:
                out[str(f)] = f.stat().st_mtime
            except OSError:
                pass
    for sub in ("puente", "visor", "massive", "edgar"):
        for f in (AQUI / sub).rglob("*.py"):
            try:
                out[str(f)] = f.stat().st_mtime
            except OSError:
                pass
    return out


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
        # BREAKAWAY_OK es lo que permite que UN hijo se escape del job, y solo
        # si lo pide explicitamente con CREATE_BREAKAWAY_FROM_JOB. Sin esto el
        # reinicio del propio supervisor se suicida: el proceso nuevo hereda el
        # job, el viejo sale, se cierra el ultimo handle y KILL_ON_JOB_CLOSE
        # mata a los dos. Medido el 2026-09-09 — quedaba todo apagado.
        JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x800
        JobObjectExtendedLimitInformation = 9
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_BREAKAWAY_OK)
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


# CUANTO PARA ATRAS SE MIRA. Yahoo guarda ~7 dias de barras de 1 minuto: mas
# atras que eso no se puede recuperar por este camino y hay que ir a Polygon,
# que ademas espera 10 dias a que los agregados diarios dejen de corregirse.
DIAS_ATRAS = 6


def _navegables(puerto: int, espera_s: float = 180.0) -> set[str] | None:
    """Las fechas que la pantalla OFRECE hoy, preguntandole a ella.

    POR QUE NO SE DEDUCE DE LAS TABLAS. Un dia es navegable por dos caminos
    —el feed en vivo y los minutos del censo— pero ademas el del censo exige
    que el dia este en `poblacion_obs`, que va diez dias atrasado a proposito.
    El 2026-09-01 tiene minutos bajados y NO se navega, justamente por eso.
    Deducirlo de las tablas es reimplementar `fechas_disponibles()` y quedar
    desincronizado el dia que esa funcion cambie; preguntarle al visor no.

    Devuelve None si el visor no contesto: ahi no se sabe, y no saber no es lo
    mismo que "falta todo".
    """
    import json
    import urllib.request
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{puerto}/api/vivo/fechas", timeout=5) as r:
                fechas = json.load(r).get("fechas") or []
            # Vacio = el indice todavia se esta armando. Se espera: decidir con
            # la lista a medio hacer bajaria dias que ya estan.
            if fechas:
                return set(fechas)
        except Exception:
            pass
        time.sleep(3)
    return None


def _dias_sin_barras(puerto: int) -> list[str]:
    """Dias habiles recientes que el censo tiene y la pantalla no puede mostrar.

    NO es "dias sin señales": es "dias sin UN SOLO DATO", que en `/vivo` se ve
    como que la flecha de dia anterior los saltea. El 2026-09-08 quedo asi
    porque el feed no corrio, y desde la pantalla el 9 parecia venir despues
    del 4.
    """
    import datetime
    import sqlite3
    sys.path.insert(0, str(AQUI))
    sys.path.insert(0, str(AQUI / "puente"))
    try:
        import config
        from escaner import GAP_MIN, LIQ_MIN, PRECIO_MAX, PRECIO_MIN
    except Exception:
        return []

    hay = _navegables(puerto)
    if hay is None:
        print("[dias] el visor no contesto que fechas tiene; no toco nada.",
              flush=True)
        return []

    hoy = ahora_ny().date()
    ventana = [(hoy - datetime.timedelta(days=k)).isoformat()
               for k in range(1, DIAS_ATRAS + 1)]

    db = sqlite3.connect(config.bars_db_path())
    try:
        faltan = []
        for d in sorted(ventana):
            if d in hay:
                continue
            n = db.execute(
                """SELECT count(*) FROM events
                   WHERE d = ? AND gap_pct >= ? AND med_dollar_volume >= ?
                     AND prev_close BETWEEN ? AND ?""",
                (d, GAP_MIN, LIQ_MIN, PRECIO_MIN, PRECIO_MAX)).fetchone()[0]
            # n == 0 puede ser "no hubo papeles" (feriado, o ninguno gapeo) o
            # "el censo no llega hasta ahi". Las dos veces no hay nada que
            # bajar, asi que da igual cual sea.
            if n:
                faltan.append(d)
        return faltan
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()


def _censo_al_dia() -> bool:
    """Pone las barras diarias y la tabla de eventos al dia. True si cambio algo.

    Sin esto el censo se queda donde quedo la ultima corrida —el 2026-09-09
    estaba clavado en el 31 de agosto, o sea septiembre entero invisible— y
    entonces `_dias_sin_barras` no ve nada que recuperar porque no sabe que
    hubo papeles.

    Son pocas llamadas: `grouped_daily` trae TODO el mercado en una por dia.
    """
    import sqlite3
    sys.path.insert(0, str(AQUI))
    try:
        import config
    except Exception:
        return False
    db = sqlite3.connect(config.bars_db_path())
    try:
        antes_d = db.execute("SELECT max(d) FROM bars_daily").fetchone()[0]
        antes_e = db.execute("SELECT max(d) FROM events").fetchone()[0]
    except sqlite3.OperationalError:
        return False
    finally:
        db.close()

    ayer = (ahora_ny().date() - __import__("datetime").timedelta(days=1)).isoformat()
    if antes_d and antes_d >= ayer:
        return False       # nada que traer

    print(f"[dias] las barras diarias llegan al {antes_d}: las pongo al dia.",
          flush=True)
    _correr("dias", [str(DIARIAS), "--days", "14"], timeout=900)

    db = sqlite3.connect(config.bars_db_path())
    try:
        despues_d = db.execute("SELECT max(d) FROM bars_daily").fetchone()[0]
    finally:
        db.close()
    if despues_d == antes_d:
        return False

    print(f"[dias] barras diarias hasta {despues_d}; recalculo los eventos.",
          flush=True)
    _correr("dias", [str(EVENTOS)], timeout=900)
    return True


def _ponerse_al_dia(puerto: int) -> None:
    """Recupera los dias recientes que quedaron sin una sola barra."""
    try:
        _censo_al_dia()
        faltan = _dias_sin_barras(puerto)
    except Exception as e:
        print(f"[dias] no pude revisar los dias pendientes ({type(e).__name__}: {e})",
              flush=True)
        return
    if not faltan:
        print("[dias] no hay dias recientes sin barras.", flush=True)
        return
    print(f"[dias] {len(faltan)} dia(s) sin barras: {', '.join(faltan)}. "
          "Los recupero.", flush=True)
    for d in faltan:
        _correr("dias", [str(RECONSTRUIR), "--dia", d, "--velas"], timeout=900)
    print("[dias] listo. Ya se pueden navegar en /vivo.", flush=True)


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

    _job = _atar_a_este_proceso()  # vive hasta que salgamos, a proposito
    visor, _ = _lanzar("visor", visor_args)
    feed, _ = _lanzar("feed", [str(FEED)])
    procs = [visor, feed]
    if a.auto:
        threading.Thread(target=_lista_del_dia, args=(a.puerto,),
                         daemon=True).start()
        # LA PUESTA AL DIA VA EN SU PROPIO HILO Y DESPUES. Puede tardar minutos
        # -baja barras diarias y recalcula eventos- y no tiene por que demorar
        # ni la pantalla ni la watchlist de hoy, que es lo urgente.
        threading.Thread(target=_ponerse_al_dia, args=(a.puerto,),
                         daemon=True).start()

    # EL CODIGO CAMBIA Y LA PANTALLA NO SE ENTERA: paso dos veces el mismo dia.
    #
    # El 2026-09-09 se arreglo el filtro del censo y la pantalla siguio
    # mostrando nueve tramos y una perdida en un papel que ya no se operaba,
    # porque el proceso de Python arrancado tres horas antes seguia vivo.
    # Cerrar la ventana del navegador no lo apaga, y la terminal esta
    # minimizada. El sintoma es el peor de todos: numeros plausibles, viejos, y
    # sin un solo aviso.
    #
    # Se vigila la fecha de los fuentes y se reinicia solo. Reiniciar es barato
    # -visor y feed no guardan estado, todo sale del disco- y el feed deduplica
    # por (simbolo, minuto), asi que no se pierde ni se repite una barra.
    ultimo = huella()
    previo = None
    try:
        while True:
            # El visor es el que manda: si se cae, no hay nada que mirar y se
            # apaga todo. El feed puede terminar solo al cierre del post-market
            # y eso no es un error.
            if visor.poll() is not None:
                print("\n  el visor termino (codigo %s); apago el feed."
                      % visor.returncode)
                break
            if feed is not None and feed.poll() is not None and feed.returncode != 0:
                print("\n  ! el feed termino con codigo %s. El visor sigue, pero "
                      "SIN barras nuevas: relanza "
                      "`python smallcaps/puente/yahoo_feed.py` aparte."
                      % feed.returncode, flush=True)
                feed = None   # no volver a avisar
                procs = [visor]

            actual = huella()
            if actual != ultimo:
                # DOS LECTURAS IGUALES ANTES DE REINICIAR. Un `git merge` o un
                # guardado toca varios archivos en el mismo segundo; reiniciar
                # con el primero deja la mitad del cambio afuera y hay que
                # reiniciar otra vez.
                if actual == previo:
                    cambiados = sorted({Path(k).name for k in actual
                                        if ultimo.get(k) != actual[k]})
                    # SI LO QUE CAMBIO ES ESTE ARCHIVO, no alcanza con reiniciar
                    # a los hijos: el supervisor seguiria corriendo el codigo
                    # viejo, que es exactamente el problema que vino a resolver.
                    # Se apagan los hijos y el proceso se reemplaza por si mismo.
                    if Path(__file__).name in cambiados:
                        print("\n~ cambio el supervisor: me reinicio entero.",
                              flush=True)
                        _apagar([x for x in procs if x is not None])
                        # NO `os.execv`: en Windows no reemplaza el proceso,
                        # crea uno nuevo que hereda el job y muere con este.
                        # Con CREATE_BREAKAWAY_FROM_JOB el nuevo nace afuera y
                        # arma el suyo. Hereda stdout, asi que el log sigue.
                        BREAKAWAY = 0x01000000
                        subprocess.Popen(
                            [sys.executable, "-u", os.path.abspath(__file__)]
                            + sys.argv[1:],
                            creationflags=BREAKAWAY, cwd=str(AQUI.parent))
                        return 0
                    print("\n  ~ cambio el codigo (%s%s): reinicio visor y feed."
                          % (", ".join(cambiados[:4]),
                             " y mas" if len(cambiados) > 4 else ""), flush=True)
                    _apagar([x for x in procs if x is not None])
                    visor, _ = _lanzar("visor", visor_args)
                    feed, _ = _lanzar("feed", [str(FEED)])
                    procs = [visor, feed]
                    ultimo = actual
                    previo = None
                    print("  ~ listo. Recarga la pantalla.\n", flush=True)
                else:
                    previo = actual
            else:
                previo = None
            try:
                visor.wait(timeout=CADA_S)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print("\n  Ctrl+C: apago visor y feed.")
    finally:
        _apagar([x for x in procs if x is not None])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
