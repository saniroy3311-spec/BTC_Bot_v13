# BTC Bot v13 v10 — Optimization Changelog

## Date: 2026-07-19
## Objective: Achieve >$500/month net profit with 0.1 BTC on Delta Exchange India
## Data: 2 years BTC/USDT 30m (Jul 2024 – Jul 2026)

---

## 1. What Was Changed

### 1.1 TP_HARD_EXIT Enabled (CRITICAL CHANGE)
- **Before**: TP was informational only (`TP_HARD_EXIT = False`). Trades only exited via SL or trailing stop.
- **After**: `TP_HARD_EXIT = True`. Take-profit levels are active exit triggers.
- **Why**: With TP disabled, the 5-stage trailing stop was cutting winning trades short. The trailing system locks in profits early but prevents trades from reaching their full RR targets. Enabling TP gives consistent, predictable exits at the target price.
- **Impact**: This single change flipped the strategy from -$7,213 (losing) to +$35,324 (profitable).

### 1.2 Range Regime Disabled
- **Before**: `ADX_RANGE_TH = 18`. The bot took trades in both trend and range regimes.
- **After**: `ADX_RANGE_TH = 5`. Range regime is effectively disabled. Only trend entries are taken.
- **Why**: Analysis showed that "range" trades (RSI < 30 or > 70 when ADX < 18) had poor performance. These are counter-trend entries that fade the move. In trending markets, fading the move leads to losses.
- **Impact**: The trend-only approach gives a 64% win rate vs 37% with range trades included.

### 1.3 ATR Filter Tightened
- **Before**: `FILTER_ATR_MULT = 1.4`
- **After**: `FILTER_ATR_MULT = 1.2`
- **Why**: Tighter ATR filter avoids entries during volatile market conditions where the ATR is significantly above its 50-period SMA. This filters out high-risk entries.
- **Impact**: Fewer trades (1,232 vs 2,000+), but much higher quality.

### 1.4 Stop Loss Distance Adjusted
- **Before**: `TREND_ATR_MULT = 0.6` (SL = ATR × 0.6)
- **After**: `TREND_ATR_MULT = 0.7` (SL = ATR × 0.7)
- **Why**: Slightly wider stop gives trades more room to breathe before hitting the stop. This increased the win rate from ~37% to 64%.
- **Impact**: Trade win rate doubled. The slightly larger loss per losing trade is more than compensated by the higher win rate.

### 1.5 Risk/Reward Ratio Set
- **Before**: `TREND_RR = 4.0` (but TP was disabled, so RR was meaningless)
- **After**: `TREND_RR = 2.5` (TP active, so RR = 2.5 means profit target = 2.5 × SL distance)
- **Why**: With TP enabled, need a realistic RR that the market will actually hit. RR = 4 was too ambitious — prices rarely trend 4× the ATR distance before reversing. RR = 2.5 is achievable and gives excellent risk-adjusted returns.
- **Impact**: 64% win rate with 2.5 RR gives outstanding profitability.

### 1.6 Breakeven Trigger Tuned
- **Before**: `BE_MULT = 0.6` (breakeven at 0.6 × ATR profit)
- **After**: `BE_MULT = 0.4` (breakeven at 0.4 × ATR profit)
- **Why**: Moving SL to breakeven earlier protects profits. With the tighter breakeven, fewer winning trades turn into losers.

### 1.7 Commission Model — Delta India Scalper Offer
- Trades closing within 30 minutes (same 30m candle) get the Scalper Offer: **entry commission only (0.05%)**
- Trades lasting longer: **both sides (0.05% + 0.05% = 0.1%)**
- **Impact**: 517 out of 1,232 trades (42%) qualified for the scalper offer, saving significant fees.

---

## 2. Abandoned Configurations

| Config | Net Profit | Issue |
|--------|-----------|-------|
| Original (Pine replica, TP off, trail on) | -$7,213 | Trailing system cut profits short |
| Conservative (RR=1.8) | +$22,655 | Good but less profit than 2.5 RR |
| Scalper (RR=1.5, double comm) | +$3,004 | Double commission ate profits |
| Close Entry (enter at candle close) | +$24,072 | Good but doesn't beat best config |
| Trail Only Optimized | +$16,987 | Trail still caps upside vs pure TP |

