"""
Generador de estrategias por programación genética, al estilo del Builder de
StrategyQuant.

En vez de optimizar los parámetros de una estrategia que ya escribiste, esto
construye las reglas desde cero: combina bloques (indicadores, comparaciones,
operadores lógicos, gestión de la posición) en genomas aleatorios, se queda con
los que mejor puntúan, los cruza, los muta y repite.

Dos decisiones de diseño que evitan que salga basura:

- Los bloques están tipados por escala. Un RSI vive entre 0 y 100 y una media
  móvil vive en unidades de precio, así que compararlos no significa nada. Sólo
  se comparan operandos de la misma escala, y las constantes sólo aparecen
  donde tienen sentido (`rsi < 30` sí, `sma(20) < 30` no, porque el precio de
  bitcoin ha pasado de 3.000 a 120.000 y ningún umbral fijo aguanta eso).
- Todo genoma lleva stop obligatorio. Sin él, la evolución tiende a descubrir
  que "no cerrar nunca las posiciones perdedoras" mejora casi cualquier métrica
  sobre histórico, y eso no es una estrategia.

Aviso que conviene tener presente: generar miles de estrategias y quedarse con
la mejor encuentra algo que parece bueno SIEMPRE, incluso sobre datos
puramente aleatorios. Por eso la evolución sólo ve el tramo in-sample y el
banco final pasa por out-of-sample y Monte Carlo antes de que nada de esto
merezca una segunda mirada. Ese filtro es el producto; el generador sólo
fabrica candidatos.
"""

import json
from dataclasses import dataclass, field
from hashlib import blake2b

import numpy as np
import pandas as pd

from . import indicadores as ind
from . import metricas as mod_metricas
from . import montecarlo
from .indicadores import Contexto
from .motor import Config, Senales, ejecutar
from .optimizar import FITNESS, partir

# ========================
# BLOQUES DISPONIBLES
# ========================
# escala: sólo se comparan operandos de la misma escala.
# constantes: (min, max, paso) si tiene sentido comparar contra un número fijo.
BLOQUES = {
    "sma":            {"escala": "precio", "periodos": [5, 10, 20, 30, 50, 100, 150, 200], "constantes": None},
    "ema":            {"escala": "precio", "periodos": [5, 10, 20, 30, 50, 100, 150, 200], "constantes": None},
    "wma":            {"escala": "precio", "periodos": [10, 20, 50, 100], "constantes": None},
    "bollinger_sup":  {"escala": "precio", "periodos": [10, 20, 30, 50], "constantes": None},
    "bollinger_inf":  {"escala": "precio", "periodos": [10, 20, 30, 50], "constantes": None},
    "maximo":         {"escala": "precio", "periodos": [10, 20, 30, 55, 80], "constantes": None},
    "minimo":         {"escala": "precio", "periodos": [10, 20, 30, 55, 80], "constantes": None},
    "rsi":            {"escala": "osc100", "periodos": [7, 14, 21, 30], "constantes": (15, 85, 5)},
    "estocastico":    {"escala": "osc100", "periodos": [7, 14, 21], "constantes": (15, 85, 5)},
    "roc":            {"escala": "pct", "periodos": [5, 10, 20, 30, 50], "constantes": (-10, 10, 1)},
    "cci":            {"escala": "cci", "periodos": [14, 20, 30], "constantes": (-200, 200, 25)},
    # MACD está en unidades de precio, así que el único umbral fijo con sentido
    # a lo largo de años es el cero.
    "macd":           {"escala": "macd", "periodos": [8, 12, 20, 30], "constantes": (0, 0, 1)},
}

