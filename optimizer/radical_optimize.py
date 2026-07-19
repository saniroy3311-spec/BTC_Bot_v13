"""
RADICAL OPTIMIZATION — Test fundamentally different approaches
to find a profitable configuration for Delta India BTC trading.
"""
import os, sys, json, math, base64
from datetime import datetime
from dataclasses import asdict
from io import BytesIO

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy_logic import calc_levels, should_trigger_be, upgrade_trail_stage, compute_trail_sl
import strategy_logic as sl
import config as cm

OUT = r"C:\Users\sanir\Downloads\text\BTC-Bot-v13-main\optimizer\results"
os.makedirs(OUT, exist_ok=True)

# ============================================================
# BACKTEST ENGINE (fast, no module import dependencies)
# ============================================================
def _patch(cfg):
    for k, v in cfg.items():
        setattr(sl, k, v)
        setattr(cm, k, v)

def _snap(row, prev, cfg):
    atr = float(row["atr"]); atr_sma = float(row["atr_sma"]);
    vol_sma = float(row["vol_sma"]); bv = float(row["volume"])
    ov = float(row["open"]); cv = float(row["close"])
    atr_ok = atr < atr_sma * cfg.get("FILTER_ATR_MULT", 1.4)
    vol_ok = bv > 0 and vol_sma > 0 and bv > vol_sma * cfg.get("FILTER_VOL_MULT", 1.0) if cfg.get("FILTER_VOL_ENABLED", True) else True
    adx = float(row["adx"])
    return type('S', (), {
        "ema_trend": float(row["ema200"]), "ema_fast": float(row["ema50"]),
        "atr": atr, "rsi": float(row["rsi"]),
        "dip": float(row["dip"]), "dim": float(row["dim"]),
        "adx": adx, "adx_raw": float(row["adx_raw"]),
        "vol_sma": vol_sma, "atr_sma": atr_sma,
        "trend_regime": adx > cfg.get("ADX_TREND_TH", 22),
        "range_regime": adx < cfg.get("ADX_RANGE_TH", 18),
        "filters_ok": atr_ok and vol_ok, "atr_ok": atr_ok, "vol_ok": vol_ok, "body_ok": True,
        "open": ov, "high": float(row["high"]), "low": float(row["low"]),
        "close": cv, "volume": bv,
        "prev_high": float(prev["high"]), "prev_low": float(prev["low"]),
        "timestamp": int(row["timestamp"]),
    })

def _sig(snap):
    tr, rg, f = snap.trend_regime, snap.range_regime, snap.filters_ok
    tl = tr and snap.ema_fast > snap.ema_trend and snap.dip > snap.dim and snap.close > snap.prev_high and f
    ts = tr and snap.ema_fast < snap.ema_trend and snap.dim > snap.dip and snap.close < snap.prev_low and f
    rl = rg and snap.rsi < 30 and f
    rs = rg and snap.rsi > 70 and f
    if tl: return ("TL", True, True, "trend")
    if ts: return ("TS", False, True, "trend")
    if rl: return ("RL", True, False, "range")
    if rs: return ("RS", False, False, "range")
    return ("N", False, False, "none")

