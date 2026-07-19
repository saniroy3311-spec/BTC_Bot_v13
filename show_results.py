import json, urllib.request
from collections import defaultdict
from datetime import datetime

req = urllib.request.Request('http://187.127.136.139/api/state')
data = json.loads(urllib.request.urlopen(req).read())
tr = data.get('trades', [])
if not tr:
    print('No trade data')
    exit()

monthly = defaultdict(float)
for t in tr:
    mk = datetime.fromtimestamp(t['entryTime']/1000).strftime('%Y-%m')
    monthly[mk] += t['netPnl']

total_net = sum(t['netPnl'] for t in tr)
wins = sum(1 for t in tr if t['netPnl'] > 0)
total = len(tr)
wr = wins/total*100
avg_mo = total_net/len(monthly)
min_mo = min(monthly.values())
max_mo = max(monthly.values())

cum=0; peak=10000; max_dd=0
for t in sorted(tr, key=lambda x: x['entryTime']):
    cum+=t['netPnl']
    bal=10000+cum
    if bal>peak: peak=bal
    dd=(peak-bal)/peak*100
    if dd>max_dd: max_dd=dd

gp = sum(t['netPnl'] for t in tr if t['netPnl']>0)
gl = abs(sum(t['netPnl'] for t in tr if t['netPnl']<0))
pf = gp/gl if gl else 99

print('=' * 55)
print('  SHIVA SNIPER - BACKTEST RESULTS')
print('  RSIMom+M3 | BTCUSDT 30m | 2 Years')
print('=' * 55)
print(f'  Total Trades:     {total}')
print(f'  Win Rate:         {wr:.1f}%')
print(f'  Total Net P/L:    ${total_net:,.2f}')
print(f'  Avg Monthly:      ${avg_mo:,.2f}')
print(f'  Min Month:        ${min_mo:,.2f}')
print(f'  Max Month:        ${max_mo:,.2f}')
print(f'  Profit Factor:    {pf:.2f}')
print(f'  Max Drawdown:     {max_dd:.2f}%')
print(f'  Base Capital:     $10,000')
print(f'  Position:         0.1 BTC (100 lots)')
print()
print('  Monthly:')
for mk in sorted(monthly.keys()):
    mt = [t for t in tr if datetime.fromtimestamp(t['entryTime']/1000).strftime('%Y-%m') == mk]
    ok = 'OK' if monthly[mk] >= 400 else 'LOW'
    print(f'  [{ok}] {mk}  {len(mt):>3} trades  ${monthly[mk]:>8,.2f}')
