"""Web Panel — real-time operations dashboard on port 39120.

Phase 8.1+: Single-page dashboard with live bot state, order book,
fill stream, event log, and SSE-based real-time updates.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sqlite3
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

app = FastAPI(title="Gate Trade Panel", version="0.2.0")

DEFAULT_DB = "data/gate_trade.db"
_ALLOWED_DB_DIRS = ["data", "/tmp"]

# In-process references set by the launcher when running embedded
_bot: Any = None
_event_queue: asyncio.Queue[dict[str, Any]] | None = None
_subscribers: list[asyncio.Queue[dict[str, Any]]] = []

# Optional token for API access (set via GATE_WEB_TOKEN env var)
_AUTH_TOKEN = os.environ.get("GATE_WEB_TOKEN", "")


def bind_bot(bot: Any) -> None:
    """Attach the running Bot instance for live data access."""
    global _bot, _event_queue
    _bot = bot
    _event_queue = asyncio.Queue(maxsize=512)
    if hasattr(bot, 'events') and hasattr(bot.events, '_on_record'):
        bot.events._on_record = lambda evt: _broadcast(evt.to_dict())


def _broadcast(event: dict[str, Any]) -> None:
    if _event_queue is not None:
        with contextlib.suppress(asyncio.QueueFull):
            _event_queue.put_nowait(event)
    dead: list[int] = []
    for i, q in enumerate(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(i)
    for i in reversed(dead):
        _subscribers.pop(i)


def _validate_db_path(db_path: str) -> Path:
    """Prevent path traversal attacks on the database path."""
    path = Path(db_path)
    # Block paths that traverse upward
    if ".." in str(path):
        raise HTTPException(status_code=403, detail="Database path not allowed")
    return path


def _open_db(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    path = _validate_db_path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ── Auth middleware ──────────────────────────────────────────────


@app.middleware("http")
async def _auth_middleware(request: Request, call_next: Any) -> Any:
    """Optional token-based auth when GATE_WEB_TOKEN is set."""
    if _AUTH_TOKEN and request.url.path.startswith("/api/"):
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {_AUTH_TOKEN}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


# ── API: Events stream (SSE) ──────────────────────────────────────


@app.get("/api/stream")
async def api_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events endpoint for real-time bot updates."""

    async def _generate() -> AsyncGenerator[str, None]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
        _subscribers.append(q)
        try:
            # Send initial event
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            if q in _subscribers:
                _subscribers.remove(q)

    return StreamingResponse(
        _generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── API: Events history ───────────────────────────────────────────


@app.get("/api/events")
async def api_events(
    limit: int = Query(default=100, le=500),
    since: float | None = None,
) -> JSONResponse:
    """Return recent bot events from the in-memory buffer or database."""
    events: list[dict[str, Any]] = []
    if _bot is not None and hasattr(_bot, 'events'):
        events = _bot.events.recent(limit=limit, since=since)
    if not events:
        # Fall back to database
        try:
            con = _open_db(DEFAULT_DB)
            rows = con.execute(
                "SELECT event_type, event_data, created_at_ms FROM event_log "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            for r in reversed(rows):
                data: dict[str, Any] = {}
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    data = json.loads(r["event_data"]) if r["event_data"] else {}
                events.append({
                    "type": r["event_type"], "ts": r["created_at_ms"] / 1000.0, **data,
                })
        except FileNotFoundError:
            pass
    return JSONResponse(events)


# ── API: Live snapshot ─────────────────────────────────────────────


@app.get("/api/snapshot")
async def api_snapshot() -> JSONResponse:
    """Return a comprehensive snapshot of current bot state."""
    if _bot is None:
        return JSONResponse({"error": "bot not connected"}, status_code=503)

    bot = _bot
    md = bot.md
    sm = bot.sm
    tox = bot.toxic_response

    orders = bot.oe.open_orders()
    order_list: list[dict[str, Any]] = []
    for o in orders:
        order_list.append({
            "id": o.order_id, "side": o.side.value,
            "price": o.price, "size": o.size, "filled": o.filled_size,
        })

    strategies: list[dict[str, Any]] = []
    for s in bot.strategies:
        strategies.append({
            "name": s.name, "active": s.active,
        })

    return JSONResponse({
        "tick": bot.tick_count,
        "uptime": round(bot.uptime_seconds, 1),
        "state": sm.state.value,
        "sub_state": sm.sub_state.value if sm.sub_state else None,
        "toxic_level": tox.level.value,
        "dry_run": bot.dry_run,
        "mid": round(md.mid_price(), 2),
        "best_bid": round(md.best_bid(), 2),
        "best_ask": round(md.best_ask(), 2),
        "spread_bps": round(md.spread_bps(), 1),
        "open_orders": len(orders),
        "order_list": order_list[:20],
        "strategies": strategies,
        "can_place": sm.can_place(),
    })


# ── API: Health / Status / Fills / Summary ────────────────────────


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def api_status(db: str = Query(default=DEFAULT_DB)) -> JSONResponse:
    if _bot is not None:
        return await api_snapshot()
    try:
        con = _open_db(db)
        state = con.execute(
            "SELECT event_data FROM event_log WHERE event_type='tick' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if state:
            data = json.loads(state["event_data"]) if state["event_data"] else {}
            return JSONResponse({"bot_state": data.get("state", "UNKNOWN"),
                                 "toxic_level": data.get("toxic_level", "NORMAL")})
        return JSONResponse({"bot_state": "UNKNOWN", "toxic_level": "NORMAL"})
    except FileNotFoundError:
        return JSONResponse({"error": "database not found"}, status_code=503)


@app.get("/api/fills")
async def api_fills(
    db: str = Query(default=DEFAULT_DB),
    limit: int = Query(default=50, le=200),
) -> JSONResponse:
    try:
        con = _open_db(db)
        rows = con.execute(
            "SELECT side, price, fill_price, filled_size, created_at_ms FROM fills "
            "ORDER BY created_at_ms DESC LIMIT ?", (limit,),
        ).fetchall()
        fills: list[dict[str, Any]] = []
        for r in rows:
            fills.append({
                "side": r["side"],
                "price": r["price"] or r["fill_price"],
                "fill_price": r["fill_price"],
                "filled_size": r["filled_size"],
                "time": datetime.fromtimestamp(
                    (r["created_at_ms"] or 0) / 1000.0, tz=UTC
                ).isoformat(),
            })
        return JSONResponse(fills)
    except FileNotFoundError:
        return JSONResponse({"error": "database not found"}, status_code=503)


@app.get("/api/summary")
async def api_summary(
    db: str = Query(default=DEFAULT_DB),
) -> JSONResponse:
    try:
        con = _open_db(db)
        target_day = date.today().isoformat()
        where = f"date(created_at_ms / 1000, 'unixepoch') = '{target_day}'"
        row = con.execute(
            "SELECT"
            "  COALESCE(SUM(CASE WHEN side='buy' THEN COALESCE(price,fill_price)*filled_size ELSE 0 END),0) AS buy_volume,"
            "  COALESCE(SUM(CASE WHEN side='sell' THEN COALESCE(price,fill_price)*filled_size ELSE 0 END),0) AS sell_volume,"
            "  COALESCE(SUM(CASE WHEN side='buy' THEN filled_size ELSE 0 END),0) AS total_bought,"
            "  COALESCE(SUM(CASE WHEN side='sell' THEN filled_size ELSE 0 END),0) AS total_sold,"
            "  COUNT(*) AS fill_count"
            " FROM fills WHERE " + where
        ).fetchone()
        row_d = dict(row)
        row_d["buy_volume"] = row_d.get("buy_volume", 0)
        row_d["sell_volume"] = row_d.get("sell_volume", 0)
        row_d["total_bought"] = row_d.get("total_bought", 0)
        row_d["total_sold"] = row_d.get("total_sold", 0)
        row_d["fill_count"] = row_d.get("fill_count", 0)
        return JSONResponse(row_d)
    except FileNotFoundError:
        return JSONResponse({"error": "database not found"}, status_code=503)


# ── Dashboard HTML ─────────────────────────────────────────────────


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gate Trade — Operations Panel</title>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
          --green: #3fb950; --red: #f85149; --yellow: #d2991d; --blue: #58a6ff; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
         background: var(--bg); color: var(--text); padding: 20px; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .subtitle { font-size: 12px; color: #484f58; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
          padding: 14px; }
  .card h2 { font-size: 11px; text-transform: uppercase; color: #8b949e; margin-bottom: 6px; }
  .card .value { font-size: 22px; font-weight: 600; }
  .green { color: var(--green); } .red { color: var(--red); }
  .yellow { color: var(--yellow); } .blue { color: var(--blue); }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
           margin-top: 16px; }
  .panel-header { padding: 10px 14px; border-bottom: 1px solid var(--border);
                  font-size: 12px; color: #8b949e; text-transform: uppercase; }
  .panel-body { padding: 10px 14px; max-height: 320px; overflow-y: auto; }
  .event-row { display: flex; gap: 10px; padding: 3px 0; font-size: 12px;
               border-bottom: 1px solid rgba(48,54,61,0.5); align-items: center; }
  .event-time { color: #484f58; min-width: 65px; font-size: 11px; }
  .event-tag { padding: 1px 6px; border-radius: 8px; font-size: 10px; font-weight: 600;
               min-width: 56px; text-align: center; white-space: nowrap; }
  .tag-tick { background: #1b2a3a; color: var(--blue); }
  .tag-order { background: #1b3a2e; color: var(--green); }
  .tag-risk { background: #3a1b1b; color: var(--red); }
  .tag-toxic { background: #3a2e1b; color: var(--yellow); }
  .tag-spike { background: #3a1b2e; color: #d27bca; }
  .tag-shutdown { background: #1b1b2a; color: #8b949e; }
  .event-detail { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .order-row { display: flex; gap: 10px; padding: 2px 0; font-size: 12px; }
  .connection-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                    margin-right: 6px; }
  .dot-live { background: var(--green); }
  .dot-dead { background: var(--red); }
  .sparkline { font-family: monospace; font-size: 10px; color: var(--blue); }
</style>
</head>
<body>
<h1>Gate Trade Panel</h1>
<div class="subtitle">
  <span class="connection-dot" id="conn-dot"></span>
  <span id="conn-status">Connecting...</span>
  &nbsp;|&nbsp; Last update: <span id="last-update">--</span>
</div>

<div class="grid">
  <div class="card">
    <h2>Bot State</h2>
    <div class="value" id="bot-state">--</div>
  </div>
  <div class="card">
    <h2>Mid Price</h2>
    <div class="value" id="mid-price">--</div>
  </div>
  <div class="card">
    <h2>Spread</h2>
    <div class="value" id="spread">--</div>
  </div>
  <div class="card">
    <h2>Toxic Level</h2>
    <div class="value" id="toxic-level">--</div>
  </div>
  <div class="card">
    <h2>Open Orders</h2>
    <div class="value" id="open-orders">--</div>
  </div>
  <div class="card">
    <h2>Tick / Uptime</h2>
    <div class="value" id="tick-uptime" style="font-size: 16px;">--</div>
  </div>
</div>

<div class="grid-2">
  <div class="panel">
    <div class="panel-header">Active Orders</div>
    <div class="panel-body" id="orders-body">
      <div style="color:#484f58;font-size:12px;">No active orders</div>
    </div>
  </div>
  <div class="panel">
    <div class="panel-header">Strategies</div>
    <div class="panel-body" id="strategies-body">
      <div style="color:#484f58;font-size:12px;">--</div>
    </div>
  </div>
</div>

<div class="panel">
  <div class="panel-header">Event Stream (Live)</div>
  <div class="panel-body" id="events-body" style="max-height: 400px;">
    <div style="color:#484f58;font-size:12px;">Waiting for events...</div>
  </div>
</div>

<script>
const MAX_EVENTS = 200;
let events = [];
let eventSource = null;

function fmtTime(ts) {
  if (!ts || ts < 1000000000000) ts = (ts || Date.now()/1000) * 1000;
  return new Date(ts).toLocaleTimeString();
}

function fmtUSD(n) { return '$' + Number(n || 0).toFixed(2); }

function setConn(ok) {
  const d = document.getElementById('conn-dot');
  d.className = 'connection-dot ' + (ok ? 'dot-live' : 'dot-dead');
  document.getElementById('conn-status').textContent = ok ? 'Live (SSE)' : 'Disconnected';
}

function addEvent(evt) {
  events.push(evt);
  if (events.length > MAX_EVENTS) events.shift();
  const body = document.getElementById('events-body');
  const tagClass = {
    tick: 'tag-tick', order_place: 'tag-order', state_change: 'tag-tick',
    risk: 'tag-risk', toxic: 'tag-toxic', spike: 'tag-spike',
    shutdown: 'tag-shutdown', error: 'tag-risk'
  };
  const html = events.map(e => {
    const tc = tagClass[e.type] || 'tag-tick';
    const detail = e.type === 'tick'
      ? 'mid=' + fmtUSD(e.mid) + ' spread=' + (e.spread_bps||0) + 'bps toxic=' + (e.toxic_level||'?')
      : e.type === 'order_place'
      ? e.side + ' ' + fmtUSD(e.price) + ' x' + (e.size||0) + (e.dry_run ? ' [dry]' : '')
      : e.type === 'risk'
      ? e.reason || 'halted'
      : e.type === 'toxic'
      ? 'level=' + (e.level||'?') + ' ratio=' + (e.ratio||0)
      : e.type === 'spike'
      ? 'mid=' + fmtUSD(e.mid) + ' cooldown=' + (e.cooldown_ms||0) + 'ms'
      : e.type === 'shutdown'
      ? 'ticks=' + (e.tick_count||0) + ' uptime=' + (e.uptime||0) + 's'
      : '';
    return '<div class="event-row">'
      + '<span class="event-time">' + fmtTime(e.ts) + '</span>'
      + '<span class="event-tag ' + tc + '">' + e.type.toUpperCase() + '</span>'
      + '<span class="event-detail">' + detail + '</span></div>';
  }).join('');
  body.innerHTML = html || '<div style="color:#484f58;font-size:12px;">Waiting for events...</div>';
  body.scrollTop = body.scrollHeight;
}

function handleSSE(data) {
  if (!data || data.type === 'connected') { setConn(true); return; }
  addEvent(data);

  // Update snapshot data from tick events
  if (data.type === 'tick') {
    if (data.state) document.getElementById('bot-state').textContent = data.state;
    if (data.mid) document.getElementById('mid-price').textContent = fmtUSD(data.mid);
    if (data.spread_bps != null) document.getElementById('spread').textContent = data.spread_bps + ' bps';
    if (data.toxic_level) document.getElementById('toxic-level').textContent = data.toxic_level;
    if (data.strategies) {
      document.getElementById('strategies-body').innerHTML = data.strategies.map(s =>
        '<div class="order-row"><span style="color:' + (s.active ? 'var(--green)' : 'var(--red)') + '">'
        + (s.active ? '●' : '○') + '</span> ' + s.name + '</div>'
      ).join('');
    }
  }
  document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
}

function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource('/api/stream');
  eventSource.onmessage = (e) => {
    try { handleSSE(JSON.parse(e.data)); } catch(_) {}
  };
  eventSource.onerror = () => { setConn(false); setTimeout(connectSSE, 3000); };
  eventSource.onopen = () => setConn(true);
}

// Also poll /api/snapshot for full state at slower rate
async function pollSnapshot() {
  try {
    const r = await fetch('/api/snapshot');
    if (!r.ok) return;
    const s = await r.json();
    document.getElementById('bot-state').textContent = s.state || '--';
    document.getElementById('mid-price').textContent = fmtUSD(s.mid);
    document.getElementById('spread').textContent = (s.spread_bps || 0) + ' bps';
    document.getElementById('toxic-level').textContent = s.toxic_level || 'NORMAL';
    document.getElementById('open-orders').textContent = s.open_orders ?? '--';
    document.getElementById('tick-uptime').textContent =
      '#' + (s.tick || 0) + ' / ' + (s.uptime || 0) + 's';
    if (s.order_list) {
      const body = document.getElementById('orders-body');
      body.innerHTML = s.order_list.length
        ? s.order_list.map(o =>
            '<div class="order-row"><span class="' + (o.side === 'buy' ? 'green' : 'red') + '">'
            + o.side.toUpperCase() + '</span> ' + fmtUSD(o.price)
            + ' <span style="color:#484f58">x' + o.size + '</span></div>'
          ).join('')
        : '<div style="color:#484f58;font-size:12px;">No active orders</div>';
    }
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
  } catch(_) {}
}

connectSSE();
setInterval(pollSnapshot, 3000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return DASHBOARD_HTML
