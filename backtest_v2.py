"""
backtest_v2.py — BTC Bot v13 Strategy Test
Tests strategies on fresh BTC data with proper exit logic
"""
import pandas as pd
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from config import ALERT_QTY, COMMISSION_PCT


def load_data(path):
    df = pd.read_csv(path)
    return {c: df[c].values.astype(float) for c in df.columns}


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


def compute_indicators(close, high, low, volume):
    n = len(close)
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    ema200 = ema(close, 200)

    # ATR
    tr = np.full(n, np.nan)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr14 = rma(tr, 14)

    # RSI
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

    return {
        "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "atr14": atr14, "rsi": rsi
    }


def test_strategy(name, data, ind, entry_fn, sl_atr=0.8, tp_mult=2.0, max_bars=15):
    """Test a strategy. entry_fn(i) -> 'short'/'long'/None"""
    close = data["close"]
    high = data["high"]
    low = data["low"]
    n = len(close)

    trades = []
    for i in range(220, n - 1):
        sig = entry_fn(i, data, ind)
        if not sig:
            continue

        side = sig
        ep = close[i]
        sd = ind["atr14"][i] * sl_atr
        sl = ep + sd if side == "short" else ep - sd
        tp = ep - sd * tp_mult if side == "short" else ep + sd * tp_mult

        exited = False
        exit_price = 0
        exit_reason = ""

        for j in range(i, min(i + max_bars, n)):
            if side == "short":
                if high[j] >= sl:
                    exit_price = sl
                    exit_reason = "SL"
                    exited = True
                    break
                elif low[j] <= tp:
                    exit_price = tp
                    exit_reason = "TP"
                    exited = True
                    break
            else:  # long
                if low[j] <= sl:
                    exit_price = sl
                    exit_reason = "SL"
                    exited = True
                    break
                elif high[j] >= tp:
                    exit_price = tp
                    exit_reason = "TP"
                    exited = True
                    break

        if not exited:
            exit_price = close[min(i + max_bars - 1, n - 1)]
            exit_reason = "Timeout"

        pl_pct = (ep - exit_price) / ep * 100 if side == "short" else (exit_price - ep) / ep * 100
        trades.append({
            "bar": i,
            "side": side,
            "entry": ep,
            "exit": exit_price,
            "reason": exit_reason,
            "pl_pct": pl_pct,
            "pl_usd": (ep - exit_price) * (ALERT_QTY if ALERT_QTY else 1) if side == "short" else (exit_price - ep) * (ALERT_QTY if ALERT_QTY else 1)
        })

    if not trades:
        print(f"  {name:40s}  No trades")
        return []

    wins = sum(1 for t in trades if t["pl_pct"] > 0)
    total_pct = sum(t["pl_pct"] for t in trades)
    avg_pct = total_pct / len(trades)

    sl_count = sum(1 for t in trades if t["reason"] == "SL")
    tp_count = sum(1 for t in trades if t["reason"] == "TP")
    to_count = sum(1 for t in trades if t["reason"] == "Timeout")

    print(f"  {name:40s}  Trades={len(trades):4d}  WR={wins/len(trades)*100:5.1f}%  "
          f"Avg={avg_pct:+.4f}%  Total={total_pct:+.2f}%  "
          f"SL={sl_count}  TP={tp_count}  To={to_count}")

    return trades


if __name__ == "__main__":
    # Load fresh data
    data_path = os.path.join(os.path.dirname(__file__), "fresh_btc_data.csv")
    raw = pd.read_csv(data_path)
    data = {c: raw[c].values.astype(float) for c in raw.columns}
    ind = compute_indicators(data["close"], data["high"], data["low"], data["volume"])
    n = len(data["close"])

    print(f"Data: {n} candles")
    print(f"Range: ${data['low'].min():.0f} - ${data['high'].max():.0f}")
    print(f"Period: {pd.to_datetime(raw['timestamp'].iloc[0], unit='ms').date()} - "
          f"{pd.to_datetime(raw['timestamp'].iloc[-1], unit='ms').date()}")
    print()

    # Strategy 1: Short in Bear (RSI bounce)
    def short_bear(i, d, ind):
        if d["close"][i] < ind["ema200"][i] and ind["rsi"][i] > 45 and ind["rsi"][i] < 70 and ind["rsi"][i-1] <= 45:
            return "short"
        return None

    # Strategy 2: Long in Bull (RSI dip)
    def long_bull(i, d, ind):
        if d["close"][i] > ind["ema200"][i] and ind["rsi"][i] < 55 and ind["rsi"][i] > 30 and ind["rsi"][i-1] >= 55:
            return "long"
        return None

    # Strategy 3: Combined short+long
    def combined(i, d, ind):
        s = short_bear(i, d, ind)
        if s:
            return s
        return long_bull(i, d, ind)

    print("=== SHORT IN BEAR (RSI bounce) ===")
    test_strategy("Short bear RSI(45-70)", data, ind, short_bear, 0.8, 2.0, 15)

    print()
    print("=== LONG IN BULL (RSI dip) ===")
    test_strategy("Long bull RSI(30-55)", data, ind, long_bull, 0.8, 2.0, 15)

    print()
    print("=== COMBINED ===")
    test_strategy("Combined", data, ind, combined, 0.8, 2.0, 15)

    # Sweep SL and TP
    print()
    print("=== PARAMETER SWEEP (Short Bear) ===")
    for sl in [0.5, 0.8, 1.0, 1.5]:
        for tp in [1.5, 2.0, 2.5, 3.0]:
            test_strategy(f"SL={sl} TP={tp}x", data, ind, short_bear, sl, tp, 15)
        print()

    # Also test on OLD 2-year data for comparison
    print()
    print("=== TEST ON OLD 2-YEAR DATA ===")
    old_path = os.path.join(os.path.dirname(__file__), "BTCUSDT_30m_2year.csv")
    if os.path.exists(old_path):
        raw_old = pd.read_csv(old_path)
        num_cols = [c for c in raw_old.columns if c in ("open","high","low","close","volume")]
        data_old = {c: raw_old[c].values.astype(float) for c in num_cols}
        ind_old = compute_indicators(data_old["close"], data_old["high"], data_old["low"], data_old["volume"])
        print(f"Old data: {len(data_old['close'])} candles")
        test_strategy("Short bear RSI(45-70)", data_old, ind_old, short_bear, 0.8, 2.0, 15)
        test_strategy("Long bull RSI(30-55)", data_old, ind_old, long_bull, 0.8, 2.0, 15)
        test_strategy("Combined", data_old, ind_old, combined, 0.8, 2.0, 15)
