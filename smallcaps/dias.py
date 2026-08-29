"""Carga de un día de evento con todo lo derivado. Lo comparten los tests y la app.

Se separa en un módulo porque hasta ahora cada script recalculaba VWAP, máximo
pre-market y expansión por su cuenta, con diferencias chicas entre sí. Una sola
definición evita que dos scripts contesten distinto la misma pregunta.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta

import config
from massive.minutes import MinuteStore

APERTURA_RTH = 9.5
CIERRE_RTH = 16.0
INICIO_PRE = 4.0


def hora(b) -> float:
    return b[0].hour + b[0].minute / 60.0


class Dia:
    """Un (ticker, día) con las barras y las derivadas que usan todos los tests.

    Todo lo que expone es **acumulativo hacia adelante**: `vwap[i]` usa barras
    0..i, nunca las futuras. Los campos que sí miran el día entero llevan el
    prefijo `_post_` para que no se cuelen en una señal por descuido.
    """

    def __init__(self, ticker: str, d: str, bars, prev_close, prev_vol, vol_dia):
        self.ticker = ticker
        self.d = d
        self.bars = bars
        self.prev_close = prev_close
        self.prev_vol = prev_vol
        self.vol_dia = vol_dia

        self.pre = [b for b in bars if INICIO_PRE <= hora(b) < APERTURA_RTH]
        self.rth = [b for b in bars if APERTURA_RTH <= hora(b) <= CIERRE_RTH]

        # VWAP acumulado desde las 04:00 (incluye pre-market, como la plataforma).
        self.vwap = []
        pv = vol = 0.0
        for b in bars:
            v = b[5] or 0.0
            tip = ((b[2] or b[4]) + (b[3] or b[4]) + (b[4] or 0)) / 3.0
            pv += tip * v
            vol += v
            self.vwap.append(pv / vol if vol else (b[4] or 0.0))

        # Máximo corriente y hace cuánto se hizo (en minutos), barra por barra.
        self.max_corriente = []
        self.edad_max = []
        mx, t_mx = float("-inf"), None
        for b in bars:
            if b[2] and b[2] > mx:
                mx, t_mx = b[2], b[0]
            self.max_corriente.append(mx)
            self.edad_max.append((b[0] - t_mx).total_seconds() / 60.0 if t_mx else 0.0)

    # -- derivadas de un solo número -------------------------------------
    @property
    def pm_high(self):
        h = [b[2] for b in self.pre if b[2]]
        return max(h) if h else None

    @property
    def expansion_pct(self):
        """Máximo pre-market vs cierre previo. Observable a las 09:30."""
        if not self.pm_high or not self.prev_close:
            return None
        return (self.pm_high / self.prev_close - 1.0) * 100.0

    @property
    def ratio_volumen(self):
        """Volumen del día vs el del día previo. Un reverse split lo deja <1."""
        if not self.prev_vol:
            return None
        return self.vol_dia / self.prev_vol

    @property
    def rth_open(self):
        return self.rth[0][1] if self.rth else None

    @property
    def rth_close(self):
        return self.rth[-1][4] if self.rth else None

    # -- consultas por hora ----------------------------------------------
    def idx_en(self, h: float):
        """Índice de la última barra en o antes de `h`. None si no hay."""
        idx = None
        for i, b in enumerate(self.bars):
            if hora(b) <= h:
                idx = i
            else:
                break
        return idx

    def precio_en(self, h: float):
        i = self.idx_en(h)
        return self.bars[i][4] if i is not None else None

    def estado_en(self, h: float):
        """`front` / `back` según el VWAP. Cero parámetros: el nivel lo pone el flujo."""
        i = self.idx_en(h)
        if i is None or not self.bars[i][4]:
            return None
        return "front" if self.bars[i][4] >= self.vwap[i] else "back"

    def excursion(self, h: float):
        """(MAE del long, MAE del short) desde `h` hasta el cierre RTH, en %.

        Ambos se devuelven como magnitud positiva de lo que se movió EN CONTRA.
        """
        p = self.precio_en(h)
        post = [b for b in self.bars if h <= hora(b) <= CIERRE_RTH]
        if not p or not post:
            return None, None
        bajo = min(b[3] for b in post if b[3])
        alto = max(b[2] for b in post if b[2])
        return (1 - bajo / p) * 100.0, (alto / p - 1) * 100.0


def _armar(store, db, ticker: str, d: str):
    """Construye un `Dia` si hay barras suficientes. None si no."""
    prev = db.execute(
        "SELECT c,v FROM bars_daily WHERE ticker=? AND d<? ORDER BY d DESC LIMIT 1",
        (ticker, d)).fetchone()
    cur = db.execute("SELECT v FROM bars_daily WHERE ticker=? AND d=?", (ticker, d)).fetchone()
    bars = store.day_bars(ticker, date.fromisoformat(d))
    if not bars or not prev:
        return None
    dia = Dia(ticker, d, bars, prev[0], prev[1], cur[0] if cur else 0.0)
    if len(dia.pre) < 10 or len(dia.rth) < 60:
        return None
    return dia


def dias_de_poblacion() -> set[tuple[str, str]]:
    """El censo observable de `poblacion_observable.py`.

    **Por qué hace falta separarlo.** Cuando termine la descarga del censo, la
    tabla `minute_log` va a tener MEZCLADOS los 1.500 días de la muestra vieja
    —sorteada por rango del día completo, o sea con look-ahead en la selección—
    y los ~2.000 del censo. Correr el análisis sobre `minute_log` a secas sería
    peor que antes: una muestra contaminada en vez de una sesgada.

    Devuelve vacío si la tabla no existe todavía.
    """
    db = sqlite3.connect(config.bars_db_path())
    try:
        return {(t, d) for t, d in db.execute("SELECT ticker,d FROM poblacion_obs")}
    except sqlite3.OperationalError:
        return set()
    finally:
        db.close()


def dias_del_evento(conn) -> list[tuple[str, str]]:
    """Los (ticker, día) que son EVENTO — la muestra sorteada, no los vecinos.

    Es la que tienen que usar los tests: la descarga trae 4 días extra por
    llamada, y meterlos en la muestra la agrandaría con días que nadie sorteó.
    """
    return list(conn.execute(
        "SELECT ticker,d FROM minute_log WHERE status='ok' ORDER BY ticker,d"))


def dias_con_barras(conn, *, min_barras: int = 70) -> list[tuple[str, str, bool]]:
    """Todos los días con barras suficientes, incluidos los vecinos. Para el visor.

    Cada descarga cubre el día del evento y los ~4 siguientes. Esos días de
    después NO sirven para medir (nadie los sorteó) pero sí para MIRAR: el
    día 2 de una parabólica es la mitad de la historia.

    El día ET se calcula en SQL restando 4 horas al epoch. Es un filtro de
    CANDIDATOS: la fecha exacta la vuelve a resolver `day_bars` al cargar, con
    zona horaria de verdad. Acá alcanza con no perder ninguno.
    """
    ev = {(t, d) for t, d in dias_del_evento(conn)}
    # El alias NO puede llamarse `n`: `bars_minute` ya tiene una columna `n`
    # (cantidad de transacciones) y SQLite resuelve el HAVING contra ESA, no
    # contra el COUNT. Con `n` el filtro devolvía 852 días en vez de 4.841.
    filas = conn.execute(
        "SELECT ticker, date(ts/1000,'unixepoch','-4 hours') AS d, COUNT(*) AS n_barras "
        "FROM bars_minute GROUP BY 1,2 HAVING n_barras >= ? ORDER BY 1,2", (min_barras,))
    return [(t, d, (t, d) in ev) for t, d, _ in filas]


def cargar(*, solo=None, incluir_vecinos: bool = False, censo: bool = False):
    """Itera días como objetos `Dia`.

    Por defecto recorre los días de evento con minutos bajados.
    `incluir_vecinos` agrega los días siguientes, para mirar.
    `censo=True` restringe al censo observable — la única forma de medir sin
    el sesgo de selección de la muestra vieja.
    """
    store = MinuteStore()
    db = sqlite3.connect(config.bars_db_path())
    try:
        if solo:
            pares = sorted(solo)
        elif incluir_vecinos:
            pares = [(t, d) for t, d, _ in dias_con_barras(store.conn)]
        else:
            pares = dias_del_evento(store.conn)
        # La variable de entorno existe para que NINGÚN script se olvide del
        # flag: `recorrer.py` la prende una vez y todo el análisis queda sobre
        # el censo. Olvidarse en un solo script contamina la corrida entera.
        censo = censo or os.environ.get("SMALLCAPS_CENSO") == "1"
        if censo and not solo:
            pob = dias_de_poblacion()
            if not pob:
                raise RuntimeError(
                    "no hay censo todavía: corré `python poblacion_observable.py`")
            antes = len(pares)
            pares = [x for x in pares if x in pob]
            print(f"  [censo observable: {len(pares)} días de {antes} bajados]",
                  flush=True)
        for t, d in pares:
            dia = _armar(store, db, t, d)
            if dia is not None:
                yield dia
    finally:
        store.close()
        db.close()
