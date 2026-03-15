"""
Configuración centralizada del sistema de trading algorítmico.
Pares, timeframes, horarios clave, scoring weights, y parámetros globales.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ========================
# API KEYS
# ========================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY", "")

# ========================
# PARES A MONITOREAR
# ========================
WATCHLIST = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
]

# ========================
# TIMEFRAMES
# ========================
TIMEFRAMES = ["1m", "5m", "15m"]
DEFAULT_TIMEFRAME = "15m"

# ========================
# HORARIOS CLAVE (UTC)
# ========================
KEY_SESSIONS = {
    "asia_open": {"start": "00:00", "end": "03:00"},
    "london_open": {"start": "08:00", "end": "11:00"},
    "ny_open": {"start": "13:30", "end": "16:00"},
    "london_ny_overlap": {"start": "13:30", "end": "17:00"},
}

# ========================
# SCORING — PESOS INICIALES (hipótesis, se auto-calibran)
# ========================
SCORING_WEIGHTS = {
    "liquidations_cluster": 15,
    "fvg_or_ob_in_zone": 15,
    "overextension": 15,
    "delta_volume_absorption": 10,
    "rsi_divergence": 10,
    "vwap_vpoc_rejection": 10,
    "volume_anomaly": 10,
    "liquidity_sweep": 10,
    "key_session": 5,
}

SCORING_CATEGORIES = {
    "A+": 85,
    "A": 70,
    "B": 55,
}
# Below 55 = NO OPERAR

# ========================
# TRADING PARAMS
# ========================
MIN_RR = 2.0          # Risk:Reward mínimo 1:2
TARGET_WIN_RATE = 0.66
MAX_TRADES_PER_DAY = 3

# ========================
# CONSENSUS THRESHOLDS
# ========================
CONSENSUS_MIN_PCT = 0.60       # 60% de variantes deben coincidir
CONSENSUS_MIN_AVG_SCORE = 70   # Score promedio mínimo para escalar a Opus

# ========================
# AGENT CONFIG
# ========================
MONITOR_INTERVAL_SECONDS = 300  # Escaneo cada 5 minutos
MAX_BUDGET_USD = 5.0            # Budget diario máximo para API de Opus

# ========================
# BINANCE CONFIG
# ========================
BINANCE_TESTNET = False  # True para usar testnet
KLINES_DEFAULT_LIMIT = 200
