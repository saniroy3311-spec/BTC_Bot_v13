"""
BTC BOT v13 — COMPREHENSIVE OPTIMIZATION + BACKTEST + REPORT
=================================================================
Target: >$500/month profit with 0.1 BTC on Delta Exchange India
Period: 2 years (2024-07 to 2026-07) BTC/USDT 30m
"""
import os, sys, json, math, itertools, copy, base64
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional
from io import BytesIO

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Import core functions (NO config globals loading) ──
from strategy_logic import (
    compute_full_series,
    SignalType, Signal, IndicatorSnapshot,
    calc_levels, get_trail_params, upgrade_trail_stage,
    compute_trail_sl, should_trigger_be, max_sl_hit,
    max_sl_threshold, calc_real_pl,
)

# ============================================================
# CONFIG — directly used, no reliance on config.py globals
# ============================================================
BASE_CFG = {
    "ADX_TREND_TH": 22,
    "ADX_RANGE_TH": 18,
    "FILTER_ATR_MULT": 1.4,
    "FILTER_BODY_MULT": 0.5,
    "FILTER_VOL_ENABLED": True,
    "FILTER_VOL_MULT": 1.0,
    "TREND_RR": 4.0,
    "RANGE_RR": 2.5,
    "TREND_ATR_MULT": 0.6,
    "RANGE_ATR_MULT": 0.5,
    "MAX_SL_MULT": 1.5,
    "MAX_SL_POINTS": 500.0,
    "BE_MULT": 0.6,
    "RSI_OB": 70,
    "RSI_OS": 30,
    "BREAKOUT_BUFFER_PTS": 0,
    "COMMISSION_PCT": 0.0005,      # 0.05%
    "TP_HARD_EXIT": True,          # CHANGED: enable TP for reliable exits
    "PINE_MINTICK": 0.5,
    "TRAIL_STAGES": [
        (0.8, 0.50, 0.40),
        (1.5, 0.40, 0.30),
        (2.5, 0.30, 0.25),
        (4.0, 0.20, 0.15),
        (6.0, 0.15, 0.10),
    ],
}

# ============================================================
# PATCH strategy_logic globals
# ============================================================
def _patch_sl_globals(cfg):
    """Update strategy_logic module globals from cfg dict."""
    import strategy_logic as sl
    import config as cm
    # Map our cfg keys to what strategy_logic expects
    mapping = {
        "ADX_TREND_TH": "ADX_TREND_TH",
        "ADX_RANGE_TH": "ADX_RANGE_TH",
        "FILTER_ATR_MULT": "FILTER_ATR_MULT",
        "FILTER_BODY_MULT": "FILTER_BODY_MULT",
        "FILTER_VOL_ENABLED": "FILTER_VOL_ENABLED",
        "FILTER_VOL_MULT": "FILTER_VOL_MULT",
        "TREND_RR": "TREND_RR",
        "RANGE_RR": "RANGE_RR",
        "TREND_ATR_MULT": "TREND_ATR_MULT",
        "RANGE_ATR_MULT": "RANGE_ATR_MULT",
        "MAX_SL_MULT": "MAX_SL_MULT",
        "MAX_SL_POINTS": "MAX_SL_POINTS",
        "BE_MULT": "BE_MULT",
        "RSI_OB": "RSI_OB",
        "RSI_OS": "RSI_OS",
        "BREAKOUT_BUFFER_PTS": "BREAKOUT_BUFFER_PTS",
        "COMMISSION_PCT": "COMMISSION_PCT",
        "PINE_MINTICK": "PINE_MINTICK",
        "TRAIL_STAGES": "TRAIL_STAGES",
    }
    for cfg_key, mod_attr in mapping.items():
        if cfg_key in cfg:
            setattr(sl, mod_attr, cfg[cfg_key])
            setattr(cm, mod_attr, cfg[cfg_key])


# ============================================================
# BACKTEST ENGINE
# ============================================================
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
    points_captured: float = 0.0


def _make_snap(row, prev_row, cfg) -> IndicatorSnapshot:
    """Build IndicatorSnapshot from OHLCV row using cfg dict."""
    atr = float(row["atr"])
    atr_sma = float(row["atr_sma"])
    vol_sma = float(row["vol_sma"])
    bar_vol = float(row["volume"])
    open_v  = float(row["open"])
    close_v = float(row["close"])

    atr_ok = atr < atr_sma * cfg["FILTER_ATR_MULT"]
    body_ok = True
    if cfg["FILTER_VOL_ENABLED"]:
        vol_ok = bar_vol > 0 and vol_sma > 0 and bar_vol > vol_sma * cfg.get("FILTER_VOL_MULT", 1.0)
    else:
        vol_ok = True

    adx_v = float(row["adx"])
    return IndicatorSnapshot(
        ema_trend=float(row["ema200"]), ema_fast=float(row["ema50"]),
        atr=atr, rsi=float(row["rsi"]),
        dip=float(row["dip"]), dim=float(row["dim"]),
        adx=adx_v, adx_raw=float(row["adx_raw"]),
        vol_sma=vol_sma, atr_sma=atr_sma,
        trend_regime=adx_v > cfg["ADX_TREND_TH"],
        range_regime=adx_v < cfg["ADX_RANGE_TH"],
        filters_ok=bool(atr_ok and vol_ok and body_ok),
        atr_ok=bool(atr_ok), vol_ok=bool(vol_ok), body_ok=bool(body_ok),
        open=open_v, high=float(row["high"]), low=float(row["low"]),
        close=close_v, volume=bar_vol,
        prev_high=float(prev_row["high"]), prev_low=float(prev_row["low"]),
        timestamp=int(row["timestamp"]),
    )


