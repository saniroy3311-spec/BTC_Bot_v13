#!/usr/bin/env python3
"""
Shiva Sniper — Parameter Optimizer
Sweeps strategy parameters to find config that achieves $400+/month minimum profit.
Base capital: $10,000 | Position: 0.1 BTC (100 lots)
"""
import json, math, time, sys, os
from datetime import datetime, timezone
from collections import defaultdict

# ─── Load CSV data (2 years BTCUSDT 30m) ───
CSV_PATH = "D:\\Projects\\claudeCode\\BTCUSDT_30m_2year.csv"

def load_csv(path):
    candles = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) < 5: continue
            try:
                candles.append({
                    "t": int(parts[0]),
                    "o": float(parts[1]),
                    "h": float(parts[2]),
                    "l": float(parts[3]),
                    "c": float(parts[4]),
                    "v": float(parts[5]) if len(parts) > 5 else 0
                })
            except: pass
    return candles

print("Loading 2-year BTCUSDT 30m data...")
data = load_csv(CSV_PATH)
print(f"Loaded {len(data)} candles")

# ─── Indicators ───
def ema(v, p):
    r = [None]*len(v); m = 2/(p+1)
    if len(v) < p: return r
    r[p-1] = sum(v[:p])/p
    for i in range(p, len(v)): r[i] = (v[i]-r[i-1])*m + r[i-1]
    return r

def sma(v, p):
    r = [None]*len(v)
    for i in range(p-1, len(v)): r[i] = sum(v[i-p+1:i+1])/p
    return r

def atr_fast(h, l, c, p=14):
    r = [None]*len(c)
    if len(c) < 2: return r
    tr = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    if len(tr) >= p:
        r[p] = sum(tr[:p])/p
        for i in range(p+1, len(c)): r[i] = (r[i-1]*(p-1)+tr[i-1])/p
    return r

def rsi(v, p=14):
    r = [None]*len(v)
    if len(v) < p+1: return r
    g, l2 = [], []
    for i in range(1, len(v)):
        d = v[i]-v[i-1]
        g.append(d if d>0 else 0)
        l2.append(-d if d<0 else 0)
    ag = sum(g[:p])/p; al = sum(l2[:p])/p
    r[p] = 100-(100/(1+ag/al if al else 999))
    for i in range(p+1, len(v)):
        ag = (ag*(p-1)+g[i-1])/p; al = (al*(p-1)+l2[i-1])/p
        r[i] = 100-(100/(1+ag/al)) if al else 100
    return r

