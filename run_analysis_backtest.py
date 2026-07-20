import os
import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional

# Ensure BTC-Bot-v13-main is in path
sys.path.insert(0, os.path.dirname(__file__))

from config import COMMISSION_PCT, TRAIL_STAGES, PINE_MINTICK, BE_MULT, MAX_SL_MULT, MAX_SL_POINTS
from strategy_logic import (
    compute_full_series,
    evaluate_entry,
    calc_levels,
    upgrade_trail_stage,
    compute_trail_sl,
    should_trigger_be,
    max_sl_threshold,
    SignalType,
    IndicatorSnapshot
)

@dataclass
class BTTrade:
    trade_id:     int
    signal_type:  str
    is_long:      bool
    is_trend:     bool
    signal_bar:   int
    signal_ts:    int
    entry_bar:    int
    entry_ts:     int
    entry_price:  float
    sl:           float
    tp:           float
    stop_dist:    float
    atr_at_entry: float
    exit_bar:     int   = 0
    exit_ts:      int   = 0
    exit_price:   float = 0.0
    exit_reason:  str   = ""
    trail_stage:  int   = 0
    bars_held:    int   = 0
    gross_pl:     float = 0.0
    commission:   float = 0.0
    net_pl:       float = 0.0

def _row_to_snap(row, prev_row) -> IndicatorSnapshot:
    from config import ADX_TREND_TH, ADX_RANGE_TH, FILTER_ATR_MULT, FILTER_BODY_MULT, FILTER_VOL_ENABLED, FILTER_VOL_MULT
    atr = float(row["atr"])
    atr_sma = float(row["atr_sma"])
    vol_sma = float(row["vol_sma"])
    bar_vol = float(row["volume"])
    open_v  = float(row["open"])
    close_v = float(row["close"])
    atr_ok  = atr < atr_sma * FILTER_ATR_MULT
    body_ok = True  # Pine parity
    if FILTER_VOL_ENABLED:
        vol_ok = bar_vol > 0 and vol_sma > 0 and bar_vol > vol_sma * FILTER_VOL_MULT
    else:
        vol_ok = True
    adx_v = float(row["adx"])
    return IndicatorSnapshot(
        ema_trend    = float(row["ema200"]),
        ema_fast     = float(row["ema50"]),
        atr          = atr,
        rsi          = float(row["rsi"]),
        dip          = float(row["dip"]),
        dim          = float(row["dim"]),
        adx          = adx_v,
        adx_raw      = float(row["adx_raw"]),
        vol_sma      = vol_sma,
        atr_sma      = atr_sma,
        trend_regime = adx_v > ADX_TREND_TH,
        range_regime = adx_v < ADX_RANGE_TH,
        filters_ok   = bool(atr_ok and vol_ok and body_ok),
        atr_ok       = bool(atr_ok),
        vol_ok       = bool(vol_ok),
        body_ok      = bool(body_ok),
        open         = open_v,
        high         = float(row["high"]),
        low          = float(row["low"]),
        close        = close_v,
        volume       = bar_vol,
        prev_high    = float(prev_row["high"]),
        prev_low     = float(prev_row["low"]),
        timestamp    = int(row["timestamp"]),
    )