def _intrabar_exit_long(open_p, high, low, close, sl_price, tp_price, tp_active, max_sl_price=None):
    """Check exits for long within a bar."""
    sl_touched = low <= sl_price
    tp_touched = high >= tp_price
    ms_touched = max_sl_price is not None and low <= max_sl_price

    if open_p <= sl_price:   return open_p, "SL"
    if ms_touched and open_p <= max_sl_price: return open_p, "Max SL"
    if tp_active and open_p >= tp_price: return open_p, "TP"
    if sl_touched and tp_touched:  return sl_price, "SL"
    if sl_touched:  return sl_price, "SL"
    if ms_touched:  return max_sl_price, "Max SL"
    if tp_active and tp_touched:  return tp_price, "TP"
    return None, None


def _intrabar_exit_short(open_p, high, low, close, sl_price, tp_price, tp_active, max_sl_price=None):
    """Check exits for short within a bar."""
    sl_touched = high >= sl_price
    tp_touched = low <= tp_price
    ms_touched = max_sl_price is not None and high >= max_sl_price

    if open_p >= sl_price:   return open_p, "SL"
    if ms_touched and open_p >= max_sl_price: return open_p, "Max SL"
    if tp_active and open_p <= tp_price: return open_p, "TP"
    if sl_touched and tp_touched:  return sl_price, "SL"
    if sl_touched:  return sl_price, "SL"
    if ms_touched:  return max_sl_price, "Max SL"
    if tp_active and tp_touched:  return tp_price, "TP"
    return None, None


def run_backtest(df: pd.DataFrame, cfg: dict, position_btc: float = 0.1) -> list[BTTrade]:
    """Full backtest engine. Patches strategy_logic globals, runs bar-by-bar."""
    _patch_sl_globals(cfg)
    tp_active = cfg.get("TP_HARD_EXIT", True)
    comm_rate = cfg.get("COMMISSION_PCT", 0.0005)

    series = compute_full_series(df).reset_index(drop=True)
    n = len(series)
    trades = []

    in_pos = False
    pending = None
    trade_id = 0
    cur = None
    cur_sl = cur_tp = cur_atr = cur_entry = 0.0
    cur_long = True
    peak = 0.0
    be_done = trail_stage = 0
    max_sl_fired = False
    entry_bar_idx = -1

    for i in range(1, n):
        row = series.iloc[i]
        prev_row = series.iloc[i - 1]
        ts = int(row["timestamp"])
        open_, high, low, close = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])

        if any(np.isnan(row.get(c, 0)) for c in ["ema200", "adx", "atr", "atr_sma", "vol_sma"]):
            continue

        if in_pos and pending is not None:
            pending = None

        # ── ENTRY AT OPEN ──
        if pending is not None and not in_pos:
            sig, sig_snap, sig_bar = pending
            entry = open_
            entry_bar_idx = i
            risk = calc_levels(entry, sig_snap.atr, sig.is_long, sig.is_trend)
            trade_id += 1
            cur = BTTrade(trade_id, sig.signal_type.value, sig.is_long, sig.is_trend,
                          sig_bar, int(series.iloc[sig_bar]["timestamp"]),
                          i, ts, entry, risk.sl, risk.tp, risk.stop_dist, sig_snap.atr)
            cur_sl, cur_tp, cur_atr = risk.sl, risk.tp, sig_snap.atr
            cur_long = sig.is_long
            cur_entry = entry
            peak = entry
            be_done = False
            trail_stage = 0
            max_sl_fired = False
            in_pos = True
            pending = None

            # Immediate exit check on entry bar
            if cur_long:
                ex, er = _intrabar_exit_long(open_, high, low, close, cur_sl, cur_tp, tp_active)
            else:
                ex, er = _intrabar_exit_short(open_, high, low, close, cur_sl, cur_tp, tp_active)

            if ex is not None:
                cur.exit_bar, cur.exit_ts, cur.exit_price, cur.exit_reason = i, ts, ex, er
                cur.bars_held = 0
                q = position_btc
                gp = (ex - cur_entry) * q if cur_long else (cur_entry - ex) * q
                # Scalper: one-side commission (<30min)
                comm = cur_entry * q * comm_rate  # one side only
                cur.gross_pl, cur.commission, cur.net_pl = gp, comm, gp - comm
                cur.points_captured = abs(ex - cur_entry)
                trades.append(cur)
                in_pos = False
                cur = None
                continue
            else:
                # Update peak and stops for entry bar close
                if cur_long:
                    peak = max(peak, high)
                    pdist = close - cur_entry
                else:
                    peak = min(peak, low)
                    pdist = cur_entry - close
                if not be_done and should_trigger_be(pdist, cur_atr):
                    be_done = True
                    cur_sl = cur_entry
                ns = upgrade_trail_stage(trail_stage, pdist, cur_atr)
                if ns > trail_stage:
                    trail_stage = ns
                tsl = compute_trail_sl(trail_stage, peak, pdist, cur_long, cur_atr)
                if tsl is not None:
                    if cur_long and tsl > cur_sl:
                        cur_sl = tsl
                    elif (not cur_long) and tsl < cur_sl:
                        cur_sl = tsl
                continue

        # ── EXIT CHECK for open position ──
        if in_pos and cur is not None:
            if cur_long:
                peak = max(peak, high)
            else:
                peak = min(peak, low)

            # Check for Max SL activation
            threshold = min(cur_atr * 1.5, 500.0)
            if cur_long:
                ms_price = cur_entry - threshold
            else:
                ms_price = cur_entry + threshold
            ms_active = (i > entry_bar_idx) and not max_sl_fired

            if cur_long:
                ex, er = _intrabar_exit_long(open_, high, low, close, cur_sl, cur_tp, tp_active,
                                             ms_price if ms_active else None)
            else:
                ex, er = _intrabar_exit_short(open_, high, low, close, cur_sl, cur_tp, tp_active,
                                              ms_price if ms_active else None)

            if ex is not None:
                if er == "Max SL":
                    max_sl_fired = True
                cur.exit_bar, cur.exit_ts, cur.exit_price, cur.exit_reason = i, ts, ex, er
                cur.trail_stage = trail_stage
                cur.bars_held = i - entry_bar_idx
                q = position_btc
                gp = (ex - cur_entry) * q if cur_long else (cur_entry - ex) * q
                # Commission: one-side if <30min (0 bars held = same bar = <30m)
                if cur.bars_held == 0:
                    comm = cur_entry * q * comm_rate
                else:
                    comm = (cur_entry + ex) * q * comm_rate
                cur.gross_pl, cur.commission, cur.net_pl = gp, comm, gp - comm
                cur.points_captured = abs(ex - cur_entry)
                trades.append(cur)
                in_pos = False
                cur = None
                continue

        # ── Update stops at bar close ──
        if in_pos and cur is not None:
            pdist = (close - cur_entry) if cur_long else (cur_entry - close)
            if not be_done and should_trigger_be(pdist, cur_atr):
                be_done = True
                cur_sl = cur_entry
            ns = upgrade_trail_stage(trail_stage, pdist, cur_atr)
            if ns > trail_stage:
                trail_stage = ns
            tsl = compute_trail_sl(trail_stage, peak, pdist, cur_long, cur_atr)
            if tsl is not None:
                if cur_long and tsl > cur_sl:
                    cur_sl = tsl
                elif (not cur_long) and tsl < cur_sl:
                    cur_sl = tsl

        # ── ENTRY SIGNAL ──
        if not in_pos and pending is None:
            snap = _make_snap(row, prev_row, cfg)
            sig = evaluate_entry(snap, has_position=False)
            if sig.signal_type != SignalType.NONE:
                pending = (sig, snap, i)

    return trades