def backtest(params, data):
    """Run backtest with given params, return metrics."""
    n = len(data)
    o = [d["o"] for d in data]
    h = [d["h"] for d in data]
    l = [d["l"] for d in data]
    c = [d["c"] for d in data]
    v = [d["v"] for d in data]
    t = [d["t"] for d in data]

    atr_v = atr_fast(h, l, c, 14)
    ema20 = ema(c, 20)
    ema50 = ema(c, 50)
    ema200 = ema(c, 200)
    vol_sma = sma(v, 20)
    rsi_v = rsi(c, 14)

    last_signal = ""
    in_pos = False; dir_pos = ""
    entry_px = 0.0; entry_atr = 0.0
    hh_since = 0.0; ll_since = 0.0
    trail_stop = 0.0
    trades = []

    lookback = params.get("lookback", 250)

    for i in range(lookback, n):
        hh_obj = datetime.fromtimestamp(t[i]/1000, tz=timezone.utc)
        hh = hh_obj.hour
        if not (params["sess_start"] <= hh <= params["sess_end"]):
            continue
        if not all([atr_v[i], ema20[i], ema50[i], ema200[i], vol_sma[i], rsi_v[i]]):
            continue

        if not in_pos:
            rml = (ema50[i] > ema200[i] and rsi_v[i] > params["rsi_long"] and
                   rsi_v[i-1] <= params["rsi_long"] and c[i] > ema20[i] and
                   v[i] > vol_sma[i] * params["vol_mult"])
            rms = (ema50[i] < ema200[i] and rsi_v[i] < params["rsi_short"] and
                   rsi_v[i-1] >= params["rsi_short"] and c[i] < ema20[i] and
                   v[i] > vol_sma[i] * params["vol_mult"])
            m3l = (c[i] > ema20[i] and ema20[i] > ema50[i] and c[i] > c[i-1] and
                   c[i-1] > c[i-2] and c[i-2] > c[i-3] and v[i] > vol_sma[i] * params["vol_mult"])
            m3s = (c[i] < ema20[i] and ema20[i] < ema50[i] and c[i] < c[i-1] and
                   c[i-1] < c[i-2] and c[i-2] < c[i-3] and v[i] > vol_sma[i] * params["vol_mult"])

            sig_hash = "RML" if rml else "RMS" if rms else "M3L" if m3l else "M3S" if m3s else ""
            sig_new = sig_hash != "" and sig_hash != last_signal

            entry_dir = ""
            if sig_new:
                if rml or m3l: entry_dir = "LONG"
                elif rms or m3s: entry_dir = "SHORT"

            if entry_dir:
                in_pos = True; dir_pos = entry_dir
                entry_px = c[i]; entry_atr = atr_v[i] if atr_v[i] else 1
                hh_since = h[i]; ll_since = l[i]
                hard_sl = entry_px - entry_atr * params["sl_atr"] if dir_pos == "LONG" else entry_px + entry_atr * params["sl_atr"]
                trail_stop = hard_sl
                last_signal = sig_hash
                trades.append({"entry_t": t[i], "entry_px": entry_px, "dir": dir_pos,
                             "hh": hh_since, "ll": ll_since, "hard_sl": hard_sl})
        else:
            atr_i = atr_v[i] if atr_v[i] else entry_atr
            stop_dist = atr_i * params["sl_atr"]
            trail_pts = atr_i * params["trail_dist"]
            exit_reason = ""; exit_px_val = 0

            if dir_pos == "LONG":
                hh_since = max(hh_since, h[i])
                trail_stop = max(trail_stop, hh_since - trail_pts)
                effective_sl = max(entry_px - stop_dist, trail_stop)
                if l[i] <= effective_sl:
                    exit_reason = "SL" if effective_sl <= entry_px - stop_dist else "Trail"
                    exit_px_val = effective_sl
            else:
                ll_since = min(ll_since, l[i])
                trail_stop = min(trail_stop if trail_stop != 0 else 999999, ll_since + trail_pts)
                effective_sl = min(entry_px + stop_dist, trail_stop)
                if h[i] >= effective_sl:
                    exit_reason = "SL" if effective_sl >= entry_px + stop_dist else "Trail"
                    exit_px_val = effective_sl

            if exit_reason:
                if dir_pos == "LONG": pts = exit_px_val - entry_px
                else: pts = entry_px - exit_px_val
                pl_raw = pts * 0.1
                comm = (entry_px + exit_px_val) * 0.1 * 0.0005
                pl_net = pl_raw - comm
                trades[-1].update({"exit_t": t[i], "exit_px": exit_px_val, "pts": pts,
                                 "pl": round(pl_net, 2), "reason": exit_reason})
                in_pos = False; trail_stop = 0

    # Close open position
    if in_pos and trades and "pl" not in trades[-1]:
        exit_px_val = c[-1]
        if dir_pos == "LONG": pts = exit_px_val - entry_px
        else: pts = entry_px - exit_px_val
        pl_raw = pts * 0.1
        comm = (entry_px + exit_px_val) * 0.1 * 0.0005
        trades[-1].update({"exit_t": t[-1], "exit_px": exit_px_val, "pts": pts,
                         "pl": round(pl_raw - comm, 2), "reason": "End"})

    trades = [tr for tr in trades if "pl" in tr]
    if not trades: return None

    # Calculate metrics
    wins = [tr for tr in trades if tr["pl"] > 0]
    losses = [tr for tr in trades if tr["pl"] <= 0]
    tt = len(trades)
    wr = len(wins)/tt*100 if tt else 0
    gp = sum(tr["pl"] for tr in wins)
    gl = abs(sum(tr["pl"] for tr in losses))
    pf = gp/gl if gl else 99
    net = sum(tr["pl"] for tr in trades)

    # Monthly breakdown
    monthly = defaultdict(lambda: {"t": 0, "pl": 0})
    for tr in trades:
        mk = datetime.fromtimestamp(tr["entry_t"]/1000, tz=timezone.utc).strftime("%Y-%m")
        monthly[mk]["t"] += 1
        monthly[mk]["pl"] += tr["pl"]

    min_monthly = min(m["pl"] for m in monthly.values()) if monthly else 0
    avg_monthly = net / len(monthly) if monthly else 0

    # Drawdown
    bal = 10000; peak = 10000; max_dd = 0
    for tr in trades:
        bal += tr["pl"]
        peak = max(peak, bal)
        dd = (peak - bal) / peak * 100
        max_dd = max(max_dd, dd)

    return {
        "trades": tt, "wins": len(wins), "losses": len(losses),
        "wr": wr, "pf": pf, "net": net,
        "avg_monthly": avg_monthly, "min_monthly": min_monthly,
        "max_dd": max_dd, "months": len(monthly),
        "monthly": dict(monthly), "all_trades": trades,
        "params": params
    }

