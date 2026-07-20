import csv, json
from datetime import datetime

trades = []
with open('bt_trades.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        t = int(row['entry_ts'])
        et = int(row['exit_ts']) if row.get('exit_ts') and row['exit_ts'] != '0' else t
        trades.append({
            'id': f"bt_{row['trade_id']}", 'symbol': 'BTCUSD',
            'direction': 'long' if row['is_long'].lower() == 'true' else 'short',
            'entryTime': t, 'entryPrice': round(float(row['entry_price']), 2),
            'exitTime': et, 'exitPrice': round(float(row['exit_price']), 2),
            'qty': 100, 'contractSize': 0.001,
            'exitReason': row.get('exit_reason', 'TP'),
            'feeType': 'taker',
            # real_pl from backtest is for 1 lot (0.001 BTC). For 0.1 BTC (100 lots):
            # multiply by 100 (lots) * 0.001 (contract_size) to get USD P/L
            'netPnl': round(float(row['real_pl']) * 100 * 0.001, 2)
        })

with open('backtest_results.json', 'w') as f:
    json.dump({'botStatus': {'status':'running','qty':100,'contractSize':0.001,'timeframe':'30m','lastUpdate':1000},
               'trades': trades, 'currentStep': 0}, f)

net = sum(t['netPnl'] for t in trades)
wins = sum(1 for t in trades if t['netPnl'] > 0)
print(f'Trades: {len(trades)}, Net: ${net:.0f}, WR: {wins/len(trades)*100:.1f}%')

monthly = {}
for t in trades:
    mk = datetime.fromtimestamp(t['entryTime']/1000).strftime('%Y-%m')
    monthly[mk] = monthly.get(mk, 0) + t['netPnl']
min_mo = min(monthly.values())
print(f'Min month: ${min_mo:.0f}')
print(f'Saved backtest_results.json')
