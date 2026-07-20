#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════╗
║  BTC Bot v13 — Multi-Timeframe Backtest Dashboard                        ║
║                                                                           ║
║  Fetches 5m / 15m / 30m BTCUSDT from Binance, runs the RSI Bounce        ║
║  strategy on each timeframe (12-month window), and generates a rich       ║
║  HTML dashboard comparing all three.                                      ║
║                                                                           ║
║  Usage:                                                                    ║
║    python backtest_dashboard.py              # full run (fetch + BT)      ║
║    python backtest_dashboard.py --no-fetch   # skip download, use cache   ║
║    python backtest_dashboard.py --csv-only   # only use existing CSV      ║
║    python backtest_dashboard.py --html-only  # re-generate from saved TSV ║
║                                                                           ║
║  Output:                                                                   ║
║    backtest_dashboard.html  — standalone HTML dashboard                   ║
║    bt_results_*.tsv         — per-timeframe raw trade CSVs                ║
╚═══════════════════════════════════════════════════════════════════════════╝
"""

import argparse, csv, json, math, os, sys, time
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd

# ─── Strategy Parameters (from the optimized config) ─────────────────────
RSI_BOUNCE_LONG_ENTER  = 50
RSI_BOUNCE_LONG_EXIT   = 25
RSI_BOUNCE_SHORT_ENTER = 40
RSI_BOUNCE_SHORT_EXIT  = 65
SL_ATR_MULT  = 0.5
TP_RR_MULT   = 1.5
COMMISSION_PCT = 0.0005  # 0.05%
MAX_BARS     = 15
POSITION_BTC = 0.1       # BTC per trade
WARMUP_BARS  = 220       # bars needed for EMA(100) + indicators
INITIAL_CAPITAL = 10000.0

TIMEFRAMES = {
    "5m":  {"mult": 5,    "limit": 2000, "color": "#3b82f6"},
    "15m": {"mult": 15,   "limit": 2000, "color": "#8b5cf6"},
    "30m": {"mult": 30,   "limit": 2000, "color": "#f59e0b"},
}

# ═══════════════════════════════════════════════════════════════════════════
#  DATA FETCHING
# ═══════════════════════════════════════════════════════════════════════════

def fetch_binance_ohlcv(timeframe: str, since: Optional[int] = None,
                        limit: int = 1000) -> list:
    """Fetch OHLCV from Binance via ccxt. Returns list of [ts, o, h, l, c, v]."""
    import ccxt
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
    all_bars = []
    batch_since = since
    while True:
        try:
            ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe,
                                          since=batch_since, limit=limit)
        except Exception as e:
            print(f"  [WARN] Fetch error: {e}")
            break
        if not ohlcv:
            break
        all_bars.extend(ohlcv)
        if len(ohlcv) < limit:
            break
        batch_since = ohlcv[-1][0] + 1
        time.sleep(0.3)  # rate limit courtesy
    return all_bars


def load_or_fetch(timeframe: str, months: int = 12) -> pd.DataFrame:
    """Load cached CSV or fetch from Binance. Returns OHLCV DataFrame."""
    cache_file = f"bt_cache_{timeframe}.csv"
    if os.path.exists(cache_file):
        print(f"  Loading cached {cache_file} ...")
        df = pd.read_csv(cache_file, parse_dates=["datetime"])
        return df

    print(f"  Fetching {timeframe} BTCUSDT from Binance ({months} months)...")
    now = datetime.now(timezone.utc)
    since = int((now - timedelta(days=months * 30)).timestamp() * 1000)
    bars = fetch_binance_ohlcv(timeframe, since=since, limit=1000)
    if not bars:
        print(f"  [FAIL] No data returned for {timeframe}")
        return pd.DataFrame()

    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    # Deduplicate by timestamp
    df = df.drop_duplicates(subset="timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)
    df.to_csv(cache_file, index=False)
    print(f"  [OK] {len(df)} bars cached -> {cache_file}")
    return df


# ═══════════════════════════════════════════════════════════════════════════
#  INDICATOR COMPUTATION  (Pine-exact — matches indicators/engine.py)
# ═══════════════════════════════════════════════════════════════════════════

def rma(arr, period):
    """Wilder's Moving Average — matches Pine's ta.rma()."""
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
    """Exponential Moving Average — matches Pine's ta.ema()."""
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
    """Compute all indicators for the RSI Bounce strategy."""
    n = len(close)
    ema_trend = ema(close, 100)
    ema50 = ema(close, 50)
    ema20 = ema(close, 20)

    # ATR 14 — Wilder's RMA of True Range
    tr = np.full(n, np.nan)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr14 = rma(tr, 14)
    atr_sma = pd.Series(atr14).rolling(50).mean().values if n >= 50 else np.full(n, np.nan)

    # RSI 14
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

    # Volume SMA
    vol_sma = np.full(n, np.nan)
    for i in range(19, n):
        vol_sma[i] = float(np.mean(volume[i - 19:i + 1]))

    return {
        "ema_trend": ema_trend,
        "ema50": ema50,
        "ema20": ema20,
        "atr14": atr14,
        "atr_sma": atr_sma,
        "rsi": rsi,
        "vol_sma": vol_sma,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  BACKTEST ENGINE  (matches backtest_12m.py logic exactly)
# ═══════════════════════════════════════════════════════════════════════════

def run_backtest(close, high, low, volume, timestamp, ind, tf_label="30m"):
    """
    RSI Bounce Strategy:
      BEAR (close < EMA100): SHORT when RSI crosses ABOVE 40, capped at 65
      BULL (close > EMA100): LONG when RSI crosses BELOW 50, floored at 25
    Exit: SL = ATR*0.5 | TP = SL*1.5 | max 15 bars
    """
    n = len(close)
    trades = []

    for i in range(WARMUP_BARS, n - 1):
        if np.isnan(ind["ema_trend"][i]) or np.isnan(ind["atr14"][i]) or np.isnan(ind["rsi"][i]):
            continue

        bear = close[i] < ind["ema_trend"][i]
        bull = close[i] > ind["ema_trend"][i]
        sig = None

        if bear and RSI_BOUNCE_SHORT_ENTER < ind["rsi"][i] < RSI_BOUNCE_SHORT_EXIT and ind["rsi"][i - 1] <= RSI_BOUNCE_SHORT_ENTER:
            sig = "short"
        if bull and RSI_BOUNCE_LONG_EXIT < ind["rsi"][i] < RSI_BOUNCE_LONG_ENTER and ind["rsi"][i - 1] >= RSI_BOUNCE_LONG_ENTER:
            sig = "long"

        if not sig:
            continue

        ep = close[i]
        sd = ind["atr14"][i] * SL_ATR_MULT
        sl = ep + sd if sig == "short" else ep - sd
        tp = ep - sd * TP_RR_MULT if sig == "short" else ep + sd * TP_RR_MULT

        exit_p = None
        rsn = None
        for j in range(i, min(i + MAX_BARS, n)):
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
            exit_p = close[min(i + MAX_BARS - 1, n - 1)]
            rsn = "Timeout"

        gross = (exit_p - ep) * POSITION_BTC if sig == "long" else (ep - exit_p) * POSITION_BTC
        comm = ep * POSITION_BTC * COMMISSION_PCT
        net = gross - comm

        trades.append({
            "ts": int(timestamp[i]),
            "datetime": datetime.fromtimestamp(timestamp[i] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "sig": sig,
            "entry": round(ep, 2),
            "exit": round(exit_p, 2),
            "reason": rsn,
            "gross": round(gross, 2),
            "comm": round(comm, 4),
            "net": round(net, 2),
            "bars_held": j - i if exit_p else MAX_BARS,
        })

    return trades


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYSIS & AGGREGATION
# ═══════════════════════════════════════════════════════════════════════════

def analyze_trades(trades):
    """Compute summary stats for a set of trades."""
    if not trades:
        return {
            "total": 0, "wins": 0, "losses": 0, "win_rate": 0,
            "gross_pl": 0, "comm": 0, "net_pl": 0,
            "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
            "best": 0, "worst": 0, "max_dd": 0, "max_dd_pct": 0,
            "sl_cnt": 0, "tp_cnt": 0, "to_cnt": 0,
            "monthly": {}, "equity_curve": [],
        }

    total = len(trades)
    wins = sum(1 for t in trades if t["net"] > 0)
    losses = total - wins
    win_rate = wins / total * 100 if total else 0
    total_gross = sum(t["gross"] for t in trades)
    total_comm = sum(t["comm"] for t in trades)
    total_net = sum(t["net"] for t in trades)

    win_trades = [t for t in trades if t["net"] > 0]
    loss_trades = [t for t in trades if t["net"] <= 0]
    avg_win = sum(t["net"] for t in win_trades) / len(win_trades) if win_trades else 0
    avg_loss = sum(t["net"] for t in loss_trades) / len(loss_trades) if loss_trades else 0

    win_pl = sum(t["net"] for t in win_trades)
    loss_pl_abs = abs(sum(t["net"] for t in loss_trades))
    profit_factor = win_pl / loss_pl_abs if loss_pl_abs else float("inf")

    best = max(t["net"] for t in trades)
    worst = min(t["net"] for t in trades)

    sl_cnt = sum(1 for t in trades if t["reason"] == "SL")
    tp_cnt = sum(1 for t in trades if t["reason"] == "TP")
    to_cnt = sum(1 for t in trades if t["reason"] == "Timeout")

    # Monthly breakdown
    monthly = {}
    for t in trades:
        dt = datetime.fromtimestamp(t["ts"] / 1000, tz=timezone.utc)
        k = dt.strftime("%Y-%m")
        if k not in monthly:
            monthly[k] = {"t": 0, "w": 0, "gross": 0.0, "comm": 0.0, "net": 0.0}
        monthly[k]["t"] += 1
        monthly[k]["w"] += 1 if t["net"] > 0 else 0
        monthly[k]["gross"] += t["gross"]
        monthly[k]["comm"] += t["comm"]
        monthly[k]["net"] += t["net"]

    # Equity curve
    equity = INITIAL_CAPITAL
    peak = equity
    max_dd = 0.0
    equity_curve = [(0, INITIAL_CAPITAL)]
    for t in trades:
        equity += t["net"]
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
        equity_curve.append((t["ts"], round(equity, 2)))

    max_dd_pct = max_dd / INITIAL_CAPITAL * 100

    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "gross_pl": round(total_gross, 2),
        "comm": round(total_comm, 2),
        "net_pl": round(total_net, 2),
        "avg_monthly": round(total_net / len(monthly), 2) if monthly else 0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "best": round(best, 2),
        "worst": round(worst, 2),
        "max_dd": round(max_dd, 2),
        "max_dd_pct": round(max_dd_pct, 2),
        "sl_cnt": sl_cnt,
        "tp_cnt": tp_cnt,
        "to_cnt": to_cnt,
        "monthly": monthly,
        "equity_curve": equity_curve,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  HTML DASHBOARD GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def _fmt(num, suffix=""):
    """Format a number for display."""
    if isinstance(num, float):
        if abs(num) >= 1_000_000:
            return f"${num:,.0f}{suffix}"
        elif abs(num) >= 1_000:
            return f"${num:,.2f}{suffix}"
        elif abs(num) >= 1:
            return f"${num:,.2f}{suffix}"
        else:
            return f"${num:.4f}{suffix}"
    return str(num)


def _bar_html(k, v, color, max_val):
    """Generate a horizontal bar segment."""
    pct = (v / max_val * 100) if max_val else 0
    return f'<div class="bar" style="width:{pct:.1f}%;background:{color}">{_fmt(v)}</div>'


def generate_dashboard(all_results):
    """Generate a standalone HTML dashboard comparing all timeframes."""
    tf_order = ["5m", "15m", "30m"]

    # ─── Build monthly tables ───────────────────────────────────────────────
    all_months = set()
    for tf in tf_order:
        if tf in all_results:
            all_months.update(all_results[tf]["analysis"]["monthly"].keys())
    all_months = sorted(all_months)

    # ─── Build equity curves ────────────────────────────────────────────────
    equity_series = {}
    for tf in tf_order:
        if tf in all_results:
            ec = all_results[tf]["analysis"]["equity_curve"]
            labels = [datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if ts else "Start"
                      for ts, _ in ec]
            values = [v for _, v in ec]
            equity_series[tf] = {"labels": labels, "values": values}

    # ─── Summary cards ──────────────────────────────────────────────────────
    cards_html = ""
    for tf in tf_order:
        if tf not in all_results:
            continue
        a = all_results[tf]["analysis"]
        tf_info = TIMEFRAMES[tf]
        color = tf_info["color"]
        bars = all_results[tf]["bars"]
        trades = all_results[tf]["trades"]

        arrow = "▲" if a["net_pl"] > 0 else "▼"
        pl_class = "positive" if a["net_pl"] > 0 else "negative"

        cards_html += f"""
        <div class="card" style="border-top:4px solid {color}">
            <div class="card-header">
                <span class="tf-badge" style="background:{color}">{tf}</span>
                <span class="bar-count">{bars:,} bars</span>
            </div>
            <div class="card-body">
                <div class="metric-row">
                    <div class="metric">
                        <div class="metric-label">Net P&L (12mo)</div>
                        <div class="metric-value {pl_class}">{arrow} {_fmt(a["net_pl"])}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Monthly Avg</div>
                        <div class="metric-value">{_fmt(a["avg_monthly"])}</div>
                    </div>
                </div>
                <div class="metric-row">
                    <div class="metric">
                        <div class="metric-label">Total Trades</div>
                        <div class="metric-value">{a["total"]}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value">{a["win_rate"]}%</div>
                    </div>
                </div>
                <div class="metric-row">
                    <div class="metric">
                        <div class="metric-label">Profit Factor</div>
                        <div class="metric-value">{a["profit_factor"]}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Max DD</div>
                        <div class="metric-value">{a["max_dd_pct"]}%</div>
                    </div>
                </div>
            </div>
        </div>"""

    # ─── Monthly table ──────────────────────────────────────────────────────
    monthly_rows = ""
    for m in all_months:
        cells = ""
        for tf in tf_order:
            if tf not in all_results:
                cells += "<td>-</td><td>-</td><td>-</td>"
                continue
            mn = all_results[tf]["analysis"]["monthly"].get(m)
            if mn:
                wr = mn["w"] / mn["t"] * 100 if mn["t"] else 0
                cls = "positive" if mn["net"] > 0 else "negative"
                cells += f"""<td>{mn["t"]}</td><td>{wr:.0f}%</td><td class="{cls}">{_fmt(mn["net"])}</td>"""
            else:
                cells += "<td>-</td><td>-</td><td>-</td>"
        monthly_rows += f"<tr><td>{m}</td>{cells}</tr>"

    # ─── Equity Chart (inline SVG sparkline per timeframe) ──────────────────
    chart_html = ""
    for tf in tf_order:
        if tf not in equity_series:
            continue
        es = equity_series[tf]
        vals = es["values"]
        if len(vals) < 2:
            continue
        color = TIMEFRAMES[tf]["color"]

        W, H = 600, 120
        min_v, max_v = min(vals), max(vals)
        rng = max_v - min_v if max_v != min_v else 1
        pts = " ".join(
            f"{int(i / (len(vals) - 1) * W) if len(vals) > 1 else 0},"
            f"{int(H - (v - min_v) / rng * (H - 20) - 10)}"
            for i, v in enumerate(vals)
        )
        start_y = int(H - (vals[0] - min_v) / rng * (H - 20) - 10)

        chart_html += f"""
        <div class="equity-chart">
            <div class="chart-label"><span class="tf-dot" style="background:{color}"></span> {tf}</div>
            <svg viewBox="0 0 {W} {H + 20}" class="chart-svg">
                <polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}" />
                <circle cx="0" cy="{start_y}" r="2.5" fill="{color}" />
                <text x="{W - 5}" y="{H + 15}" text-anchor="end" fill="#94a3b8" font-size="10">{_fmt(vals[-1])}</text>
                <text x="0" y="{H + 15}" fill="#94a3b8" font-size="10">{_fmt(vals[0])}</text>
            </svg>
        </div>"""

    # ─── Exit reason breakdown bars ─────────────────────────────────────────
    exit_bars = ""
    for tf in tf_order:
        if tf not in all_results:
            continue
        a = all_results[tf]["analysis"]
        total = a["total"] or 1
        color = TIMEFRAMES[tf]["color"]
        exit_bars += f"""
        <div class="exit-row">
            <div class="exit-label">{tf}</div>
            <div class="exit-bars">
                <div class="bar-segment sl-bar" style="width:{a['sl_cnt']/total*100:.1f}%">SL {a['sl_cnt']}</div>
                <div class="bar-segment tp-bar" style="width:{a['tp_cnt']/total*100:.1f}%">TP {a['tp_cnt']}</div>
                <div class="bar-segment to-bar" style="width:{a['to_cnt']/total*100:.1f}%">TO {a['to_cnt']}</div>
            </div>
        </div>"""

    # ─── Trade list (last 20 per timeframe) ─────────────────────────────────
    trade_tables = ""
    for tf in tf_order:
        if tf not in all_results:
            continue
        trades = all_results[tf]["trades"]
        if not trades:
            continue
        recent = trades[-20:] if len(trades) > 20 else trades
        rows = ""
        for t in reversed(recent):
            cls = "positive" if t["net"] > 0 else ("negative" if t["net"] < 0 else "")
            rows += f"""<tr>
                <td>{t["datetime"]}</td>
                <td>{t["sig"]}</td>
                <td>{t["entry"]}</td>
                <td>{t["exit"]}</td>
                <td>{t["reason"]}</td>
                <td class="{cls}">{_fmt(t["net"])}</td>
            </tr>"""
        trade_tables += f"""
        <div class="trade-table-wrap">
            <h3 class="table-title">📋 {tf} — Last {min(20, len(trades))} Trades</h3>
            <table class="trade-table">
                <tr><th>Date</th><th>Side</th><th>Entry</th><th>Exit</th><th>Reason</th><th>P&L</th></tr>
                {rows}
            </table>
        </div>"""

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Compute monthly total cells (must be before the f-string that uses it)
    monthly_total_cells = ""
    for tf in tf_order:
        if tf not in all_results:
            monthly_total_cells += "<td>-</td><td>-</td><td>-</td>"
            continue
        a = all_results[tf]["analysis"]
        cls = "positive" if a["net_pl"] > 0 else "negative"
        monthly_total_cells += f'''<td>{a["total"]}</td><td>{a["win_rate"]}%</td><td class="{cls}">{_fmt(a["net_pl"])}</td>'''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BTC Bot v13 — Multi-Timeframe Backtest Dashboard</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background: #0f172a; color: #e2e8f0; padding: 24px;
}}
.header {{
    background: linear-gradient(135deg, #1e293b, #0f172a);
    padding: 28px 32px; border-radius: 16px; margin-bottom: 24px;
    border: 1px solid #1e293b;
}}
.header h1 {{ font-size: 24px; font-weight: 700; color: #f8fafc; }}
.header .sub {{ color: #94a3b8; font-size: 13px; margin-top: 6px; }}
.header .sub span {{ color: #64748b; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }}
.card {{
    background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155;
}}
.card-header {{ display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }}
.tf-badge {{
    display: inline-block; padding: 2px 12px; border-radius: 20px; color: #fff;
    font-size: 13px; font-weight: 600; letter-spacing: 0.5px;
}}
.bar-count {{ color: #64748b; font-size: 12px; }}
.card-body {{ display: flex; flex-direction: column; gap: 12px; }}
.metric-row {{ display: flex; justify-content: space-between; gap: 8px; }}
.metric {{ flex: 1; }}
.metric-label {{ color: #94a3b8; font-size: 11px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }}
.metric-value {{ font-size: 18px; font-weight: 700; margin-top: 2px; }}
.positive {{ color: #22c55e; }}
.negative {{ color: #ef4444; }}

.section {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #334155; }}
.section h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 16px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}

table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{ padding: 8px 12px; text-align: right; border-bottom: 1px solid #1e293b; }}
th {{ color: #64748b; font-weight: 500; font-size: 11px; text-transform: uppercase; }}
td:first-child {{ text-align: left; }}
tr:hover td {{ background: #263548; }}

.equity-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
.equity-chart {{ background: #1e293b; border-radius: 8px; padding: 12px; border: 1px solid #334155; }}
.chart-label {{ font-size: 12px; color: #94a3b8; margin-bottom: 6px; }}
.tf-dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; }}
.chart-svg {{ width: 100%; height: auto; }}

.exit-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }}
.exit-label {{ width: 40px; font-weight: 600; font-size: 13px; }}
.exit-bars {{ display: flex; flex: 1; height: 28px; border-radius: 6px; overflow: hidden; }}
.bar-segment {{ display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 600; color: #fff; transition: width 0.3s; }}
.sl-bar {{ background: #ef4444; }}
.tp-bar {{ background: #22c55e; }}
.to-bar {{ background: #64748b; }}

.trade-table-wrap {{ margin-top: 16px; }}
.trade-table-wrap + .trade-table-wrap {{ margin-top: 32px; }}
.table-title {{ font-size: 14px; font-weight: 600; margin-bottom: 8px; color: #e2e8f0; }}

.kpi-strip {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }}
.kpi {{ background: #0f172a; padding: 6px 14px; border-radius: 20px; font-size: 12px; }}
.kpi-label {{ color: #64748b; }}
.kpi-value {{ font-weight: 600; }}

@media (max-width: 900px) {{ .grid, .equity-grid {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>

<div class="header">
    <h1>⚡ BTC Bot v13 — Multi-Timeframe Backtest Dashboard</h1>
    <div class="sub">
        12-Month RSI Bounce Strategy · 0.1 BTC Position · Generated {now}
        <span> · Commission: {COMMISSION_PCT*100:.2f}%</span>
    </div>
</div>

<div class="grid">
    {cards_html}
</div>

<div class="section">
    <h2>📊 Monthly Net P&L Comparison</h2>
    <div style="overflow-x:auto">
    <table>
        <tr>
            <th>Month</th>
            <th colspan="3" style="text-align:center;color:#3b82f6">5m</th>
            <th colspan="3" style="text-align:center;color:#8b5cf6">15m</th>
            <th colspan="3" style="text-align:center;color:#f59e0b">30m</th>
        </tr>
        <tr>
            <th></th>
            <th>Trades</th><th>WR</th><th>Net $</th>
            <th>Trades</th><th>WR</th><th>Net $</th>
            <th>Trades</th><th>WR</th><th>Net $</th>
        </tr>
        {monthly_rows}
        <tr style="font-weight:700;background:#0f172a">
            <td>TOTAL</td>
            {monthly_total_cells}
        </tr>
    </table>
    </div>
</div>

<div class="section">
    <h2>📈 Equity Curves</h2>
    <div class="equity-grid">
        {chart_html}
    </div>
</div>

<div class="section">
    <h2>🚪 Exit Reason Breakdown</h2>
    {exit_bars}
</div>

<div class="section">
    <h2>📋 Recent Trades</h2>
    {trade_tables}
</div>

</body>
</html>"""

    return html


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def save_trades_tsv(trades, filepath):
    """Save trades to TSV for external analysis."""
    if not trades:
        return
    with open(filepath, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=trades[0].keys(), delimiter="\t")
        w.writeheader()
        w.writerows(trades)


def main():
    parser = argparse.ArgumentParser(description="Multi-Timeframe Backtest Dashboard")
    parser.add_argument("--no-fetch", action="store_true", help="Skip download, use cache files only")
    parser.add_argument("--csv-only", action="store_true", help="Only use the existing 30m CSV, skip fetch")
    parser.add_argument("--html-only", action="store_true", help="Re-generate HTML from saved TSV files")
    parser.add_argument("--months", type=int, default=12, help="Months of data (default: 12)")
    args = parser.parse_args()

    all_results = {}

    if args.html_only:
        # Load from saved TSV files
        for tf in TIMEFRAMES:
            tsv_path = f"bt_results_{tf}.tsv"
            if not os.path.exists(tsv_path):
                continue
            print(f"Loading saved results: {tsv_path}")
            df = pd.read_csv(tsv_path, sep="\t")
            trades = df.to_dict("records")
            all_results[tf] = {
                "trades": trades,
                "bars": len(trades) * 10,  # rough estimate
                "analysis": analyze_trades(trades),
            }
            print(f"  {tf}: {len(trades)} trades loaded")
    else:
        for tf, info in TIMEFRAMES.items():
            print(f"\n{'='*60}")
            print(f"  TIMEFRAME: {tf}")
            print(f"{'='*60}")

            if args.csv_only and tf != "30m":
                print(f"  Skipping {tf} (--csv-only mode)")
                continue

            if args.csv_only:
                csv_path = "BTCUSDT_30m_2year.csv"
                if not os.path.exists(csv_path):
                    print(f"  [FAIL] CSV not found: {csv_path}")
                    continue
                print(f"  Loading {csv_path} ...")
                raw = pd.read_csv(csv_path)
            else:
                df = load_or_fetch(tf, months=args.months)
                if df.empty:
                    print(f"  [FAIL] No data for {tf}")
                    continue
                raw = df

            # Ensure numeric columns
            for c in ["open", "high", "low", "close", "volume"]:
                raw[c] = pd.to_numeric(raw[c], errors="coerce").astype(float)

            # Slice last N months
            if not args.csv_only and "timestamp" in raw.columns and len(raw) > 100:
                cutoff = int((datetime.now(timezone.utc) - timedelta(days=args.months * 30)).timestamp() * 1000)
                raw = raw[pd.to_numeric(raw["timestamp"], errors="coerce") >= cutoff].reset_index(drop=True)

            close = raw["close"].values.astype(float)
            high = raw["high"].values.astype(float)
            low = raw["low"].values.astype(float)
            volume = raw["volume"].values.astype(float)
            timestamp = raw["timestamp"].values.astype(int)

            n = len(close)
            print(f"  Bars: {n}")
            print(f"  Range: ${low.min():.0f} — ${high.max():.0f}")

            ind = compute_indicators(close, high, low, volume)
            trades = run_backtest(close, high, low, volume, timestamp, ind, tf)

            print(f"  Trades: {len(trades)}")

            # Save raw trades
            tsv_path = f"bt_results_{tf}.tsv"
            save_trades_tsv(trades, tsv_path)
            print(f"  Saved -> {tsv_path}")

            analysis = analyze_trades(trades)
            all_results[tf] = {
                "trades": trades,
                "bars": n,
                "analysis": analysis,
            }

            a = analysis
            arrow = "▲" if a["net_pl"] > 0 else "▼"
            print(f"  Net P&L: ${a['net_pl']:+,.2f}  |  Trades: {a['total']}  |  "
                  f"WR: {a['win_rate']}%  |  PF: {a['profit_factor']}  |  "
                  f"Max DD: {a['max_dd_pct']}%")

    if not all_results:
        print("\n[FAIL] No results to display.")
        return

    # Generate HTML
    print(f"\n{'='*60}")
    print("  Generating HTML dashboard...")
    html = generate_dashboard(all_results)

    out_path = "backtest_dashboard.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  [OK] Dashboard -> {out_path}")
    print(f"{'='*60}\n")
    print(f"Open backtest_dashboard.html in your browser to view results.")


if __name__ == "__main__":
    main()
