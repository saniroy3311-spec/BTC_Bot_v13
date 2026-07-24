// ============================================================
//  Shiva Sniper — Live Dashboard API Server
//  Run: node server.js
//
//  Endpoints:
//    GET  /api/state   → returns current bot state (dashboard polls this)
//    POST /api/state   → bot pushes state updates here
//    GET  /            → serves the dashboard HTML
// ============================================================

const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;

// ─── Telegram config ───────────────────────────────────────
// Priority: config.json > env vars > no notifications
// Create config.json on VPS: { "botToken": "...", "chatId": "..." }
let TELEGRAM_BOT_TOKEN = null;
let TELEGRAM_CHAT_ID = null;
try {
  const cfgPath = path.join(__dirname, 'config.json');
  if (fs.existsSync(cfgPath)) {
    const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    TELEGRAM_BOT_TOKEN = cfg.botToken || process.env.TELEGRAM_BOT_TOKEN;
    TELEGRAM_CHAT_ID = cfg.chatId || process.env.TELEGRAM_CHAT_ID;
  } else {
    TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
    TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;
  }
} catch (e) {
  TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
  TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;
}

if (TELEGRAM_BOT_TOKEN && TELEGRAM_CHAT_ID) {
  console.log('[Telegram] Notifications enabled');
} else {
  console.log('[Telegram] Notifications disabled (set botToken + chatId in config.json or env vars)');
}

// Track last notified trade IDs so we don't spam duplicates
const notifiedTrades = new Set();

async function sendTelegram(message) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  try {
    const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: TELEGRAM_CHAT_ID,
        text: message,
        parse_mode: 'HTML',
        disable_web_page_preview: true
      })
    });
  } catch (err) {
    console.error('[Telegram] Failed:', err.message);
  }
}

function formatTradeNotification(trade) {
  const dir = trade.direction === 'long' ? '🟢 LONG' : '🔴 SHORT';
  const pnl = ((trade.exitPrice - trade.entryPrice) * (trade.direction === 'long' ? 1 : -1) * trade.qty * trade.contractSize).toFixed(2);
  const symbol = trade.symbol || 'BTCUSD';
  const reason = trade.exitReason || 'manual';
  const holdMin = trade.exitTime && trade.entryTime ? Math.round((trade.exitTime - trade.entryTime) / 60000) : '?';

  return (
    `<b>🤖 Shiva Sniper — Trade Closed</b>\n` +
    `<b>${dir}</b> ${symbol}\n` +
    `─────────────────\n` +
    `Entry: $${Number(trade.entryPrice).toLocaleString()}\n` +
    `Exit:  $${Number(trade.exitPrice).toLocaleString()}\n` +
    `P&L:   <b>${pnl >= 0 ? '+' : ''}$${Number(pnl).toLocaleString()}</b>\n` +
    `Reason: ${reason.toUpperCase()}\n` +
    `Hold:  ${holdMin}m\n` +
    `─────────────────\n` +
    `📊 <a href="http://${process.env.HOST || 'localhost'}:${PORT}/">View Dashboard</a>`
  );
}

function formatStatusNotification(status, oldStatus) {
  const icons = { running: '✅', stopped: '⏹️', error: '⚠️' };
  return (
    `<b>${icons[status] || '🔄'} Bot Status Changed</b>\n` +
    `${oldStatus ? `From: ${oldStatus.toUpperCase()}\n` : ''}` +
    `To:   <b>${status.toUpperCase()}</b>`
  );
}

// ─── State store (persisted to dashboard_state.json) ──────
const STATE_FILE = path.join(__dirname, 'dashboard_state.json');

let state = {
  botStatus: null,
  openTrade: null,
  trades: [],
  currentStep: -1,
  lastUpdate: null
};

// Load persisted state on boot so the trade log survives restarts
try {
  if (fs.existsSync(STATE_FILE)) {
    const saved = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    state = { ...state, ...saved };
    (state.trades || []).forEach(t => notifiedTrades.add(t.id));
    console.log(`[State] Restored ${state.trades.length} trades from ${STATE_FILE}`);
  }
} catch (e) {
  console.error('[State] Failed to restore state:', e.message);
}

// Debounced save — at most one write per 2s burst of updates
let saveTimer = null;
function scheduleSave() {
  if (saveTimer) return;
  saveTimer = setTimeout(() => {
    saveTimer = null;
    fs.writeFile(STATE_FILE, JSON.stringify(state), err => {
      if (err) console.error('[State] Save failed:', err.message);
    });
  }, 2000);
}

