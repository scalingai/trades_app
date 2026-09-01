import streamlit as st
import pandas as pd
import os
from pathlib import Path

# ========================
# CONFIGURACIÓN Y PESOS
# ========================
PESOS_CONFIRMACIONES = {
    "Overextension": 15,
    "Volumen PM >500k": 5,
    "Float <20M": 5,
    "Divergencia RSI": 10,
    "Manipulación de highs": 15,
    "Rechazo VWAP": 10,
    "IBI (Intent Break Impulse)": 15
}

PESOS_HH = {
    "0-30": 15,
    "30-60": 10,
    "60-90": 5,
    ">90": 0
}

# EL REGISTRO NO PUEDE DEPENDER DE DESDE DONDE SE ABRA LA APP.
#
# Estaba como "trades.csv" a secas, o sea relativo al directorio de trabajo:
# abrirla desde otra carpeta creaba OTRO archivo vacio y el historial
# "desaparecia". Con un acceso directo en la barra de tareas eso pasa solo.
#
# Va junto a la data durable del proyecto, fuera del repo: el codigo se
# reemplaza y los worktrees se borran, pero el registro es lo unico que no se
# puede volver a generar.
_DATA = Path(os.environ.get("SMALLCAPS_DATA_DIR",
                            Path.home() / "Apps" / "algotrade-data" / "smallcaps"))
_DATA.mkdir(parents=True, exist_ok=True)
ARCHIVO = str(_DATA / "trades.csv")

# ========================
# FUNCIONES AUXILIARES
# ========================

def calcular_puntaje(hh, checks):
    """Suma el peso de HH más las confirmaciones activas."""
    total = PESOS_HH[hh]
    for var, activo in checks.items():
        if activo:
            total += PESOS_CONFIRMACIONES[var]
    return total

def categoria_por_puntaje(puntaje):
    """Clasifica según el puntaje total."""
    if puntaje >= 85:
        return "A+"
    elif puntaje >= 70:
        return "A"
    elif puntaje >= 61:
        return "B"
    else:
        return "NO ABRIR"

def guardar_trade(data):
    """Guarda el trade en CSV, creando el archivo si no existe."""
    if os.path.exists(ARCHIVO):
        df = pd.read_csv(ARCHIVO)
    else:
        df = pd.DataFrame(columns=[
            "Fecha", "Ticker", "HH",
            "Overextension", "Volumen PM >500k", "Float <20M",
            "Divergencia RSI", "Manipulación de highs",
            "Rechazo VWAP", "IBI (Intent Break Impulse)",
            "Puntaje", "Categoría"
        ])
    df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
    df.to_csv(ARCHIVO, index=False)

def cargar_historial():
    """Carga el historial si existe."""
    if os.path.exists(ARCHIVO):
        return pd.read_csv(ARCHIVO)
    else:
        return pd.DataFrame(columns=[
            "Fecha", "Ticker", "HH",
            "Overextension", "Volumen PM >500k", "Float <20M",
            "Divergencia RSI", "Manipulación de highs",
            "Rechazo VWAP", "IBI (Intent Break Impulse)",
            "Puntaje", "Categoría"
        ])

# ========================
# CONFIGURACIÓN DE LA APP
# ========================
# `page_icon` es el favicon, y con la ventana en modo aplicacion es el icono
# que Windows muestra en la barra de tareas. Sin esto queda el de Chrome.
st.set_page_config(page_title="Trades — Small Caps", page_icon="📊",
                   layout="centered")
st.title("📊 Registro de Trades - Small Caps")

# ========================
# FORMULARIO
# ========================

st.subheader("✏️ Registrar nuevo trade")

# Fecha y Ticker
fecha = st.date_input("Fecha del trade")
ticker = st.text_input("Ticker")

# Dropdown HH
hh = st.selectbox("Higher High (HH)", ["0-30", "30-60", "60-90", ">90"])

# Checkboxes confirmaciones
st.write("### ✅ Confirmaciones")
checks = {}
for c in PESOS_CONFIRMACIONES.keys():
    checks[c] = st.checkbox(c)

# ========================
# BOTÓN CALCULAR
# ========================

# UN BOTON ADENTRO DE OTRO NO SE PUEDE APRETAR NUNCA.
#
# Esto estaba escrito como `if st.button("Calcular"): ... if st.button("Guardar")`,
# y por eso NO EXISTIA `trades.csv`: la app jamas guardo un trade. En Streamlit
# un boton devuelve True solo en la pasada inmediatamente posterior a su propio
# click. Al apretar "Guardar" se dispara un rerun en el que "Calcular" ya
# devuelve False, asi que el bloque de adentro —incluido el guardado— no llega a
# ejecutarse nunca. No falla ni avisa: simplemente no pasa nada.
#
# El resultado del calculo se guarda en `session_state`, que sobrevive al rerun,
# y "Guardar" queda al mismo nivel.

if st.button("Calcular Probabilidad"):
    puntaje = calcular_puntaje(hh, checks)
    st.session_state["calculo"] = {
        "puntaje": puntaje,
        "categoria": categoria_por_puntaje(puntaje),
    }

calculo = st.session_state.get("calculo")
if calculo:
    st.success(f"**Puntaje total:** {calculo['puntaje']} | "
               f"**Categoría:** {calculo['categoria']}")

    if st.button("Guardar Trade"):
        data = {
            "Fecha": fecha,
            "Ticker": ticker,
            "HH": hh,
        }
        # Agregar las confirmaciones
        for c in checks:
            data[c] = checks[c]
        # Puntaje y categoría
        data["Puntaje"] = calculo["puntaje"]
        data["Categoría"] = calculo["categoria"]

        guardar_trade(data)
        # Se limpia para que el proximo rerun no vuelva a ofrecer guardar el
        # mismo trade: sin esto, cada interaccion con la pagina deja el boton
        # ahi y es facil cargarlo dos veces.
        st.session_state["calculo"] = None
        st.success("✅ Trade guardado correctamente")

# ========================
# HISTÓRICO DE TRADES
# ========================
st.subheader("📑 Histórico de Trades")

df_hist = cargar_historial()

if df_hist.empty:
    st.warning("⚠️ No hay trades guardados todavía.")
else:
    st.dataframe(df_hist)

    # Descargar histórico como CSV
    csv = df_hist.to_csv(index=False).encode('utf-8')
    st.download_button("⬇️ Descargar historial CSV", csv, "historial_trades.csv", "text/csv")