# ─── Parameter Sweep ───
print("=" * 60)
print("SHIVA SNIPER OPTIMIZER — Target: $400+/month minimum")
print("=" * 60)

# Parameter ranges to sweep
sweep_configs = [
    # [sl_atr, trail_dist, vol_mult, rsi_long, rsi_short]
    [0.3, 0.3, 1.3, 55, 45],  # Default
    [0.4, 0.4, 1.2, 55, 45],
    [0.5, 0.5, 1.2, 55, 45],
    [0.3, 0.5, 1.3, 50, 50],
    [0.4, 0.6, 1.4, 50, 50],
    [0.25, 0.35, 1.5, 60, 40],
    [0.35, 0.45, 1.3, 60, 40],
    [0.3, 0.4, 1.5, 55, 45],
    [0.45, 0.5, 1.2, 58, 42],
    [0.5, 0.6, 1.4, 55, 45],
    [0.25, 0.3, 1.4, 58, 42],
    [0.35, 0.5, 1.5, 52, 48],
    [0.4, 0.4, 1.5, 60, 40],
    [0.3, 0.6, 1.2, 50, 50],
    [0.25, 0.4, 1.6, 55, 45],
]

results = []
best = None

for cfg_idx, cfg in enumerate(sweep_configs):
    params = {
        "sl_atr": cfg[0], "trail_dist": cfg[1], "vol_mult": cfg[2],
        "rsi_long": cfg[3], "rsi_short": cfg[4],
        "sess_start": 1, "sess_end": 22, "lookback": 250
    }

    result = backtest(params, data)
    if not result:
        print(f"  Config {cfg_idx+1}: No trades")
        continue

    passed = result["min_monthly"] >= 400
    star = "⭐" if passed else " "
    print(f"{star} Config {cfg_idx+1}: SL={cfg[0]} Trail={cfg[1]} Vol={cfg[2]} RSI({cfg[3]},{cfg[4]})"
          f" → {result['trades']} trades, WR={result['wr']:.1f}%, "
          f"Net=${result['net']:.0f}, AvgMo=${result['avg_monthly']:.0f}, "
          f"MinMo=${result['min_monthly']:.0f}, DD={result['max_dd']:.1f}%")

    results.append(result)

    if passed and (not best or result["min_monthly"] > best["min_monthly"]):
        best = result

