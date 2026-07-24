/**
 * Shiva Sniper — React Dashboard Component
 *
 * Props:
 *   currentStage  : string   — one of "Fetch Candle","Eval Signal","Entry Check",
 *                               "Position Open","Monitor SL/TP","Exit","Log Trade","↻"
 *   botStatus     : object   — { status, qty, contractSize, timeframe, lastUpdate }
 *   openTrade     : object?  — { direction, entryPrice, entryTime, sl, tp, currentPrice, unrealizedPnl }
 *   trades        : array    — TradeLogEntry[] (see spec)
 *
 * Usage:
 *   <ShivaSniperDashboard currentStage="Position Open" botStatus={{...}} trades={[...]} />
 */

import React, { useState, useMemo } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts';

// ─── Constants ───
const FEE_RATE_TAKER = 0.0005;
const FEE_RATE_MAKER = 0.0002;
const GST = 0.18;
const SCALP_BTC = 30 * 60;
const SCALP_OTHER = 15 * 60;

const STEPS = [
  { id: 'fetch', l: 'Fetch Candle' },
  { id: 'eval', l: 'Eval Signal' },
  { id: 'entry', l: 'Entry Check' },
  { id: 'pos', l: 'Position Open' },
  { id: 'mon', l: 'Monitor SL/TP' },
  { id: 'exit', l: 'Exit' },
  { id: 'log', l: 'Log Trade' },
  { id: 'loop', l: '↻' },
];

// ─── Fee helpers ───
const calcFee = (p, q, cs, t = 'taker') =>
  p * q * cs * (t === 'maker' ? FEE_RATE_MAKER : FEE_RATE_TAKER) * (1 + GST);

const computeTrade = (t) => {
  const pts = (t.exitPrice - t.entryPrice) * (t.direction === 'long' ? 1 : -1);
  const gross = pts * t.qty * t.contractSize;
  const hold = (t.exitTime - t.entryTime) / 1000;
  const btcEth = t.symbol === 'BTCUSD' || t.symbol === 'ETHUSD';
  const window = btcEth ? SCALP_BTC : SCALP_OTHER;
  const entryFee = calcFee(t.entryPrice, t.qty, t.contractSize, t.feeType);
  let exitFee = 0, scalper = false;
  if (t.exitReason === 'liquidation') {
    exitFee = calcFee(t.exitPrice, t.qty, t.contractSize, t.feeType);
  } else if (hold <= window) {
    scalper = true;
  } else {
    exitFee = calcFee(t.exitPrice, t.qty, t.contractSize, t.feeType);
  }
  return { ...t, pointsCaptured: pts, grossPnl: gross, totalCommission: entryFee + exitFee, netPnl: gross - entryFee - exitFee, scalperApplied: scalper };
};

