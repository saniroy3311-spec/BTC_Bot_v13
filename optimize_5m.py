#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║  BTC Bot v13 — 5m Parameter Optimizer                                   ║
║                                                                           ║
║  Staged grid search over cached 5m BTCUSDT data to find optimal           ║
║  strategy parameters for 5-minute timeframe trading.                      ║
║                                                                           ║
║  Usage:                                                                    ║
║    python optimize_5m.py                     # full staged sweep           ║
║    python optimize_5m.py --fast              # quick test (small sweep)    ║
║    python optimize_5m.py --show-baseline     # show current 30m config     ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import csv, json, math, os, sys, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

DATA_PATH = "bt_cache_5m.csv"
OUT_DIR   = "optimizer/results"
os.makedirs(OUT_DIR, exist_ok=True)

# ─── Baseline (current 30m-optimized config) ────────────────────────────
BASELINE = {
    "SL_ATR_MULT": 0.5,
    "TP_RR_MULT": 1.5,
    "RSI_BOUNCE_SHORT_ENTER": 40,
    "RSI_BOUNCE_SHORT_EXIT": 65,
    "RSI_BOUNCE_LONG_ENTER": 50,
    "RSI_BOUNCE_LONG_EXIT": 25,
    "FILTER_ATR_MULT": 1.4,
    "FILTER_BODY_MULT": 0.5,
    "FILTER_VOL_ENABLED": True,
    "FILTER_VOL_MULT": 1.0,
    "MAX_SL_POINTS": 500.0,
    "MAX_BARS": 15,
    "COMMISSION_PCT": 0.0005,
    "POSITION_BTC": 0.1,
}

INITIAL_CAPITAL = 10000.0
POSITION_BTC = 0.1
COMMISSION_PCT = 0.0005
WARMUP_BARS = 220


# ─── INDICATORS (Pine-exact, matches backtest_dashboard.py) ──────────────

def rma(arr, period):
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period:
        return out
    out[period - 1] = float(np.mean(arr[:period]))
    a = 1.0 / period
    for i in range(period, n):
        out[i] = arr[i] * a + out[i - 1] * (1 - a)
    return out


def ema(arr, period):
    n = len(arr)
    out = np.full(n, np.nan)
    if n < period:
        return out
    out[period - 1] = float(np.mean(arr[:period]))
    m = 2.0 / (period + 1)
    for i in range(period, n):
        out[i] = arr[i] * m + out[i - 1] * (1 - m)
    return out


def compute_indicators(close, high, low, volume):
    n = len(close)
    ema_trend = ema(close, 100)
    tr = np.full(n, np.nan)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr14 = rma(tr, 14)
    atr_sma = pd.Series(atr14).rolling(50).mean().values if n >= 50 else np.full(n, np.nan)
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    gain = np.insert(gain, 0, 0)
    loss = np.insert(loss, 0, 0)
    avg_gain = rma(gain, 14)
    avg_loss = rma(loss, 14)
    rsi = np.full(n, 50.0)
    for i in range(14, n):
        if avg_loss[i] == 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 100.0 - 100.0 / (1.0 + avg_gain[i] / avg_loss[i])
    vol_sma = np.full(n, np.nan)
    for i in range(19, n):
        vol_sma[i] = float(np.mean(volume[i - 19:i + 1]))
    return {"ema_trend": ema_trend, "atr14": atr14, "atr_sma": atr_sma,
            "rsi": rsi, "vol_sma": vol_sma}


# ─── BACKTEST (single param set, pre-computed indicators) ───────────────

