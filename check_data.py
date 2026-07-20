import json
d = json.load(open('backtest_results.json'))
tr = d['trades']
print(f'Trades: {len(tr)}')
print(f'Sample: {tr[0]["id"]} netPnl={tr[0]["netPnl"]}')
net = sum(t['netPnl'] for t in tr)
print(f'Total net: ${net:.2f}')
wins = sum(1 for t in tr if t['netPnl'] > 0)
print(f'WR: {wins}/{len(tr)} = {wins/len(tr)*100:.1f}%')
