"""Web Panel — FastAPI monitoring dashboard on port 39120.

Phase 8.1: Single-page dashboard with bot status, fills, orders, and
daily summary. Auto-refreshing via polling.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Gate Trade Panel", version="0.1.0")

DEFAULT_DB = "data/gate_trade.db"


def _open_db(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ── API endpoints ──────────────────────────────────────────────────


@app.get("/api/health")
async def api_health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def api_status(db: str = Query(default=DEFAULT_DB)) -> JSONResponse:
    try:
        con = _open_db(db)
        state = con.execute(
            "SELECT key, value FROM state WHERE key IN ('bot_state', 'toxic_level')"
        ).fetchall()
        state_map = {r["key"]: r["value"] for r in state}

        fill_count = con.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"]
        order_count = con.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE status='open'"
        ).fetchone()["n"]

        return JSONResponse({
            "bot_state": state_map.get("bot_state", "UNKNOWN"),
            "toxic_level": state_map.get("toxic_level", "NORMAL"),
            "total_fills": fill_count,
            "open_orders": order_count,
        })
    except FileNotFoundError:
        return JSONResponse({"error": "database not found"}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/fills")
async def api_fills(
    db: str = Query(default=DEFAULT_DB),
    limit: int = Query(default=50, le=200),
    since: str | None = None,
) -> JSONResponse:
    try:
        con = _open_db(db)
        if since:
            rows = con.execute(
                "SELECT side, price, filled_size, created_at FROM fills"
                " WHERE datetime(created_at, 'unixepoch') > ?"
                " ORDER BY created_at DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT side, price, filled_size, created_at FROM fills"
                " ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        fills: list[dict[str, Any]] = []
        for r in rows:
            fills.append({
                "side": r["side"],
                "price": r["price"],
                "filled_size": r["filled_size"],
                "time": datetime.fromtimestamp(r["created_at"], tz=UTC).isoformat(),
            })
        return JSONResponse(fills)
    except FileNotFoundError:
        return JSONResponse({"error": "database not found"}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/summary")
async def api_summary(
    db: str = Query(default=DEFAULT_DB),
    day: str | None = None,
) -> JSONResponse:
    try:
        con = _open_db(db)
        target_day = day or date.today().isoformat()
        where = f"date(created_at, 'unixepoch') = '{target_day}'"

        row = con.execute(
            "SELECT"
            "  COALESCE(SUM(CASE WHEN side='buy' THEN price*filled_size ELSE 0 END),0) AS buy_volume,"
            "  COALESCE(SUM(CASE WHEN side='sell' THEN price*filled_size ELSE 0 END),0) AS sell_volume,"
            "  COALESCE(SUM(CASE WHEN side='buy' THEN filled_size ELSE 0 END),0) AS total_bought,"
            "  COALESCE(SUM(CASE WHEN side='sell' THEN filled_size ELSE 0 END),0) AS total_sold,"
            "  COUNT(*) AS fill_count"
            " FROM fills WHERE " + where
        ).fetchone()

        return JSONResponse(dict(row))
    except FileNotFoundError:
        return JSONResponse({"error": "database not found"}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Dashboard HTML ─────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gate Trade Panel</title>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #c9d1d9;
          --green: #3fb950; --red: #f85149; --yellow: #d2991d; --blue: #58a6ff; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
         background: var(--bg); color: var(--text); padding: 24px; }
  h1 { font-size: 20px; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
          padding: 16px; }
  .card h2 { font-size: 12px; text-transform: uppercase; color: #8b949e; margin-bottom: 8px; }
  .card .value { font-size: 24px; font-weight: 600; }
  .green { color: var(--green); } .red { color: var(--red); } .yellow { color: var(--yellow); }
  table { width: 100%; border-collapse: collapse; margin-top: 20px; }
  th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }
  th { color: #8b949e; font-weight: 500; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .badge-running { background: #1b3a1b; color: var(--green); }
  .badge-halt { background: #3a1b1b; color: var(--red); }
  .badge-elevated { background: #3a2e1b; color: var(--yellow); }
  .badge-dormant { background: #3a1b2e; color: #d27bca; }
  .badge-normal { background: #1b2a3a; color: var(--blue); }
  .refreshed { font-size: 11px; color: #484f58; margin-top: 24px; }
  .section-title { font-size: 16px; margin: 24px 0 12px; color: #8b949e; }
</style>
</head>
<body>
<h1>Gate Trade Panel</h1>

<div class="grid">
  <div class="card">
    <h2>Bot State</h2>
    <div class="value" id="bot-state">--</div>
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
    <h2>Total Fills</h2>
    <div class="value" id="total-fills">--</div>
  </div>
</div>

<div class="section-title">Today's Summary</div>
<div class="grid" style="margin-bottom: 16px;">
  <div class="card">
    <h2>Fill Count</h2>
    <div class="value" id="sum-fills">--</div>
  </div>
  <div class="card">
    <h2>Buy Volume</h2>
    <div class="value" id="sum-buy">--</div>
  </div>
  <div class="card">
    <h2>Sell Volume</h2>
    <div class="value" id="sum-sell">--</div>
  </div>
  <div class="card">
    <h2>Net</h2>
    <div class="value" id="sum-net">--</div>
  </div>
</div>

<div class="section-title">Recent Fills</div>
<table>
  <thead><tr><th>Time</th><th>Side</th><th>Size</th><th>Price</th></tr></thead>
  <tbody id="fills-body"><tr><td colspan="4">Loading...</td></tr></tbody>
</table>

<p class="refreshed" id="refreshed">Last update: --</p>

<script>
const API = '/api';
async function refresh() {
  try {
    const [status, summary, fills] = await Promise.all([
      fetch(API + '/status').then(r => r.json()),
      fetch(API + '/summary').then(r => r.json()),
      fetch(API + '/fills?limit=20').then(r => r.json()),
    ]);

    // Status cards
    const state = status.bot_state || 'UNKNOWN';
    const el = document.getElementById('bot-state');
    el.textContent = state;
    el.className = 'value badge ' + (
      state.includes('COOLDOWN') || state === 'EMERGENCY' ? 'badge-elevated' :
      state === 'RUNNING' ? 'badge-running' :
      state === 'HALT' ? 'badge-halt' : 'badge-normal');

    const tl = document.getElementById('toxic-level');
    const tlv = status.toxic_level || 'NORMAL';
    tl.textContent = tlv;
    tl.className = 'value badge ' + (
      tlv === 'HALT' ? 'badge-halt' : tlv === 'DORMANT' ? 'badge-dormant' :
      tlv === 'ELEVATED' ? 'badge-elevated' : 'badge-normal');

    document.getElementById('open-orders').textContent = status.open_orders ?? '--';
    document.getElementById('total-fills').textContent = status.total_fills ?? '--';

    // Summary
    document.getElementById('sum-fills').textContent = summary.fill_count ?? '--';
    document.getElementById('sum-buy').textContent = '$' + Number(summary.buy_volume || 0).toFixed(2);
    document.getElementById('sum-sell').textContent = '$' + Number(summary.sell_volume || 0).toFixed(2);
    const net = Number(summary.sell_volume || 0) - Number(summary.buy_volume || 0);
    const netEl = document.getElementById('sum-net');
    netEl.textContent = '$' + net.toFixed(2);
    netEl.className = 'value ' + (net >= 0 ? 'green' : 'red');

    // Fills table
    const tbody = document.getElementById('fills-body');
    if (Array.isArray(fills) && fills.length) {
      tbody.innerHTML = fills.map(f => {
        const cls = f.side === 'buy' ? 'green' : 'red';
        return '<tr><td>' + f.time.slice(11,19) + '</td>' +
               '<td class="' + cls + '">' + f.side.toUpperCase() + '</td>' +
               '<td>' + Number(f.filled_size).toFixed(6) + '</td>' +
               '<td>$' + Number(f.price).toFixed(2) + '</td></tr>';
      }).join('');
    } else {
      tbody.innerHTML = '<tr><td colspan="4">No fills today</td></tr>';
    }

    document.getElementById('refreshed').textContent =
      'Last update: ' + new Date().toLocaleTimeString();
  } catch(e) {
    console.error('refresh failed', e);
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return DASHBOARD_HTML
