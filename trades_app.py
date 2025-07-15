import streamlit as st
import pandas as pd
import os

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

ARCHIVO = "trades.csv"

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
st.set_page_config(page_title="Registro de Trades", layout="centered")
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

if st.button("Calcular Probabilidad"):
    # Calcular puntaje y categoría
    puntaje = calcular_puntaje(hh, checks)
    cat = categoria_por_puntaje(puntaje)

    st.success(f"**Puntaje total:** {puntaje} | **Categoría:** {cat}")

    # ========================
    # BOTÓN GUARDAR
    # ========================
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
        data["Puntaje"] = puntaje
        data["Categoría"] = cat

        guardar_trade(data)
        st.info("✅ Trade guardado correctamente")

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
