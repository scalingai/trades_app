# War Room — Sistema de Trading Algorítmico

## Qué es este proyecto
Sistema de trading algorítmico para crypto (Binance) con 4 estrategias corriendo 261 variantes de parámetros en paralelo. Claude Opus 4.6 actúa como juez final cuando hay consenso fuerte. Incluye capa macro automática con calendario de eventos, polling programado, conjeturas con probabilidades, y dashboard visual.

## Estado actual
- Infraestructura de datos: COMPLETA (tools/)
- 4 estrategias con grids de parámetros: COMPLETAS (strategies/)
- Motor orquestador: COMPLETO (engine.py)
- Tracker + auto-calibración: COMPLETO (tracker/)
- Agente CLI: COMPLETO (agent.py)
- Capa macro automática: PENDIENTE (macro/)
- Dashboard visual (War Room UI): PENDIENTE (dashboard.py)
- Scheduler de cron jobs: PENDIENTE (scheduler.py)
- Integración con Claude Agent SDK para Opus como juez: PENDIENTE
- Control de TradingView via Playwright (screenshots de charts): PENDIENTE

## Arquitectura

```
trades_app/
├── trades_app.py              # App Streamlit original (registro manual de trades)
├── agent.py                   # CLI entry point (interactive, --scan, --monitor, --performance)
├── engine.py                  # Motor: collect_snapshot() → run_all_strategies() → calculate_consensus()
├── config.py                  # Watchlist, timeframes, scoring weights, thresholds
├── scheduler.py               # PENDIENTE — Orquestador de cron jobs automáticos
├── dashboard.py               # PENDIENTE — War Room Streamlit con todos los paneles
├── tools/                     # Data providers
│   ├── market_data.py         # Binance: precios, klines OHLCV
│   ├── order_flow.py          # Binance: order book, delta volume, funding, absorción
│   ├── liquidations.py        # Coinglass: liquidaciones, OI, long/short ratio
│   ├── smart_money.py         # ICT: FVG, Order Blocks, Liquidity Sweeps, BOS/CHoCH
│   ├── volume_profile.py      # VPOC, Value Area (numpy)
│   └── technical.py           # RSI, EMA, VWAP, divergencias, TradingView TA
├── strategies/                # 4 estrategias × N variantes = 261 total
│   ├── base.py                # Strategy base class + Signal dataclass
│   ├── ict_pure.py            # ICT: FVG + OB + sweeps + BOS (72 variantes)
│   ├── order_flow_strategy.py # Order flow: delta + absorción + book (81 variantes)
│   ├── volume_profile_strategy.py # Vol profile: VPOC + VA + anomalías (81 variantes)
│   └── hybrid.py              # Híbrida: scoring 100pts, 3 weight sets (27 variantes)
├── macro/                     # PENDIENTE — Capa macro automática
│   ├── calendar.py            # Calendario económico + crypto events (Investing.com, CoinGlass)
│   ├── poller.py              # Polling programado pre/post evento (web search)
│   ├── context.py             # Contexto semanal/diario generado por Opus
│   └── conjectures.py         # Árbol de conjeturas con probabilidades actualizables
├── tracker/
│   ├── performance.py         # Win rate, RR, P&L por variante
│   └── calibrator.py          # Auto-calibración de pesos basada en correlación
└── data/                      # CSVs de propuestas y resultados
```

## Flujo de ejecución (3 capas)

### Capa 1: Motor cuantitativo (código puro, cada 5 min)
1. **DATOS**: Se recolecta un snapshot con todos los datos de mercado (1 vez por ciclo)
2. **ENGINE**: Las 261 variantes evalúan el snapshot (sin costo API)
3. **CONSENSO**: Si >60% coinciden con score >70 → escalar a Opus

### Capa 2: Macro automática (Opus, programado)
1. **Domingo 20:00 UTC**: Opus genera contexto semanal (bias, niveles, narrativa)
2. **Pre-evento (5 min antes)**: Polling automático de expectativas
3. **Post-evento (1 min después)**: Polling del dato real → actualiza bias
4. **Cada 4h**: Routine poll (Fear & Greed, funding, OI)
5. **Conjeturas**: Opus genera escenarios ("si BTC pierde 66k → flush a 63k") con probabilidades que se actualizan en tiempo real

### Capa 3: Juez final (Opus, solo cuando hay señal)
1. Recibe: snapshot + consenso + contexto macro + conjeturas activas
2. Toma screenshot del chart de TradingView
3. Combina análisis visual + datos duros + macro
4. Veredicto: TRADE o NO TRADE con entry/stop/target/RR
5. Espera aprobación del trader

