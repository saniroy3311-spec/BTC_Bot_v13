"""
Shiva Sniper — Live Dashboard Push (real integration, not the example file)

Pushes bot status / open trade / closed trade events to the
shiva-dashboard Node server (server.js) running on this VPS.

Configure via .env:
    DASHBOARD_PUSH_URL=http://localhost:3005/api/state
    DASHBOARD_PUSH_ENABLED=true
"""

import os
import time
import logging
import requests

logger = logging.getLogger("dashboard_push")

DASHBOARD_PUSH_URL = os.environ.get("DASHBOARD_PUSH_URL", "http://localhost:3005/api/state")
DASHBOARD_PUSH_ENABLED = os.environ.get("DASHBOARD_PUSH_ENABLED", "true").lower() == "true"


def _post(data: dict) -> None:
    if not DASHBOARD_PUSH_ENABLED:
        return
    try:
        r = requests.post(DASHBOARD_PUSH_URL, json=data, timeout=3)
        if r.status_code != 200:
            logger.warning(f"[DASH-PUSH] HTTP {r.status_code}: {r.text[:200]}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"[DASH-PUSH] Error: {e}")


def push_status(status: str, qty=None, contract_size=None, timeframe=None) -> None:
    _post({
        "botStatus": {
            "status": status,
            "qty": qty,
            "contractSize": contract_size,
            "timeframe": timeframe,
            "lastUpdate": int(time.time() * 1000),
        }
    })


def push_open_trade(direction, entry_price, sl, tp, current_price=None, unrealized_pnl=None) -> None:
    if direction is None:
        _post({"openTrade": None})
        return
    _post({
        "openTrade": {
            "direction": direction,
            "entryPrice": entry_price,
            "entryTime": int(time.time() * 1000),
            "sl": sl,
            "tp": tp,
            "currentPrice": current_price if current_price is not None else entry_price,
            "unrealizedPnl": unrealized_pnl or 0.0,
        }
    })


def push_trade(trade_id, direction, entry_price, exit_price, entry_time, exit_time,
               qty, contract_size, exit_reason, symbol="BTCUSD", fee_type="taker") -> None:
    _post({
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
            "feeType": fee_type,
        }
    })
    _post({"openTrade": None})


def push_workflow_step(step_index: int) -> None:
    _post({"currentStep": step_index})


def push_trade_id(entry_time_ms: int) -> str:
    return f"t{entry_time_ms}"
