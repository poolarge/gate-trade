# Decisions

## 2026-05-05 — Project bootstrap

### D1: Python 3.11+ and asyncio
Rationale: Single-threaded asyncio is sufficient for a single-pair bot. Multi-pair
requires more concurrency but v1 is single-pair only. `asyncio.to_thread` wraps
blocking REST SDK calls without adding a second runtime.

### D2: Protocol/ABC architecture
Every subsystem is defined as a Protocol first, with a Mock for testing.
Implementations depend on Protocols, not concrete classes. This allows
independent development and testing of each module.

### D3: gate_api SDK for REST, raw websockets for streaming
The official gate_api SDK covers all REST endpoints. Using a separate
websockets-based `WsManager` for streaming gives full control over reconnect
logic, message dispatch, and subscription management.

### D4: Pydantic config with env overlay
Config is YAML-first with `GATE_` prefixed env vars for secrets. A `local.yaml`
(not committed) holds credentials for development.

### D5: Token-bucket rate limiter
Exchange rate limits are enforced via a single token-bucket limiter shared
across all API calls, with `max_wait_sec` gating to bound worst-case latency.

### D6: 9-state machine with cooldown timers
The bot has 9 main states + 4 RUNNING sub-states (per the v1.7 design document).
Three independent cooldown timers (fill, cancel, self-trade) prevent the bot
from acting on stale information after state-changing events.

### D7: No historical backtest dependency
Parameter tuning is done via gray-release live data, not historical backtesting.
Markout data (Phase 6) provides the feedback loop for strategy refinement.