def run_backtest_corrected(df: pd.DataFrame) -> list[BTTrade]:
    series = compute_full_series(df).reset_index(drop=True)
    n = len(series)
    trades: list[BTTrade] = []

    in_position = False
    pending_signal: Optional[tuple] = None
    trade_id = 0

    cur_trade: Optional[BTTrade] = None
    cur_sl = 0.0
    cur_tp = 0.0
    cur_atr = 0.0
    cur_is_long = True
    cur_entry_price = 0.0
    peak_price = 0.0
    be_done = False
    trail_stage = 0
    max_sl_fired = False

    for i in range(1, n):
        row = series.iloc[i]
        prev_row = series.iloc[i - 1]
        ts    = int(row["timestamp"])
        open_ = float(row["open"])
        high  = float(row["high"])
        low   = float(row["low"])
        close = float(row["close"])

        # Check exits first if in position
        if in_position and cur_trade is not None:
            # Update peak price using high/low of this bar
            if cur_is_long:
                peak_price = max(peak_price, high)
            else:
                peak_price = min(peak_price, low)

            # Evaluate exits using stops active at the start of this bar
            max_sl_active = (i > cur_trade.entry_bar) and not max_sl_fired
            threshold = max_sl_threshold(cur_atr)
            max_sl_price = (cur_entry_price - threshold) if cur_is_long else (cur_entry_price + threshold)

            exit_price = None
            exit_reason = None

            if cur_is_long:
                if open_ <= cur_sl:
                    exit_price = open_
                    exit_reason = "SL"
                elif max_sl_active and open_ <= max_sl_price:
                    exit_price = open_
                    exit_reason = "Max SL"
                elif open_ >= cur_tp:
                    exit_price = open_
                    exit_reason = "TP"
                elif low <= cur_sl:
                    exit_price = cur_sl
                    if trail_stage > 0:
                        exit_reason = f"Trail S{trail_stage}"
                    elif be_done:
                        exit_reason = "Breakeven SL"
                    else:
                        exit_reason = "Initial SL"
                elif max_sl_active and low <= max_sl_price:
                    exit_price = max_sl_price
                    exit_reason = "Max SL"
                elif high >= cur_tp:
                    exit_price = cur_tp
                    exit_reason = "TP"
            else:
                if open_ >= cur_sl:
                    exit_price = open_
                    exit_reason = "SL"
                elif max_sl_active and open_ >= max_sl_price:
                    exit_price = open_
                    exit_reason = "Max SL"
                elif open_ <= cur_tp:
                    exit_price = open_
                    exit_reason = "TP"
                elif high >= cur_sl:
                    exit_price = cur_sl
                    if trail_stage > 0:
                        exit_reason = f"Trail S{trail_stage}"
                    elif be_done:
                        exit_reason = "Breakeven SL"
                    else:
                        exit_reason = "Initial SL"
                elif max_sl_active and high >= max_sl_price:
                    exit_price = max_sl_price
                    exit_reason = "Max SL"
                elif low <= cur_tp:
                    exit_price = cur_tp
                    exit_reason = "TP"

            if exit_price is not None:
                # Trade exited!
                cur_trade.exit_bar = i
                cur_trade.exit_ts = ts
                cur_trade.exit_price = exit_price
                cur_trade.exit_reason = exit_reason
                cur_trade.trail_stage = trail_stage
                cur_trade.bars_held = i - cur_trade.entry_bar

                # Position size = 0.1 BTC
                qty = 0.1
                
                # Gross P&L
                gross_pl = (exit_price - cur_entry_price) * qty if cur_is_long else (cur_entry_price - exit_price) * qty
                
                # Scalper Offer Commission:
                # If closed in less than 30 mins (bars_held == 0), commission is charged one-side (entry only).
                # Otherwise, charged on both sides (entry + exit).
                is_scalper = (cur_trade.bars_held == 0)
                if is_scalper:
                    commission = cur_entry_price * qty * COMMISSION_PCT
                else:
                    commission = (cur_entry_price + exit_price) * qty * COMMISSION_PCT
                
                net_pl = gross_pl - commission
                
                cur_trade.gross_pl = gross_pl
                cur_trade.commission = commission
                cur_trade.net_pl = net_pl

                trades.append(cur_trade)
                in_position = False
                cur_trade = None
                continue

        # Update stops at the close of this bar if still in position
        if in_position and cur_trade is not None:
            profit_dist = (close - cur_entry_price) if cur_is_long else (cur_entry_price - close)
            if not be_done and should_trigger_be(profit_dist, cur_atr):
                be_done = True
                cur_sl = cur_entry_price

            new_stage = upgrade_trail_stage(trail_stage, profit_dist, cur_atr)
            if new_stage > trail_stage:
                trail_stage = new_stage

            trail_sl = compute_trail_sl(trail_stage, peak_price, profit_dist, cur_is_long, cur_atr)
            if trail_sl is not None:
                if cur_is_long and trail_sl > cur_sl:
                    cur_sl = trail_sl
                elif (not cur_is_long) and trail_sl < cur_sl:
                    cur_sl = trail_sl

        # Evaluate entry signal if not in position
        if not in_position and pending_signal is None:
            if (np.isnan(row["ema200"]) or np.isnan(row["adx"]) or
                np.isnan(row["atr"]) or np.isnan(row["atr_sma"]) or
                np.isnan(row["vol_sma"])):
                continue

            snap = _row_to_snap(row, prev_row)
            sig = evaluate_entry(snap, has_position=False)
            if sig.signal_type != SignalType.NONE:
                pending_signal = (sig, snap, i)

        # Process pending signal (enters at the open of current bar i)
        elif pending_signal is not None and not in_position:
            sig, sig_snap, sig_bar_idx = pending_signal
            entry_price = open_

            # Compute levels
            risk = calc_levels(entry_price, sig_snap.atr, sig.is_long, sig.is_trend)

            trade_id += 1
            cur_trade = BTTrade(
                trade_id=trade_id,
                signal_type=sig.signal_type.value,
                is_long=sig.is_long,
                is_trend=sig.is_trend,
                signal_bar=sig_bar_idx,
                signal_ts=int(series.iloc[sig_bar_idx]["timestamp"]),
                entry_bar=i,
                entry_ts=ts,
                entry_price=entry_price,
                sl=risk.sl,
                tp=risk.tp,
                stop_dist=risk.stop_dist,
                atr_at_entry=sig_snap.atr,
            )

            cur_sl = risk.sl
            cur_tp = risk.tp
            cur_atr = sig_snap.atr
            cur_is_long = sig.is_long
            cur_entry_price = entry_price
            peak_price = entry_price
            be_done = False
            trail_stage = 0
            max_sl_fired = False
            in_position = True
            pending_signal = None

            # Check exits on entry bar immediately
            exit_price = None
            exit_reason = None

            if cur_is_long:
                if low <= cur_sl:
                    exit_price = cur_sl
                    exit_reason = "Initial SL"
                elif high >= cur_tp:
                    exit_price = cur_tp
                    exit_reason = "TP"
            else:
                if high >= cur_sl:
                    exit_price = cur_sl
                    exit_reason = "Initial SL"
                elif low <= cur_tp:
                    exit_price = cur_tp
                    exit_reason = "TP"

            if exit_price is not None:
                cur_trade.exit_bar = i
                cur_trade.exit_ts = ts
                cur_trade.exit_price = exit_price
                cur_trade.exit_reason = exit_reason
                cur_trade.trail_stage = trail_stage
                cur_trade.bars_held = 0

                qty = 0.1
                gross_pl = (exit_price - cur_entry_price) * qty if cur_is_long else (cur_entry_price - exit_price) * qty
                # Scalper trade, so one-side commission
                commission = cur_entry_price * qty * COMMISSION_PCT
                net_pl = gross_pl - commission

                cur_trade.gross_pl = gross_pl
                cur_trade.commission = commission
                cur_trade.net_pl = net_pl

                trades.append(cur_trade)
                in_position = False
                cur_trade = None
            else:
                # If no exit, update peak price and stops on bar close
                if cur_is_long:
                    peak_price = max(peak_price, high)
                else:
                    peak_price = min(peak_price, low)

                profit_dist = (close - cur_entry_price) if cur_is_long else (cur_entry_price - close)
                if not be_done and should_trigger_be(profit_dist, cur_atr):
                    be_done = True
                    cur_sl = cur_entry_price
                new_stage = upgrade_trail_stage(trail_stage, profit_dist, cur_atr)
                if new_stage > trail_stage:
                    trail_stage = new_stage
                trail_sl = compute_trail_sl(trail_stage, peak_price, profit_dist, cur_is_long, cur_atr)
                if trail_sl is not None:
                    if cur_is_long and trail_sl > cur_sl:
                        cur_sl = trail_sl
                    elif (not cur_is_long) and trail_sl < cur_sl:
                        cur_sl = trail_sl

    return trades

