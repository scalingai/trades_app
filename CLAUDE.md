# War Room — Sistema de Trading Algorítmico

## Qué es este proyecto
Sistema de trading algorítmico para crypto (Binance) con 4 estrategias corriendo 261 variantes de parámetros en paralelo. Claude Opus 4.6 actúa como juez final cuando hay consenso fuerte entre las variantes.

## Estado actual
- Infraestructura de datos: COMPLETA (tools/)
- 4 estrategias con grids de parámetros: COMPLETAS (strategies/)
- Motor orquestador: COMPLETO (engine.py)
- Tracker + auto-calibración: COMPLETO (tracker/)
- Agente CLI: COMPLETO (agent.py)
- Dashboard visual (War Room UI): PENDIENTE
- Integración con Claude Agent SDK para Opus como juez: PENDIENTE
- Control de TradingView via Playwright (screenshots de charts): PENDIENTE

## Arquitectura

```
trades_app/
├── trades_app.py              # App Streamlit original (registro manual de trades)
├── agent.py                   # CLI entry point (interactive, --scan, --monitor, --performance)
├── engine.py                  # Motor: collect_snapshot() → run_all_strategies() → calculate_consensus()
├── config.py                  # Watchlist, timeframes, scoring weights, thresholds
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
├── tracker/
│   ├── performance.py         # Win rate, RR, P&L por variante
│   └── calibrator.py          # Auto-calibración de pesos basada en correlación
└── data/                      # CSVs de propuestas y resultados
```

## Flujo de ejecución
1. **DATOS**: Se recolecta un snapshot con todos los datos de mercado para un símbolo (1 vez por ciclo)
2. **ENGINE**: Las 261 variantes evalúan el snapshot en código puro (sin costo API)
3. **CONSENSO**: Si >60% de variantes coinciden en dirección con score promedio >70 → escalar
4. **OPUS** (pendiente): Claude analiza datos duros + screenshot visual del chart → veredicto final
5. **TRACKING**: Cada variante registra si acertó o no → auto-calibración de pesos

## Cómo correr
```bash
pip install -r requirements.txt
cp .env.example .env  # Configurar API keys
python agent.py              # Modo interactivo
python agent.py --scan       # Escaneo único
python agent.py --monitor    # Loop cada 5 min
python agent.py --performance # Stats
```

## Scoring system (100 puntos, pesos auto-calibrables)
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

Categorías: A+ (≥85), A (≥70), B (≥55), NO OPERAR (<55)

## Próximos pasos
1. Probar con datos reales de Binance (necesita conexión a internet sin proxy)
2. Integrar Claude Agent SDK para que Opus sea el juez final
3. Agregar control de TradingView via Playwright (screenshots de charts)
4. Construir dashboard visual (War Room) en Streamlit con charts embebidos
5. Backtesting: correr estrategias contra datos históricos para validar pesos

## Contexto del trader
- Experiencia en ICT (Inner Circle Trader)
- Foco: order flow, liquidaciones, bookmap, horarios clave, tick-by-tick
- Estilo: intradía corto plazo, pocos trades, RR 1:2 a 1:5, win rate target 66%+
- Exchange: Binance (cuenta existente)
- TradingView: plan gratuito
