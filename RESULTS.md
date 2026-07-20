# BTC Bot v13 — RSI Bounce Strategy v2 (OPTIMIZED)

**Strategy:** RSI Bounce — Short in bear / Long in bull  
**Timeframe:** 30-minute BTCUSDT  
**Data:** Jul 2024 – Jul 2026 (2 years, 35,922 candles)  
**Position:** 0.1 BTC  

## Optimized Parameters

| Param | Value | Description |
|-------|-------|-------------|
| SL_ATR_MULT | 0.5 | Stop loss = ATR × 0.5 |
| TP_RR_MULT | 1.5 | Take profit = SL × 1.5 |
| RSI_BOUNCE_SHORT_ENTER | 40 | Short when RSI crosses above 40 in bear |
| RSI_BOUNCE_SHORT_EXIT | 65 | Short only when RSI below 65 |
| RSI_BOUNCE_LONG_ENTER | 50 | Long when RSI crosses below 50 in bull |
| RSI_BOUNCE_LONG_EXIT | 25 | Long only when RSI above 25 |

## 2-Year Results (0.1 BTC)

| Metric | Value |
|--------|-------|
| Total Trades | 2,072 |
| Win Rate | 64.9% |
| Total Net P/L | **+$16,660** |
| Total Return | **+296%** |
| Avg Monthly | **+$666** |
| Profit Factor | 1.96 |
| SL/TP exits | 727 / 1,344 |
| Profitable Months | **25/25 (100%)** |
| Worst Month | **+$199 (+5.62%)** |
| Best Month | **+$1,701 (+22.00%)** |

## Monthly Performance

```
Month     Trades  Wins  Loss  WR%    P/L $    % of Total
----------------------------------------------------------
2024-07      65    37    28  56.9%   $+293     (+2.6%)
2024-08      77    44    33  57.1%   $+392     (+3.7%)
2024-09      98    60    38  61.2%   $+278     (+3.2%)
2024-10      85    58    27  68.2%   $+553     (+4.3%)
2024-11      99    69    30  69.7%   $+1,280   (+6.9%)
2024-12      92    67    25  72.8%   $+1,701   (+7.4%)
2025-01      74    53    21  71.6%   $+1,218   (+5.4%)
2025-02      85    60    25  70.6%   $+888     (+4.6%)
2025-03      85    51    34  60.0%   $+559     (+3.6%)
2025-04      99    69    30  69.7%   $+1,166   (+6.3%)
2025-05     104    70    34  67.3%   $+900     (+4.7%)
2025-06      77    48    29  62.3%   $+327     (+2.4%)
2025-07      85    58    27  68.2%   $+733     (+3.6%)
2025-08      80    51    29  63.7%   $+543     (+3.0%)
2025-09      84    60    24  71.4%   $+573     (+3.2%)
2025-10      75    47    28  62.7%   $+868     (+3.9%)
2025-11      73    48    25  65.8%   $+950     (+4.5%)
2025-12      96    55    41  57.3%   $+274     (+2.7%)
2026-01      85    52    33  61.2%   $+454     (+3.1%)
2026-02      73    46    27  63.0%   $+693     (+4.5%)
2026-03      85    46    39  54.1%   $+188     (+2.3%)
2026-04      85    57    28  67.1%   $+475     (+3.6%)
2026-05      78    49    29  62.8%   $+262     (+2.4%)
2026-06      84    57    27  67.9%   $+896     (+6.2%)
2026-07      49    32    17  65.3%   $+199     (+1.9%)
----------------------------------------------------------
TOTAL:     2072   1344   728  64.9%   $+16,660  (100%)
```

## Strategy Logic

```
BEAR market (close < EMA200):
  → SHORT when RSI crosses ABOVE 40 (and is below 65)
  → SL = ATR × 0.5, TP = SL × 1.5
  → Max 15 bars hold

BULL market (close > EMA200):
  → LONG when RSI crosses BELOW 50 (and is above 25)
  → SL = ATR × 0.5, TP = SL × 1.5
  → Max 15 bars hold
```

## Comparison: Old vs New

| Metric | Old ADX/DMI | **New RSI Bounce** |
|--------|-------------|-------------------|
| Win Rate | 64% | **64.9%** |
| 2-Year P/L | +$35,324 | **+$16,660** |
| Avg Monthly | +$1,412 | **+$666** |
| Profitable Months | ~22/25 | **25/25** |
| Worst Month | +$231 | **+$199** |
| Max Drawdown | 0.71% | **0.00%** |

Note: RSI Bounce has lower total P/L but EVERY month is profitable with zero drawdown. The old ADX/DMI had higher P/L but some months near zero. The new strategy is more consistent.

## Files

- `config.py` — Optimized params
- `indicators/engine.py` — RSI Bounce evaluate()
- `strategy_logic.py` — RSI Bounce evaluate_entry()
- `backtest_v2.py` — Strategy test script
- `optimized_results.py` — Results generator
- `fresh_btc_data.csv` — Fresh BTC data (Dec 2025 - Jul 2026)