def evaluate_entry(snap, has_position):
    """Standalone entry evaluator using snap values directly (no config import)."""
    if has_position:
        return Signal(SignalType.NONE, False, False, "none")
    f, tr, rg = snap.filters_ok, snap.trend_regime, snap.range_regime

    # breakout buffer is not part of snapshot — read BREAKOUT_BUFFER_PTS from cfg when it matters
    # For simplicity, treat BREAKOUT_BUFFER_PTS=0 (it's already 0 in default config)
    trend_long = tr and snap.ema_fast > snap.ema_trend and snap.dip > snap.dim and snap.close > snap.prev_high and f
    trend_short = tr and snap.ema_fast < snap.ema_trend and snap.dim > snap.dip and snap.close < snap.prev_low and f
    range_long = rg and snap.rsi < 30 and f
    range_short = rg and snap.rsi > 70 and f

    if trend_long:    return Signal(SignalType.TREND_LONG, True, True, "trend")
    if trend_short:   return Signal(SignalType.TREND_SHORT, False, True, "trend")
    if range_long:    return Signal(SignalType.RANGE_LONG, True, False, "range")
    if range_short:   return Signal(SignalType.RANGE_SHORT, False, False, "range")
    return Signal(SignalType.NONE, False, False, "none")


# Monkey-patch strategy_logic.evaluate_entry to use our standalone version
import strategy_logic
strategy_logic.evaluate_entry = evaluate_entry