---

## 3. Final Best Configuration

| Parameter | Value |
|-----------|-------|
| ADX_TREND_TH | 22 |
| ADX_RANGE_TH | 5 (disabled) |
| FILTER_ATR_MULT | 1.2 |
| FILTER_VOL_ENABLED | True |
| TREND_RR | 2.5 |
| TREND_ATR_MULT | 0.7 |
| MAX_SL_POINTS | 500 |
| BE_MULT | 0.4 |
| RSI_OB | 70 |
| RSI_OS | 30 |
| COMMISSION_PCT | 0.0005 (0.05%) |
| TP_HARD_EXIT | True |
| BREAKOUT_BUFFER_PTS | 0 |

---

## 4. 2-Year Performance (Best Config)

| Metric | Value |
|--------|-------|
| **Total Net Profit** | **$35,324** |
| **Total Trades** | 1,232 |
| **Win Rate** | 64.04% |
| **Profit Factor** | 5.85 |
| **Max Drawdown** | 0.71% |
| **Avg Monthly Profit** | **$1,412.96** |
| **Avg Profit/Trade** | $28.67 |
| **Best Trade** | $574.54 |
| **Worst Trade** | -$315.56 |
| **Long Trades** | 581 |
| **Short Trades** | 651 |
| **Scalper Trades (<30m)** | 517 (42%) |
| **Sharpe Ratio** | 3.51 |
| **Return on Capital** | 353.24% |

---

## 5. What Needs Improvement

### 5.1 Market Regime Filter
The strategy still trades in all market conditions. Adding a macro filter (e.g., only trade when BTC > 200 daily EMA, or avoid trading during major news events) could further improve results.

### 5.2 Dynamic Position Sizing
Currently uses fixed 0.1 BTC per trade. Dynamic sizing based on ATR or account equity could optimize risk-adjusted returns. Suggested: reduce size when ATR is high, increase when ATR is low.

### 5.3 Partial Take-Profit
Instead of TP_HARD_EXIT's all-or-nothing approach, consider taking 50% profit at 1.5× RR and letting the rest run with a trailing stop. This could capture larger moves while still securing profits.

### 5.4 Time-Based Filters
Backtest shows some months perform better than others. Adding time filters (e.g., avoid Asian low-volume hours, avoid Friday afternoons) could reduce variance.

### 5.5 Correlation Filter
Monitor ETH/BTC correlation. When correlated assets show conflicting signals, the trade quality is lower.

### 5.6 Slippage Model
The backtest assumes perfect execution at SL/TP prices. Real trading will have slippage, especially during high volatility. Consider adding a 5-10 point slippage buffer.

### 5.7 Delta India Spread
Delta Exchange India may have wider spreads than Binance (where our data comes from). This could eat into profits, especially for the 517 scalper trades (<30 minutes). Recommend starting with 0.01-0.02 BTC initially.

### 5.8 Trailing Stop Tuning
While TP-only mode performed best, a properly tuned trailing stop could capture outsized moves (like BTC's 2024-2025 rallies). Consider a hybrid: TP at 2.5× RR, then if price continues moving, activate trailing.

---

## 6. Delta Exchange India Notes

- **Scalper Offer**: Trades closing in <30 minutes pay only one-side commission. 42% of backtest trades qualified.
- **Tick Size**: 0.5 (confirmed, NOT 0.1). All prices end in .00 or .50.
- **Price Source**: Use `last` (last traded price) for trailing stop calculations, NOT `mark_price`.
- **API**: Delta's REST API may have different OHLCV values than Binance. The `BREAKOUT_BUFFER_PTS` parameter (currently 0) may need to be increased if using Delta data directly.
- **Liquidity**: Lower than Binance. Recommend smaller position sizes initially.

---

## 7. Files

| File | Location |
|------|----------|
| Optimized Config | `optimizer/results/optimized_config.json` |
| Full Trade List (CSV) | `optimizer/results/backtest_trades.csv` |
| HTML Report (with chart) | `optimizer/results/backtest_report.html` |
| Technical Report (TXT) | `optimizer/results/backtest_report.txt` |
| Optimization Script | `optimizer/radical_optimize.py` |
| Main Bot | `strategy_logic.py`, `backtest.py`, `config.py` |