const fmtTime = (ts) => {
  if (!ts) return '—';
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

const fmtDateOnly = (ts) => {
  if (!ts) return '—';
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const fmtTimeOnly = (ts) => {
  if (!ts) return '—';
  const d = new Date(ts);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
};

const fmtHold = (ms) => {
  if (!ms) return '—';
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}m ${s % 60}s`;
};

const fmtUsd = (v) => {
  if (v == null) return '$0';
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toFixed(2)}`;
};

// ─── Tabs ───
function TabBar({ active, onChange }) {
  return (
    <div className="flex border-b border-[rgba(31,42,36,0.15)] mb-4">
      {['Overview', 'Trade Log'].map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-[3px] -mb-px ${
            active === t
              ? 'text-[#2D6A4F] border-[#2D6A4F]'
              : 'text-[rgba(31,42,36,0.55)] border-transparent hover:text-[#2D6A4F]'
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

// ─── Status Dot ───
function StatusDot({ status }) {
  return (
    <span className="relative inline-flex w-2 h-2">
      <span
        className={`absolute inset-0 rounded-full ${
          status === 'running'
            ? 'bg-[#3A7D44] animate-ping opacity-40'
            : 'hidden'
        }`}
      />
      <span
        className={`relative inline-block w-2 h-2 rounded-full ${
          status === 'running'
            ? 'bg-[#3A7D44]'
            : status === 'error'
            ? 'bg-[#E07A3E]'
            : 'bg-[#8A8A82]'
        }`}
      />
    </span>
  );
}

// ─── Workflow ───
const MARCHING_ANTS = `
@keyframes march { 0% { left: -8px; } 100% { left: 100%; } }
@keyframes wf-glow { 0%,100% { box-shadow: 0 0 0 0 rgba(224,122,62,0.4); } 50% { box-shadow: 0 0 0 6px rgba(224,122,62,0); } }
@keyframes spin-once { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
`;

function WorkflowStrip({ currentStage }) {
  const [cycleCount, setCycleCount] = React.useState(0);
  const prevRef = React.useRef(currentStage);

  React.useEffect(() => {
    if (prevRef.current === '↻' && currentStage === 'Fetch Candle') {
      setCycleCount((c) => c + 1);
    }
    prevRef.current = currentStage;
  }, [currentStage]);

  const activeIdx = STEPS.findIndex((s) => s.l === currentStage);

  return (
    <div className="bg-white border border-[rgba(31,42,36,0.15)] p-3">
      <style>{MARCHING_ANTS}</style>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs font-semibold text-[#1F2A24]">Bot Cycle</h3>
        <span className="text-[0.65rem] font-semibold text-[#E07A3E]">
          {currentStage || 'Awaiting bot...'}
        </span>
      </div>
      <div className="flex items-center overflow-x-auto pb-1">
        {STEPS.map((s, i) => {
          const isDone = activeIdx >= 0 && i < activeIdx;
          const isActive = i === activeIdx;
          const isFuture = activeIdx < 0 || i > activeIdx;
          return (
            <React.Fragment key={s.id}>
              <div
                className={`flex-shrink-0 px-[5px] py-[3px] text-[0.55rem] font-semibold whitespace-nowrap border-[1.5px] transition-all leading-tight ${
                  isActive
                    ? 'border-[#E07A3E] text-[#1F2A24] bg-[rgba(224,122,62,0.06)] shadow-[0_0_0_3px_rgba(224,122,62,0.1)]'
                    : isDone
                    ? 'border-[#2D6A4F] text-[#2D6A4F] bg-[rgba(45,106,79,0.05)]'
                    : 'border-[rgba(31,42,36,0.15)] text-[rgba(31,42,36,0.55)]'
                } ${isActive ? 'animate-[wf-glow_1.2s_ease-in-out_infinite]' : ''}`}
              >
                {s.l}
                {s.id === 'loop' && cycleCount > 0 && (
                  <span
                    className="inline-block ml-0.5"
                    key={cycleCount}
                    style={{ animation: 'spin-once 0.5s ease-out' }}
                  >
                    {cycleCount}
                  </span>
                )}
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`flex-shrink-0 w-[18px] h-[2px] relative overflow-hidden ${
                    isDone
                      ? 'bg-[#2D6A4F]'
                      : isActive
                      ? 'bg-[#E07A3E]'
                      : 'bg-[rgba(31,42,36,0.15)]'
                  }`}
                >
                  {isActive && (
                    <span
                      className="absolute top-0 w-[6px] h-full bg-[#E07A3E] opacity-70"
                      style={{ animation: 'march 0.6s linear infinite' }}
                    />
                  )}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

// ─── Stats Row ───
function StatsRow({ botStatus, openTrade }) {
  const items = [
    { label: 'QTY (LOTS)', value: botStatus?.qty ?? '—' },
    { label: 'TIMEFRAME', value: botStatus?.timeframe ?? '—' },
    {
      label: 'DIRECTION',
      value: openTrade ? (openTrade.direction === 'long' ? '🟢 Long' : '🔴 Short') : '—',
      sub: openTrade?.entryPrice ? `$${openTrade.entryPrice.toLocaleString()}` : null,
    },
    {
      label: 'UNREALIZED P/L',
      value: openTrade ? fmtUsd(openTrade.unrealizedPnl) : '—',
      cls: openTrade?.unrealizedPnl != null ? (openTrade.unrealizedPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]') : '',
    },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 bg-white border border-[rgba(31,42,36,0.15)]">
      {items.map((item) => (
        <div key={item.label} className="px-3 py-2 border-r border-b border-[rgba(31,42,36,0.08)] last:border-r-0">
          <div className="text-[0.55rem] uppercase tracking-wider text-[rgba(31,42,36,0.55)] mb-0.5">{item.label}</div>
          <div className={`text-sm font-bold text-[#1F2A24] ${item.cls || ''}`}>{item.value}</div>
          {item.sub && <div className="text-[0.55rem] text-[rgba(31,42,36,0.55)]">{item.sub}</div>}
        </div>
      ))}
    </div>
  );
}

// ─── Price Ladder ───
function PriceLadder({ openTrade }) {
  if (!openTrade) return null;
  const { sl, entryPrice, currentPrice, tp } = openTrade;
  const prices = [sl, entryPrice, currentPrice, tp].filter((p) => p != null);
  if (prices.length < 2) return null;
  const mn = Math.min(...prices);
  const mx = Math.max(...prices);
  const r = mx - mn || 1;
  const pct = (v) => `${((v - mn) / r) * 100}%`;
  return (
    <div className="bg-white border border-[rgba(31,42,36,0.15)] p-3">
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs font-semibold text-[#1F2A24]">Open Trade</span>
        <span className="text-[0.65rem]">
          {openTrade.direction === 'long' ? '🟢 Long' : '🔴 Short'}
          <span className={`ml-2 font-mono text-xs font-semibold ${openTrade.unrealizedPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'}`}>
            {fmtUsd(openTrade.unrealizedPnl)}
          </span>
        </span>
      </div>
      <div className="relative h-[5px] bg-[#D4D2CA] mt-3 mb-1">
        <div className="absolute top-1/2 -translate-y-1/2 w-[10px] h-[10px] border-[1.5px] bg-white z-[3]" style={{ left: pct(entryPrice), borderColor: '#2D6A4F' }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-[8px] h-[8px] border-[1.5px] bg-white z-[2]" style={{ left: pct(sl), borderColor: '#B8863B' }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-[8px] h-[8px] border-[1.5px] bg-white z-[2]" style={{ left: pct(tp), borderColor: '#3A7D44' }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-[8px] h-[8px] border-[1.5px] z-[4]" style={{ left: pct(currentPrice), borderColor: '#E07A3E', background: '#E07A3E' }} />
      </div>
      <div className="flex justify-between text-[0.55rem] text-[rgba(31,42,36,0.55)]">
        <span className="text-[#B8863B] font-semibold">SL: ${sl?.toLocaleString() || '—'}</span>
        <span className="text-[#2D6A4F] font-semibold">Entry: ${entryPrice?.toLocaleString() || '—'}</span>
        <span className="text-[#E07A3E] font-semibold">Cur: ${currentPrice?.toLocaleString() || '—'}</span>
        <span className="text-[#3A7D44] font-semibold">TP: ${tp?.toLocaleString() || '—'}</span>
      </div>
    </div>
  );
}

// ─── Equity Curve ───
function EquityCurve({ trades }) {
  const chartData = useMemo(() => {
    if (!trades || !trades.length) return null;
    let cum = 0;
    return trades
      .slice()
      .sort((a, b) => a.entryTime - b.entryTime)
      .map((t) => {
        cum += t.netPnl;
        return { time: fmtTime(t.entryTime), cum: Number(cum.toFixed(2)) };
      });
  }, [trades]);

  if (!chartData) {
    return (
      <div className="bg-white border border-[rgba(31,42,36,0.15)] p-4 flex items-center gap-2 text-[0.75rem] text-[rgba(31,42,36,0.55)]">
        <span>📈</span> <span>Waiting for trades...</span>
      </div>
    );
  }

  return (
    <div className="bg-white border border-[rgba(31,42,36,0.15)] p-3">
      <h3 className="text-xs font-semibold text-[#1F2A24] mb-2">Equity Curve</h3>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="rgba(31,42,36,0.06)" />
          <XAxis dataKey="time" tick={{ fontSize: 9, fill: '#8A8A82' }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 9, fill: '#8A8A82' }} tickFormatter={(v) => fmtUsd(v)} width={60} />
          <Tooltip
            formatter={(v) => [fmtUsd(v), 'Net P/L']}
            contentStyle={{ fontSize: 12, background: '#fff', border: '1px solid rgba(31,42,36,0.15)', borderRadius: 0 }}
          />
          <Line
            type="monotone"
            dataKey="cum"
            stroke="#2D6A4F"
            strokeWidth={2}
            dot={false}
            fill="rgba(45,106,79,0.08)"
            fillOpacity={1}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─── Overview Page ───
function OverviewPage({ currentStage, botStatus, openTrade, trades }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-[1.3fr_1fr] gap-3">
      <div className="flex flex-col gap-3">
        <WorkflowStrip currentStage={currentStage} />
        <StatsRow botStatus={botStatus} openTrade={openTrade} />
        {openTrade && <PriceLadder openTrade={openTrade} />}
      </div>
      <div>
        <EquityCurve trades={trades} />
      </div>
    </div>
  );
}

// ─── Trade Log Page ───
function TradeLogPage({ trades }) {
  const [sortKey, setSortKey] = useState('entryTime');
  const [sortAsc, setSortAsc] = useState(false);
  const [expanded, setExpanded] = useState(null);

  const computed = useMemo(() => trades.map(computeTrade), [trades]);

  const sorted = useMemo(() => {
    return [...computed].sort((a, b) => {
      let va = a[sortKey], vb = b[sortKey];
      if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
      return va < vb ? (sortAsc ? -1 : 1) : va > vb ? (sortAsc ? 1 : -1) : 0;
    });
  }, [computed, sortKey, sortAsc]);

  const summary = useMemo(() => {
    const total = computed.length;
    const wins = computed.filter((t) => t.netPnl > 0).length;
    return {
      total,
      winRate: total ? ((wins / total) * 100).toFixed(1) : '0.0',
      netPnl: computed.reduce((s, t) => s + t.netPnl, 0),
      comm: computed.reduce((s, t) => s + t.totalCommission, 0),
    };
  }, [computed]);

  const handleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  };

  const SortArrow = ({ col }) => (
    <span className="ml-0.5 text-[0.55rem] opacity-40">
      {sortKey === col ? (sortAsc ? '▲' : '▼') : '▲▼'}
    </span>
  );

  if (!trades || !trades.length) {
    return (
      <div className="text-center py-8 text-[rgba(31,42,36,0.55)] text-sm">
        📋 No trade history
      </div>
    );
  }

  // Summary bar
  const summaryData = [
    { label: 'Total Trades', value: summary.total, cls: '' },
    { label: 'Win Rate', value: `${summary.winRate}%`, cls: '' },
    { label: 'Net P/L', value: fmtUsd(summary.netPnl), cls: summary.netPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]' },
    { label: 'Commission', value: fmtUsd(summary.comm), cls: '' },
  ];

  const cols = [
    { key: 'entryTime', label: 'Date' },
    { key: '_entryTimeOnly', label: 'Entry Time' },
    { key: 'entryPrice', label: 'Entry Point' },
    { key: '_exitTimeOnly', label: 'Exit Time' },
    { key: 'exitPrice', label: 'Exit Point' },
    { key: 'direction', label: 'Dir' },
    { key: 'pointsCaptured', label: 'Pts' },
    { key: 'exitReason', label: 'Exit' },
    { key: 'grossPnl', label: 'Gross' },
    { key: 'totalCommission', label: 'Comm' },
    { key: 'netPnl', label: 'Net' },
    { key: '_scalper', label: 'Scalper' },
    { key: '_hold', label: 'Hold' },
  ];

  return (
    <div>
      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-4">
        {summaryData.map((s) => (
          <div key={s.label} className="bg-white border border-[rgba(31,42,36,0.15)] px-3 py-2">
            <div className="text-[0.55rem] uppercase tracking-wider text-[rgba(31,42,36,0.55)]">{s.label}</div>
            <div className={`text-sm font-bold text-[#1F2A24] ${s.cls}`}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Desktop table */}
      <div className="overflow-x-auto bg-white border border-[rgba(31,42,36,0.15)] hidden md:block">
        <table className="w-full text-[0.68rem] border-collapse">
          <thead>
            <tr>
              {cols.map((c, i) => (
                <th
                  key={c.key + i}
                  onClick={c.key[0] !== '_' ? () => handleSort(c.key) : undefined}
                  className={`text-left px-2 py-1.5 font-semibold text-[0.6rem] uppercase tracking-wider text-[rgba(31,42,36,0.55)] border-b-2 border-[rgba(31,42,36,0.12)] whitespace-nowrap ${c.key[0] !== '_' ? 'cursor-pointer hover:text-[#2D6A4F]' : ''} ${sortKey === c.key ? 'text-[#2D6A4F]' : ''}`}
                >
                  {c.label}
                  {c.key[0] !== '_' && <SortArrow col={c.key} />}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => (
              <tr key={t.id} className="hover:bg-[rgba(45,106,79,0.04)]">
                <td className="px-2 py-1.5 whitespace-nowrap font-mono font-bold text-[#1F2A24]">{fmtDateOnly(t.entryTime)}</td>
                <td className="px-2 py-1.5 whitespace-nowrap font-mono">{fmtTimeOnly(t.entryTime)}</td>
                <td className="px-2 py-1.5 text-right font-mono">${(t.entryPrice || 0).toLocaleString()}</td>
                <td className="px-2 py-1.5 whitespace-nowrap font-mono">{fmtTimeOnly(t.exitTime)}</td>
                <td className="px-2 py-1.5 text-right font-mono">${(t.exitPrice || 0).toLocaleString()}</td>
                <td className="px-2 py-1.5">{t.direction === 'long' ? 'L' : 'S'}</td>
                <td className={`px-2 py-1.5 text-right font-mono ${(t.pointsCaptured || 0) >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'}`}>{t.pointsCaptured.toFixed(0)}</td>
                <td className="px-2 py-1.5">
                  <span className={`inline-block text-[0.55rem] font-semibold px-1.5 py-0.5 ${t.netPnl >= 0 ? 'bg-[#3A7D44] text-white' : 'bg-[#B8863B] text-white'}`}>
                    {t.exitReason || '—'}
                  </span>
                </td>
                <td className={`px-2 py-1.5 text-right font-mono ${(t.grossPnl || 0) >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'}`}>{fmtUsd(t.grossPnl)}</td>
                <td className="px-2 py-1.5 text-right font-mono">{fmtUsd(t.totalCommission)}</td>
                <td className={`px-2 py-1.5 text-right font-mono font-semibold ${t.netPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'}`}>{fmtUsd(t.netPnl)}</td>
                <td className="px-2 py-1.5">{t.scalperApplied ? <span className="text-[0.55rem] font-semibold text-[#E07A3E] border border-[#E07A3E] px-1">Scalper ✓</span> : '—'}</td>
                <td className="px-2 py-1.5 font-mono whitespace-nowrap">{fmtHold(t.exitTime - t.entryTime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile cards */}
      <div className="md:hidden flex flex-col gap-2">
        {sorted.map((t) => {
          const open = expanded === t.id;
          return (
            <div key={t.id} className="bg-white border border-[rgba(31,42,36,0.15)]">
              <div
                className="flex justify-between items-center px-3 py-2 cursor-pointer select-none"
                onClick={() => setExpanded(open ? null : t.id)}
              >
                <span className="text-xs font-bold">
                  {t.direction === 'long' ? '🟢 Long' : '🔴 Short'} · {fmtTime(t.entryTime)}
                </span>
                <span className={`text-xs font-bold font-mono ${t.netPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'}`}>
                  {fmtUsd(t.netPnl)}
                </span>
              </div>
              {open && (
                <div className="px-3 py-2 border-t border-[rgba(31,42,36,0.15)] text-[0.68rem] space-y-1">
                  <Row label="Exit" value={fmtTime(t.exitTime)} />
                  <Row label="Price" value={`$${t.entryPrice.toLocaleString()} → $${t.exitPrice.toLocaleString()}`} />
                  <Row label="Pts" value={t.pointsCaptured.toFixed(0)} />
                  <Row label="Exit" value={t.exitReason || '—'} valueCls={t.netPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'} />
                  <Row label="Gross" value={fmtUsd(t.grossPnl)} />
                  <Row label="Comm" value={fmtUsd(t.totalCommission)} />
                  <Row label="Net" value={fmtUsd(t.netPnl)} valueCls={`font-semibold ${t.netPnl >= 0 ? 'text-[#3A7D44]' : 'text-[#B8863B]'}`} />
                  <Row label="Scalper" value={t.scalperApplied ? '✓' : '—'} />
                  <Row label="Hold" value={fmtHold(t.exitTime - t.entryTime)} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Row({ label, value, valueCls }) {
  return (
    <div className="flex justify-between">
      <span className="text-[rgba(31,42,36,0.55)]">{label}</span>
      <span className={`font-medium ${valueCls || ''}`}>{value}</span>
    </div>
  );
}

// ─── Main Component ───
export default function ShivaSniperDashboard({
  currentStage = null,
  botStatus = null,
  openTrade = null,
  trades = [],
}) {
  const [tab, setTab] = useState('Overview');

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-0 font-sans text-[#1F2A24]">
      {/* Top Bar */}
      <div className="flex items-center gap-2 px-3 py-2 mb-3 bg-white border border-[rgba(31,42,36,0.15)] text-xs">
        <StatusDot status={botStatus?.status} />
        <span className="font-medium text-[#1F2A24]">{botStatus?.status === 'running' ? 'Live' : botStatus?.status || 'Offline'}</span>
        <span className="ml-auto text-[0.65rem] text-[rgba(31,42,36,0.55)]">
          {botStatus?.lastUpdate ? fmtTime(botStatus.lastUpdate) : ''}
        </span>
      </div>

      {/* Title + Tabs */}
      <div className="flex items-center gap-4 border-b border-[rgba(31,42,36,0.15)] pb-3 mb-4">
        <h1 className="text-base font-bold text-[#2D6A4F] whitespace-nowrap">Shiva Sniper</h1>
        <TabBar active={tab} onChange={setTab} />
      </div>

      {/* Pages */}
      {tab === 'Overview' && (
        <OverviewPage
          currentStage={currentStage}
          botStatus={botStatus}
          openTrade={openTrade}
          trades={trades}
        />
      )}
      {tab === 'Trade Log' && <TradeLogPage trades={trades} />}
    </div>
  );
}
