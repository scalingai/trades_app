import streamlit as st
import pandas as pd
import os

# ===== CONFIGURACIÓN =====
PESOS = {
    "Overextension": 15,
    "Volumen PM >500k": 5,
    "Float <20M": 5,
    "RSI": 10,
    "Manipulación de highs": 15,
    "VWAP": 10,
    "IBI": 15
}

PESOS_HH = {
    "0-30": 15,
    "30-60": 10,
    "60-90": 5,
    ">90": 0
}

ARCHIVO = "trades.csv"

# ===== FUNCIONES =====
def calcular_puntaje(hh, checks):
    total = PESOS_HH[hh]
    for var, activo in checks.items():
        if activo:
            total += PESOS[var]
    return total

def categoria_por_puntaje(puntaje):
    if puntaje >= 85:
        return "A+"
    elif puntaje >= 70:
        return "A"
    elif puntaje >= 61:
        return "B"
    else:
        return "NO ABRIR"

def guardar_trade(data):
    if os.path.exists(ARCHIVO):
        df = pd.read_csv(ARCHIVO)
    else:
        df = pd.DataFrame(columns=[
            "Fecha","Ticker","HH","Overext","Volumen",
            "Float","RSI","Manip","VWAP","IBI","Puntaje","Categoría"
        ])
    df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
    df.to_csv(ARCHIVO, index=False)

# ===== INTERFAZ STREAMLIT =====
st.set_page_config(page_title="Registro de Trades", layout="centered")
st.title("📊 Registro de Trades - Small Caps")

# Formulario
fecha = st.date_input("Fecha")
ticker = st.text_input("Ticker")

hh = st.selectbox("Higher High (HH)", ["0-30","30-60","60-90",">90"])

# Checkboxes confirmaciones
st.write("### Confirmaciones:")
overext = st.checkbox("Overextension")
volumen = st.checkbox("Volumen PM >500k")
float_low = st.checkbox("Float <20M")
rsi = st.checkbox("Divergencia RSI")
manip = st.checkbox("Manipulación de highs")
vwap = st.checkbox("Rechazo VWAP")
ibi = st.checkbox("IBI (Intent Break Impulse)")

checks = {
    "Overextension": overext,
    "Volumen PM >500k": volumen,
    "Float <20M": float_low,
    "RSI": rsi,
    "Manipulación de highs": manip,
    "VWAP": vwap,
    "IBI": ibi
}

# Botón para calcular puntaje
if st.button("Calcular Probabilidad"):
    puntaje = calcular_puntaje(hh, checks)
    cat = categoria_por_puntaje(puntaje)
    st.success(f"**Puntaje:** {puntaje} | **Categoría:** {cat}")

    # Botón Guardar dentro del cálculo
    if st.button("Guardar Trade"):
        data = {
            "Fecha": fecha,
            "Ticker": ticker,
            "HH": hh,
            "Overext": overext,
            "Volumen": volumen,
            "Float": float_low,
            "RSI": rsi,
            "Manip": manip,
            "VWAP": vwap,
            "IBI": ibi,
            "Puntaje": puntaje,
            "Categoría": cat
        }
        guardar_trade(data)
        st.info("✅ Trade guardado correctamente")

# Mostrar histórico
if os.path.exists(ARCHIVO):
    st.write("### Histórico de Trades")
    df_hist = pd.read_csv(ARCHIVO)
    st.dataframe(df_hist)
