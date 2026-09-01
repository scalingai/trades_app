#!/usr/bin/env python3
"""Cuanto de la linea de base sale de saber el futuro.

`clasificar_apertura(hasta=10.0)` mira barras hasta las 10:00 para decidir si el
dia es "fade". Pero `senales_swing(desde=9.75)` entra desde las 09:45. Los trades
entre 09:45 y 10:00 usan una etiqueta que a esa hora todavia NO se conoce.

Tres versiones, para separar cuanto vale el sesgo de cuanto vale el tramo:
  A. como estaba          etiqueta a las 10:00, entradas desde 09:45   (sesgada)
  B. entradas desde 10:00 etiqueta a las 10:00, entradas desde 10:00   (limpia)
  C. etiqueta temprana    etiqueta a las 09:45, entradas desde 09:45   (limpia)

Si A >> B y C, el numero de la linea de base estaba inflado.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import chavineta
from motor import universo, evaluar, linea, encabezado
from sesion import señales_swing

dias = universo()
print(encabezado()); print("  " + "-"*104)

r = evaluar("audit·A·como-estaba", lambda d: señales_swing(d), dias=dias,
            familia="auditoria", stop=45.0, pob={"min_expansion": 150},
            notas="etiqueta 10:00, entradas 09:45 — SESGADA")
print(linea(r)); a = r["ret_nom"]

r = evaluar("audit·B·desde-10", lambda d: señales_swing(d, desde=10.0), dias=dias,
            familia="auditoria", stop=45.0, pob={"min_expansion": 150},
            notas="etiqueta 10:00, entradas 10:00 — limpia")
print(linea(r)); b = r["ret_nom"]

_orig = chavineta.clasificar_apertura
def temprana(dia, **kw):
    kw.setdefault("hasta", 9.75)
    return _orig(dia, **kw)
import motor
motor.clasificar_apertura = temprana
r = evaluar("audit·C·etiqueta-0945", lambda d: señales_swing(d), dias=dias,
            familia="auditoria", stop=45.0, pob={"min_expansion": 150},
            notas="etiqueta 09:45, entradas 09:45 — limpia")
print(linea(r)); c = r["ret_nom"]
motor.clasificar_apertura = _orig

print(f"""
  A (como estaba, sesgada)   {a:.1f}%
  B (entrar desde 10:00)     {b:.1f}%   ->  el sesgo vale {a-b:+.1f} puntos
  C (etiquetar a las 09:45)  {c:.1f}%   ->  el sesgo vale {a-c:+.1f} puntos

  B y C separan dos cosas distintas: B renuncia al tramo 09:45-10:00 entero,
  C lo conserva pero decide con menos informacion. Si C ~ A, el problema era
  solo la etiqueta y se arregla gratis. Si C ~ B, el tramo temprano valia por
  el sesgo y hay que restarlo de todo lo medido hasta hoy.
""")
