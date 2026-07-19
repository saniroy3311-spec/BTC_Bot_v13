# BTC Bot v13 — Automated Bitcoin Trading Bot

**Exchange:** Delta Exchange India  
**Timeframe:** 30-minute candles  
**Position Size:** 0.01 BTC (start) → 0.1 BTC (full)  
**Target:** >$500/month net profit  
**Achieved:** $1,412/month average (2-year backtest: Jul 2024 – Jul 2026)

---

## Overview

BTC Bot v13 is an automated Bitcoin trading bot optimized for **Delta Exchange India**. It uses technical indicators (EMA, ADX, ATR, RSI, DMI) to identify trend entries on 30-minute BTC/USD candles and executes trades with a fixed stop loss and take profit.

The bot was extensively backtested over 2 years of data and optimized for real-life trading conditions, including Delta India's Scalper Offer commission structure.

## Results (2-Year Backtest)

| Metric | Value |
|--------|-------|
| **Total Net Profit** | **+$35,324** |
| **Average Monthly** | **+$1,412** |
| **Win Rate** | 64% |
| **Profit Factor** | 5.85 |
| **Max Drawdown** | 0.71% |
| **Total Trades** | 1,232 |
| **Scalper Trades (<30m)** | 517 (42%) |

## Key Features

- **Trend-Only Trading** — Only trades with the trend, no counter-trend range trades
- **Take Profit Enabled** — Trades close at a realistic 2.5x risk target
- **Delta India Optimized** — Scalper Offer (one-side fee for trades under 30min)
- **5-Stage Risk Management** — Initial SL, breakeven, and emergency Max SL
- **Telegram / WhatsApp Alerts** — Real-time trade notifications
- **Binance Signal Feed** — Uses Binance OHLCV for accurate indicator calculation

## File Structure

```
D:\BTC Bot v13\
├── config.py           # Main configuration (optimized for Delta India)
├── .env                # Environment overrides (API keys, settings)
├── strategy_logic.py   # Core strategy logic (indicators, signals, risk)
├── backtest.py         # Backtesting engine
├── main.py             # Main bot loop (live trading)
├── execution.py        # Trade execution module
├── monitor/
│   └── trail_loop.py   # Position monitoring & trailing stop
├── feed/
│   ├── binance_price_feed.py  # Binance OHLCV + tick data
│   ├── ws_feed.py             # WebSocket feed handler
│   └── fills_feed.py          # Order fill tracking
├── orders/
│   └── manager.py      # Order management (Delta Exchange API)
├── risk/
│   ├── calculator.py   # Risk & position sizing
│   └── lot_sizing.py   # Lot size conversion
├── optimizer/
│   └── results/        # Backtest reports & optimized config
├── dashboard/          # Web dashboard
├── infra/              # Telegram, WhatsApp, journal, heartbeat
└── CHANGELOG_OPTIMIZATION.md  # Full changelog
```

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API Keys
Edit `.env` and set your Delta Exchange API credentials:
```
DELTA_API_KEY=your_key
DELTA_API_SECRET=your_secret
```

### 3. Start with Testnet
Default is `DELTA_TESTNET=true` in `.env` — use this for at least 1 week.

### 4. Run the Bot
```bash
python main.py
```

### 5. Monitor
- Check Telegram for trade alerts
- Open the dashboard: `http://localhost:5000`

## Safety Recommendations

1. **Start with 0.01 BTC** — Do NOT use 0.1 BTC immediately
2. **Testnet first** — Run on Delta testnet for at least 1 week
3. **Monitor daily** — Check the bot every day for the first month
4. **Scale gradually** — Increase position size only after consistent profitability
5. **Have a backup plan** — Know how to manually close trades if needed

## Risk Warning

Trading cryptocurrencies carries substantial risk. This bot is provided for educational purposes. Past performance does not guarantee future results. Never trade with money you cannot afford to lose.

---

**BTC Bot v13** — Built for Delta Exchange India  
Generated: July 2026
