#!/usr/bin/env python3
"""Re-corre todo el análisis sobre el CENSO observable y guarda la salida.

Se corre una vez que `poblacion_observable.py` terminó. Prende
`SMALLCAPS_CENSO=1`, que hace que `dias.cargar()` restrinja la población en
todos los scripts a la vez — la alternativa era pasar un flag en cada uno y
alcanzaba con olvidarse en uno solo para contaminar la corrida entera.

**Qué es lo que se está contestando.** Todos los resultados del proyecto llevan
el mismo caveat: la muestra de minutos se sorteó de días con rango DIARIO > 40%,
que a las 09:30 no se conoce. Esta corrida usa una población seleccionada solo
con lo observable antes de la apertura. Si los gradientes sobreviven, el edge
existe. Si no sobreviven, no existe.

**No hay que ajustar nada antes de mirar.** Los umbrales quedaron fijados en
las rondas anteriores; el trabajo de hoy es leer, no recalibrar. Cambiar un
parámetro después de ver este resultado convierte la validación en búsqueda.

    python recorrer.py                 # corre todo, guarda en el dir de datos
    python recorrer.py --solo ventana  # uno solo
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

AQUI = Path(__file__).resolve().parent

# El orden importa: `momentos` reconstruye la tabla que consume `test_ratios`.
PASOS = [
    ("momentos", ["momentos.py"],
     "reconstruye el dataset por minuto sobre el censo"),
    ("ventana", ["test_ventana.py", "--min-expansion", "100"],
     "el perfil horario — dónde está la plata en el día"),
    ("lados", ["test_lados.py"],
     "front side vs back side, con MAE"),
    ("frontlong", ["test_frontlong.py"],
     "el gradiente de expansión, que es la hipótesis central"),
    ("ratios", ["test_ratios.py"],
     "ratios fijos vs target en un nivel"),
    ("salidas", ["test_salidas.py"],
     "salida por anomalía de volumen durante el trade"),
    ("chavineta", ["chavineta.py", "--pasivo"],
     "la técnica con niveles, agotamiento y reclaim"),
    ("reciclaje", ["test_reciclaje.py"],
     "escalonado mecánico, para contrastar con el anterior"),
    ("signals", ["test_signals.py"],
     "las 8 señales de cero parámetros de la primera ronda"),
    ("ict", ["test_ict.py"],
     "las 3 señales ICT de la segunda ronda"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Re-corrido completo sobre el censo")
    ap.add_argument("--solo", default="", help="correr un solo paso por nombre")
    ap.add_argument("--sin-censo", action="store_true",
                    help="correr sobre la muestra vieja, para comparar")
    args = ap.parse_args(argv)

    entorno = dict(os.environ)
    if not args.sin_censo:
        entorno["SMALLCAPS_CENSO"] = "1"
    entorno["PYTHONIOENCODING"] = "utf-8"

    sello = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires"))
    etiqueta = "censo" if not args.sin_censo else "muestra-vieja"
    destino = config.data_dir() / f"recorrido-{etiqueta}-{sello:%Y%m%d-%H%M}.txt"

    pasos = [p for p in PASOS if not args.solo or p[0] == args.solo]
    if not pasos:
        print(f"no existe el paso '{args.solo}'. Hay: "
              + ", ".join(p[0] for p in PASOS))
        return 1

    print("=" * 76)
    print(f"  RE-CORRIDO SOBRE {'EL CENSO OBSERVABLE' if not args.sin_censo else 'LA MUESTRA VIEJA'}")
    print(f"  {len(pasos)} pasos  ·  salida en {destino}")
    print("=" * 76, flush=True)

    t0 = time.time()
    with destino.open("w", encoding="utf-8") as fh:
        fh.write(f"# Re-corrido {etiqueta} · {sello:%Y-%m-%d %H:%M} ART\n")
        for nombre, cmd, desc in pasos:
            print(f"\n  ▸ {nombre}: {desc}", flush=True)
            fh.write("\n" + "=" * 78 + f"\n### {nombre} — {desc}\n"
                     + f"### $ python {' '.join(cmd)}\n" + "=" * 78 + "\n")
            r = subprocess.run([sys.executable, *cmd], cwd=AQUI, env=entorno,
                               capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            fh.write(r.stdout or "")
            if r.returncode != 0:
                fh.write(f"\n[FALLÓ con código {r.returncode}]\n{r.stderr}\n")
                print(f"    falló ({r.returncode}) — queda anotado y sigue")
            else:
                print(f"    ok ({len(r.stdout.splitlines())} líneas)")
            fh.flush()

    print(f"\n  listo en {(time.time()-t0)/60:.1f} min → {destino}")
    print("  Leer, NO recalibrar. Cambiar un umbral después de ver esto")
    print("  convierte la validación en búsqueda.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