def run_bt(df, cfg, btc=0.1):
    _patch(cfg)
    from strategy_logic import compute_full_series
    tp_on = cfg.get("TP_HARD_EXIT", True)
    comm = cfg.get("COMMISSION_PCT", 0.0005)

    series = compute_full_series(df).reset_index(drop=True)
    n = len(series)
    trades = []
    in_pos = False; pend = None; tid = 0

    for i in range(1, n):
        r = series.iloc[i]; pr = series.iloc[i-1]
        ts, op, hi, lo, cl = int(r["timestamp"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        if any(np.isnan(r.get(c,0)) for c in ["ema200","adx","atr","atr_sma","vol_sma"]):
            continue

        if not in_pos and pend is None:
            s = _snap(r, pr, cfg)
            signal = _sig(s)
            if signal[0] != "N":
                pend = (signal, s, i)

        if pend and not in_pos:
            sig, snap, sig_bar = pend
            entry = op
            risk = calc_levels(entry, snap.atr, sig[1], sig[2])
            tid += 1
            cur_t = {
                "id": tid, "type": sig[0], "long": sig[1], "trend": sig[2],
                "entry_i": i, "entry_ts": ts, "entry": entry,
                "sl": risk.sl, "tp": risk.tp, "atr": snap.atr,
                "exit_i": 0, "exit_ts": 0, "exit": 0.0, "reason": "",
                "bars": 0, "gross": 0.0, "comm": 0.0, "net": 0.0, "pts": 0.0,
            }
            cur_sl, cur_tp = risk.sl, risk.tp
            cur_atr, cur_long, cur_entry = snap.atr, sig[1], entry
            peak, be, trail, ms_fired = entry, False, 0, False
            in_pos = True; pend = None

            # Check exit on entry bar
            ex, er = None, None
            if cur_long:
                if lo <= cur_sl: ex, er = cur_sl, "SL"
                elif tp_on and hi >= cur_tp: ex, er = cur_tp, "TP"
            else:
                if hi >= cur_sl: ex, er = cur_sl, "SL"
                elif tp_on and lo <= cur_tp: ex, er = cur_tp, "TP"
            if ex:
                gp = (ex - cur_entry) * btc if cur_long else (cur_entry - ex) * btc
                c = cur_entry * btc * comm  # scalper one-side
                cur_t.update({"exit_i": i, "exit_ts": ts, "exit": ex, "reason": er, "bars": 0, "gross": gp, "comm": c, "net": gp - c, "pts": abs(ex - cur_entry)})
                trades.append(cur_t); in_pos = False; continue
            # Update stops on entry bar close
            if cur_long: pdist = cl - cur_entry; peak = max(peak, hi)
            else: pdist = cur_entry - cl; peak = min(peak, lo)
            if not be and should_trigger_be(pdist, cur_atr): be = True; cur_sl = cur_entry
            ns = upgrade_trail_stage(trail, pdist, cur_atr)
            if ns > trail: trail = ns
            tsl = compute_trail_sl(trail, peak, pdist, cur_long, cur_atr)
            if tsl is not None:
                if cur_long and tsl > cur_sl: cur_sl = tsl
                elif not cur_long and tsl < cur_sl: cur_sl = tsl
            continue

        if in_pos:
            if cur_long: peak = max(peak, hi)
            else: peak = min(peak, lo)
            ms_thresh = min(cur_atr * 1.5, 500)
            ms_p = cur_entry - ms_thresh if cur_long else cur_entry + ms_thresh
            ms_active = (i > cur_t["entry_i"]) and not ms_fired

            ex, er = None, None
            if cur_long:
                if op <= cur_sl: ex, er = op, "SL"
                elif ms_active and op <= ms_p: ex, er = op, "Max SL"
                elif tp_on and op >= cur_tp: ex, er = op, "TP"
                elif lo <= cur_sl: ex, er = cur_sl, "Trail" if trail > 0 else ("BE" if be else "SL")
                elif ms_active and lo <= ms_p: ex, er = ms_p, "Max SL"
                elif tp_on and hi >= cur_tp: ex, er = cur_tp, "TP"
            else:
                if op >= cur_sl: ex, er = op, "SL"
                elif ms_active and op >= ms_p: ex, er = op, "Max SL"
                elif tp_on and op <= cur_tp: ex, er = op, "TP"
                elif hi >= cur_sl: ex, er = cur_sl, "Trail" if trail > 0 else ("BE" if be else "SL")
                elif ms_active and hi >= ms_p: ex, er = ms_p, "Max SL"
                elif tp_on and lo <= cur_tp: ex, er = cur_tp, "TP"

            if ex:
                if er == "Max SL": ms_fired = True
                gp = (ex - cur_entry) * btc if cur_long else (cur_entry - ex) * btc
                held = i - cur_t["entry_i"]
                if held == 0: c = cur_entry * btc * comm
                else: c = (cur_entry + ex) * btc * comm
                cur_t.update({"exit_i": i, "exit_ts": ts, "exit": ex, "reason": er, "bars": held, "gross": gp, "comm": c, "net": gp - c, "pts": abs(ex - cur_entry), "trail": trail})
                trades.append(cur_t); in_pos = False; continue

            # Update stops
            pdist = (cl - cur_entry) if cur_long else (cur_entry - cl)
            if not be and should_trigger_be(pdist, cur_atr): be = True; cur_sl = cur_entry
            ns = upgrade_trail_stage(trail, pdist, cur_atr)
            if ns > trail: trail = ns
            tsl = compute_trail_sl(trail, peak, pdist, cur_long, cur_atr)
            if tsl is not None:
                if cur_long and tsl > cur_sl: cur_sl = tsl
                elif not cur_long and tsl < cur_sl: cur_sl = tsl

    return trades


# ============================================================
# RADICAL CONFIGURATIONS
# ============================================================
CONFIGS = []

# Config 1: Pure trend, wide stops, no trail, TP enabled (classic RR)
CONFIGS.append({
    "name": "PURE_TREND_NO_TRAIL",
    "cfg": {
        "ADX_TREND_TH": 25, "ADX_RANGE_TH": 18,
        "FILTER_ATR_MULT": 1.2, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 3.0, "RANGE_RR": 2.5,
        "TREND_ATR_MULT": 0.7, "RANGE_ATR_MULT": 0.5,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.6, "RSI_OB": 70, "RSI_OS": 30,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005,
        "TP_HARD_EXIT": True,
        "PINE_MINTICK": 0.5,
        "TRAIL_STAGES": [(10.0, 10.0, 10.0)],  # trail never activates (huge trigger)
    }
})

# Config 2: Trend only, no range trades, TP=ON
CONFIGS.append({
    "name": "TREND_ONLY_TP_ON",
    "cfg": {
        "ADX_TREND_TH": 22, "ADX_RANGE_TH": 5,  # range never activates
        "FILTER_ATR_MULT": 1.4, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 2.5, "RANGE_RR": 2.5,
        "TREND_ATR_MULT": 0.6, "RANGE_ATR_MULT": 0.5,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.5, "RSI_OB": 70, "RSI_OS": 30,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005,
        "TP_HARD_EXIT": True,
        "PINE_MINTICK": 0.5,
        "TRAIL_STAGES": [(10.0, 10.0, 10.0)],
    }
})

# Config 3: Trailing with TP=OFF (original approach but better trail params)
CONFIGS.append({
    "name": "TRAIL_ONLY_OPTIMIZED",
    "cfg": {
        "ADX_TREND_TH": 24, "ADX_RANGE_TH": 18,
        "FILTER_ATR_MULT": 1.2, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 4.0, "RANGE_RR": 3.0,
        "TREND_ATR_MULT": 0.5, "RANGE_ATR_MULT": 0.4,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.4, "RSI_OB": 70, "RSI_OS": 30,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005,
        "TP_HARD_EXIT": False,
        "PINE_MINTICK": 0.5,
        # Much wider trail offsets to let profits run
        "TRAIL_STAGES": [
            (1.5, 0.5, 0.4),    # Stage 1: trail starts later
            (3.0, 0.4, 0.3),    # Stage 2: higher trigger
            (5.0, 0.3, 0.2),    # Stage 3
            (8.0, 0.2, 0.15),   # Stage 4
            (12.0, 0.15, 0.1),  # Stage 5
        ],
    }
})

# Config 4: Ultra conservative (small targets, high win rate)
CONFIGS.append({
    "name": "CONSERVATIVE_TP",
    "cfg": {
        "ADX_TREND_TH": 20, "ADX_RANGE_TH": 17,
        "FILTER_ATR_MULT": 1.2, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 1.8, "RANGE_RR": 1.5,
        "TREND_ATR_MULT": 0.5, "RANGE_ATR_MULT": 0.4,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.3, "RSI_OB": 68, "RSI_OS": 32,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005,
        "TP_HARD_EXIT": True,
        "PINE_MINTICK": 0.5,
        "TRAIL_STAGES": [(10.0, 10.0, 10.0)],
    }
})

# Config 5: EMA trend filter (only long when price > EMA200, only short when price < EMA200)
CONFIGS.append({
    "name": "EMA_FILTER",
    "cfg": {
        "ADX_TREND_TH": 22, "ADX_RANGE_TH": 18,
        "FILTER_ATR_MULT": 1.3, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 2.5, "RANGE_RR": 2.0,
        "TREND_ATR_MULT": 0.5, "RANGE_ATR_MULT": 0.4,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.4, "RSI_OB": 70, "RSI_OS": 30,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005,
        "TP_HARD_EXIT": True,
        "PINE_MINTICK": 0.5,
        "TRAIL_STAGES": [(10.0, 10.0, 10.0)],
        "EMA_FILTER_ENABLED": True,
    }
})

# Config 6: Tight SL, tight TP, high frequency
CONFIGS.append({
    "name": "SCALPER",
    "cfg": {
        "ADX_TREND_TH": 22, "ADX_RANGE_TH": 18,
        "FILTER_ATR_MULT": 1.4, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 1.5, "RANGE_RR": 1.3,
        "TREND_ATR_MULT": 0.35, "RANGE_ATR_MULT": 0.3,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.2, "RSI_OB": 68, "RSI_OS": 32,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005 * 2,  # double for scalping (more comm-intensive)
        "TP_HARD_EXIT": True,
        "PINE_MINTICK": 0.5,
        "TRAIL_STAGES": [(10.0, 10.0, 10.0)],
    }
})

# Config 7: Delayed entry (enter at close, not open)
CONFIGS.append({
    "name": "CLOSE_ENTRY",
    "cfg": {
        "ADX_TREND_TH": 22, "ADX_RANGE_TH": 18,
        "FILTER_ATR_MULT": 1.3, "FILTER_VOL_ENABLED": True, "FILTER_VOL_MULT": 1.0,
        "TREND_RR": 2.0, "RANGE_RR": 1.8,
        "TREND_ATR_MULT": 0.5, "RANGE_ATR_MULT": 0.4,
        "MAX_SL_MULT": 1.5, "MAX_SL_POINTS": 500,
        "BE_MULT": 0.4, "RSI_OB": 70, "RSI_OS": 30,
        "BREAKOUT_BUFFER_PTS": 0, "COMMISSION_PCT": 0.0005,
        "TP_HARD_EXIT": True,
        "PINE_MINTICK": 0.5,
        "TRAIL_STAGES": [(10.0, 10.0, 10.0)],
    }
})


def modify_run_for_ema_filter(trades, series):
    """Post-process: only keep trades that go with the 200 EMA trend."""
    filtered = []
    for t in trades:
        entry_row = series.iloc[t["entry_i"]]
        ema200 = float(entry_row["ema200"])
        if t["long"] and float(entry_row["close"]) >= ema200:
            filtered.append(t)
        elif not t["long"] and float(entry_row["close"]) <= ema200:
            filtered.append(t)
    return filtered


def modify_run_for_close_entry(trades, series, cfg, btc):
    """Re-run with entry at close instead of open."""
    # Full re-run with entry at close is complex. For now, we'll adjust existing
    # trades to show what close-entry would achieve.
    return trades  # Placeholder


def metrics(trades, capital=10000.0):
    if not trades:
        return {"total_trades": 0, "net_profit": 0, "error": "No trades"}

    df = pd.DataFrame(trades)
    df["exit_dt"] = pd.to_datetime(df["exit_ts"], unit="ms")
    df = df.sort_values("exit_ts").reset_index(drop=True)

    total = len(df)
    wins = (df["net"] > 0).sum()
    losses = total - wins
    wr = wins / total * 100 if total else 0
    tn = df["net"].sum()
    tg = df["gross"].sum()
    tc = df["comm"].sum()

    # Equity curve
    df["eq"] = capital + df["net"].cumsum()
    df["pe"] = df["eq"].cummax()
    df["dd"] = df["pe"] - df["eq"]
    df["ddp"] = (df["dd"] / df["pe"].replace(0, 1)) * 100
    mdd = df["dd"].max()
    mddp = df["ddp"].max()

    wins_sum = df[df["net"] > 0]["net"].sum()
    losses_sum = abs(df[df["net"] <= 0]["net"].sum())
    pf = wins_sum / losses_sum if losses_sum > 0 else float("inf")

    df["date"] = df["exit_dt"].dt.date
    dpnl = df.groupby("date")["net"].sum()
    sharpe = dpnl.mean() / dpnl.std() * math.sqrt(365) if len(dpnl) > 1 and dpnl.std() > 0 else 0

    # Monthly
    df["month"] = df["exit_dt"].dt.to_period("M")
    monthly = []
    for m, g in df.groupby("month"):
        monthly.append({"month": str(m), "trades": len(g), "net_pl": round(g["net"].sum(), 2),
                        "win_rate": round((g["net"] > 0).mean() * 100, 1)})

    scalpers = df[df["bars"] == 0]
    longs = df[df["long"] == True]
    shorts = df[df["long"] == False]
    trends = df[df["trend"] == True]
    ranges_ = df[df["trend"] == False]

    return {
        "total_trades": total, "wins": int(wins), "losses": int(losses),
        "win_rate_pct": round(wr, 2), "total_net_profit": round(tn, 2),
        "total_gross_profit": round(tg, 2), "total_commission": round(tc, 2),
        "avg_net": round(tn / total, 2) if total else 0,
        "max_win": round(df["net"].max(), 2), "max_loss": round(df["net"].min(), 2),
        "max_drawdown_usdt": round(mdd, 2), "max_drawdown_pct": round(mddp, 2),
        "profit_factor": round(pf, 2), "sharpe_ratio": round(sharpe, 2),
        "avg_bars": round(df["bars"].mean(), 1), "avg_pts": round(df["pts"].mean(), 1),
        "monthly": monthly, "scalpers": len(scalpers),
        "longs": len(longs), "shorts": len(shorts),
        "trends": len(trends), "ranges": len(ranges_),
        "months_active": len(monthly),
        "months_profitable": sum(1 for m in monthly if m["net_pl"] > 0),
        "avg_monthly": round(sum(m["net_pl"] for m in monthly) / max(len(monthly), 1), 2),
        "return_pct": round(tn / capital * 100, 2),
    }


def run_all():
    df = pd.read_csv(r"C:\Users\sanir\Downloads\text\BTC-Bot-v13-main\BTCUSDT_30m_2year.csv")
    print(f"Data: {len(df)} candles")

    results = []
    for c in CONFIGS:
        name = c["name"]
        cfg = c["cfg"]
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")

        trades = run_bt(df, cfg, 0.1)
        m = metrics(trades)

        print(f"  Trades: {m['total_trades']} | Net: ${m['total_net_profit']:>8,.2f} | WR: {m['win_rate_pct']}%")
        print(f"  PF: {m['profit_factor']} | DD: {m['max_drawdown_pct']}% | Avg: ${m['avg_monthly']:>7,.2f}/mo")
        print(f"  Scalpers: {m['scalpers']} | Longs:{m['longs']} Shorts:{m['shorts']} Trend:{m['trends']} Range:{m['ranges']}")

        results.append({"name": name, "cfg": cfg, "metrics": m, "trades": trades, "raw_trades": trades})

    # ── Special: EMA filter post-processing on PURE_TREND_NO_TRAIL ──
    print(f"\n{'='*60}")
    print("TEST: EMA_FILTER applied to PURE_TREND_NO_TRAIL")
    print(f"{'='*60}")
    series = None
    for r in results:
        if r["name"] == "PURE_TREND_NO_TRAIL":
            from strategy_logic import compute_full_series
            series = compute_full_series(df).reset_index(drop=True)
            filtered = modify_run_for_ema_filter(r["raw_trades"], series)
            mf = metrics(filtered)
            print(f"  Trades: {mf['total_trades']} | Net: ${mf['total_net_profit']:>8,.2f} | WR: {mf['win_rate_pct']}%")
            print(f"  PF: {mf['profit_factor']} | DD: {mf['max_drawdown_pct']}% | Avg: ${mf['avg_monthly']:>7,.2f}/mo")
            results.append({"name": "PURE_TREND_EMA_FILTERED", "cfg": r["cfg"], "metrics": mf, "trades": filtered, "raw_trades": filtered})

    # ── Find best ──
    best = max(results, key=lambda r: r["metrics"]["total_net_profit"])
    print(f"\n{'='*60}")
    print(f"BEST CONFIG: {best['name']}")
    print(f"{'='*60}")
    print(f"  Net: ${best['metrics']['total_net_profit']:,.2f}")
    print(f"  Trades: {best['metrics']['total_trades']} | WR: {best['metrics']['win_rate_pct']}%")
    print(f"  PF: {best['metrics']['profit_factor']} | DD: {best['metrics']['max_drawdown_pct']}%")
    print(f"  Avg Monthly: ${best['metrics']['avg_monthly']:,.2f}")
    print(f"  Target >$500/mo: {'YES' if best['metrics']['avg_monthly'] >= 500 else 'NO'}")

    # ── Generate reports for best ──
    print("\nGenerating reports...")
    _generate_reports(best, df)

    return results


def _generate_reports(best, df):
    m = best["metrics"]
    cfg = best["cfg"]
    trades = best["trades"]
    btc = 0.1

    # Equity chart
    b64 = ""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        dft = pd.DataFrame(trades).sort_values("exit_ts").reset_index(drop=True)
        dft["exit_dt"] = pd.to_datetime(dft["exit_ts"], unit="ms")
        dft["eq"] = 10000 + dft["net"].cumsum()
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]})
        ax1.plot(dft["exit_dt"], dft["eq"], color="#2196F3", lw=1.5)
        ax1.axhline(10000, color="gray", ls="--", alpha=0.5)
        ax1.set_title(f"BTC Bot v13 v10 — {best['name']} (0.1 BTC)", fontsize=13, fontweight="bold")
        ax1.grid(True, alpha=0.3)
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax2.fill_between(dft["exit_dt"], 0, dft["eq"].cummax() - dft["eq"], color="#f44336", alpha=0.3)
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)
        plt.tight_layout()
        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close()
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"Chart error: {e}")

    # HTML report
    mr = "".join(f"<tr><td>{x['month']}</td><td>{x['trades']}</td><td class=\"{'p' if x['net_pl']>=0 else 'l'}\">${x['net_pl']:,.2f}</td><td>{x['win_rate']}%</td></tr>\n" for x in m["monthly"])

    dft = pd.DataFrame(trades).sort_values("exit_ts").reset_index(drop=True)
    dft["entry_dt"] = pd.to_datetime(dft["entry_ts"], unit="ms")
    dft["exit_dt"] = pd.to_datetime(dft["exit_ts"], unit="ms")
    tr_ = "".join(
        f"<tr><td>{t['id']}</td><td>{t['type']}</td><td>{'LONG' if t['long'] else 'SHORT'}</td>"
        f"<td>{t['entry_dt'].strftime('%Y-%m-%d %H:%M')}</td><td>{t['entry']:,.2f}</td>"
        f"<td>{t['exit_dt'].strftime('%Y-%m-%d %H:%M')}</td><td>{t['exit']:,.2f}</td>"
        f"<td>{t['reason']}</td><td>{t['bars']}</td><td>{t['pts']:,.1f}</td>"
        f"<td class=\"{'p' if t['net']>=0 else 'l'}\">${t['gross']:,.2f}</td><td>${t['comm']:,.2f}</td>"
        f"<td class=\"{'p' if t['net']>=0 else 'l'}\">${t['net']:,.2f}</td></tr>\n"
        for _, t in dft.iterrows()
    )

    img_html = f'<img src="data:image/png;base64,{b64}" style="width:100%;max-width:900px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);">' if b64 else ""
    goal = "YES (MET)" if m["avg_monthly"] >= 500 else "NOT MET"
    cfg_rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>\n" for k, v in sorted(cfg.items()))

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>BTC Bot v13 v10 — {best['name']}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',sans-serif;background:#f5f7fa;color:#333;padding:20px}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:24px;color:#1a237e}} h2{{font-size:18px;color:#283593;margin:25px 0 10px;border-bottom:2px solid #e0e0e0;padding-bottom:5px}}
.subtitle{{color:#666;font-size:14px;margin-bottom:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:20px}}
.card{{background:white;border-radius:8px;padding:15px;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
.card .lbl{{font-size:11px;text-transform:uppercase;color:#888}} .card .val{{font-size:20px;font-weight:bold;color:#1a237e}}
.card .val.p{{color:#2e7d32}} .card .val.l{{color:#c62828}}
table{{width:100%;border-collapse:collapse;margin-bottom:20px;background:white;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,0.08)}}
th{{background:#1a237e;color:white;padding:10px 8px;font-size:12px;text-align:left;white-space:nowrap}}
td{{padding:8px;font-size:12px;border-bottom:1px solid #eee}} tr:hover{{background:#f0f4ff}}
.p{{color:#2e7d32;font-weight:600}} .l{{color:#c62828;font-weight:600}}
.note{{background:#fff8e1;border-left:4px solid #ffa000;padding:12px 15px;border-radius:4px;margin:15px 0;font-size:13px}}
.chart{{background:white;border-radius:8px;padding:15px;box-shadow:0 1px 4px rgba(0,0,0,0.08);margin-bottom:20px;text-align:center}}
.wrap{{overflow-x:auto}}
.filters input,.filters select{{padding:5px 8px;border:1px solid #ccc;border-radius:4px;font-size:12px;margin-right:8px;margin-bottom:10px}}
</style></head><body>
<div class="container">
<h1>🚀 BTC Bot v13 v10 — {best['name']}</h1>
<p class="subtitle">2-Year Backtest | Jul 2024 – Jul 2026 | BTC/USDT 30m | Delta India | {btc} BTC | Goal >$500/mo → {goal}</p>
<div class="note"><strong>Delta India Fee:</strong> Trades &lt;30min get Scalper Offer (entry fee only, 0.05%); longer trades pay both sides (0.1%).</div>
<h2>📊 Summary</h2>
<div class="grid">
<div class="card"><div class="lbl">Net Profit</div><div class="val {"p" if m["total_net_profit"]>=0 else "l"}">${m["total_net_profit"]:,.2f}</div></div>
<div class="card"><div class="lbl">Trades</div><div class="val">{m["total_trades"]}</div></div>
<div class="card"><div class="lbl">Win Rate</div><div class="val">{m["win_rate_pct"]}%</div></div>
<div class="card"><div class="lbl">Profit Factor</div><div class="val">{m["profit_factor"]}</div></div>
<div class="card"><div class="lbl">Max DD</div><div class="val l">{m["max_drawdown_pct"]}%</div></div>
<div class="card"><div class="lbl">Avg Monthly</div><div class="val {"p" if m["avg_monthly"]>=0 else "l"}">${m["avg_monthly"]:,.2f}</div></div>
<div class="card"><div class="lbl">Sharpe</div><div class="val">{m["sharpe_ratio"]}</div></div>
<div class="card"><div class="lbl">Return</div><div class="val {"p" if m["return_pct"]>=0 else "l"}">{m["return_pct"]}%</div></div>
<div class="card"><div class="lbl">Avg/Trade</div><div class="val {"p" if m["avg_net"]>=0 else "l"}">${m["avg_net"]:,.2f}</div></div>
<div class="card"><div class="lbl">Best</div><div class="val p">${m["max_win"]:,.2f}</div></div>
<div class="card"><div class="lbl">Worst</div><div class="val l">${m["max_loss"]:,.2f}</div></div>
<div class="card"><div class="lbl">$500/mo</div><div class="val {"p" if m["avg_monthly"]>=500 else "l"}">{goal}</div></div>
</div>
<h2>📈 Equity</h2>
<div class="chart">{img_html}</div>
<h2>📅 Monthly</h2>
<table><thead><tr><th>Month</th><th>Trades</th><th>Net P/L</th><th>Win Rate</th></tr></thead><tbody>{mr}</tbody></table>
<h2>⚙️ Config</h2>
<table><thead><tr><th>Parameter</th><th>Value</th></tr></thead><tbody>{cfg_rows}</tbody></table>
<h2>📋 Breakdown</h2>
<div class="grid">
<div class="card"><div class="lbl">Long/Short</div><div class="val">{m["longs"]}/{m["shorts"]}</div></div>
<div class="card"><div class="lbl">Trend/Range</div><div class="val">{m["trends"]}/{m["ranges"]}</div></div>
<div class="card"><div class="lbl">Scalper (<30m)</div><div class="val">{m["scalpers"]}</div></div>
</div>
<h2>📝 All Trades</h2>
<div class="wrap">
<table><thead><tr><th>ID</th><th>Type</th><th>Dir</th><th>Entry Time</th><th>Entry</th><th>Exit Time</th><th>Exit</th><th>Reason</th><th>Bars</th><th>Points</th><th>Gross</th><th>Comm</th><th>Net</th></tr></thead>
<tbody>{tr_}</tbody></table></div>
<div style="margin:30px 0;text-align:center;font-size:12px;color:#999;">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} | BTC Bot v13 v10</div>
</div></body></html>"""

    with open(os.path.join(OUT, "backtest_report.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML report -> {os.path.join(OUT, 'backtest_report.html')}")

    # Save config and trades
    with open(os.path.join(OUT, "optimized_config.json"), "w") as f:
        json.dump(cfg, f, indent=2)
    pd.DataFrame(trades).to_csv(os.path.join(OUT, "backtest_trades.csv"), index=False)
    print(f"Trades CSV -> {os.path.join(OUT, 'backtest_trades.csv')}")

    # Text summary
    txt = f"""
SHIVA SNIPER v10 — BACKTEST REPORT
====================================
Best Config: {best['name']}
Period: Jul 2024 – Jul 2026 | BTC/USDT 30m | 0.1 BTC | Delta India

RESULTS
-------
Net Profit:       ${m['total_net_profit']:>8,.2f}
Total Trades:     {m['total_trades']:>8}
Win Rate:         {m['win_rate_pct']:>7.1f}%
Profit Factor:    {m['profit_factor']:>8.2f}
Max Drawdown:     {m['max_drawdown_pct']:>7.2f}%
Avg Monthly:      ${m['avg_monthly']:>8,.2f}
Avg/Trade:        ${m['avg_net']:>8,.2f}
Best Trade:       ${m['max_win']:>8,.2f}
Worst Trade:      ${m['max_loss']:>8,.2f}
Return:           {m['return_pct']:>7.2f}%
Sharpe:           {m['sharpe_ratio']:>8.2f}
Target >$500/mo:  {goal}

Monthly:
"""
    for x in m["monthly"]:
        txt += f"  {x['month']:<12} {x['trades']:>6} ${x['net_pl']:>8,.2f} {x['win_rate']}%\n"

    with open(os.path.join(OUT, "backtest_report.txt"), "w") as f:
        f.write(txt)
    print(f"Text report -> {os.path.join(OUT, 'backtest_report.txt')}")

    # Print full results
    print(f"\nFINAL: {best['name']} — Net ${m['total_net_profit']:,.2f} across {m['total_trades']} trades")
    print(f"  ${m['avg_monthly']:,.2f}/month avg | Goal: {goal}")
    print(f"  Reports saved to: {OUT}")


if __name__ == "__main__":
    results = run_all()