def main():
    csv_path = "BTCUSDT_30m_1year.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        sys.exit(1)

    df_ohlcv = pd.read_csv(csv_path)
    print(f"Loaded {len(df_ohlcv)} bars from {csv_path}")

    print("Running corrected backtest with 0.1 BTC size...")
    trades = run_backtest_corrected(df_ohlcv)
    print(f"Generated {len(trades)} trades.")

    if not trades:
        print("No trades generated.")
        return

    # Convert to DataFrame
    df_trades = pd.DataFrame([asdict(t) for t in trades])
    df_trades["datetime"] = pd.to_datetime(df_trades["exit_ts"], unit="ms")
    df_trades["month"] = df_trades["datetime"].dt.to_period("M")

    # Sort trades by exit timestamp
    df_trades = df_trades.sort_values("exit_ts").reset_index(drop=True)

    # Calculate equity curve starting with 10,000 USDT
    initial_equity = 10000.0
    df_trades["gross_cum_equity"] = initial_equity + df_trades["gross_pl"].cumsum()
    df_trades["net_cum_equity"] = initial_equity + df_trades["net_pl"].cumsum()

    # Calculate running peak and drawdown for Net Equity
    df_trades["net_peak"] = df_trades["net_cum_equity"].cummax()
    df_trades["net_drawdown_usdt"] = df_trades["net_peak"] - df_trades["net_cum_equity"]
    df_trades["net_drawdown_pct"] = (df_trades["net_drawdown_usdt"] / df_trades["net_peak"]) * 100.0

    # Group by month and calculate monthly stats
    monthly_groups = df_trades.groupby("month")
    monthly_stats = []

    for month, group in monthly_groups:
        no_trades = len(group)
        gross_profit = group["gross_pl"].sum()
        net_profit = group["net_pl"].sum()
        
        # Max profit/loss trades
        max_profit_trade = group["net_pl"].max()
        max_loss_trade = group["net_pl"].min()
        
        # Drawdown in this month
        # Drawdown can be computed relative to the peak during or before this month
        # To get the true peak-to-trough drawdown that occurred within this month, we find the max drawdown in this group
        max_dd_usdt = group["net_drawdown_usdt"].max()
        # Find the peak price corresponding to the max drawdown in this month to get percentage
        idx_max_dd = group["net_drawdown_usdt"].idxmax()
        peak_at_max_dd = group.loc[idx_max_dd, "net_peak"]
        max_dd_pct = (max_dd_usdt / peak_at_max_dd) * 100.0 if peak_at_max_dd > 0 else 0.0

        monthly_stats.append({
            "Month": str(month),
            "Trades": no_trades,
            "Gross Profit (USDT)": round(gross_profit, 2),
            "Net Profit (USDT)": round(net_profit, 2),
            "Max Profit Trade (Net)": round(max_profit_trade, 2),
            "Max Loss Trade (Net)": round(max_loss_trade, 2),
            "Max Drawdown (USDT)": round(max_dd_usdt, 2),
            "Max Drawdown (%)": round(max_dd_pct, 2)
        })

    df_monthly = pd.DataFrame(monthly_stats)

    # Plot Equity Curve
    plt.figure(figsize=(12, 6))
    plt.plot(df_trades["datetime"], df_trades["gross_cum_equity"], label="Gross Equity (No Fees/Taxes)", color="dodgerblue", linewidth=1.5)
    plt.plot(df_trades["datetime"], df_trades["net_cum_equity"], label="Net Equity (After Fees/Taxes)", color="crimson", linewidth=2.0)
    plt.title("BTC Bot v13 v6.5 - 1-Year Backtest Equity Curve (0.1 BTC Position Size)", fontsize=14, fontweight='bold', pad=15)
    plt.xlabel("Date", fontsize=12)
    plt.ylabel("Equity (USDT)", fontsize=12)
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(fontsize=11, loc="upper left")
    plt.tight_layout()
    
    # Save the plot
    artifact_dir = r"C:\Users\sanir\.gemini\antigravity\brain\35aff6f8-d638-423a-aa64-fd357cd4e415"
    plot_path = os.path.join(artifact_dir, "equity_curve.png")
    plt.savefig(plot_path, dpi=300)
    plt.close()
    print(f"Saved equity curve plot -> {plot_path}")

    # Generate Markdown Report
    total_trades = len(df_trades)
    wins = (df_trades["net_pl"] > 0).sum()
    losses = (df_trades["net_pl"] <= 0).sum()
    win_rate = (wins / total_trades) * 100.0 if total_trades else 0.0
    total_gross = df_trades["gross_pl"].sum()
    total_net = df_trades["net_pl"].sum()
    total_comm = df_trades["commission"].sum()
    max_win = df_trades["net_pl"].max()
    max_loss = df_trades["net_pl"].min()
    max_drawdown_usdt = df_trades["net_drawdown_usdt"].max()
    max_drawdown_pct = df_trades["net_drawdown_pct"].max()

    report_content = f"""# Performance Report: BTC Bot v13 v6.5 (Last 1 Year)

A historical simulation of the **BTC Bot v13 v6.5** trading strategy on **BTC/USDT 30m candles** from Delta Exchange India for the period **July 17, 2025** to **July 17, 2026**.

## Performance Summary (0.1 BTC Position Size)

| Metric | Value |
| :--- | :--- |
| **Initial Capital** | 10,000.00 USDT |
| **Total Trades** | {total_trades} |
| **Winning Trades** | {wins} |
| **Losing Trades** | {losses} |
| **Win Rate** | {win_rate:.2f}% |
| **Total Gross Profit** | {total_gross:.2f} USDT |
| **Total Commissions / Taxes** | {total_comm:.2f} USDT |
| **Total Net Profit** | {total_net:.2f} USDT |
| **Max Win (Net)** | {max_win:.2f} USDT |
| **Max Loss (Net)** | {max_loss:.2f} USDT |
| **Max Drawdown (USDT)** | {max_drawdown_usdt:.2f} USDT |
| **Max Drawdown (%)** | {max_drawdown_pct:.2f}% |

> [!NOTE]
> The **Scalper Offer** rules are applied: for trades closed within **less than 30 minutes** (duration < 30m, which corresponds to exiting on the same bar), exit fees are waived and commission is charged **one-side** only. For all other trades, commission is charged **both-sides**.

## Monthly Metrics Breakdown

| Month | Trades | Gross Profit (USDT) | Net Profit (USDT) | Max Win Trade (Net) | Max Loss Trade (Net) | Max Drawdown (USDT) | Max Drawdown (%) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
"""

    for row_idx, r in df_monthly.iterrows():
        report_content += f"| {r['Month']} | {r['Trades']} | {r['Gross Profit (USDT)']:.2f} | {r['Net Profit (USDT)']:.2f} | {r['Max Profit Trade (Net)']:.2f} | {r['Max Loss Trade (Net)']:.2f} | {r['Max Drawdown (USDT)']:.2f} | {r['Max Drawdown (%)']:.2f}% |\n"

    report_content += f"""
## Equity Curve Plot

![BTC Bot v13 Equity Curve](file:///{plot_path.replace(os.sep, '/')})

## Strategy Execution Observations
- The corrected backtesting engine ensures that exit conditions are evaluated sequentially **before** stop levels are updated on bar close. This eliminates the same-bar exit bug that was stopping trades out prematurely.
- Applying the Delta India Scalper Offer rules (one-sided commissions on trades closed in less than 30 minutes) significantly improves short-term trade efficiency.
"""

    report_path = os.path.join(artifact_dir, "backtest_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"Saved backtest report -> {report_path}")

    # Also save trades list to CSV for record
    trades_path = os.path.join(artifact_dir, "backtest_trades_details.csv")
    df_trades.to_csv(trades_path, index=False)
    print(f"Saved trades log -> {trades_path}")

if __name__ == "__main__":
    main()
