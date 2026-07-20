"""
Shiva Sniper — Bot → Dashboard Push Example

Your live trading bot calls these functions to push state
to the dashboard server running on your VPS.

Usage:
    from bot_push_example import push_status, push_trade, push_open_trade

    push_status("running", qty=33, contract_size=0.001, timeframe="30m")
    push_trade("t01", direction="long", entry_price=63200, ...)
    push_open_trade("long", entry_price=64150, sl=63720, tp=65180)
"""

import requests
import json
import time

# ─── CONFIG: Change this to your VPS domain ─────────────────
DASHBOARD_URL = "http://your-vps-domain.com:3000/api/state"
# Or with a subdomain:
# DASHBOARD_URL = "https://shiva.yourdomain.com/api/state"


def push_status(status, qty, contract_size, timeframe):
    """Update bot status (running/stopped/error)."""
    payload = {
        "botStatus": {
            "status": status,
            "qty": qty,
            "contractSize": contract_size,
            "timeframe": timeframe,
            "lastUpdate": int(time.time() * 1000)
        }
    }
    _post(payload)


def push_open_trade(direction, entry_price, sl, tp, current_price=None, unrealized_pnl=None):
    """Update the currently open trade (or None to clear)."""
    if direction is None:
        payload = {"openTrade": None}
    else:
        payload = {
            "openTrade": {
                "direction": direction,
                "entryPrice": entry_price,
                "entryTime": int(time.time() * 1000),
                "sl": sl,
                "tp": tp,
                "currentPrice": current_price or entry_price,
                "unrealizedPnl": unrealized_pnl or 0.0
            }
        }
    _post(payload)


def push_trade(trade_id, direction, entry_price, exit_price, entry_time, exit_time,
               qty, contract_size, exit_reason, symbol="BTCUSD", fee_type="taker"):
    """Push a completed trade to the dashboard."""
    payload = {
        "trade": {
            "id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entryTime": entry_time,
            "entryPrice": entry_price,
            "exitTime": exit_time,
            "exitPrice": exit_price,
            "qty": qty,
            "contractSize": contract_size,
            "exitReason": exit_reason,
            "feeType": fee_type
        }
    }
    _post(payload)


def push_workflow_step(step_index):
    """Set the current workflow step (0-7)."""
    payload = {"currentStep": step_index}
    _post(payload)


def push_trades_bulk(trades_list):
    """Replace the entire trade history."""
    payload = {"trades": trades_list}
    _post(payload)


def _post(data):
    try:
        r = requests.post(DASHBOARD_URL, json=data, timeout=5)
        if r.status_code == 200:
            print(f"[Dashboard] OK — {r.json()}")
        else:
            print(f"[Dashboard] HTTP {r.status_code}: {r.text}")
    except requests.exceptions.RequestException as e:
        print(f"[Dashboard] Error: {e}")


# ─── Example usage ──────────────────────────────────────────
if __name__ == "__main__":
    # When bot starts:
    push_status("running", qty=33, contract_size=0.001, timeframe="30m")

    # When a trade opens:
    push_open_trade("long", entry_price=64150, sl=63720, tp=65180,
                    current_price=64300, unrealized_pnl=5.25)

    # When a trade closes:
    push_trade(
        trade_id="t001",
        direction="long",
        entry_price=63200,
        exit_price=64780,
        entry_time=int(time.time() * 1000) - 3600000,
        exit_time=int(time.time() * 1000),
        qty=33,
        contract_size=0.001,
        exit_reason="TP",
        symbol="BTCUSD"
    )

    # When workflow step changes:
    push_workflow_step(3)