def run_backtest(close, high, low, volume, timestamp, ind, cfg) -> list[dict]:
    """Run backtest with given config on pre-computed indicators."""
    sl_atr = cfg["SL_ATR_MULT"]
    tp_rr = cfg["TP_RR_MULT"]
    rsi_se = cfg["RSI_BOUNCE_SHORT_ENTER"]
    rsi_sx = cfg["RSI_BOUNCE_SHORT_EXIT"]
    rsi_le = cfg["RSI_BOUNCE_LONG_ENTER"]
    rsi_lx = cfg["RSI_BOUNCE_LONG_EXIT"]
    filt_atr = cfg.get("FILTER_ATR_MULT", 1.4)
    max_sl_pts = cfg.get("MAX_SL_POINTS", 500.0)
    max_bars = cfg.get("MAX_BARS", 15)
    vol_enabled = cfg.get("FILTER_VOL_ENABLED", True)
    vol_mult = cfg.get("FILTER_VOL_MULT", 1.0)

    n = len(close)
    trades = []

    for i in range(WARMUP_BARS, n - 1):
        if np.isnan(ind["ema_trend"][i]) or np.isnan(ind["atr14"][i]) or np.isnan(ind["rsi"][i]):
            continue

        # Filters
        atr_ok = ind["atr14"][i] < ind["atr_sma"][i] * filt_atr
        vol_ok = True
        if vol_enabled and ind["vol_sma"][i] > 0:
            vol_ok = volume[i] > ind["vol_sma"][i] * vol_mult
        if not (atr_ok and vol_ok):
            continue

        bear = close[i] < ind["ema_trend"][i]
        bull = close[i] > ind["ema_trend"][i]
        sig = None

        if bear and rsi_se < ind["rsi"][i] < rsi_sx and ind["rsi"][i - 1] <= rsi_se:
            sig = "short"
        if bull and rsi_lx < ind["rsi"][i] < rsi_le and ind["rsi"][i - 1] >= rsi_le:
            sig = "long"

        if not sig:
            continue

        ep = close[i]
        sd = min(ind["atr14"][i] * sl_atr, max_sl_pts)
        sl = ep + sd if sig == "short" else ep - sd
        tp = ep - sd * tp_rr if sig == "short" else ep + sd * tp_rr

        exit_p = None
        rsn = None
        for j in range(i, min(i + max_bars, n)):
            if sig == "short":
                if high[j] >= sl:
                    exit_p, rsn = sl, "SL"
                    break
                elif low[j] <= tp:
                    exit_p, rsn = tp, "TP"
                    break
            else:
                if low[j] <= sl:
                    exit_p, rsn = sl, "SL"
                    break
                elif high[j] >= tp:
                    exit_p, rsn = tp, "TP"
                    break

        if exit_p is None:
            exit_p = close[min(i + max_bars - 1, n - 1)]
            rsn = "Timeout"

        gross = (exit_p - ep) * POSITION_BTC if sig == "long" else (ep - exit_p) * POSITION_BTC
        comm = ep * POSITION_BTC * COMMISSION_PCT
        net = gross - comm

        trades.append({
            "ts": int(timestamp[i]),
            "sig": sig,
            "net": net,
            "gross": gross,
            "reason": rsn,
        })

    return trades


# ─── SCORING ────────────────────────────────────────────────────────────

def score_trades(trades):
    if not trades:
        return {"total": 0, "wins": 0, "win_rate": 0, "net_pl": 0,
                "profit_factor": 0, "max_dd_pct": 0, "score": -99999}

    total = len(trades)
    wins = sum(1 for t in trades if t["net"] > 0)
    win_rate = wins / total * 100
    total_net = sum(t["net"] for t in trades)

    win_pl = sum(t["net"] for t in trades if t["net"] > 0)
    loss_pl = abs(sum(t["net"] for t in trades if t["net"] <= 0))
    pf = win_pl / loss_pl if loss_pl else float("inf")

    equity = INITIAL_CAPITAL
    peak = equity
    max_dd = 0
    for t in trades:
        equity += t["net"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = max_dd / INITIAL_CAPITAL * 100

    # Score: reward profit, win rate, profit factor; penalize drawdown
    s = total_net * (win_rate / 100) * pf / max(1, max_dd_pct + 0.5)

    return {"total": total, "wins": wins, "win_rate": round(win_rate, 1),
            "net_pl": round(total_net, 2), "profit_factor": round(pf, 2),
            "max_dd_pct": round(max_dd_pct, 2), "score": round(s, 2)}


def print_result(label, m):
    arrow = "+" if m["net_pl"] > 0 else "-"
    print(f"  {label:45s} Trades={m['total']:4d}  WR={m['win_rate']:5.1f}%  "
          f"Net={arrow}${m['net_pl']:>+8.2f}  PF={m['profit_factor']:>5.2f}  "
          f"DD={m['max_dd_pct']:>4.1f}%  Score={m['score']:>8.2f}")


# ─── DATA LOADING ───────────────────────────────────────────────────────

def load_5m_data():
    if not os.path.exists(DATA_PATH):
        print(f"[FAIL] Data file not found: {DATA_PATH}")
        print("  Run 'python backtest_dashboard.py --months 12' first to cache 5m data.")
        sys.exit(1)

    print(f"Loading {DATA_PATH} ...")
    df = pd.read_csv(DATA_PATH)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)

    # Slice last 12 months
    cutoff = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp() * 1000)
    df = df[pd.to_numeric(df["timestamp"], errors="coerce") >= cutoff].reset_index(drop=True)

    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    volume = df["volume"].values.astype(float)
    timestamp = df["timestamp"].values.astype(int)
    n = len(close)

    print(f"Bars: {n:,}  Range: ${low.min():,.0f} — ${high.max():,.0f}")
    print(f"Period: {datetime.fromtimestamp(timestamp[0]/1000).date()} — {datetime.fromtimestamp(timestamp[-1]/1000).date()}")

    # Compute indicators once
    print("Computing indicators...")
    t0 = time.time()
    ind = compute_indicators(close, high, low, volume)
    print(f"  Done in {time.time()-t0:.1f}s")
    return close, high, low, volume, timestamp, ind


