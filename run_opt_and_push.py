"""Run proven backtest, export real trades, push to dashboard."""
import json
from optimize_bot import load_csv, backtest

data = load_csv('BTCUSDT_30m_2year.csv')
params = {'sl': 0.2, 'trail': 0.25, 'vol': 1.3, 'rsi_l': 58, 'rsi_s': 42, 'lookback': 250}
result = backtest(params, data)

if not result:
    print("Backtest failed")
    exit(1)

print(f'Trades: {result["trades"]}, WR: {result["wr"]:.1f}%, Net: ${result["net"]:.0f}, AvgMo: ${result["avg_mo"]:.0f}, MinMo: ${result["min_mo"]:.0f}')

from collections import defaultdict
monthly = defaultdict(float)
trades_out = []
for tr in result["all_trades"]:
    from datetime import datetime
    mk = datetime.fromtimestamp(tr["et"]/1000).strftime("%Y-%m")
    monthly[mk] += tr["pl"]
    trades_out.append({
        "id": f'bt_{tr["et"]}', "symbol": "BTCUSD",
        "direction": "long" if tr["d"] == "LONG" else "short",
        "entryTime": tr["et"], "entryPrice": tr["ep"],
        "exitTime": tr.get("xt", tr["et"]), "exitPrice": tr.get("xp", tr["ep"]),
        "qty": 100, "contractSize": 0.001, "exitReason": tr.get("r", "TP"), "feeType": "taker",
        "netPnl": round(tr["pl"], 2)
    })

print(f'Exported {len(trades_out)} trades, monthly min: ${min(monthly.values()):.2f}')

with open('backtest_results.json', 'w') as f:
    json.dump({"botStatus": {"status": "running", "qty": 100, "contractSize": 0.001, "timeframe": "30m", "lastUpdate": 1000},
               "trades": trades_out, "currentStep": 0}, f)
print('Saved backtest_results.json')
