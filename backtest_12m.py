"""
backtest_12m.py — 12-month backtest matching optimized_results.py logic exactly.
Enters at bar close, simple SL/TP exit, max 15 bars, one-side commission.
"""
import os, sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from config import COMMISSION_PCT, SL_ATR_MULT, TP_RR_MULT
from backtest_v2 import compute_indicators

CSV_PATH = "D:/BTC_Bot_v13/BTCUSDT_30m_2year.csv"
QTY = 0.1  # BTC position size

# Strategy params (from optimized_results.py)
SL = SL_ATR_MULT   # 0.5
TP = TP_RR_MULT    # 1.5
SE, SX = 40, 65    # short enter, short exit RSI bounds
LE, LX = 50, 25    # long enter, long exit RSI bounds
MAX_BARS = 15

def main():
    raw = pd.read_csv(CSV_PATH)

    # Slice last 12 months
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=365)
    cutoff_ms = int(cutoff_dt.timestamp() * 1000)
    raw = raw[pd.to_numeric(raw["timestamp"], errors="coerce") >= cutoff_ms].reset_index(drop=True).copy()

    num_cols = ["open", "high", "low", "close", "volume"]
    data = {c: raw[c].values.astype(float) for c in num_cols}
    ind = compute_indicators(data["close"], data["high"], data["low"], data["volume"])
    n = len(data["close"])

    start_dt = datetime.fromtimestamp(raw["timestamp"].iloc[0] / 1000, tz=timezone.utc)
    end_dt = datetime.fromtimestamp(raw["timestamp"].iloc[-1] / 1000, tz=timezone.utc)
    print(f"Data: {n} 30m bars")
    print(f"Range: {start_dt.date()} -> {end_dt.date()}")
    print(f"Params: SL={SL}atr  TP={TP}x  RSI({SE}-{SX})short  RSI({LE}-{LX})long  QTY={QTY} BTC")
    print()

    trades = []
    for i in range(220, n - 1):
        bear = data["close"][i] < ind["ema_trend"][i]
        bull = data["close"][i] > ind["ema_trend"][i]
        sig = None
        if bear and ind["rsi"][i] > SE and ind["rsi"][i] < SX and ind["rsi"][i-1] <= SE:
            sig = "short"
        if bull and ind["rsi"][i] < LE and ind["rsi"][i] > LX and ind["rsi"][i-1] >= LE:
            sig = "long"
        if not sig:
            continue

        ep = data["close"][i]
        sd = ind["atr14"][i] * SL
        sl = ep + sd if sig == "short" else ep - sd
        tp = ep - sd * TP if sig == "short" else ep + sd * TP

        exit_p = None
        rsn = None
        for j in range(i, min(i + MAX_BARS, n)):
            if sig == "short":
                if data["high"][j] >= sl:
                    exit_p, rsn = sl, "SL"
                    break
                elif data["low"][j] <= tp:
                    exit_p, rsn = tp, "TP"
                    break
            else:
                if data["low"][j] <= sl:
                    exit_p, rsn = sl, "SL"
                    break
                elif data["high"][j] >= tp:
                    exit_p, rsn = tp, "TP"
                    break
        if exit_p is None:
            exit_p = data["close"][min(i + MAX_BARS - 1, n - 1)]
            rsn = "Timeout"

        gross = (exit_p - ep) * QTY if sig == "long" else (ep - exit_p) * QTY
        comm = ep * QTY * COMMISSION_PCT  # one-side commission
        net = gross - comm

        trades.append({
            "ts": int(raw.iloc[i]["timestamp"]),
            "sig": sig,
            "entry": ep,
            "exit": exit_p,
            "reason": rsn,
            "gross": gross,
            "comm": comm,
            "net": net,
        })

    # === Summary ===
    t = len(trades)
    if t == 0:
        print("No trades generated.")
        return

    wins = sum(1 for x in trades if x["net"] > 0)
    losses = t - wins
    win_rate = wins / t * 100
    total_gross = sum(x["gross"] for x in trades)
    total_comm = sum(x["comm"] for x in trades)
    total_net = sum(x["net"] for x in trades)
    win_pl = sum(x["net"] for x in trades if x["net"] > 0)
    loss_pl = sum(x["net"] for x in trades if x["net"] < 0)
    profit_factor = abs(win_pl / loss_pl) if loss_pl else float("inf")
    best = max(x["net"] for x in trades)
    worst = min(x["net"] for x in trades)
    avg_win = win_pl / wins if wins else 0
    avg_loss = loss_pl / losses if losses else 0

    sl_cnt = sum(1 for x in trades if x["reason"] == "SL")
    tp_cnt = sum(1 for x in trades if x["reason"] == "TP")
    to_cnt = sum(1 for x in trades if x["reason"] == "Timeout")

    # Monthly breakdown
    monthly = {}
    for x in trades:
        dt = datetime.fromtimestamp(x["ts"] / 1000, tz=timezone.utc)
        k = dt.strftime("%Y-%m")
        if k not in monthly:
            monthly[k] = {"t": 0, "w": 0, "gross": 0.0, "comm": 0.0, "net": 0.0}
        monthly[k]["t"] += 1
        monthly[k]["w"] += 1 if x["net"] > 0 else 0
        monthly[k]["gross"] += x["gross"]
        monthly[k]["comm"] += x["comm"]
        monthly[k]["net"] += x["net"]

    # Equity curve for drawdown
    equity = 10000.0
    peak = equity
    max_dd = 0.0
    for x in trades:
        equity += x["net"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = max_dd / 10000 * 100

    # === Print Report ===
    print("=" * 72)
    print(f"  BTC Bot v13 — 12-Month Backtest (RSI Bounce)")
    print(f"  Period: {start_dt.date()} -> {end_dt.date()}")
    print(f"  Position: {QTY} BTC  ({t} trades)")
    print("=" * 72)
    print(f"  {'Metric':<35s} {'Value':>15s}")
    print(f"  {'-'*35} {'-'*15}")
    print(f"  {'Total Trades':<35s} {t:>15d}")
    print(f"  {'Wins':<35s} {wins:>15d}")
    print(f"  {'Losses':<35s} {losses:>15d}")
    print(f"  {'Win Rate':<35s} {win_rate:>14.1f}%")
    print(f"  {'Profit Factor':<35s} {profit_factor:>15.2f}")
    print(f"  {'Total Gross P&L':<35s} ${total_gross:>13.2f}")
    print(f"  {'Total Commission':<35s} ${total_comm:>13.2f}")
    print(f"  {'Total Net P&L':<35s} ${total_net:>13.2f}")
    print(f"  {'Avg Monthly Net':<35s} ${total_net/len(monthly):>13.2f}")
    print(f"  {'Avg Win':<35s} ${avg_win:>13.2f}")
    print(f"  {'Avg Loss':<35s} ${avg_loss:>13.2f}")
    print(f"  {'Best Trade':<35s} ${best:>13.2f}")
    print(f"  {'Worst Trade':<35s} ${worst:>13.2f}")
    print(f"  {'Max Drawdown ($)':<35s} ${max_dd:>13.2f}")
    print(f"  {'Max Drawdown (%)':<35s} {max_dd_pct:>14.2f}%")
    print(f"  {'SL / TP / Timeout':<35s} {sl_cnt:>5d} / {tp_cnt:>4d} / {to_cnt:>3d}")
    print()

    # Monthly table
    print(f"  {'Month':<8s} {'Trades':>6s} {'Wins':>4s} {'Loss':>4s} {'WR%':>6s} {'Gross $':>10s} {'Comm $':>8s} {'Net $':>10s}")
    print(f"  {'-'*8} {'-'*6} {'-'*4} {'-'*4} {'-'*6} {'-'*10} {'-'*8} {'-'*10}")
    for m in sorted(monthly.keys()):
        d = monthly[m]
        wr = d["w"] / d["t"] * 100
        losses = d["t"] - d["w"]
        print(f"  {m:<8s} {d['t']:>6d} {d['w']:>4d} {losses:>4d} {wr:>5.1f}% ${d['gross']:>7.2f} ${d['comm']:>6.2f} ${d['net']:>7.2f}")

    # Save CSV
    df_t = pd.DataFrame(trades)
    df_t.to_csv("D:/BTC_Bot_v13/backtest_12m_trades.csv", index=False)
    print(f"\n  Trades saved -> backtest_12m_trades.csv")

if __name__ == "__main__":
    main()
