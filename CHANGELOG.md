# Changelog

## [0.1.0] — 2026-05-05
### Phase 0 — Scaffold & Contracts (complete)
- Project scaffold with pyproject.toml, Makefile, mypy, ruff, pytest
- 8 Protocol definitions: GateClient, MarketData, OrderEngine, RefPriceEngine, StateMachine, Strategy, RiskManager, Persistence
- 8 Mock implementations + 84 contract tests (all passing)
- Token-bucket rate limiter, structured logging, exception hierarchy
- WebSocket connection manager with auto-reconnect, message dispatch, re-subscription
- GateClient REST: gate_api SDK wired for orders (submit, cancel, cancel_all, fetch_open_orders, fetch_order), account (fetch_balance, fetch_all_balances), pair metadata
- Pydantic config schema with YAML layering (default + local) and GATE_ env var overlay
- Healthcheck script (scripts/healthcheck.py)
- DECISIONS.md, Makefile with test/lint/typecheck/ci targets

### Phase 1 — Market Data + Order Engine + Persistence (complete)
- LiveMarketData: WS-driven orderbook with snapshot + incremental delta, sorted levels
- Derived indicators: flash crash detection (5% drop), depth wall detection (5× avg), imbalance, VWAP, depth-at-price
- LiveOrderEngine: rate-limited placement with tick alignment, tag-based tracking (gt:pair:nonce), cancel_by_tag, reconcile (exchange diff)
- SqlitePersistence: WAL-mode SQLite for orders/fills/state/markouts with crash recovery
- 156 total tests, mypy strict + ruff clean