# Contexto semanal. Se añade al catálogo con la misma interfaz que el resto de
# bloques, así que la evolución puede combinar libremente señales intradía con
# filtros de marco superior. Todas son causales (ver superior.py).
BLOQUES_SEMANALES = {
    "sem_ant_close":  {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_ant_high":   {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_ant_low":    {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_ant_medio":  {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_open":       {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_high_hasta": {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_low_hasta":  {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_pivote":     {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_r1":         {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_s1":         {"escala": "precio", "periodos": [0], "constantes": None},
    "sem_sma":        {"escala": "precio", "periodos": [2, 4, 8, 13, 26], "constantes": None},
    "sem_pos_rango":  {"escala": "osc100", "periodos": [0], "constantes": (0, 100, 10)},
    "sem_pos_semana": {"escala": "osc100", "periodos": [0], "constantes": (0, 100, 10)},
    "sem_var":        {"escala": "pct", "periodos": [1, 2, 4], "constantes": (-15, 15, 2.5)},
}

NOMBRES_SEMANALES = set(BLOQUES_SEMANALES)
BLOQUES.update(BLOQUES_SEMANALES)

CAMPOS_PRECIO = ["close", "high", "low"]
OPERADORES = [">", "<", "cruza_arriba", "cruza_abajo"]
LOGICOS = ["y", "o"]

STOPS_ATR = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
OBJETIVOS_ATR = [0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
MAX_BARRAS = [0, 24, 48, 96, 200]


@dataclass
class Opciones:
    """
    Restricciones sobre la forma de los genomas que puede producir la evolución.

    modo "bracket" fija objetivo = stop (ratio 1:1 exacto) y quita las
    condiciones de salida, de forma que toda operación acaba en stop, en
    objetivo o por tiempo. Es la única manera de que el win rate signifique lo
    que se espera que signifique: con salidas por señal, ganancias y pérdidas
    dejan de ser simétricas y el acierto ya no se puede comparar contra el
    umbral de equilibrio del 1:1.
    """
    modo: str = "libre"
    max_barras: tuple = tuple(MAX_BARRAS)
    stops_atr: tuple = tuple(STOPS_ATR)

    def aplicar(self, genoma):
        if self.modo == "bracket":
            genoma.objetivo_atr = genoma.stop_atr
            genoma.salida = []
        return genoma


OPCIONES_POR_DEFECTO = Opciones()

# Escalas que admiten operandos de precio crudo (close, high, low).
ESCALAS_CON_PRECIO = {"precio"}


def _escalas_disponibles():
    return sorted({b["escala"] for b in BLOQUES.values()})


def _bloques_de(escala):
    return [n for n, b in BLOQUES.items() if b["escala"] == escala]


# ========================
# GENOMA
# ========================

@dataclass
class Genoma:
    """
    Una estrategia generada.

    entrada / salida son listas de condiciones combinadas con `logico`. El lado
    corto es el reflejo del largo, lo que reduce a la mitad el espacio de
    búsqueda y evita estrategias que sólo funcionan en una dirección por
    casualidad.
    """
    entrada: list
    logico_entrada: str = "y"
    salida: list = field(default_factory=list)
    logico_salida: str = "o"
    stop_atr: float = 2.0
    objetivo_atr: float = 0.0
    max_barras: int = 0
    periodo_atr: int = 14

    def como_dict(self):
        return {
            "entrada": self.entrada, "logico_entrada": self.logico_entrada,
            "salida": self.salida, "logico_salida": self.logico_salida,
            "stop_atr": self.stop_atr, "objetivo_atr": self.objetivo_atr,
            "max_barras": self.max_barras, "periodo_atr": self.periodo_atr,
        }

    @staticmethod
    def desde_dict(d):
        return Genoma(**d)

    def canonico(self):
        """
        Forma normalizada del genoma: dos genomas que operan igual dan el mismo
        canónico aunque se escriban distinto.

        Hace falta porque hay campos que no influyen en el comportamiento y, sin
        normalizarlos, el banco se llena de la misma estrategia repetida. El
        operador lógico no significa nada con una sola condición, el conector de
        salida no significa nada sin condiciones de salida, y como "y"/"o" son
        conmutativos el orden de las condiciones tampoco cambia el resultado.
        """
        ordenar = lambda cs: sorted(cs, key=lambda c: json.dumps(c, sort_keys=True))
        entrada = ordenar(self.entrada)
        salida = ordenar(self.salida)
        return {
            "entrada": entrada,
            "logico_entrada": self.logico_entrada if len(entrada) > 1 else "y",
            "salida": salida,
            "logico_salida": self.logico_salida if len(salida) > 1 else "o",
            "stop_atr": self.stop_atr,
            "objetivo_atr": self.objetivo_atr,
            "max_barras": self.max_barras,
            "periodo_atr": self.periodo_atr,
        }

    def huella(self):
        """Identidad del genoma, para no guardar dos veces la misma estrategia."""
        crudo = json.dumps(self.canonico(), sort_keys=True).encode()
        return blake2b(crudo, digest_size=8).hexdigest()

    def describir(self):
        """Pseudocódigo legible de la estrategia."""
        conector = " Y " if self.logico_entrada == "y" else " O "
        entrada = conector.join(_texto_condicion(c) for c in self.entrada)
        lineas = [f"  LARGO si   {entrada}",
                  f"  CORTO si   {conector.join(_texto_condicion(_invertir(c)) for c in self.entrada)}"]
        if self.salida:
            conector_s = " Y " if self.logico_salida == "y" else " O "
            lineas.append(f"  SALIR si   {conector_s.join(_texto_condicion(c) for c in self.salida)}")
        gestion = [f"stop {self.stop_atr}×ATR({self.periodo_atr})"]
        if self.objetivo_atr:
            gestion.append(f"objetivo {self.objetivo_atr}×ATR")
        if self.max_barras:
            gestion.append(f"máx {self.max_barras} barras")
        lineas.append(f"  GESTIÓN    {', '.join(gestion)}")
        return "\n".join(lineas)


def _texto_operando(op):
    if op["clase"] == "indicador":
        return f"{op['nombre']}({op['periodo']})"
    if op["clase"] == "precio":
        return op["campo"]
    return str(op["valor"])


def _texto_condicion(c):
    simbolos = {">": ">", "<": "<", "cruza_arriba": "cruza ↑", "cruza_abajo": "cruza ↓"}
    return f"{_texto_operando(c['izq'])} {simbolos[c['op']]} {_texto_operando(c['der'])}"


def _invertir(condicion):
    """Refleja una condición para el lado corto."""
    opuesto = {">": "<", "<": ">", "cruza_arriba": "cruza_abajo", "cruza_abajo": "cruza_arriba"}
    return {**condicion, "op": opuesto[condicion["op"]]}


# ========================
# CREACIÓN ALEATORIA
# ========================

def _operando_aleatorio(rng, escala, permitir_constante=True):
    opciones = []
    bloques = _bloques_de(escala)
    if bloques:
        opciones.append("indicador")
    if escala in ESCALAS_CON_PRECIO:
        opciones.append("precio")
    info_const = next((BLOQUES[b]["constantes"] for b in bloques
                       if BLOQUES[b]["constantes"]), None)
    if permitir_constante and info_const:
        opciones.append("constante")

    clase = opciones[rng.integers(len(opciones))]
    if clase == "indicador":
        nombre = bloques[rng.integers(len(bloques))]
        periodos = BLOQUES[nombre]["periodos"]
        return {"clase": "indicador", "nombre": nombre,
                "periodo": int(periodos[rng.integers(len(periodos))])}
    if clase == "precio":
        return {"clase": "precio", "campo": CAMPOS_PRECIO[rng.integers(len(CAMPOS_PRECIO))]}

    minimo, maximo, paso = info_const
    if minimo == maximo:
        valor = minimo
    else:
        posibles = np.arange(minimo, maximo + paso, paso)
        valor = float(posibles[rng.integers(len(posibles))])
    return {"clase": "constante", "valor": valor}


def _degenerada(condicion):
    """
    Una condición que compara un operando consigo mismo (`macd(30) < macd(30)`)
    es constante: siempre falsa. No rompe nada, pero ensucia el banco con
    genomas distintos que se comportan igual y gasta presupuesto de búsqueda.
    """
    return condicion["izq"] == condicion["der"]


def _condicion_aleatoria(rng, intentos=8):
    escalas = _escalas_disponibles()
    for _ in range(intentos):
        escala = escalas[rng.integers(len(escalas))]
        izq = _operando_aleatorio(rng, escala, permitir_constante=False)
        der = _operando_aleatorio(rng, escala, permitir_constante=True)
        condicion = {"izq": izq, "op": OPERADORES[rng.integers(len(OPERADORES))], "der": der}
        if not _degenerada(condicion):
            return condicion
    # Salida de emergencia: una comparación con sentido garantizado.
    return {"izq": {"clase": "precio", "campo": "close"}, "op": ">",
            "der": {"clase": "indicador", "nombre": "sma", "periodo": 50}}


def _sanear(genoma, rng):
    """
    Quita las condiciones degeneradas que puedan haber aparecido al cruzar o
    mutar (cambiar el periodo de un lado puede igualarlo al otro).
    """
    genoma.entrada = [c for c in genoma.entrada if not _degenerada(c)]
    genoma.salida = [c for c in genoma.salida if not _degenerada(c)]
    if not genoma.entrada:
        genoma.entrada = [_condicion_aleatoria(rng)]
    return genoma


def genoma_aleatorio(rng, max_condiciones=3, opciones=None):
    opciones = opciones or OPCIONES_POR_DEFECTO
    n_entrada = int(rng.integers(1, max_condiciones + 1))
    n_salida = int(rng.integers(0, 3))
    genoma = Genoma(
        entrada=[_condicion_aleatoria(rng) for _ in range(n_entrada)],
        logico_entrada=LOGICOS[rng.integers(len(LOGICOS))],
        salida=[_condicion_aleatoria(rng) for _ in range(n_salida)],
        logico_salida=LOGICOS[rng.integers(len(LOGICOS))],
        stop_atr=float(opciones.stops_atr[rng.integers(len(opciones.stops_atr))]),
        objetivo_atr=float(OBJETIVOS_ATR[rng.integers(len(OBJETIVOS_ATR))]),
        max_barras=int(opciones.max_barras[rng.integers(len(opciones.max_barras))]),
    )
    return _sanear(opciones.aplicar(genoma), rng)


# ========================
# EVALUACIÓN
# ========================

def _valor_operando(op, contexto):
    if op["clase"] == "indicador":
        return contexto.ind(op["nombre"], op["periodo"])
    if op["clase"] == "precio":
        return getattr(contexto, op["campo"])
    return np.full(len(contexto), op["valor"], dtype=float)


def _valor_condicion(cond, contexto):
    a = _valor_operando(cond["izq"], contexto)
    b = _valor_operando(cond["der"], contexto)
    op = cond["op"]
    # Las comparaciones con NaN dan False, así que las barras de calentamiento
    # de cada indicador quedan descartadas solas.
    with np.errstate(invalid="ignore"):
        if op == ">":
            return a > b
        if op == "<":
            return a < b
        if op == "cruza_arriba":
            return ind.cruza_arriba(a, b)
        return ind.cruza_abajo(a, b)


def _combinar(mascaras, logico, largo):
    if not mascaras:
        return np.zeros(largo, dtype=bool)
    salida = mascaras[0]
    for m in mascaras[1:]:
        salida = (salida & m) if logico == "y" else (salida | m)
    return salida


def senales_de(genoma, contexto):
    """Traduce un genoma a las señales que entiende el motor."""
    n = len(contexto)
    entrada_l = _combinar([_valor_condicion(c, contexto) for c in genoma.entrada],
                          genoma.logico_entrada, n)
    entrada_c = _combinar([_valor_condicion(_invertir(c), contexto) for c in genoma.entrada],
                          genoma.logico_entrada, n)

    salida_l = salida_c = None
    if genoma.salida:
        salida_l = _combinar([_valor_condicion(c, contexto) for c in genoma.salida],
                             genoma.logico_salida, n)
        salida_c = _combinar([_valor_condicion(_invertir(c), contexto) for c in genoma.salida],
                             genoma.logico_salida, n)

    atr = contexto.ind("atr", genoma.periodo_atr)
    return Senales(
        entrada_larga=entrada_l, salida_larga=salida_l,
        entrada_corta=entrada_c, salida_corta=salida_c,
        dist_stop=atr * genoma.stop_atr,
        dist_objetivo=atr * genoma.objetivo_atr if genoma.objetivo_atr else None,
    )


def evaluar(genoma, contexto, config, intervalo):
    config_local = config
    if genoma.max_barras:
        config_local = Config(**{**config.__dict__, "max_barras": genoma.max_barras})
    resultado = ejecutar(contexto.datos, senales_de(genoma, contexto), config_local)
    return mod_metricas.calcular(resultado, intervalo, config.capital), resultado


def puntuar(metricas, criterio, min_operaciones):
    """Fitness. Sin operaciones suficientes, la estrategia no puntúa."""
    if metricas["n_operaciones"] < min_operaciones:
        return -np.inf
    valor = FITNESS[criterio](metricas)
    return valor if np.isfinite(valor) else -np.inf


# ========================
# OPERADORES GENÉTICOS
# ========================

def cruzar(a, b, rng, opciones=None):
    """Mezcla dos genomas tomando bloques enteros de cada padre."""
    hijo = Genoma(
        entrada=list(a.entrada if rng.random() < 0.5 else b.entrada),
        logico_entrada=a.logico_entrada if rng.random() < 0.5 else b.logico_entrada,
        salida=list(a.salida if rng.random() < 0.5 else b.salida),
        logico_salida=a.logico_salida if rng.random() < 0.5 else b.logico_salida,
        stop_atr=a.stop_atr if rng.random() < 0.5 else b.stop_atr,
        objetivo_atr=a.objetivo_atr if rng.random() < 0.5 else b.objetivo_atr,
        max_barras=a.max_barras if rng.random() < 0.5 else b.max_barras,
    )
    # Intercambio de una condición suelta, para mezclar dentro de las reglas y
    # no sólo entre bloques.
    if hijo.entrada and b.entrada and rng.random() < 0.5:
        i = int(rng.integers(len(hijo.entrada)))
        hijo.entrada = list(hijo.entrada)
        hijo.entrada[i] = dict(b.entrada[int(rng.integers(len(b.entrada)))])
    return _sanear((opciones or OPCIONES_POR_DEFECTO).aplicar(hijo), rng)


def mutar(genoma, rng, probabilidad=0.3, opciones=None):
    """Aplica una mutación al azar sobre una copia del genoma."""
    opciones = opciones or OPCIONES_POR_DEFECTO
    g = Genoma.desde_dict(json.loads(json.dumps(genoma.como_dict())))

    acciones = ["condicion", "operador", "periodo", "logico", "stop", "objetivo",
                "max_barras", "anadir", "quitar"]
    for _ in range(1 + int(rng.random() < probabilidad)):
        accion = acciones[rng.integers(len(acciones))]

        if accion == "condicion" and g.entrada:
            g.entrada[int(rng.integers(len(g.entrada)))] = _condicion_aleatoria(rng)
        elif accion == "operador" and g.entrada:
            c = g.entrada[int(rng.integers(len(g.entrada)))]
            c["op"] = OPERADORES[rng.integers(len(OPERADORES))]
        elif accion == "periodo" and g.entrada:
            c = g.entrada[int(rng.integers(len(g.entrada)))]
            lado = c["izq"] if rng.random() < 0.5 else c["der"]
            if lado["clase"] == "indicador":
                periodos = BLOQUES[lado["nombre"]]["periodos"]
                lado["periodo"] = int(periodos[rng.integers(len(periodos))])
        elif accion == "logico":
            g.logico_entrada = LOGICOS[rng.integers(len(LOGICOS))]
        elif accion == "stop":
            g.stop_atr = float(opciones.stops_atr[rng.integers(len(opciones.stops_atr))])
        elif accion == "objetivo":
            g.objetivo_atr = float(OBJETIVOS_ATR[rng.integers(len(OBJETIVOS_ATR))])
        elif accion == "max_barras":
            g.max_barras = int(opciones.max_barras[rng.integers(len(opciones.max_barras))])
        elif accion == "anadir" and len(g.entrada) < 3:
            g.entrada.append(_condicion_aleatoria(rng))
        elif accion == "quitar" and len(g.entrada) > 1:
            g.entrada.pop(int(rng.integers(len(g.entrada))))
    return _sanear(opciones.aplicar(g), rng)


def _torneo(poblacion, puntuaciones, rng, tamano=3):
    indices = rng.integers(0, len(poblacion), tamano)
    mejor = max(indices, key=lambda i: puntuaciones[i])
    return poblacion[mejor]


# ========================
# EVOLUCIÓN
# ========================

@dataclass
class Candidata:
    genoma: Genoma
    fitness_is: float
    metricas_is: dict
    metricas_oos: dict = None

    @property
    def huella(self):
        return self.genoma.huella()


def evolucionar(datos, config=None, criterio="compuesto", poblacion=120, generaciones=25,
                min_operaciones=40, fraccion_oos=0.3, elite=0.1, semilla=42,
                banco_max=50, verboso=True, opciones=None):
    """
    Evoluciona una población de estrategias sobre el tramo in-sample.

    El tramo out-of-sample no se toca durante la evolución: se usa sólo al
    final para puntuar el banco. Si se usara antes, dejaría de ser válido como
    validación, que es justo el error que estas herramientas invitan a cometer.
    """
    config = config or Config()
    opciones = opciones or OPCIONES_POR_DEFECTO
    rng = np.random.default_rng(semilla)
    particion = partir(datos, fraccion_oos)
    ctx_is = Contexto(particion.entrenamiento)
    intervalo = datos.intervalo

    actual = [genoma_aleatorio(rng, opciones=opciones) for _ in range(poblacion)]
    banco = {}
    n_elite = max(1, int(poblacion * elite))

    for generacion in range(generaciones):
        puntuaciones, metricas_gen = [], []
        for g in actual:
            try:
                m, _ = evaluar(g, ctx_is, config, intervalo)
            except (ValueError, KeyError, IndexError):
                m = None
            if m is None:
                puntuaciones.append(-np.inf)
                metricas_gen.append(None)
                continue
            puntuaciones.append(puntuar(m, criterio, min_operaciones))
            metricas_gen.append(m)

        # Al banco sólo entran genomas con fitness real, y nunca dos veces.
        for g, p, m in zip(actual, puntuaciones, metricas_gen):
            if np.isfinite(p) and p > 0 and m is not None:
                banco.setdefault(g.huella(), Candidata(g, p, m))

        orden = np.argsort(puntuaciones)[::-1]
        validos = [p for p in puntuaciones if np.isfinite(p)]
        if verboso:
            mejor = puntuaciones[orden[0]]
            media = np.mean(validos) if validos else float("nan")
            print(f"  gen {generacion + 1:>3}/{generaciones}  mejor {mejor:>8.2f}  "
                  f"media {media:>8.2f}  válidas {len(validos):>4}/{poblacion}  "
                  f"banco {len(banco)}")

        if generacion == generaciones - 1:
            break

        siguiente = [actual[i] for i in orden[:n_elite]]
        while len(siguiente) < poblacion:
            if rng.random() < 0.15:
                siguiente.append(genoma_aleatorio(rng, opciones=opciones))   # sangre nueva
            else:
                padre = _torneo(actual, puntuaciones, rng)
                madre = _torneo(actual, puntuaciones, rng)
                siguiente.append(mutar(cruzar(padre, madre, rng, opciones), rng,
                                       opciones=opciones))
        actual = siguiente

    # Validación fuera de muestra de todo el banco, una sola vez y al final.
    ctx_oos = Contexto(particion.validacion)
    candidatas = sorted(banco.values(), key=lambda c: c.fitness_is, reverse=True)[:banco_max]
    for c in candidatas:
        try:
            c.metricas_oos, _ = evaluar(c.genoma, ctx_oos, config, intervalo)
        except (ValueError, KeyError, IndexError):
            c.metricas_oos = None
    return candidatas


# ========================
# FILTRO DE ROBUSTEZ
# ========================

def filtrar(candidatas, datos, config=None, min_ops_oos=10, min_retorno_oos=0.0,
            max_dd_p95=0.6, n_montecarlo=500, verboso=True):
    """
    Aplica los cross-checks a un banco de candidatas y devuelve sólo las que
    sobreviven a todos.

    Es lo que convierte un montón de curvas bonitas en una lista corta que
    merece atención. Que no sobreviva ninguna es un resultado perfectamente
    normal, y mucho más informativo que quedarse con la menos mala.
    """
    config = config or Config()
    supervivientes = []
    descartes = {"sin_oos": 0, "oos_negativo": 0, "pocas_ops": 0, "drawdown_mc": 0}

    contexto_total = Contexto(datos)
    for c in candidatas:
        if c.metricas_oos is None:
            descartes["sin_oos"] += 1
            continue
        if c.metricas_oos["n_operaciones"] < min_ops_oos:
            descartes["pocas_ops"] += 1
            continue
        if c.metricas_oos["retorno_total"] <= min_retorno_oos:
            descartes["oos_negativo"] += 1
            continue

        # Monte Carlo sobre toda la serie: si el percentil 95 de drawdown es
        # inasumible, da igual lo bien que se vea la curva original.
        _, resultado = evaluar(c.genoma, contexto_total, config, datos.intervalo)
        mc = montecarlo.sobre_operaciones(resultado, n=n_montecarlo, tipo="barajar",
                                          capital=config.capital)
        if mc.n == 0 or mc.percentiles()["drawdown"][95] > max_dd_p95:
            descartes["drawdown_mc"] += 1
            continue

        c.mc = mc
        supervivientes.append(c)

    if verboso:
        print(f"\n  {len(candidatas)} candidatas → {len(supervivientes)} supervivientes")
        for motivo, cuantas in descartes.items():
            if cuantas:
                print(f"    descartadas por {motivo}: {cuantas}")
    return supervivientes


def tabla(candidatas):
    """Banco de estrategias como DataFrame, ordenado por fitness in-sample."""
    filas = []
    for i, c in enumerate(candidatas):
        fila = {
            "id": c.huella[:8],
            "fitness_is": c.fitness_is,
            "is_cagr": c.metricas_is["cagr"],
            "is_dd": c.metricas_is["max_drawdown"],
            "is_ops": c.metricas_is["n_operaciones"],
            "is_estab": c.metricas_is["estabilidad"],
        }
        if c.metricas_oos:
            fila.update({
                "oos_cagr": c.metricas_oos["cagr"],
                "oos_dd": c.metricas_oos["max_drawdown"],
                "oos_ops": c.metricas_oos["n_operaciones"],
                "oos_retorno": c.metricas_oos["retorno_total"],
            })
        filas.append(fila)
    return pd.DataFrame(filas)


def guardar(candidatas, ruta):
    """Serializa el banco a JSON para poder recuperarlo después."""
    datos = [{"genoma": c.genoma.como_dict(), "fitness_is": c.fitness_is,
              "metricas_is": c.metricas_is, "metricas_oos": c.metricas_oos}
             for c in candidatas]
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


def leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        crudo = json.load(f)
    return [Candidata(Genoma.desde_dict(d["genoma"]), d["fitness_is"],
                      d["metricas_is"], d.get("metricas_oos")) for d in crudo]
