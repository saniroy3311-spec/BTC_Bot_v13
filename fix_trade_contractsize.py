"""
fix_trade_contractsize.py
─────────────────────────────────────────────────────────────────────
Run ONCE on the VPS to correct the stored trade that was pushed with
contractSize = 0.1 (total BTC position) instead of
contractSize = 0.001 (BTC per lot — the correct Delta per-lot size).

Usage:
    python fix_trade_contractsize.py

What it does:
    1. Fetches current trades from the dashboard Node server
    2. For any trade with contractSize != 0.001, re-pushes it with
       contractSize = 0.001 so the dashboard recalculates correctly:
         Gross = points × qty × 0.001
         Fees  = price  × qty × 0.001 × rate × (1 + GST)
"""
import os, json, time, requests

PUSH_URL = os.environ.get("DASHBOARD_PUSH_URL", "http://localhost:3005/api/state")
STATE_URL = PUSH_URL.replace("/api/state", "/api/state")   # same endpoint for GET

CORRECT_CS = 0.001   # BTC_PER_LOT — the canonical per-lot contract size

def get_state():
    try:
        r = requests.get(STATE_URL, timeout=5)
        return r.json()
    except Exception as e:
        print(f"[ERROR] Cannot reach dashboard server at {STATE_URL}: {e}")
        return None

def repush_trade(trade: dict):
    corrected = dict(trade)
    corrected["contractSize"] = CORRECT_CS
    payload = {"trade": corrected}
    r = requests.post(PUSH_URL, json=payload, timeout=5)
    if r.status_code == 200:
        print(f"  ✅ Re-pushed trade {trade.get('id','')} with contractSize=0.001")
    else:
        print(f"  ❌ Failed: HTTP {r.status_code} — {r.text[:200]}")

def main():
    print("=" * 60)
    print("  fix_trade_contractsize.py — BTC Bot v13")
    print("=" * 60)

    state = get_state()
    if state is None:
        return

    # Trades may be in state["trades"] or state["trade"] (single)
    trades = state.get("trades", [])
    if not trades:
        # Try direct trade key
        t = state.get("trade")
        if t:
            trades = [t]

    if not trades:
        print("[INFO] No trades found in dashboard state.")
        print("       Nothing to fix.")
        return

    print(f"[INFO] Found {len(trades)} trade(s) in dashboard state.")
    fixed = 0
    for t in trades:
        cs = t.get("contractSize", None)
        tid = t.get("id", "unknown")
        print(f"\n  Trade {tid}:")
        print(f"    contractSize = {cs}")
        if cs != CORRECT_CS:
            print(f"    → WRONG (should be {CORRECT_CS}). Fixing…")
            repush_trade(t)
            fixed += 1
        else:
            print(f"    → Already correct. Skipping.")

    print(f"\n[DONE] Fixed {fixed} trade(s).")
    print("       Refresh the dashboard to see corrected P&L values.")

if __name__ == "__main__":
    main()