# ─── STAGED SWEEP ──────────────────────────────────────────────────────

def stage1_sl_tp(close, high, low, volume, timestamp, ind):
    """Sweep SL_ATR_MULT × TP_RR_MULT with fixed RSI thresholds."""
    print("\n" + "=" * 70)
    print("  STAGE 1: SL_ATR_MULT × TP_RR_MULT sweep")
    print("=" * 70)

    sl_values = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0]
    tp_values = [1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0]
    best_score = -99999
    best_cfg = None
    results = []

    for sl in sl_values:
        for tp in tp_values:
            cfg = dict(BASELINE, SL_ATR_MULT=sl, TP_RR_MULT=tp)
            trades = run_backtest(close, high, low, volume, timestamp, ind, cfg)
            m = score_trades(trades)
            results.append((m["score"], sl, tp, m))
            if m["score"] > best_score and m["total"] >= 50:
                best_score = m["score"]
                best_cfg = cfg

    results.sort(key=lambda x: x[0], reverse=True)
    for s, sl, tp, m in results[:10]:
        print_result(f"SL={sl:.1f}  TP={tp:.1f}", m)

    print(f"\n  Best: SL={best_cfg['SL_ATR_MULT']:.1f}  TP={best_cfg['TP_RR_MULT']:.1f}")
    return best_cfg


def stage2_rsi(close, high, low, volume, timestamp, ind, sl_tp_cfg):
    """Sweep RSI thresholds with best SL/TP fixed."""
    print("\n" + "=" * 70)
    print("  STAGE 2: RSI thresholds sweep")
    print("=" * 70)

    short_enter_values = [35, 38, 40, 42, 45]
    long_enter_values = [45, 48, 50, 52, 55]
    best_score = -99999
    best_cfg = None
    results = []

    for se in short_enter_values:
        for le in long_enter_values:
            cfg = dict(sl_tp_cfg,
                       RSI_BOUNCE_SHORT_ENTER=se,
                       RSI_BOUNCE_LONG_ENTER=le)
            trades = run_backtest(close, high, low, volume, timestamp, ind, cfg)
            m = score_trades(trades)
            results.append((m["score"], se, le, m))
            if m["score"] > best_score and m["total"] >= 50:
                best_score = m["score"]
                best_cfg = cfg

    results.sort(key=lambda x: x[0], reverse=True)
    for s, se, le, m in results[:10]:
        print_result(f"ShortEnter={se}  LongEnter={le}", m)

    print(f"\n  Best: ShortEnter={best_cfg['RSI_BOUNCE_SHORT_ENTER']}  LongEnter={best_cfg['RSI_BOUNCE_LONG_ENTER']}")
    return best_cfg


def stage3_filters(close, high, low, volume, timestamp, ind, prev_cfg):
    """Sweep filter parameters."""
    print("\n" + "=" * 70)
    print("  STAGE 3: Filter parameters sweep")
    print("=" * 70)

    atr_mult_values = [1.0, 1.2, 1.4, 1.6, 2.0]
    max_sl_values = [200, 300, 500, 800]
    best_score = -99999
    best_cfg = None
    results = []

    for atr_m in atr_mult_values:
        for ms in max_sl_values:
            cfg = dict(prev_cfg, FILTER_ATR_MULT=atr_m, MAX_SL_POINTS=float(ms))
            trades = run_backtest(close, high, low, volume, timestamp, ind, cfg)
            m = score_trades(trades)
            results.append((m["score"], atr_m, ms, m))
            if m["score"] > best_score and m["total"] >= 50:
                best_score = m["score"]
                best_cfg = cfg

    results.sort(key=lambda x: x[0], reverse=True)
    for s, atr_m, ms, m in results[:10]:
        print_result(f"ATR_Mult={atr_m:.1f}  MaxSL={ms}", m)

    print(f"\n  Best: ATR_Mult={best_cfg['FILTER_ATR_MULT']:.1f}  MaxSL={best_cfg['MAX_SL_POINTS']:.0f}")
    return best_cfg