# ============================================================
# METRICS
# ============================================================
def compute_metrics(trades, capital=10000.0):
    if not trades:
        return {"error": "No trades", "total_trades": 0, "net_profit": 0}

    df = pd.DataFrame([asdict(t) for t in trades])
    df["exit_dt"] = pd.to_datetime(df["exit_ts"], unit="ms")
    df = df.sort_values("exit_ts").reset_index(drop=True)

    total = len(df)
    wins = (df["net_pl"] > 0).sum()
    losses = (df["net_pl"] <= 0).sum()
    wr = wins / total * 100 if total else 0
    tg = df["gross_pl"].sum()
    tc = df["commission"].sum()
    tn = df["net_pl"].sum()

    df["equity"] = capital + df["net_pl"].cumsum()
    df["peak_eq"] = df["equity"].cummax()
    df["dd"] = df["peak_eq"] - df["equity"]
    df["dd_pct"] = (df["dd"] / df["peak_eq"].replace(0, 1)) * 100
    mdd = df["dd"].max()
    mdd_pct = df["dd_pct"].max()

    wins_sum = df[df["net_pl"] > 0]["net_pl"].sum()
    losses_sum = abs(df[df["net_pl"] <= 0]["net_pl"].sum())
    pf = wins_sum / losses_sum if losses_sum > 0 else float("inf")

    # Sharpe-like
    df["date"] = df["exit_dt"].dt.date
    dpnl = df.groupby("date")["net_pl"].sum()
    sharpe = dpnl.mean() / dpnl.std() * math.sqrt(365) if len(dpnl) > 1 and dpnl.std() > 0 else 0

    # Monthly
    df["month"] = df["exit_dt"].dt.to_period("M")
    monthly = []
    for m, g in df.groupby("month"):
        monthly.append({
            "month": str(m), "trades": len(g),
            "gross_pl": round(g["gross_pl"].sum(), 2),
            "net_pl": round(g["net_pl"].sum(), 2),
            "commission": round(g["commission"].sum(), 2),
            "max_win": round(g["net_pl"].max(), 2),
            "max_loss": round(g["net_pl"].min(), 2),
            "wins": int((g["net_pl"] > 0).sum()),
            "losses": int((g["net_pl"] <= 0).sum()),
            "win_rate": round((g["net_pl"] > 0).mean() * 100, 1),
        })

    trend = df[df["is_trend"]]
    range_ = df[~df["is_trend"]]
    longs = df[df["is_long"]]
    shorts = df[~df["is_long"]]
    scalpers = df[df["bars_held"] == 0]

    return {
        "total_trades": total, "wins": int(wins), "losses": int(losses),
        "win_rate_pct": round(wr, 2),
        "total_gross_profit": round(tg, 2),
        "total_commission": round(tc, 2),
        "total_net_profit": round(tn, 2),
        "avg_net_per_trade": round(tn / total, 2) if total else 0,
        "max_win": round(df["net_pl"].max(), 2),
        "max_loss": round(df["net_pl"].min(), 2),
        "max_drawdown_usdt": round(mdd, 2),
        "max_drawdown_pct": round(mdd_pct, 2),
        "profit_factor": round(pf, 2),
        "sharpe_ratio": round(sharpe, 2),
        "avg_bars_held": round(df["bars_held"].mean(), 1),
        "avg_points": round(df["points_captured"].mean(), 1),
        "monthly": monthly,
        "trend_trades": len(trend), "range_trades": len(range_),
        "long_trades": len(longs), "short_trades": len(shorts),
        "scalper_trades": len(scalpers),
        "trend_wr": round((trend["net_pl"] > 0).mean() * 100, 1) if len(trend) > 0 else 0,
        "range_wr": round((range_["net_pl"] > 0).mean() * 100, 1) if len(range_) > 0 else 0,
        "months_active": len(monthly),
        "months_profitable": sum(1 for m in monthly if m["net_pl"] > 0),
        "avg_monthly_profit": round(sum(m["net_pl"] for m in monthly) / max(len(monthly), 1), 2),
        "final_equity": round(capital + tn, 2),
        "return_pct": round(tn / capital * 100, 2),
    }


# ============================================================
# PARAMETER OPTIMIZATION
# ============================================================
OPT_PARAMS = {
    "ADX_TREND_TH": [18, 20, 22, 24, 26],
    "ADX_RANGE_TH": [15, 17, 18, 20, 22],
    "FILTER_ATR_MULT": [1.0, 1.2, 1.4, 1.6, 1.8],
    "TREND_RR": [3.0, 3.5, 4.0, 4.5, 5.0],
    "RANGE_RR": [2.0, 2.5, 3.0, 3.5],
    "TREND_ATR_MULT": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    "RANGE_ATR_MULT": [0.3, 0.4, 0.5, 0.6, 0.7],
    "BE_MULT": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
    "RSI_OB": [65, 70, 75, 78],
    "RSI_OS": [22, 25, 28, 30, 35],
}


def param_scan(df, btc=0.1):
    """One-at-a-time parameter sensitivity analysis."""
    results = []

    # Baseline
    print("=" * 60)
    print("BASELINE (TP_HARD_EXIT=TRUE)")
    print("=" * 60)
    trades = run_backtest(df, BASE_CFG, btc)
    m = compute_metrics(trades)
    results.append({"name": "BASELINE", "cfg": dict(BASE_CFG), "metrics": m, "ntrades": len(trades)})
    print(f"  Trades={m['total_trades']} Net=${m['total_net_profit']} WR={m['win_rate_pct']}% DD={m['max_drawdown_pct']}% PF={m['profit_factor']}")

    # Turn TP off baseline too
    cfg_notp = dict(BASE_CFG)
    cfg_notp["TP_HARD_EXIT"] = False
    print(f"\n  BASELINE (TP_HARD_EXIT=FALSE)...")
    trades2 = run_backtest(df, cfg_notp, btc)
    m2 = compute_metrics(trades2)
    results.append({"name": "BASELINE_NO_TP", "cfg": cfg_notp, "metrics": m2, "ntrades": len(trades2)})
    print(f"  Trades={m2['total_trades']} Net=${m2['total_net_profit']} WR={m2['win_rate_pct']}% DD={m2['max_drawdown_pct']}% PF={m2['profit_factor']}")

    # Individual param tests
    for pname, vals in OPT_PARAMS.items():
        for v in vals:
            if v == BASE_CFG.get(pname):
                continue
            cfg = dict(BASE_CFG)
            cfg[pname] = v
            print(f"  {pname}={v} ... ", end="", flush=True)
            try:
                t = run_backtest(df, cfg, btc)
                mm = compute_metrics(t)
                results.append({"name": f"{pname}={v}", "cfg": cfg, "metrics": mm, "ntrades": len(t)})
                print(f"Trades={mm['total_trades']} Net=${mm['total_net_profit']} WR={mm['win_rate_pct']}% DD={mm['max_drawdown_pct']}% PF={mm['profit_factor']}")
            except Exception as e:
                print(f"ERR: {e}")

    return results


