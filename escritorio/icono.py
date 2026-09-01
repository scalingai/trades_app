#!/usr/bin/env python3
"""Dibuja el icono de la app. Se corre una vez y queda `trades.ico`.

Se genera por codigo y no se guarda un binario en git a proposito: un `.ico` es
opaco —no se puede revisar en un diff ni saber que cambio— y este son treinta
lineas que cualquiera puede leer y ajustar.

Windows elige el tamaño segun donde lo dibuje: 16 px en la barra de tareas, 256
en el explorador. Un solo tamaño escalado se ve borroso, asi que se dibuja
grande y se guardan todas las medidas en el mismo archivo.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "trades.ico"

FONDO = (19, 25, 34)        # el mismo del visor
VERDE = (38, 166, 154)
ROJO = (239, 83, 80)
TAMANOS = [256, 128, 64, 48, 32, 16]


def vela(d, x, ancho, cuerpo_y0, cuerpo_y1, mecha_y0, mecha_y1, color):
    """Una vela: mecha fina y cuerpo grueso, como en el grafico."""
    cx = x + ancho // 2
    grosor = max(2, ancho // 6)
    d.rectangle([cx - grosor // 2, mecha_y0, cx + grosor // 2, mecha_y1],
                fill=color)
    d.rectangle([x, cuerpo_y0, x + ancho, cuerpo_y1], fill=color)


def dibujar(n: int = 256) -> Image.Image:
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(n * 0.22)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=r, fill=FONDO + (255,))

    # Tres velas: sube, sube, y la roja grande que es lo que operamos.
    ancho = int(n * 0.16)
    hueco = int(n * 0.07)
    x0 = int(n * 0.16)
    vela(d, x0, ancho, int(n * .52), int(n * .70), int(n * .46), int(n * .76), VERDE)
    vela(d, x0 + ancho + hueco, ancho,
         int(n * .34), int(n * .56), int(n * .26), int(n * .62), VERDE)
    vela(d, x0 + 2 * (ancho + hueco), ancho,
         int(n * .30), int(n * .74), int(n * .22), int(n * .82), ROJO)
    return img


def main() -> int:
    base = dibujar(256)
    base.save(SALIDA, format="ICO",
              sizes=[(t, t) for t in TAMANOS])
    print(f"  icono escrito: {SALIDA}  ({SALIDA.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