# If no config hit $400, find the best and try refined sweeps around it
if not best:
    print("\n⚠️ No config hit $400/month minimum. Running refined sweeps...")
    # Sort by min_monthly descending, take top 3
    results.sort(key=lambda r: r["min_monthly"], reverse=True)
    top = results[:3]

    refinements = []
    for r in top:
        p = r["params"]
        # Try variations around the best params
        for sl_delta in [-0.05, 0, 0.05, 0.1]:
            for trail_delta in [-0.05, 0, 0.05, 0.1]:
                for vol_delta in [-0.1, 0, 0.1, 0.2]:
                    new_sl = round(p["sl_atr"] + sl_delta, 2)
                    new_trail = round(p["trail_dist"] + trail_delta, 2)
                    new_vol = round(p["vol_mult"] + vol_delta, 1)
                    if new_sl < 0.15 or new_sl > 0.7: continue
                    if new_trail < 0.15 or new_trail > 0.8: continue
                    if new_vol < 0.8 or new_vol > 2.0: continue
                    refinements.append({
                        "sl_atr": new_sl, "trail_dist": new_trail, "vol_mult": new_vol,
                        "rsi_long": p["rsi_long"], "rsi_short": p["rsi_short"],
                        "sess_start": 1, "sess_end": 22, "lookback": 250
                    })

    # Remove duplicates
    uniq = {}
    for r in refinements:
        key = f"{r['sl_atr']}_{r['trail_dist']}_{r['vol_mult']}_{r['rsi_long']}_{r['rsi_short']}"
        uniq[key] = r

    for params in uniq.values():
        result = backtest(params, data)
        if not result: continue
        results.append(result)
        passed = result["min_monthly"] >= 400
        star = "⭐" if passed else " "
        print(f"{star} Refined: SL={params['sl_atr']} Trail={params['trail_dist']} Vol={params['vol_mult']}"
              f" → {result['trades']} trades, WR={result['wr']:.1f}%, "
              f"Net=${result['net']:.0f}, AvgMo=${result['avg_monthly']:.0f}, "
              f"MinMo=${result['min_monthly']:.0f}, DD={result['max_dd']:.1f}%")
        if passed and (not best or result["min_monthly"] > best["min_monthly"]):
            best = result

# Select best result
if best:
    print(f"\n{'='*60}")
    print(f"✅ OPTIMUM FOUND — Min Monthly: ${best['min_monthly']:.0f}")
    print(f"{'='*60}")
else:
    print(f"\n{'='*60}")
    print(f"⚠️ Best available (closest to target):")
    results.sort(key=lambda r: r["min_monthly"], reverse=True)
    best = results[0]
    print(f"{'='*60}")

p = best["params"]
print(f"Parameters: SL={p['sl_atr']} ATR, Trail={p['trail_dist']} ATR, Vol={p['vol_mult']}x")
print(f"  RSI Long>{p['rsi_long']}, RSI Short<{p['rsi_short']}")
print(f"Trades: {best['trades']} | Win Rate: {best['wr']:.1f}%")
print(f"Net Profit: ${best['net']:.2f}")
print(f"Avg Monthly: ${best['avg_monthly']:.2f}")
print(f"Min Monthly: ${best['min_monthly']:.2f}")
print(f"Max Drawdown: {best['max_dd']:.2f}%")
print(f"Profit Factor: {best['pf']:.2f}")

# ─── Export results as JSON for dashboard ───
trades_out = []
for tr in best["all_trades"]:
    trades_out.append({
        "id": f"bt_{tr['entry_t']}",
        "symbol": "BTCUSD",
        "direction": "long" if tr["dir"] == "LONG" else "short",
        "entryTime": tr["entry_t"],
        "entryPrice": tr["entry_px"],
        "exitTime": tr.get("exit_t", tr["entry_t"]),
        "exitPrice": tr.get("exit_px", tr["entry_px"]),
        "qty": 100,  # 0.1 BTC = 100 lots
        "contractSize": 0.001,
        "exitReason": tr.get("reason", "TP"),
        "feeType": "taker"
    })

output = {
    "botStatus": {"status": "running", "qty": 100, "contractSize": 0.001, "timeframe": "30m",
                  "lastUpdate": int(time.time()*1000)},
    "trades": trades_out,
    "currentStep": 0,
    "backtest": {
        "params": {"sl_atr": p["sl_atr"], "trail_dist": p["trail_dist"], "vol_mult": p["vol_mult"],
                  "rsi_long": p["rsi_long"], "rsi_short": p["rsi_short"]},
        "net": round(best["net"], 2),
        "avg_monthly": round(best["avg_monthly"], 2),
        "min_monthly": round(best["min_monthly"], 2),
        "max_dd": round(best["max_dd"], 2),
        "wr": round(best["wr"], 1),
        "pf": round(best["pf"], 2),
        "trades": best["trades"],
        "months": best["months"],
        "monthly": best["monthly"]
    }
}

# Save to file
out_path = "D:\\Projects\\claudeCode\\backtest_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"\n✅ Results saved to {out_path}")
print(f"   Total trades exported: {len(trades_out)}")
print(f"\n💡 To push to dashboard:")
print(f"   curl -X POST http://YOUR_VPS:3000/api/state -H 'Content-Type: application/json' -d @{out_path}")