## Dashboard War Room (PENDIENTE)
```
┌────────────┬──────────────────────────┬─────────────────────┐
│ WATCHLIST   │ CHART EMBEBIDO           │ CONJETURAS          │
│ BTC A+ ▲   │ (lightweight-charts)     │ A: Flush 63k  40%  │
│ ETH B  —   │ + overlays FVG, OB       │ B: Break 69k  25%  │
│ SOL A  ▼   │                          │ C: Range      35%  │
├────────────┤                          ├─────────────────────│
│ MACRO      │                          │ CALENDARIO          │
│ Bias: BEAR │──────────────────────────│ ● CPI  Mar12 12:30 │
│ F&G: 78    │ OPUS ANALYSIS            │ ● FOMC Mar13 18:00 │
│ Fund: +0.03│ Score 87 → A+            │ ● ETH  Mar14 00:00 │
├────────────┤ Entry/Stop/Target        ├─────────────────────│
│ ORDER FLOW │ [APROBAR] [RECHAZAR]     │ PERFORMANCE         │
│ VOL PROFILE│                          │ WR: 72% | RR: 2.8  │
└────────────┴──────────────────────────┴─────────────────────┘
```

## Cómo correr
```bash
pip install -r requirements.txt
cp .env.example .env  # Configurar API keys

# Motor + CLI
python agent.py              # Modo interactivo
python agent.py --scan       # Escaneo único
python agent.py --monitor    # Loop cada 5 min
python agent.py --performance # Stats

# Scheduler (background) — PENDIENTE
python scheduler.py          # Cron jobs automáticos (macro polls, contexto)

# Dashboard — PENDIENTE
streamlit run dashboard.py   # War Room visual
```

## Scoring system (100 puntos, pesos auto-calibrables)
Los pesos son hipótesis iniciales que se ajustan automáticamente con datos reales de performance (tracker/calibrator.py). Después de 30+ trades, el sistema sugiere nuevos pesos basados en correlación con wins.

| Factor | Peso | Fuente |
|---|---|---|
| Liquidaciones clustered | 15 | Coinglass |
| FVG / Order Block en zona | 15 | smart_money.py |
| Overextension (vs EMA20) | 15 | technical.py |
| Delta volume (absorción) | 10 | order_flow.py |
| Divergencia RSI | 10 | technical.py |
| Rechazo VWAP / VPOC | 10 | volume_profile.py |
| Volumen anómalo (>2x avg) | 10 | market_data.py |
| Liquidity sweep reciente | 10 | smart_money.py |
| Horario clave (session) | 5 | config.py |
| **Multiplicador macro** | ±15% | macro/context.py |

Categorías: A+ (≥85), A (≥70), B (≥55), NO OPERAR (<55)

## Conjeturas (macro/conjectures.py — PENDIENTE)
Opus genera 3-5 conjeturas por semana. Cada una tiene:
- Condición de activación ("BTC close < 66000")
- Probabilidad actualizable (40% → 55% → triggered)
- Bias direccional (afecta scoring)
- Target e invalidación
- Status: active | triggered | invalidated

Se evalúan contra datos reales cada ciclo del engine.

## Próximos pasos (en orden de prioridad)
1. **Probar motor existente** con datos reales de Binance desde la PC del trader
2. **Implementar macro/calendar.py** — calendario de eventos con horarios
3. **Implementar macro/poller.py** — polling pre/post evento
4. **Implementar macro/context.py** — contexto semanal Opus
5. **Implementar macro/conjectures.py** — árbol de conjeturas
6. **Implementar scheduler.py** — cron jobs automáticos
7. **Modificar engine.py** — inyectar macro_context al snapshot
8. **Implementar dashboard.py** — War Room Streamlit
9. **Integrar Claude Agent SDK** — Opus como juez final con screenshots
10. **Backtesting** — validar estrategias contra datos históricos

## Contexto del trader
- Experiencia en ICT (Inner Circle Trader) — años operando manual sin consistencia
- Foco: order flow, liquidaciones, bookmap, horarios clave, tick-by-tick
- Estilo: intradía corto plazo, pocos trades semanales, calidad sobre cantidad
- Objetivo: RR 1:2 a 1:5, win rate 66%+
- Exchange: Binance (cuenta existente)
- TradingView: plan gratuito
- Filosofía: seguir el sistema mecánicamente, sin sesgo emocional
- Opus como analista macro + juez final, no como bot autónomo
