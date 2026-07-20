# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BTC Bot v13 is an automated Bitcoin trading bot for **Delta Exchange India**. It enters trend/range trades on 30-minute BTC/USD candles using technical indicators (EMA, ADX, ATR, RSI, DMI) and manages exits via a trailing stop system that matches Pine Script behavior. The bot was 2-year backtested achieving ~$1,412/month average with 64% win rate.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run live bot
python main.py

# Run backtest (2-year dataset)
python backtest.py
python backtest_12m.py        # 12-month backtest with 0.1 BTC position

# Parameter sweeps & optimization
python optimize_bot.py                     # Sweep params for >$400/month target
python optimizer/optimize_and_backtest.py  # Comprehensive opt + backtest + report
python optimizer/radical_optimize.py       # Test fundamentally different approaches

# Analysis & results
python show_results.py                     # Display dashboard of backtest results
python optimized_results.py                # Summarize best config
python run_analysis_backtest.py            # Full analysis with charts
python run_opt_and_push.py                 # Optimize then push results to Telegram
python debug_trades.py                     # Debug specific trades

# Dashboard (Node.js version)
node server.js                             # Serves dashboard at http://localhost:3000

# Client Dashboard (FastAPI version)
uvicorn dashboard.main:app --port 8082     # Client management dashboard

# Deployment
bash scripts/deploy.sh                     # Deploy to VPS via rsync+ssh
bash scripts/status.sh                     # Check bot health on VPS

# Docker
docker build -t btc_bot_v13_bot .
docker run btc_bot_v13_bot

# Systemd
systemctl start btc_bot_v13               # Start as systemd service
systemctl status btc_bot_v13
journalctl -u btc_bot_v13 -f              # Live logs

