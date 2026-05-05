# Gate Spot Unilateral Accumulation + Market Making Strategy — Implementation Plan

**Source:** https://claude.luluta.org/plan.md
**Saved:** 2026-05-05
**Status:** Phase 0-1 complete, Phase 2 next

---

## Directory/File Map

```
project-root/
├── pyproject.toml                    # ruff / mypy / pytest config
├── Makefile                          # test / lint / typecheck / ci targets
├── CHANGELOG.md
├── DECISIONS.md                      # Lightweight ADR
├── PLAN.md                           # This file
├── config/
│   ├── default.yaml                  # Default configuration
│   └── local.yaml                    # Secrets (gitignored)
├── src/gate_trade/
│   ├── client/
│   │   ├── contract.py               # GateClient Protocol
│   │   ├── gate_client.py            # GateIoClient impl (gate_api SDK)
│   │   └── ws_manager.py             # WebSocket manager
│   ├── config/schema.py              # Pydantic config schema
│   ├── guardrails/
│   │   ├── exceptions.py             # Exception hierarchy
│   │   ├── logging.py                # Structured logging
│   │   └── rate_limiter.py           # Token-bucket rate limiter
│   ├── market/
│   │   ├── contract.py               # MarketData Protocol
│   │   └── market_data.py            # LiveMarketData impl
│   ├── order/
│   │   ├── contract.py               # OrderEngine Protocol
│   │   └── order_engine.py           # LiveOrderEngine impl
│   ├── price/contract.py             # RefPriceEngine Protocol
│   ├── state/contract.py             # StateMachine Protocol
│   ├── strategy/contract.py          # Strategy Protocol
│   ├── risk/contract.py              # RiskManager Protocol
│   ├── persistence/
│   │   ├── contract.py               # Persistence Protocol
│   │   └── sqlite.py                 # SqlitePersistence impl
│   └── types.py                      # Shared types/enums
├── mocks/                            # Mock implementations for all 8 protocols
├── tests/
│   ├── contracts/                    # 8 contract test files (84 tests)
│   ├── test_market/                  # LiveMarketData tests (27 tests)
│   ├── test_order/                   # LiveOrderEngine tests
│   ├── test_persistence/             # SqlitePersistence tests
│   └── ...
└── scripts/
    └── healthcheck.py
```

---

## Phase 0 — Scaffolding + Interface Contracts (4 iterations, ~2 days) ✅ COMPLETE

### 0.1: Repository + Engineering Infrastructure ✅
- pyproject.toml (ruff/mypy/pytest), Makefile, CHANGELOG.md, DECISIONS.md

### 0.2: All Protocols/ABCs + Contract Tests + Mocks ✅
- 8 Protocols: GateClient, MarketData, OrderEngine, RefPriceEngine, StateMachine, Strategy, RiskManager, Persistence
- 8 Mocks, 84 contract tests

### 0.3: Real GateClient ✅
- GateIoClient wired to gate_api SDK, healthcheck script

### 0.4: Startup Guardrails + Config Schema ✅
- Pydantic schema, YAML layering, GATE_ env overlay

---

## Phase 1 — Market Data + Order Engine (5 iterations, ~5 days) ✅ COMPLETE

### 1.1: Orderbook Full + Incremental Maintenance ✅
- LiveMarketData with snapshot + delta, sorted levels

### 1.2: Derived Indicators ✅
- Flash crash (5% drop), depth wall (5x avg), imbalance, VWAP, depth-at-price

### 1.3: Order Engine Core + Token Bucket ✅
- LiveOrderEngine: rate-limited, tick-aligned, tag-based tracking

### 1.4: Reconcile + Tag System ✅
- Exchange diff reconcile, gt:pair:nonce tag format

### 1.5: SQLite Persistence ✅
- SqlitePersistence: WAL mode, orders/fills/state/markouts, crash recovery

---

## Phase 2 — State Machine + 5 Strategy Modules + RefPrice + Risk (7 iterations)

### 2.1: Minimal State Machine Skeleton
**Files:** `src/gate_trade/state/state_machine.py`
**Output:** IDLE/RUNNING/HALTED three-state flow
**Acceptance:** Clear state-transition logging in dry-run

