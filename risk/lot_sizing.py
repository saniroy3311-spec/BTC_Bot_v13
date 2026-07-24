"""
risk/lot_sizing.py — BTC Bot v13 v10
──────────────────────────────────────────────────────────────────────
Delta Exchange India BTCUSD perpetual contract sizing.

CONTRACT SPEC (verified against Delta-TransactionLog-OrderHistory.csv):
    1 Lot = 0.001 BTC face value  →  0.1 BTC = 100 Lots
    P&L (USD) = Points × Qty × 0.001  (inverse-style, $1 face per lot)

EXAMPLES:
    btc_to_lots(0.001) → 1
    btc_to_lots(0.05)  → 50
    btc_to_lots(0.1)   → 100
    btc_to_lots(1.0)   → 1000
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

# Delta Exchange BTCUSD contract spec
BTC_PER_LOT       = 0.001          # 1 lot = 0.001 BTC face value
USD_PER_POINT_LOT = 0.001          # P&L = points × qty × 0.001 USD
MIN_LOTS          = 1
MAX_LOTS          = 1_000_000      # sanity ceiling


def btc_to_lots(btc_size: float) -> int:
    """
    Convert intended BTC position size → Delta lots (contracts).

    Rule:  0.1 BTC = 100 Lots  ⇒  lots = btc_size / 0.001 = btc_size × 1000
    Always rounds to the nearest integer lot; clamps to [1, 1_000_000].

    Raises ValueError if btc_size <= 0.
    """
    if btc_size is None or btc_size <= 0:
        raise ValueError(f"btc_size must be > 0, got {btc_size!r}")

    raw_lots = btc_size / BTC_PER_LOT
    lots     = int(round(raw_lots))
    lots     = max(MIN_LOTS, min(MAX_LOTS, lots))

    if abs(raw_lots - lots) > 1e-6:
        logger.warning(
            f"btc_to_lots: {btc_size} BTC = {raw_lots:.4f} lots → rounded to {lots}"
        )
    return lots


def lots_to_btc(qty_lots: int) -> float:
    """Inverse — useful for logging/display."""
    return qty_lots * BTC_PER_LOT


def compute_pnl_usd(entry: float, exit_price: float, qty_lots: int,
                    is_long: bool) -> float:
    """
    Exact Delta P&L formula (verified against CSV transaction log):
        Points = (exit - entry) if LONG else (entry - exit)
        P&L USD = Points × qty × 0.001

    Returns the realised P&L in USD before fees.
    """
    points = (exit_price - entry) if is_long else (entry - exit_price)
    return round(points * qty_lots * USD_PER_POINT_LOT, 4)


def compute_points(entry: float, exit_price: float, is_long: bool) -> float:
    """Raw price points captured (positive = profit, negative = loss)."""
    return round((exit_price - entry) if is_long else (entry - exit_price), 2)


FEE_TAKER         = 0.0005
FEE_MAKER         = 0.0002
GST               = 0.18
SCALP_HOLD_WINDOW = 1800  # 30 minutes in seconds


def compute_trade_fees(
    entry_price  : float,
    exit_price   : float,
    qty_lots     : int,
    hold_seconds : float = 0,
    fee_type     : str   = "taker",
) -> dict:
    """
    Delta India commission fees + 18% GST + scalper fee waiver under 30 minutes.

    Contract spec: 1 lot = BTC_PER_LOT (0.001 BTC) face value.
    Fee = price × qty × BTC_PER_LOT × rate × (1 + GST)
    Scalper waiver: exit fee = 0 when hold time ≤ 30 minutes.
    """
    rate      = FEE_MAKER if fee_type == "maker" else FEE_TAKER
    cs        = BTC_PER_LOT                       # always 0.001 — canonical per-lot size
    entry_fee = entry_price * qty_lots * cs * rate * (1 + GST)

    scalper  = hold_seconds is not None and hold_seconds <= SCALP_HOLD_WINDOW
    exit_fee = 0.0 if scalper else (exit_price * qty_lots * cs * rate * (1 + GST))

    total = entry_fee + exit_fee
    return {
        "entry"  : round(entry_fee, 4),
        "exit"   : round(exit_fee, 4),
        "total"  : round(total, 4),
        "scalper": scalper,
    }


def compute_trade_pnl(
    entry_price  : float,
    exit_price   : float,
    qty_lots     : int,
    is_long      : bool,
    hold_seconds : float = 0,
    fee_type     : str   = "taker",
) -> dict:
    """
    Complete P&L breakdown (verified formula from Delta CSV log):

        Gross (USD) = points × qty_lots × BTC_PER_LOT   (= points × qty × 0.001)
        Fees  (USD) = price  × qty_lots × BTC_PER_LOT × rate × (1+GST)
        Net         = Gross − Fees

    100 lots × 0.001 BTC/lot = 0.1 BTC total position
    """
    points    = compute_points(entry_price, exit_price, is_long)
    cs        = BTC_PER_LOT                       # 0.001 — DO NOT substitute total BTC position
    gross     = points * qty_lots * cs
    fees_info = compute_trade_fees(entry_price, exit_price, qty_lots, hold_seconds, fee_type)
    net       = gross - fees_info["total"]
    return {
        "points" : points,
        "gross"  : round(gross, 4),
        "fees"   : round(fees_info["total"], 4),
        "net"    : round(net, 4),
        "scalper": fees_info["scalper"],
    }