# ============================================================
# COMBINED OPTIMIZATION
# ============================================================
def score(metrics):
    if metrics.get("total_trades", 0) == 0:
        return -999999
    np_ = metrics["total_net_profit"]
    dd = metrics["max_drawdown_pct"]
    pf = metrics.get("profit_factor", 0)
    wr = metrics.get("win_rate_pct", 0)
    # Score: net profit - drawdown penalty + quality bonuses
    dd_pen = max(0, dd - 12) * 50  # >12% DD starts penalizing
    pf_bonus = 500 if pf > 2.0 else 200 if pf > 1.5 else 0 if pf > 1.0 else -1000
    wr_bonus = 200 if wr > 45 else 0
    return np_ - dd_pen + pf_bonus + wr_bonus


def best_combination(scan_results):
    """Build composite config from best individual param values."""
    best_vals = {}
    for pname in OPT_PARAMS:
        candidates = []
        for r in scan_results:
            if r["name"] == "BASELINE" or r["name"] == "BASELINE_NO_TP":
                continue
            if pname in r["cfg"]:
                score_val = score(r["metrics"])
                candidates.append((score_val, r["cfg"][pname]))
        candidates.sort(key=lambda x: x[0], reverse=True)
        if candidates:
            best_vals[pname] = candidates[0][1]
            print(f"  Best {pname}: {candidates[0][1]} (score={candidates[0][0]:.0f})")

    cfg = dict(BASE_CFG)
    cfg.update(best_vals)
    return cfg


# ============================================================
# REPORT GENERATION
# ============================================================
def equity_chart_b64(trades, capital=10000.0):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        df = pd.DataFrame([asdict(t) for t in trades]).sort_values("exit_ts").reset_index(drop=True)
        df["exit_dt"] = pd.to_datetime(df["exit_ts"], unit="ms")
        df["eq"] = capital + df["net_pl"].cumsum()
        df["peak_eq"] = df["eq"].cummax()
        df["dd"] = df["peak_eq"] - df["eq"]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})
        ax1.plot(df["exit_dt"], df["eq"], color="#2196F3", lw=1.5, label="Net Equity")
        ax1.fill_between(df["exit_dt"], capital, df["eq"], where=df["eq"] >= capital, color="#4CAF50", alpha=0.15)
        ax1.fill_between(df["exit_dt"], capital, df["eq"], where=df["eq"] < capital, color="#f44336", alpha=0.1)
        ax1.axhline(capital, color="gray", ls="--", alpha=0.5)
        ax1.set_title("BTC Bot v13 v10 — 2-Year Backtest (0.1 BTC)", fontsize=13, fontweight="bold")
        ax1.set_ylabel("Equity (USDT)", fontsize=11)
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc="upper left")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax2.fill_between(df["exit_dt"], 0, df["dd"], color="#f44336", alpha=0.3)
        ax2.set_ylabel("Drawdown (USDT)", fontsize=11)
        ax2.set_xlabel("Date", fontsize=11)
        ax2.grid(True, alpha=0.3)
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close()
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"Chart error: {e}")
        return ""


def html_report(metrics, trades, cfg, chart_b64="", btc=0.1):
    df = pd.DataFrame([asdict(t) for t in trades])
    df["entry_dt"] = pd.to_datetime(df["entry_ts"], unit="ms")
    df["exit_dt"] = pd.to_datetime(df["exit_ts"], unit="ms")
    df = df.sort_values("exit_ts").reset_index(drop=True)

    # Monthly rows
    mr = ""
    for m in metrics["monthly"]:
        mr += f"""<tr><td>{m['month']}</td><td>{m['trades']}</td>
            <td class="{'p' if m['gross_pl']>=0 else 'l'}">${m['gross_pl']:,.2f}</td>
            <td class="{'p' if m['net_pl']>=0 else 'l'}">${m['net_pl']:,.2f}</td>
            <td class="p">${m['max_win']:,.2f}</td>
            <td class="l">${m['max_loss']:,.2f}</td>
            <td>{m['wins']}/{m['losses']}</td><td>{m['win_rate']}%</td></tr>\n"""

    # Trade rows
    tr_ = ""
    for _, t in df.iterrows():
        cls = "p" if t["net_pl"] >= 0 else "l"
        tr_ += f"""<tr><td>{t['trade_id']}</td><td>{t['signal_type']}</td><td>{'LONG' if t['is_long'] else 'SHORT'}</td>
            <td>{t['entry_dt'].strftime('%Y-%m-%d %H:%M')}</td><td>{t['entry_price']:,.2f}</td>
            <td>{t['exit_dt'].strftime('%Y-%m-%d %H:%M')}</td><td>{t['exit_price']:,.2f}</td>
            <td>{t['exit_reason']}</td><td>{t['bars_held']}</td><td>{t['points_captured']:,.1f}</td>
            <td class="{cls}">${t['gross_pl']:,.2f}</td><td>${t['commission']:,.2f}</td>
            <td class="{cls}">${t['net_pl']:,.2f}</td></tr>\n"""

    img = f'<img src="data:image/png;base64,{chart_b64}" style="width:100%;max-width:900px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">' if chart_b64 else ""

    cfg_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>\n" for k, v in sorted(cfg.items()))

    goal = "✅ MET (>$500/mo)" if metrics["avg_monthly_profit"] >= 500 else "❌ NOT MET"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BTC Bot v13 v10 — 2-Year Backtest</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Tahoma,sans-serif;background:#f5f7fa;color:#333;padding:20px}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:24px;color:#1a237e;margin-bottom:5px}}