// ─── Tiny JSON body parser ─────────────────────────────────
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try { resolve(JSON.parse(body)); }
      catch (e) { reject(new Error('Invalid JSON')); }
    });
    req.on('error', reject);
  });
}

// ─── MIME types ────────────────────────────────────────────
const MIME = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

// ─── Routes ────────────────────────────────────────────────
async function handleRequest(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname;

  // CORS headers (allow your bot from any origin)
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  // ── GET /api/state — dashboard polls this ──────────────
  if (pathname === '/api/state' && req.method === 'GET') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      ...state,
      lastUpdate: state.lastUpdate || Date.now()
    }));
    return;
  }

  // ── POST /api/reset — clear all dashboard state ─────────
  if (pathname === '/api/reset' && req.method === 'POST') {
    state = { botStatus: null, openTrade: null, trades: [], currentStep: -1, lastUpdate: Date.now() };
    notifiedTrades.clear();
    try {
      if (fs.existsSync(STATE_FILE)) fs.unlinkSync(STATE_FILE);
    } catch (e) {}
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', message: 'Dashboard state cleared' }));
    return;
  }

  // ── POST /api/state — bot pushes updates ──────────────
  if (pathname === '/api/state' && req.method === 'POST') {
    try {
      const body = await parseBody(req);
      state.lastUpdate = Date.now();

      // Bot can push any combination of fields
      if (body.botStatus !== undefined) {
        state.botStatus = body.botStatus;
      }
      if (body.openTrade !== undefined) {
        state.openTrade = body.openTrade;
      }
      if (body.trade) {
        // Single new trade — append or update
        const idx = state.trades.findIndex(t => t.id === body.trade.id);
        if (idx >= 0) {
          state.trades[idx] = body.trade;
        } else {
          state.trades.push(body.trade);
          notifiedTrades.add(body.trade.id);
        }
      }
      if (body.trades) {
        state.trades = body.trades;
        // Reset notified set on bulk replace
        notifiedTrades.clear();
        body.trades.forEach(t => notifiedTrades.add(t.id));
      }
      if (body.currentStep !== undefined) state.currentStep = body.currentStep;
      // Also accept flat fields that match the model directly
      if (body.status) {
        state.botStatus = { status: body.status, qty: body.qty, contractSize: body.contractSize, timeframe: body.timeframe, lastUpdate: state.lastUpdate };
      }
      if (body.direction) state.openTrade = { direction: body.direction, entryPrice: body.entryPrice, entryTime: body.entryTime, sl: body.sl, tp: body.tp, currentPrice: body.currentPrice, unrealizedPnl: body.unrealizedPnl };

      // Keep max 5000 trades in memory
      if (state.trades.length > 5000) state.trades = state.trades.slice(-5000);

      scheduleSave();

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, tradesCount: state.trades.length }));
    } catch (err) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  // ── GET / — serve dashboard HTML ─────────────────────
  // Allowlist only: never serve arbitrary files from the app dir (which holds
  // .env, ecosystem.config.js, source, etc.). The dashboard uses CDN assets, so
  // the only file we expose is dashboard.html.
  const SERVE_ALLOW = { '/': 'dashboard.html', '/dashboard.html': 'dashboard.html' };
  const allowed = SERVE_ALLOW[pathname];
  if (!allowed) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found');
    return;
  }
  const fullPath = path.join(__dirname, allowed);

  try {
    const content = fs.readFileSync(fullPath);
    const ext = path.extname(allowed);
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': 'no-cache, no-store, must-revalidate',
      'Pragma': 'no-cache',
      'Expires': '0'
    });
    res.end(content);
  } catch (err) {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not found');
  }
}

// ─── Start ─────────────────────────────────────────────────
const server = http.createServer(handleRequest);
server.listen(PORT, () => {
  console.log(`Shiva Sniper Dashboard Server`);
  console.log(`  Dashboard: http://0.0.0.0:${PORT}/`);
  console.log(`  API:       POST/GET http://0.0.0.0:${PORT}/api/state`);
  console.log(`  Bot pushes: curl -X POST http://0.0.0.0:${PORT}/api/state -H 'Content-Type: application/json' -d '{...}'`);
});