def stage4_maxbars(close, high, low, volume, timestamp, ind, prev_cfg):
    """Sweep MAX_BARS."""
    print("\n" + "=" * 70)
    print("  STAGE 4: MAX_BARS sweep")
    print("=" * 70)

    max_bars_values = [8, 10, 12, 15, 20, 25, 30]
    best_score = -99999
    best_cfg = None
    results = []

    for mb in max_bars_values:
        cfg = dict(prev_cfg, MAX_BARS=mb)
        trades = run_backtest(close, high, low, volume, timestamp, ind, cfg)
        m = score_trades(trades)
        results.append((m["score"], mb, m))
        if m["score"] > best_score and m["total"] >= 50:
            best_score = m["score"]
            best_cfg = cfg

    results.sort(key=lambda x: x[0], reverse=True)
    for s, mb, m in results[:7]:
        print_result(f"MAX_BARS={mb}", m)

    print(f"\n  Best: MAX_BARS={best_cfg['MAX_BARS']}")
    return best_cfg


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="Quick test with reduced sweep")
    ap.add_argument("--show-baseline", action="store_true", help="Show baseline config performance")
    args = ap.parse_args()

    close, high, low, volume, timestamp, ind = load_5m_data()

    # Show baseline performance
    print("\nBaseline (30m-optimized config on 5m data):")
    trades = run_backtest(close, high, low, volume, timestamp, ind, BASELINE)
    m = score_trades(trades)
    print_result("BASELINE", m)

    if args.show_baseline:
        return

    if args.fast:
        print("\n[Fast mode] Sweeping only SL/TP and RSI...")
        cfg = stage1_sl_tp(close, high, low, volume, timestamp, ind)
        cfg = stage2_rsi(close, high, low, volume, timestamp, ind, cfg)
    else:
        cfg = stage1_sl_tp(close, high, low, volume, timestamp, ind)
        cfg = stage2_rsi(close, high, low, volume, timestamp, ind, cfg)
        cfg = stage3_filters(close, high, low, volume, timestamp, ind, cfg)
        cfg = stage4_maxbars(close, high, low, volume, timestamp, ind, cfg)

    # ── Final run with best config ──────────────────────────────────────
    print("\n" + "=" * 70)
    print("  FINAL OPTIMIZED CONFIG (5m)")
    print("=" * 70)
    for k, v in cfg.items():
        print(f"    {k:30s} = {v}")

    trades = run_backtest(close, high, low, volume, timestamp, ind, cfg)
    m = score_trades(trades)
    print_result("OPTIMIZED 5m", m)

    # Compare to baseline
    base_trades = run_backtest(close, high, low, volume, timestamp, ind, BASELINE)
    bm = score_trades(base_trades)
    improvement = ((m["net_pl"] - bm["net_pl"]) / abs(bm["net_pl"]) * 100) if bm["net_pl"] != 0 else 0
    print(f"\n  Improvement vs Baseline: {improvement:+.1f}% net P&L")

    # ── Save optimized config ──────────────────────────────────────────
    out_path = os.path.join(OUT_DIR, "optimized_5m_config.json")
    json.dump(cfg, open(out_path, "w"), indent=2)
    print(f"\n  Config saved -> {out_path}")

    # ── Save final trades ──────────────────────────────────────────────
    tsv_path = os.path.join(OUT_DIR, "bt_results_5m_best.tsv")
    if trades:
        with open(tsv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=trades[0].keys(), delimiter="\t")
            w.writeheader()
            w.writerows(trades)
        print(f"  Trades saved -> {tsv_path}")

    # ── Summary ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"  {'Metric':<30s} {'Baseline (30m cfg)':>18s}  {'Optimized 5m':>18s}")
    print(f"  {'-'*30} {'-'*18}  {'-'*18}")
    for k in ["total", "win_rate", "net_pl", "profit_factor", "max_dd_pct"]:
        bv = bm.get(k, "-")
        ov = m.get(k, "-")
        print(f"  {k:<30s} {str(bv):>18s}  {str(ov):>18s}")

    # Save summary
    summary = {
        "baseline": bm,
        "optimized": m,
        "config": cfg,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    summary_path = os.path.join(OUT_DIR, "optimized_5m_summary.json")
    json.dump(summary, open(summary_path, "w"), indent=2)
    print(f"\n  Full summary -> {summary_path}")


if __name__ == "__main__":
    main()