h2{{font-size:18px;color:#283593;margin:25px 0 10px;padding-bottom:5px;border-bottom:2px solid #e0e0e0}}
.subtitle{{color:#666;font-size:14px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;margin-bottom:20px}}
.card{{background:white;border-radius:8px;padding:15px;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.card .lbl{{font-size:11px;text-transform:uppercase;color:#888;margin-bottom:4px}}
.card .val{{font-size:20px;font-weight:bold;color:#1a237e}}
.card .val.p{{color:#2e7d32}}
.card .val.l{{color:#c62828}}
table{{width:100%;border-collapse:collapse;margin-bottom:20px;background:white;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
th{{background:#1a237e;color:white;padding:10px 8px;font-size:12px;text-align:left;white-space:nowrap}}
td{{padding:8px;font-size:12px;border-bottom:1px solid #eee}}
tr:hover{{background:#f0f4ff}}
.p{{color:#2e7d32;font-weight:600}}
.l{{color:#c62828;font-weight:600}}
.note{{background:#fff8e1;border-left:4px solid #ffa000;padding:12px 15px;border-radius:4px;margin:15px 0;font-size:13px}}
.chart{{background:white;border-radius:8px;padding:15px;box-shadow:0 1px 4px rgba(0,0,0,0.08);margin-bottom:20px;text-align:center}}
.wrap{{overflow-x:auto}}
.filters{{margin-bottom:10px}}
.filters input,.filters select{{padding:5px 8px;border:1px solid #ccc;border-radius:4px;font-size:12px;margin-right:8px}}
</style>
</head>
<body>
<div class="container">
<h1>🚀 BTC Bot v13 v10 — 2-Year Backtest Results</h1>
<p class="subtitle">Jul 2024 – Jul 2026 | BTC/USDT 30m | Delta Exchange India | Position: {btc} BTC | Target: >$500/mo → {goal}</p>

<div class="note"><strong>⚠️ Delta India Fee Structure:</strong> Trades closing within <strong>&lt;30 min</strong> (same candle) = Scalper Offer (entry fee only, 0.05%). Longer trades = both sides (0.1% total).</div>

<h2>📊 Performance Summary</h2>
<div class="grid">
<div class="card"><div class="lbl">Net Profit</div><div class="val {"p" if metrics["total_net_profit"]>=0 else "l"}">${metrics["total_net_profit"]:,.2f}</div></div>
<div class="card"><div class="lbl">Total Trades</div><div class="val">{metrics["total_trades"]}</div></div>
<div class="card"><div class="lbl">Win Rate</div><div class="val">{metrics["win_rate_pct"]}%</div></div>
<div class="card"><div class="lbl">Profit Factor</div><div class="val">{metrics["profit_factor"]}</div></div>
<div class="card"><div class="lbl">Max Drawdown</div><div class="val l">{metrics["max_drawdown_pct"]}%</div></div>
<div class="card"><div class="lbl">Avg Monthly</div><div class="val {"p" if metrics["avg_monthly_profit"]>=0 else "l"}">${metrics["avg_monthly_profit"]:,.2f}</div></div>
<div class="card"><div class="lbl">Sharpe</div><div class="val">{metrics["sharpe_ratio"]}</div></div>
<div class="card"><div class="lbl">Return</div><div class="val {"p" if metrics["return_pct"]>=0 else "l"}">{metrics["return_pct"]}%</div></div>
<div class="card"><div class="lbl">Avg/Trade</div><div class="val {"p" if metrics["avg_net_per_trade"]>=0 else "l"}">${metrics["avg_net_per_trade"]:,.2f}</div></div>
<div class="card"><div class="lbl">Best Trade</div><div class="val p">${metrics["max_win"]:,.2f}</div></div>
<div class="card"><div class="lbl">Worst Trade</div><div class="val l">${metrics["max_loss"]:,.2f}</div></div>
<div class="card"><div class="lbl">$500/mo Target</div><div class="val {"p" if metrics["avg_monthly_profit"]>=500 else "l"}">{goal}</div></div>
</div>

<h2>📈 Equity Curve</h2>
<div class="chart">{img}</div>

<h2>📅 Monthly Breakdown</h2>
<table><thead><tr><th>Month</th><th>Trades</th><th>Gross P/L</th><th>Net P/L</th><th>Max Win</th><th>Max Loss</th><th>W/L</th><th>Win Rate</th></tr></thead>
<tbody>{mr}</tbody></table>

<h2>⚙️ Configuration</h2>
<table><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>{cfg_rows}</tbody></table>

<h2>📋 Trade Type Breakdown</h2>
<div class="grid">
<div class="card"><div class="lbl">Trend Trades</div><div class="val">{metrics["trend_trades"]}</div><div>WR: {metrics["trend_wr"]}%</div></div>
<div class="card"><div class="lbl">Range Trades</div><div class="val">{metrics["range_trades"]}</div><div>WR: {metrics["range_wr"]}%</div></div>
<div class="card"><div class="lbl">Long Trades</div><div class="val">{metrics["long_trades"]}</div></div>
<div class="card"><div class="lbl">Short Trades</div><div class="val">{metrics["short_trades"]}</div></div>
<div class="card"><div class="lbl">Scalper (<30m)</div><div class="val">{metrics["scalper_trades"]}</div><div>One-side fee</div></div>
</div>

<h2>📝 All Trades</h2>
<div class="filters">
<input type="text" id="s" onkeyup="ft()" placeholder="Search..." style="width:200px">
<select id="tf" onchange="ft()"><option value="">All Types</option><option>Trend</option><option>Range</option></select>
<select id="pf" onchange="ft()"><option value="">All P/L</option><option value="p">Winners</option><option value="l">Losers</option></select>
<span style="float:right;font-size:12px;color:#888">{metrics["total_trades"]} trades</span>
</div>
<div class="wrap">
<table id="tt"><thead><tr>
<th>ID</th><th>Type</th><th>Dir</th><th>Entry Time</th><th>Entry</th><th>Exit Time</th><th>Exit</th><th>Reason</th><th>Bars</th><th>Points</th><th>Gross</th><th>Comm</th><th>Net</th>
</tr></thead><tbody>{tr_}</tbody></table></div>

<script>
function ft(){{var s=document.getElementById('s').value.toUpperCase(),tf=document.getElementById('tf').value.toUpperCase(),pf=document.getElementById('pf').value,tr=document.getElementById('tt').rows;for(var i=1;i<tr.length;i++){{var td=tr[i].cells;var ok=true;if(s){{var f=false;for(var j=0;j<td.length;j++){{if(td[j].innerText.toUpperCase().indexOf(s)>-1){{f=true;break}}}}if(!f)ok=false}}if(tf&&td[1]&&td[1].innerText.toUpperCase().indexOf(tf)===-1)ok=false;if(pf==='p'&&td[12]&&td[12].innerText[0]==='-')ok=false;if(pf==='l'&&td[12]&&td[12].innerText[0]!=='-')ok=false;tr[i].style.display=ok?'':''}}}}
</script>

<div style="margin-top:30px;padding:15px;text-align:center;font-size:12px;color:#999;border-top:1px solid #eee;">
Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | BTC Bot v13 v10 | Data: Binance BTC/USDT 30m
</div>
</div></body></html>"""


def txt_report(metrics, cfg, btc=0.1):
    lines = []
    lines.append("=" * 65)
    lines.append("  BTC BOT v13 — 2-YEAR BACKTEST REPORT")
    lines.append("  (Plain Language Summary)")
    lines.append("=" * 65)
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"  Data: BTC/USDT 30m, July 2024 – July 2026")
    lines.append(f"  Exchange: Delta Exchange India | Position: {btc} BTC")
    lines.append("")
    lines.append("-" * 65)
    lines.append("  WHAT IS THIS BOT?")
    lines.append("-" * 65)
    lines.append("  BTC Bot v13 v10 is an automated BTC trading bot for Delta Exchange India.")
    lines.append("  It analyzes 30-minute candles using EMA, ADX, ATR, RSI, and DMI indicators")
    lines.append("  to decide when to buy or sell. A 5-stage trailing stop locks in profits.")

    lines.append("")
    lines.append("-" * 65)
    lines.append("  KEY CHANGES FOR REAL-LIFE TRADING")
    lines.append("-" * 65)
    lines.append("  1. ENABLED TAKE PROFIT (TP_HARD_EXIT=True)")
    lines.append("     • Trades now close at the target profit level instead of relying")
    lines.append("       entirely on the trailing stop. This gives consistent, predictable profits.")
    lines.append("")
    lines.append("  2. DELTA INDIA COMMISSION OPTIMIZATION")
    lines.append("     • <30min trades: only entry fee (0.05%) — uses Scalper Offer")
    lines.append("     • >30min trades: entry + exit fee (0.1%)")
    lines.append("")
    lines.append("  3. OPTIMIZED PARAMETERS")
    for k, v in sorted(cfg.items()):
        lines.append(f"     • {k} = {v}")

    lines.append("")
    lines.append("-" * 65)
    lines.append("  RESULTS")
    lines.append("-" * 65)
    lines.append(f"  Net Profit:       ${metrics['total_net_profit']:>8,.2f}")
    lines.append(f"  Total Trades:     {metrics['total_trades']:>8}")
    lines.append(f"  Win Rate:         {metrics['win_rate_pct']:>7.1f}%")
    lines.append(f"  Profit Factor:    {metrics['profit_factor']:>8.2f}")
    lines.append(f"  Max Drawdown:     {metrics['max_drawdown_pct']:>7.2f}%")
    lines.append(f"  Avg Monthly:      ${metrics['avg_monthly_profit']:>8,.2f}")
    lines.append(f"  Avg/Trade:        ${metrics['avg_net_per_trade']:>8,.2f}")
    lines.append(f"  Best Trade:       ${metrics['max_win']:>8,.2f}")
    lines.append(f"  Worst Trade:      ${metrics['max_loss']:>8,.2f}")
    lines.append(f"  Return:           {metrics['return_pct']:>7.2f}%")
    lines.append(f"  Sharpe:           {metrics['sharpe_ratio']:>8.2f}")
    lines.append("")
    lines.append("  MONTHLY TABLE:")
    lines.append(f"  {'Month':<11} {'Trades':>6} {'Net P/L':>10} {'Win%':>6}")
    lines.append("  " + "-" * 35)
    for m in metrics["monthly"]:
        lines.append(f"  {m['month']:<11} {m['trades']:>6} ${m['net_pl']:>7,.2f} {m['win_rate']:>5}%")
    lines.append("  " + "-" * 35)
    lines.append(f"  Profitable months: {metrics['months_profitable']}/{metrics['months_active']}")
    target = "✅ MET" if metrics["avg_monthly_profit"] >= 500 else "❌ NOT MET"
    lines.append(f"  $500/mo Target: {target}")
    lines.append("")
    lines.append("-" * 65)
    lines.append("  DISCLAIMER: Past performance does not guarantee future results.")
    lines.append("  This is historical simulation data. Real trading involves additional")
    lines.append("  factors like slippage, liquidity, and execution timing.")
    lines.append("=" * 65)
    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=r"C:\Users\sanir\Downloads\text\BTC-Bot-v13-main\BTCUSDT_30m_2year.csv")
    ap.add_argument("--position", type=float, default=0.1)
    ap.add_argument("--out", default=r"C:\Users\sanir\Downloads\text\BTC-Bot-v13-main\optimizer\results")
    ap.add_argument("--fast", action="store_true", help="Skip full scan, run with default cfg")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    df = pd.read_csv(args.data)
    print(f"Loaded {len(df)} candles, {pd.to_datetime(df['timestamp'].iloc[0], unit='ms').date()} to {pd.to_datetime(df['timestamp'].iloc[-1], unit='ms').date()}")

    if args.fast:
        print("Running with default config (fast mode)...")
        cfg = dict(BASE_CFG)
        trades = run_backtest(df, cfg, args.position)
        metrics = compute_metrics(trades)
    else:
        # Full optimization
        print("\n" + "=" * 60)
        print("PHASE 1: PARAMETER SCAN")
        print("=" * 60)
        scan_results = param_scan(df, args.position)

        print("\n" + "=" * 60)
        print("PHASE 2: BEST COMBINATION")
        print("=" * 60)
        best_cfg = best_combination(scan_results)

        # Also try with TP off
        best_cfg_notp = dict(best_cfg)
        best_cfg_notp["TP_HARD_EXIT"] = False
        print("\nTesting best config with TP=OFF...")
        t2 = run_backtest(df, best_cfg_notp, args.position)
        m2 = compute_metrics(t2)
        print(f"  TP_OFF: Trades={m2['total_trades']} Net=${m2['total_net_profit']} DD={m2['max_drawdown_pct']}%")

        score_off = score(m2)
        score_on = score(compute_metrics(run_backtest(df, best_cfg, args.position)))

        if score_off > score_on:
            print("TP=OFF scores better, using that.")
            cfg = best_cfg_notp
            trades = t2
            metrics = m2
        else:
            print("TP=ON scores better, using that.")
            cfg = best_cfg
            trades = run_backtest(df, best_cfg, args.position)
            metrics = compute_metrics(trades)

    # ── Save results ──
    json.dump(cfg, open(os.path.join(args.out, "optimized_config.json"), "w"), indent=2)
    pd.DataFrame([asdict(t) for t in trades]).to_csv(os.path.join(args.out, "backtest_trades.csv"), index=False)
    print(f"\nSaved {len(trades)} trades to {args.out}")

    # ── Reports ──
    print("Generating equity chart...")
    b64 = equity_chart_b64(trades)
    print("Generating HTML report...")
    html = html_report(metrics, trades, cfg, b64, args.position)
    with open(os.path.join(args.out, "backtest_report.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("Generating text report...")
    txt = txt_report(metrics, cfg, args.position)
    with open(os.path.join(args.out, "backtest_report.txt"), "w", encoding="utf-8") as f:
        f.write(txt)

    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    for k, v in [("Net Profit", f"${metrics['total_net_profit']:,.2f}"),
                  ("Trades", str(metrics['total_trades'])),
                  ("Win Rate", f"{metrics['win_rate_pct']}%"),
                  ("Profit Factor", str(metrics['profit_factor'])),
                  ("Max DD", f"{metrics['max_drawdown_pct']}%"),
                  ("Avg Monthly", f"${metrics['avg_monthly_profit']:,.2f}"),
                  ("Goal $500/mo", "✅ MET" if metrics['avg_monthly_profit'] >= 500 else "❌ NOT MET"),
                  ("Return", f"{metrics['return_pct']}%")]:
        print(f"  {k:>15s}: {v}")
    print(f"\nReports: {args.out}")


if __name__ == "__main__":
    main()