### 2.2: RefPriceEngine with Self-Fill Exclusion
**Files:** `src/gate_trade/price/ref_price_engine.py`
**Output:** mid, microprice, TWAP, self-fill exclusion
**Acceptance:** Injecting own-taker-fill event does not pull ref price

### 2.3: Accumulator with Ratchet + Collapse Protection
**Files:** `src/gate_trade/strategy/accum.py`
**Output:** Ladder calculation, tick alignment, collapse protection, SUSPENDED gate, v1.7 ratchet
**Acceptance:** Ref-spike test case confirms ladder does not move upward

### 2.4: Depth Keeper with ACTIVE/DORMANT + Hysteresis
**Files:** `src/gate_trade/strategy/depth.py`
**Output:** 3-tier quote placement, ACTIVE/DORMANT toggle, anti-spoof detection
**Acceptance:** Counterparty bait-and-cancel does not trigger DORMANT

### 2.5: Full 9-State Expansion + RUNNING Sub-States
**Files:** `src/gate_trade/state/state_machine.py` (extended)
**Output:** 9 main states + RUNNING sub-states + PRICE_SPIKE_COOLDOWN
**Acceptance:** Exhaustive state-transition parameterized tests pass

### 2.6: Risk Manager — should_halt + should_resume
**Files:** `src/gate_trade/risk/risk_manager.py`
**Output:** should_halt(), should_resume(), HIT_CAP_COOLDOWN
**Acceptance:** Manual trigger injection → halt → resume conditions met → auto-resume

### 2.7: Three Independent Cooldown Timers
**Files:** `src/gate_trade/state/cooldown.py`
**Output:** Price-move-up cooldown, taker-fill cooldown, compliance-quote existence timer
**Acceptance:** Compliance depth maintained even during cooldown periods

---

## Phase 3 — Hot Configuration + CLI (3 iterations)

### 3.1: File Watcher + Diff + Three-Level Dispatch
### 3.2: Dangerous Change Two-Step Confirmation
### 3.3: gate-admin CLI

---

## Phase 4 — Alerts + systemd + Daily Report (2 iterations)
### 4.1: Multi-Channel Alerts (Telegram + email)
### 4.2: systemd User Unit + Daily Report

---

## Phase 5 — Graduated Go-Live (4 weeks)
- dry-run 7d → 100U 7d → 1,000U 7d → 10,000U 7d → 100,000U
- 6 gate checks before each scale-up

---

## Phase 6 — Markout + Toxic Detector (parallel with gray release, 3 iterations)
### 6.1: MarkoutRecorder
### 6.2: Simplified Toxic Detector (Boolean Conjunction)
### 6.3: Toxic Response

---

## Phase 7 — Smasher (3-5 iterations, after ≥2 weeks markout data)
### 7.x: probe, iceberg_detect, trickle, verify

---

## Phase 8 — Web Panel (Optional, 1 iteration)
### 8.1: FastAPI + HTML/JS on port 39120

---

## Phase 9 — Historical Replay (Optional, far future)

---

## Key Parameters

| Parameter | Value |
|---|---|
| precision / tick_size | 4 digits (0.0001) |
| min_base_amount | 0.01 |
| min_quote_amount | 3 USDT |
| fee (maker = taker) | 0.2% |
| up_rate / down_rate | 0.30 daily max |
| trade_status | tradable |

---

## Testing Strategy

| Type | Tool | Execution |
|---|---|---|
| Unit | pytest | pre-commit + CI |
| Contract | pytest (Protocol-based) | pre-commit + CI |
| Integration | pytest + aioresponses | CI only (@slow) |
| State machine exhaustive | pytest parametrized | Phase 2 exit gate |
| Type checking | mypy strict | pre-commit + CI |
| Lint | ruff | pre-commit + CI |
| Dry-run endurance | --dry-run | Phase exit gate |
| Attack scenario injection | tests/scenarios/ | Phase 2/6 exit gate |

---

## DoD (Definition of Done) per iteration:
1. Feature runs under dry-run without exceptions
2. Unit/integration tests have new coverage
3. No new ruff/mypy warnings
4. CHANGELOG.md entry added
5. Interface contracts synced if changed
6. Git commit + tag (v0.<phase>.<iter>)

---

## Scope Explicitly Excluded:
- Perpetuals / futures
- Cross-exchange arbitrage
- Proprietary MM P&L optimization
- Multi-pair concurrency
- Historical backtesting for parameter optimization
