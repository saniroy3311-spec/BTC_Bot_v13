import json
with open('backtest_real_results.json') as f:
    trades = json.load(f)
print(f'Total trades: {len(trades)}')
if trades:
    t = trades[0]
    print(f'First: is_long={t.get("is_long")}, entry={t.get("entry_price")}, exit={t.get("exit_price")}')
    print(f'  sl={t.get("sl")}, tp={t.get("tp")}, pl={t.get("real_pl")}, reason={t.get("exit_reason")}')
    t2 = trades[min(10, len(trades)-1)]
    print(f'Trade 11: is_long={t2.get("is_long")}, entry={t2.get("entry_price")}, exit={t2.get("exit_price")}')
    print(f'  sl={t2.get("sl")}, tp={t2.get("tp")}, pl={t2.get("real_pl")}, reason={t2.get("exit_reason")}')
    longs = sum(1 for t in trades if t.get('is_long'))
    shorts = sum(1 for t in trades if not t.get('is_long'))
    print(f'Longs: {longs}, Shorts: {shorts}')
    pos_pl = sum(1 for t in trades if t.get('real_pl',0) > 0)
    neg_pl = sum(1 for t in trades if t.get('real_pl',0) <= 0)
    total_pl = sum(t.get('real_pl',0) for t in trades)
    print(f'Wins: {pos_pl}, Losses: {neg_pl}, Total PL: {total_pl:.2f}')
