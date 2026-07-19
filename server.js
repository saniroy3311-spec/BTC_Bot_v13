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

// ─── In-memory state store ─────────────────────────────────
let state = {
  botStatus: null,
  openTrade: null,
  trades: [],
  currentStep: -1,
  lastUpdate: null
};

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

  // ── POST /api/state — bot pushes updates ──────────────
  if (pathname === '/api/state' && req.method === 'POST') {
    try {
      const body = await parseBody(req);
      state.lastUpdate = Date.now();

      // Bot can push any combination of fields
      if (body.botStatus !== undefined) state.botStatus = body.botStatus;
      if (body.openTrade !== undefined) state.openTrade = body.openTrade;
      if (body.trade) {
        // Single new trade — append or update
        const idx = state.trades.findIndex(t => t.id === body.trade.id);
        if (idx >= 0) state.trades[idx] = body.trade;
        else state.trades.push(body.trade);
      }
      if (body.trades) state.trades = body.trades;
      if (body.currentStep !== undefined) state.currentStep = body.currentStep;
      // Also accept flat fields that match the model directly
      if (body.status) state.botStatus = { status: body.status, qty: body.qty, contractSize: body.contractSize, timeframe: body.timeframe, lastUpdate: state.lastUpdate };
      if (body.direction) state.openTrade = { direction: body.direction, entryPrice: body.entryPrice, entryTime: body.entryTime, sl: body.sl, tp: body.tp, currentPrice: body.currentPrice, unrealizedPnl: body.unrealizedPnl };

      // Keep max 500 trades in memory
      if (state.trades.length > 500) state.trades = state.trades.slice(-500);

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, tradesCount: state.trades.length }));
    } catch (err) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  // ── GET / — serve dashboard HTML ─────────────────────
  let filePath = pathname === '/' ? '/dashboard.html' : pathname;
  const fullPath = path.join(__dirname, filePath);

  try {
    const content = fs.readFileSync(fullPath);
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
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