# PM2
pm2 start ecosystem.config.js             # Start FastAPI dashboard via PM2
```

## Architecture

### Module Layout

```
D:\BTC_Bot_v13\
├── main.py                 # Entry point — asyncio event loop, wires all subsystems
├── config.py               # All tunable parameters (env-overridable via .env)
├── strategy_logic.py       # Core Pine parity logic — signals, indicators, risk math
├── execution.py            # Trade execution via ccxt (Delta Exchange)
├── backtest.py             # Backtesting engine (full 2-year CSV)
├── backtest_v2.py          # Alternate backtest implementation
├── backtest_12m.py         # 12-month focused backtest
├── optimize_bot.py         # Standalone parameter optimizer
│
├── strategy/
│   └── signal.py           # Thin re-export layer for evaluate() + SignalType
│
├── indicators/
│   └── engine.py           # Indicator computation (numba-accelerated, Pine-exact)
│
├── feed/
│   ├── ws_feed.py           # Binance WebSocket candle feed (primary entry data)
│   ├── binance_price_feed.py# Binance aggTrade price feed (for exit monitoring)
│   └── fills_feed.py        # Order fill tracking via WebSocket
│
├── monitor/
│   └── trail_loop.py        # Position monitoring & trailing stop logic (Pine-exact)
│
├── orders/
│   └── manager.py           # Delta Exchange order management (bracket architecture)
│
├── risk/
│   ├── calculator.py        # SL/TP level calculation, P&L math
│   └── lot_sizing.py        # Lot/BTC position size conversion
│
├── infra/
│   ├── telegram.py          # Telegram trade alerts + daily summaries
│   ├── telegram_controller.py# Telegram command interface (status/daily/stats)
│   ├── whatsapp.py          # WhatsApp notifications
│   ├── whatsapp_controller.py
│   ├── journal.py           # Persistent trade journal (SQLite + PostgreSQL)
│   ├── gsheet.py            # Google Sheets trade logging
│   └── heartbeat.py         # Health check file writer
│
├── dashboard/
│   ├── main.py              # FastAPI client management dashboard (port 8082)
│   ├── database.py          # Client DB schema (clients, invoices, audit logs)
│   ├── index.html           # Dashboard frontend
│   └── styles.css
│
├── optimizer/
│   ├── optimize_and_backtest.py  # Full pipeline: config → sweep → report
│   ├── radical_optimize.py       # Experimental parameter exploration
│   ├── changes_report.py         # Diff report between config versions
│   ├── generate_pdf.py           # PDF report generation
│   └── results/                  # Backtest reports + optimized configs
│
├── server.py               # (Legacy) HTTP server serving dashboard.html + /api/*
├── server.js               # Node.js dashboard server (port 3000, Telegram alerts)
├── dashboard.html          # (Legacy) Live trading dashboard HTML
├── dashboard_push.py       # (Legacy) State push to dashboard server
│
├── phase1/ through phase5/ # Development phases / experiment iterations
├── pine_strategy/          # Pine Script reference strategies
├── scripts/
│   ├── deploy.sh           # VPS deployment script (rsync + systemd)
│   └── status.sh           # VPS health check script
│
├── Dockerfile              # Container build with python:3.12-slim
├── ecosystem.config.js     # PM2 config for FastAPI dashboard
├── systemd/                # systemd service unit file
│
├── BTCUSDT_30m_2year.csv   # 2-year BTC/USDT 30m OHLCV data
├── fresh_btc_data.csv      # Fresh BTC data export
├── .env                    # API keys + environment overrides (gitignored)
├── requirements.txt        # Python dependencies
└── package.json            # Node.js deps (dashboard)
```

### Data Flow (Live Trading)

```
Binance WS (wss://stream.binance.com:9443/ws/btcusdt@aggTrade)
  │
  ▼
CandleFeed (ws_feed.py)         BinancePriceFeed (binance_price_feed.py)
  │  ┌─ 30m OHLCV for entry        │  ┌─ aggTrade ticks for exit monitoring
  ▼  ▼                              ▼  ▼
indicators/engine.py (compute)    TrailMonitor (trail_loop.py)
  │  ┌─ EMA/ADX/ATR/RSI/DMI         │  ┌─ Trail SL, TP, Breakeven, Max SL
  ▼  ▼                              ▼  ▼
strategy/signal.py (evaluate)    Execution (orders/manager.py)
  │  ┌─ Trend/Range entry signal      │  ┌─ Market exit close_position()
  ▼  ▼                              ▼  ▼
Risk (risk/calculator.py) ──── Delta Exchange API (ccxt async)
  │  ┌─ SL/TP level calculation
  ▼
Journal (infra/journal.py) ──→ SQLite / PostgreSQL + Google Sheets
  │
  ▼
Telegram (infra/telegram.py) ──→ Notifications (entry/exit/daily/error)
```

### Key Design Decisions

1. **Pine Parity** — Bot behavior is tuned to match Pine Script's `calc_on_every_tick=false` strategy execution model. Entry signals fire only at confirmed bar close. Stage upgrades and breakeven activation also happen only at bar close. Trail SL fires intrabar (matching Pine's `strategy.exit()` behavior).

2. **Bracket Architecture** — A bracket order is placed ONCE at entry with the initial SL (crash/disconnect protection). The bracket is NEVER amended — Python (TrailMonitor) owns all trail/BE/tighten logic and fires exits via market order on tick. This avoids the previous bug where frequent bracket amendments caused stale order IDs and API churn.

3. **Binance Price Feed** — Exit monitoring uses Binance aggTrade prices (same source as Pine's broker emulator) rather than Delta Exchange prices, which run ~100-150 pts lower. This prevents phantom SL/TP triggers from data-source divergence.

4. **Config Overrides** — `config.py` is the source of truth for all parameters. Every value can be overridden via `.env` environment variables. The file has extensive comments documenting the optimization history and Pine derivations.

5. **No ML** — This is a purely rules-based trading bot. There are no machine learning models, neural networks, or GPU-accelerated components. The `numba` dependency is optional and only speeds up indicator computation.

### Environment Variables (.env)

Key overrides available (see `config.py` for full list):
- `DELTA_API_KEY` / `DELTA_API_SECRET` — Exchange credentials
- `DELTA_TESTNET=true` — Testnet mode (default for safe testing)
- `SYMBOL=BTC/USD:USD` — Trading pair
- `POSITION_BTC_SIZE=0.01` — Position size in BTC
- `PAPER_TRADING=true` — Paper trading mode
- `DASHBOARD_PORT=10000` — Dashboard server port
- `DATABASE_URL` — PostgreSQL connection string (Supabase)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — Telegram alerts
- `BINANCE_SIGNAL_FEED=true` — Use Binance REST for indicators
- `FILTER_VOL_ENABLED=true` — Volume filter (must be true with Binance feed)

### Backtesting

The 2-year backtest CSV (`BTCUSDT_30m_2year.csv`) contains ~35,000 rows of 30m BTC/USDT OHLCV data. `backtest.py` runs the full 2-year simulation entering at bar close with simple SL/TP exit, matching the bot's optimized configuration. The optimizer tools sweep parameter combinations to find configurations achieving >$500/month profit targets.
