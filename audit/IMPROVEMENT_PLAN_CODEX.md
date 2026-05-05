# Gate Trade 综合改进计划

项目：`https://github.com/poolarge/gate-trade`

本地仓库：`/home/ubuntu/gate-trade-DeepSeek`

当前基线：`2e4210a Move audit reports into audit/ directory, add comparison and comprehensive reports`

参考材料：

- `AUDIT_deepseek-v4-pro.md`
- `IMPROVEMENT_deepseek-v4-pro.md`
- `AUDIT_CODEX.md`
- `IMPROVEMENT_CODEX.md`

生成时间：2026-05-05 UTC

签名：Codex · 风控拆解工程师

## 0. 校准结论

DeepSeek-v4 的报告和 Codex 的审计结论在核心方向上是一致的：当前项目可以作为策略原型继续推进，但还没有达到实盘交易机器人的最低安全门槛。两份报告共同确认的优先问题包括：

- live 模式的数据链路不可靠。
- 风控没有拿到真实账户状态。
- shutdown 撤单保护不足。
- Web 面板默认暴露且没有认证。
- Gate.io 客户端和 WebSocket 管理器测试不足。
- 部署、CI、依赖和 GitHub 治理需要补齐。

需要按当前代码校正的点：

- DeepSeek-v4 提到的 `config/local.yaml` 明文密钥不在当前 Git 跟踪文件中；如果本机存在该文件并包含真实 key，仍应立即轮换密钥。
- 当前仓库已经有 `systemd/gate-trade.service`，问题不是缺少 systemd，而是 `ExecStart` 指向不存在的 `gate_trade.main`。
- 当前状态名是 `RUNNING`、`COOLDOWN_PRICE_SPIKE` 等；DeepSeek-v4 文档中出现的 `ACTIVE`、`COOLDOWN_FLASH_CRASH` 等名称不应直接照搬。
- 当前测试在补装 `httpx` 后为 `469 passed`，不是 DeepSeek-v4 文档中的 156 个测试。
- 当前 `Balance` 字段为 `currency`，不是 `asset`；真实问题是风控传入空余额，以及 `RiskManager` 把所有非零余额都按目标 base 资产计算。

本计划以当前代码为准，吸收两份报告中可验证、可落地的建议。

## 1. 开发原则落地方式

### 1.1 小步快跑

所有改动拆成小 PR，每个 PR 只拥有一个主要风险点：

- 一个 PR 一般控制在 1 到 3 个模块内。
- 每个 PR 必须包含测试。
- 每个 PR 必须能独立回滚。
- live 下单能力必须通过显式开关逐步恢复。

### 1.2 敏捷迭代

采用 7 个短迭代，每个迭代都有可运行状态和验收标准：

1. 迭代 0：建立安全基线和 CI。
2. 迭代 1：live preflight 与面板安全默认值。
3. 迭代 2：WebSocket 生命周期和订阅分发。
4. 迭代 3：账户状态、订单对账和风控输入。
5. 迭代 4：订单安全、撤单保护和 shutdown。
6. 迭代 5：状态机、cooldown 和恢复语义。
7. 迭代 6：持久化、日报、Web 面板和部署治理。

### 1.3 功能模块化

新增或强化下列模块边界：

- `runtime/preflight`：启动前安全检查。
- `client/ws_manager`：连接、重连、订阅、分发。
- `account/state`：余额和交易所 open orders 快照。
- `risk/policy`：纯风控决策，不直接下单。
- `order/safety`：订单价格、数量、notional、精度校验。
- `bot/orchestrator`：tick 编排，不直接塞业务细节。
- `web/snapshot`：Web 面板只读快照，不访问私有属性。
- `persistence/migrations`：数据库 schema 演进。

### 1.4 阶段性测试

每个迭代都必须至少有三层测试：

- 单元测试：模块内部逻辑。
- 集成测试：模块间接口契约。
- 运行测试：dry-run 或带 mock exchange 的生命周期测试。

live 相关改动额外要求：

- 未满足 preflight 时不得触发 `submit_order()`。
- shutdown 后 exchange open orders 必须归零或进入 `EMERGENCY`。
- 账户状态过期时必须 fail closed。

### 1.5 易维护升级

维护性要求：

- 所有模块间通信使用 typed dataclass 或 Protocol。
- Web 面板不得访问 bot 私有字段。
- 配置新增项必须进入 schema、默认配置、README 和测试。
- 数据库 schema 改动必须有迁移函数和回归测试。
- GitHub CI 作为合并门禁。

## 2. 模块通信接口设计

### 2.1 Runtime / Preflight 模块

职责：决定 live 是否允许启动，不参与策略决策。

建议文件：

- `src/gate_trade/runtime/preflight.py`
- `tests/test_runtime/test_preflight.py`

核心接口：

```python
from dataclasses import dataclass, field
from enum import Enum

class PreflightLevel(str, Enum):
    OK = "OK"
    WARN = "WARN"
    BLOCK = "BLOCK"

@dataclass(slots=True)
class PreflightCheck:
    name: str
    level: PreflightLevel
    message: str
    data: dict[str, object] = field(default_factory=dict)

@dataclass(slots=True)
class PreflightReport:
    mode: str
    pair: str
    checks: list[PreflightCheck]

    @property
    def blocked(self) -> bool:
        return any(c.level == PreflightLevel.BLOCK for c in self.checks)
```

对外函数：

```python
async def run_live_preflight(
    config: AppConfig,
    client: GateIoClient,
    pair: str,
    web_host: str,
    allow_public_panel: bool,
) -> PreflightReport:
    ...
```

通信关系：

| 调用方 | 被调用方 | 数据 | 失败策略 |
|--------|----------|------|----------|
| `scripts/run.py` | `run_live_preflight` | `AppConfig`, `GateIoClient`, pair | `BLOCK` 时退出 |
| `run_live_preflight` | `GateIoClient` | metadata、balances、open orders | REST 失败则 `BLOCK` |
| `run_live_preflight` | Web 配置 | host、token | 公网无鉴权则 `BLOCK` |

内部流程：

1. 检查 `--live` 是否同时带强确认参数。
2. 检查 API key 和 secret 是否存在。
3. 检查 pair 不为 `TARGET_USDT`。
4. 调用 `fetch_pair_meta(pair)`，校验交易对可交易。
5. 调用 `fetch_all_balances()`，校验账户状态可读。
6. 调用 `fetch_open_orders(pair)`，记录启动前挂单。
7. 检查 Web host 和 token。
8. 输出 `PreflightReport`，写入 event log。
9. 如果 `blocked=True`，不启动 bot、不启动下单路径。

验收测试：

- API key 缺失时 blocked。
- REST metadata 失败时 blocked。
- balances 失败时 blocked。
- public panel 无 token 时 blocked。
- dry-run 不走 live preflight。

### 2.2 WebSocket 模块

职责：维护连接、重连、订阅和消息分发，不解析业务对象。

现有文件：

- `src/gate_trade/client/ws_manager.py`

建议接口：

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class SubscriptionKey:
    channel: str
    topic: str

@dataclass(slots=True)
class WsEnvelope:
    channel: str
    event: str
    topic: str
    raw: dict[str, object]
```

核心方法：

```python
async def connect(self) -> None
async def close(self) -> None
def subscribe(self, channel: str, topic: str) -> asyncio.Queue[WsEnvelope]
async def wait_connected(self, timeout: float) -> bool
```

通信关系：

| 调用方 | 被调用方 | 数据 | 失败策略 |
|--------|----------|------|----------|
| `GateIoClient.subscribe_orderbook` | `WsManager.subscribe` | `spot.order_book`, topic | 无消息则等待 |
| `WsManager.reader_task` | subscriber queue | `WsEnvelope` | 队列满时丢最旧消息并计数 |
| `Bot` / `healthcheck` | `WsManager.wait_connected` | timeout | 超时则失败 |

内部流程：

1. `connect()` 设置 `_running=True`。
2. 创建 `_reader_task` 和 `_ping_task`。
3. 建立连接成功后设置 `_connected_event`。
4. `_reader_loop` 读取 raw JSON。
5. `_route_key(raw)` 解析 channel 和 topic。
6. 按 `SubscriptionKey(channel, topic)` 投递到队列。
7. 连接断开后指数退避重连。
8. 重连成功后调用 `_resubscribe()`。
9. `close()` 取消 task、关闭连接、清理 event。

验收测试：

- `await connect()` 连接成功后能返回。
- reader task 收到 order book 样例后投递到正确队列。
- event 为 `update` 时不会错误使用 `channel:event` 分发。
- ping task 会启动并在 close 后停止。
- 断线后能重连并重新订阅。

### 2.3 GateIoClient 解析模块

职责：把 REST/WS 原始数据转换成内部类型。

现有文件：

- `src/gate_trade/client/gate_client.py`

建议保持现有 `GateClient` Protocol，但增加解析测试和错误语义。

关键输入输出：

```python
async def fetch_all_balances() -> list[Balance]
async def fetch_open_orders(pair: str) -> list[Order]
async def fetch_pair_meta(pair: str) -> PairMeta
async def subscribe_orderbook(pair: str) -> AsyncIterator[OrderBook]
async def subscribe_orders(pair: str) -> AsyncIterator[list[Order]]
async def subscribe_balance() -> AsyncIterator[list[Balance]]
```

内部流程：

1. REST 调用统一走 `asyncio.to_thread`。
2. API 异常统一映射到项目异常：`AuthError`、`RateLimitExceeded`、`OrderNotFound`、`ExchangeError`。
3. WS 原始消息只在 `GateIoClient` 转成领域对象。
4. 解析失败记录 warning，不终止 reader task。

验收测试：

- `_parse_orderbook` 覆盖 bids/asks 正常、空、字段缺失。
- `_parse_orders` 覆盖 open、closed、cancelled、异常状态。
- `_parse_balances` 只返回 total > 0 的资产。
- `_handle_api_error` 覆盖 401、403、404、429、500。

### 2.4 Account State 模块

职责：维护账户和交易所订单的可信快照，给风控和面板使用。

建议文件：

- `src/gate_trade/account/state.py`
- `tests/test_account/test_state.py`

核心接口：

```python
from dataclasses import dataclass, field

@dataclass(slots=True)
class AccountSnapshot:
    pair: str
    balances: list[Balance]
    exchange_open_orders: list[Order]
    updated_at_ms: int
    source: str

@dataclass(slots=True)
class AccountHealth:
    fresh: bool
    reason: str
    age_ms: int

class AccountStateStore:
    def update_balances(self, balances: list[Balance], now_ms: int) -> None: ...
    def update_open_orders(self, pair: str, orders: list[Order], now_ms: int) -> None: ...
    def snapshot(self, pair: str) -> AccountSnapshot: ...
    def health(self, now_ms: int, max_age_ms: int) -> AccountHealth: ...
```

通信关系：

| 调用方 | 被调用方 | 数据 | 失败策略 |
|--------|----------|------|----------|
| REST sync task | `AccountStateStore` | balances/open orders | 失败保留旧快照并标记 stale |
| WS orders/balances feed | `AccountStateStore` | 增量事件 | 解析失败不污染快照 |
| `Bot._tick` | `AccountStateStore.snapshot` | `AccountSnapshot` | stale 则禁止下单 |
| Web 面板 | `AccountStateStore.snapshot` | 只读快照 | 无快照返回 degraded |

内部流程：

1. 启动时 REST 获取 balances 和 open orders。
2. 写入 `AccountStateStore`。
3. 后台周期 reconcile，例如每 10 秒。
4. WS 增量更新可提前刷新快照。
5. 每个 tick 检查 `health()`。
6. 如果快照 stale，bot 进入 risk block，不提交订单。
7. Web 面板显示账户快照时间和 stale 原因。

验收测试：

- 初始无快照时 `fresh=False`。
- 快照超过 `max_age_ms` 时 stale。
- 只更新余额不更新订单时仍可标记订单 stale。
- pair 过滤正确。

### 2.5 Risk Policy 模块

职责：把账户、订单和行情输入转换为风控决策。

现有文件：

- `src/gate_trade/risk/risk_manager.py`

建议从“内部 mutate 状态”逐步升级为“输出决策对象”，保留兼容属性。

核心接口：

```python
from dataclasses import dataclass
from enum import Enum

class RiskAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK_NEW_ORDERS = "BLOCK_NEW_ORDERS"
    CANCEL_AND_BLOCK = "CANCEL_AND_BLOCK"
    EMERGENCY = "EMERGENCY"

@dataclass(slots=True)
class RiskInput:
    pair: str
    base_currency: str
    quote_currency: str
    balances: list[Balance]
    open_orders: list[Order]
    mid_price: float
    account_fresh: bool

@dataclass(slots=True)
class RiskDecision:
    action: RiskAction
    reasons: list[str]
    position_notional: float
    open_order_count: int
    max_order_size_notional: float
```

通信关系：

| 调用方 | 被调用方 | 数据 | 失败策略 |
|--------|----------|------|----------|
| `Bot._tick` | `RiskManager.evaluate_input` | `RiskInput` | `action != ALLOW` 则不下单 |
| `OrderSafety` | `RiskDecision` | max notional | 超限拒单 |
| Web 面板 | `RiskDecision` | 风险状态 | 只读 |

内部流程：

1. 拆分 pair，得到 base 和 quote。
2. 只计算 base balance。
3. 计算 pending buy notional。
4. 计算 open order count。
5. 检查 account snapshot freshness。
6. 检查 flash crash。
7. 检查 position cap。
8. 检查 order count cap。
9. 输出 `RiskDecision`。
10. Bot 根据决策进入 `RUNNING`、`COOLDOWN_*` 或 `EMERGENCY`。

验收测试：

- BTC_USDT 只计算 BTC，不计算 ETH、USDT。
- 账户状态 stale 时 `BLOCK_NEW_ORDERS`。
- open orders 达上限时 block。
- flash crash 时 emergency 或 cooldown。
- position cap 清除后进入 cooldown，再恢复。

### 2.6 Order Safety / Order Engine 模块

职责：在订单提交前进行最后一道本地安全校验。

现有文件：

- `src/gate_trade/order/order_engine.py`

建议新增：

- `src/gate_trade/order/safety.py`

核心接口：

```python
@dataclass(slots=True)
class OrderSafetyContext:
    pair: str
    ref_price: float
    max_price_deviation_pct: float
    max_order_size_notional: float
    tick_size: float
    min_base: float
    min_quote: float

@dataclass(slots=True)
class OrderValidation:
    ok: bool
    reason: str = ""
    aligned_price: float = 0.0
    aligned_size: float = 0.0
```

对外函数：

```python
def validate_order(req: OrderRequest, ctx: OrderSafetyContext) -> OrderValidation:
    ...
```

内部流程：

1. 检查 pair 与当前 bot pair 一致。
2. 检查 price、size 大于 0。
3. 按 tick size 对齐 price。
4. 按 pair metadata 对齐 size。
5. 检查 notional 不超过 `max_order_size_notional`。
6. 检查 notional 不低于交易所最小值。
7. 检查价格偏离 ref price 不超过阈值。
8. 返回对齐后的价格和数量。
9. `LiveOrderEngine.place()` 只提交通过校验的订单。

验收测试：

- price <= 0 拒绝。
- size <= 0 拒绝。
- 超过单笔 notional 拒绝。
- 超过价格偏离拒绝。
- tick/size 对齐正确。

### 2.7 Bot Orchestrator 模块

职责：tick 编排和模块调度，不承载复杂业务逻辑。

现有文件：

- `src/gate_trade/bot.py`

建议引入 tick 上下文：

```python
@dataclass(slots=True)
class TickContext:
    pair: str
    now_ms: int
    mid: float
    best_bid: float
    best_ask: float
    account: AccountSnapshot
    risk: RiskDecision | None = None

@dataclass(slots=True)
class TickResult:
    placed: int
    cancelled: int
    blocked: bool
    reasons: list[str]
```

内部 tick 流程：

1. 记录 tick count。
2. 读取 market data；无 mid 则记录 degraded tick 并返回。
3. 读取 account snapshot；stale 则 risk block。
4. 更新 ref price。
5. 处理 spike protection。
6. 构建 `RiskInput`。
7. 获取 `RiskDecision`。
8. 如果不允许下单，记录原因并返回。
9. 更新策略 market context。
10. 收集 desired orders。
11. 对每个 order 执行 `OrderSafety`。
12. live 模式提交订单，dry-run 只记录 event。
13. 更新 markout 和 toxic response。
14. 记录 tick summary。

验收测试：

- stale account 时策略不会下单。
- risk block 时不会调用 order engine。
- dry-run 不调用真实 place。
- order safety 拒单会记录 event。
- tick 出错时进入 alert 或 degraded，不吞掉关键异常。

### 2.8 Shutdown Safety 模块

职责：停止流程和残留订单清理。

建议文件：

- `src/gate_trade/runtime/shutdown.py`

核心接口：

```python
@dataclass(slots=True)
class ShutdownReport:
    pair: str
    reconciled_orders: int
    cancelled_orders: int
    failed_cancels: int
    safe: bool
    reasons: list[str]

async def safe_shutdown(pair: str, order_engine: OrderEngine, client: GateClient) -> ShutdownReport:
    ...
```

内部流程：

1. 停止新订单提交。
2. reconcile exchange open orders。
3. 筛选当前 pair 和 bot tag。
4. 执行 cancel。
5. 再次 fetch open orders 验证。
6. 若仍有残留，记录 critical alert。
7. 返回 `ShutdownReport`。

验收测试：

- shutdown 使用真实 pair。
- exchange 有 orphan orders 时能发现。
- cancel 失败时 report `safe=False`。
- report 被写入 event log。

### 2.9 Web Panel / Snapshot 模块

职责：只读展示状态，不访问 bot 私有属性，不提供危险控制接口。

现有文件：

- `src/gate_trade/web/panel.py`

建议新增：

- `Bot.snapshot() -> BotSnapshot`

核心接口：

```python
@dataclass(slots=True)
class BotSnapshot:
    pair: str
    tick: int
    uptime: float
    state: str
    dry_run: bool
    market: dict[str, object]
    risk: dict[str, object]
    account: dict[str, object]
    orders: list[dict[str, object]]
```

认证接口：

```python
async def require_panel_auth(authorization: str | None = Header(None)) -> None:
    ...
```

内部流程：

1. 所有 `/api/*` 敏感接口先过 auth。
2. `/api/snapshot` 调用 `bot.snapshot()`。
3. `/api/events` 只读取 event logger 或 DB。
4. `/api/fills` 使用固定 DB 路径，不允许 query 参数传任意路径。
5. SSE stream 只推送脱敏事件。

验收测试：

- 默认 host 为 `127.0.0.1`。
- 无 token 请求 snapshot 返回 401 或 403。
- 有 token 返回 snapshot。
- `db` query 参数不能读取任意路径。

### 2.10 Persistence / Reporting 模块

职责：保证订单、成交、事件和报表 schema 一致。

现有文件：

- `src/gate_trade/persistence/sqlite.py`
- `src/gate_trade/web/panel.py`
- `scripts/daily_report.py`

建议 schema：

```sql
CREATE TABLE fills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT NOT NULL,
    pair          TEXT NOT NULL,
    side          TEXT NOT NULL,
    price         REAL NOT NULL,
    filled_size   REAL NOT NULL,
    created_at_ms INTEGER NOT NULL DEFAULT (strftime('%s','now') * 1000)
);
```

内部流程：

1. `save_fill()` 写入 side、price、created_at_ms。
2. Web panel 查询 `created_at_ms`。
3. daily report 查询同一字段。
4. README 示例同步。
5. 对旧库执行轻量迁移或明确不兼容版本。

验收测试：

- 新库 schema 与 Web API 查询一致。
- `/api/fills` 能返回数据。
- `/api/summary` 能返回当日统计。
- `scripts/daily_report.py` 能生成报告。

### 2.11 Config / Secrets 模块

职责：统一配置加载和敏感信息处理。

现有文件：

- `src/gate_trade/config/schema.py`
- `scripts/run.py`
- `scripts/healthcheck.py`

核心流程：

1. `default.yaml` 提供安全默认值。
2. `local.yaml` 只用于非敏感本地覆盖。
3. API key/secret 只从环境变量读取。
4. `run.py` 和 `healthcheck.py` 使用同一个 loader。
5. 配置校验失败时启动失败。

建议新增：

```python
def load_app_config(path: str | Path) -> AppConfig:
    """Load default YAML, optional local YAML, then GATE_* env overlay."""
```

验收测试：

- run 和 healthcheck 加载结果一致。
- 环境变量优先级最高。
- `GATE_CONFIG` 的语义明确。
- `.gitignore` 包含 `data/`、`*.db`、`config/local.yaml`。

## 3. 迭代计划

### 迭代 0：安全基线和工程门禁

目标：在不改业务行为的前提下，建立可持续开发门禁。

范围：

- 补 `httpx` 到 dev dependencies。
- 增加 GitHub Actions。
- 增加 `.gitignore` 中 `data/`、`*.db`、`*.db-wal`。
- 记录 DeepSeek-v4 与 Codex 报告中的校准点。
- 确认 `config/local.yaml` 不入库；如本机存在真实 key，轮换密钥。

模块接口影响：

- 不改运行时接口。

内部流程：

1. 更新 `pyproject.toml`。
2. 新增 CI workflow。
3. 运行 pytest、ruff、mypy、bandit、pip-audit。
4. 修掉 ruff 中明显的 import 和未使用变量问题。

验收：

- 全新环境 `pip install -e '.[dev]'` 后可直接 pytest。
- CI 能运行。
- `pytest` 通过。
- `mypy` 通过。
- `ruff` 通过。

建议 PR：

- `chore/ci-dev-deps`

### 迭代 1：live 启动安全和面板安全默认值

目标：任何不安全 live 条件都不能进入真实下单路径。

范围：

- 新增 live preflight。
- `--live` 增加强确认参数。
- Web panel 默认 `127.0.0.1`。
- 增加 panel token auth。
- 统一 `run.py` 和 `healthcheck.py` 配置加载。

模块接口：

- `run_live_preflight(config, client, pair, web_host, allow_public_panel) -> PreflightReport`
- `require_panel_auth(...)`
- `load_app_config(path) -> AppConfig`

内部流程：

1. `scripts/run.py` 解析 live 参数。
2. 加载统一配置。
3. 构建 `GateIoClient`。
4. 执行 preflight。
5. preflight blocked 则输出报告并退出。
6. preflight OK 才继续初始化 bot。

阶段性测试：

- 缺 key 阻断。
- public panel 无 token 阻断。
- dry-run 不要求 key。
- run 和 healthcheck 加载同一配置。

建议 PR：

- `feat/live-preflight`
- `fix/web-panel-safe-default`
- `fix/config-loader-unification`

### 迭代 2：WebSocket 生命周期和分发

目标：live 行情流能可靠进入 `LiveMarketData`，连接不会卡住启动流程。

范围：

- `WsManager.connect()` 改为非阻塞后台 task 模式。
- 启动 ping loop。
- 修复订阅 key 和消息分发。
- 增加 Gate.io WS 样例解析测试。

模块接口：

- `SubscriptionKey(channel, topic)`
- `WsEnvelope(channel, event, topic, raw)`
- `WsManager.wait_connected(timeout)`

内部流程：

1. `connect()` 创建 reader/ping task。
2. reader 成功连接后设置 connected event。
3. subscribe 以 channel/topic 注册队列。
4. reader 解析 raw topic 后分发。
5. close 取消所有 task。

阶段性测试：

- 本地 WS server 下 `connect()` 能返回。
- order book update 投递到正确队列。
- reconnect 后 resubscribe。
- close 后没有 pending task warning。

建议 PR：

- `fix/ws-lifecycle`
- `fix/ws-dispatch-routing`
- `test/gate-client-ws-parsers`

### 迭代 3：账户状态与风控输入

目标：风控使用真实余额和交易所 open orders，账户数据过期时 fail closed。

范围：

- 新增 `AccountStateStore`。
- 启动时获取 balances 和 open orders。
- 周期性 reconcile。
- Bot tick 使用 `AccountSnapshot`。
- `RiskManager` 只计算目标 base currency。

模块接口：

- `AccountSnapshot`
- `AccountHealth`
- `RiskInput`
- `RiskDecision`

内部流程：

1. live 启动完成 preflight 后初始化 account snapshot。
2. Bot 每 tick 读取 snapshot。
3. snapshot stale 时不下单。
4. 风控计算 base 持仓和 pending buy。
5. 风控输出 decision。
6. Bot 根据 decision 执行动作。

阶段性测试：

- 无 account snapshot 时 live tick 不下单。
- BTC_USDT 只计算 BTC。
- exchange open buy orders 计入风险。
- stale account 触发 block。

建议 PR：

- `feat/account-state-store`
- `fix/risk-real-balances`
- `fix/risk-base-currency-filter`

### 迭代 4：订单安全和 shutdown

目标：任何订单提交前有本地安全边界，任何退出都尽力撤掉当前策略挂单。

范围：

- 新增 `OrderSafety`。
- 使用 `max_order_size_notional`。
- 增加价格偏离边界。
- 结合 pair metadata 做精度和最小金额校验。
- `Bot` 保存 pair。
- shutdown reconcile 并按 pair/tag 撤单。

模块接口：

- `OrderSafetyContext`
- `OrderValidation`
- `ShutdownReport`
- `safe_shutdown(pair, order_engine, client)`

内部下单流程：

1. strategy 输出 desired orders。
2. Bot 为每个 order 构建 safety context。
3. OrderSafety 校验并对齐。
4. 被拒订单写 event，不提交。
5. 通过订单交给 `LiveOrderEngine.place()`。
6. place 仍保留底层 price/size 基础校验。

内部 shutdown 流程：

1. 停止新订单。
2. reconcile exchange open orders。
3. 按 pair/tag 筛选。
4. cancel。
5. 再次 fetch open orders 验证。
6. 残留则 alert critical。

阶段性测试：

- 超过单笔 notional 拒单。
- 价格偏离 ref 超限拒单。
- shutdown 传入真实 pair。
- orphan order 能被发现并取消。

建议 PR：

- `feat/order-safety`
- `fix/max-order-notional`
- `fix/shutdown-cancel-pair`
- `feat/shutdown-report`

### 迭代 5：状态机和恢复语义

目标：cooldown、emergency、重启恢复都有明确状态路径。

范围：

- 修复 `_enter_cooldown` 绕过 transition 的问题。
- 主循环允许 cooldown 状态执行恢复检查。
- cooldown 到期显式回 `RUNNING`。
- 持久化 unsafe state。
- 崩溃后从 unsafe state 恢复需要人工确认或 preflight。

模块接口：

- `StateRecoveryPolicy`
- `PersistedRuntimeState`

内部流程：

1. 状态变化统一走 `transition()`。
2. cooldown 开始时记录截止时间。
3. tick 中先调用 `state_machine.update_time(now)`。
4. 到期后 transition 回 `RUNNING` 或 `IDLE`。
5. shutdown 保存最终状态。
6. 启动时读取上次状态。
7. 上次为 `EMERGENCY` 或 `COOLDOWN_*` 时 preflight blocked 或要求人工确认。

阶段性测试：

- 非法状态转换被拒。
- spike cooldown 到期后恢复。
- emergency 不会自动下单。
- unsafe persisted state 阻断 live。

建议 PR：

- `fix/state-transition-cooldown`
- `fix/spike-cooldown-resume`
- `feat/recovery-policy`

### 迭代 6：持久化、日报、Web 面板和部署

目标：监控和复盘数据可信，部署入口真实可用。

范围：

- 修正 fills schema。
- 修 `/api/fills`、`/api/summary`。
- 修 `scripts/daily_report.py`。
- Web 面板改用 `Bot.snapshot()`。
- systemd `ExecStart` 指向真实入口。
- README 和部署说明同步。

模块接口：

- `BotSnapshot`
- `SqlitePersistence.migrate()`
- `DailySummary`

内部流程：

1. `open()` 时检查 schema version。
2. 新库创建正确 schema。
3. 旧库按可控方式迁移或提示重建。
4. Web API 只查固定 DB。
5. daily report 和 Web API 使用同一字段。
6. systemd 默认 dry-run 或明确 live 参数。

阶段性测试：

- 新库 API summary 可用。
- daily report 可用。
- Web panel 不访问 `_md`、`_oe` 等私有属性。
- `python -m gate_trade.main` 可用，或 systemd 改成 `scripts/run.py`。

建议 PR：

- `fix/fills-schema-reporting`
- `feat/bot-snapshot-api`
- `fix/systemd-entrypoint`
- `docs/runbook-update`

## 4. PR 切分建议

按风险和依赖关系排序：

1. `chore/ci-dev-deps`
2. `fix/config-loader-unification`
3. `fix/web-panel-safe-default`
4. `feat/live-preflight`
5. `fix/ws-lifecycle`
6. `fix/ws-dispatch-routing`
7. `test/gate-client-ws-parsers`
8. `feat/account-state-store`
9. `fix/risk-real-balances`
10. `fix/risk-base-currency-filter`
11. `feat/order-safety`
12. `fix/shutdown-cancel-pair`
13. `fix/spike-cooldown-resume`
14. `feat/recovery-policy`
15. `fix/fills-schema-reporting`
16. `feat/bot-snapshot-api`
17. `fix/systemd-entrypoint`

每个 PR 的 Definition of Done：

- 有测试。
- dry-run 可运行。
- 不引入真实下单默认路径。
- 文档更新。
- CI 通过。

## 5. 阶段性测试矩阵

| 阶段 | pytest | ruff | mypy | bandit | dry-run | mock live |
|------|--------|------|------|--------|---------|-----------|
| 迭代 0 | 必须 | 必须 | 必须 | 建议 | 可选 | 不要求 |
| 迭代 1 | 必须 | 必须 | 必须 | 必须 | 必须 | preflight |
| 迭代 2 | 必须 | 必须 | 必须 | 建议 | 必须 | WS mock |
| 迭代 3 | 必须 | 必须 | 必须 | 建议 | 必须 | account mock |
| 迭代 4 | 必须 | 必须 | 必须 | 建议 | 必须 | order mock |
| 迭代 5 | 必须 | 必须 | 必须 | 建议 | 必须 | recovery mock |
| 迭代 6 | 必须 | 必须 | 必须 | 必须 | 必须 | full mock |

新增重点测试文件：

- `tests/test_runtime/test_preflight.py`
- `tests/test_client/test_ws_manager.py`
- `tests/test_client/test_gate_client.py`
- `tests/test_account/test_state.py`
- `tests/test_risk/test_policy_live_inputs.py`
- `tests/test_order/test_safety.py`
- `tests/test_runtime/test_shutdown.py`
- `tests/test_web/test_auth.py`
- `tests/test_scripts/test_run_preflight.py`

## 6. 模块内部工作流总览

### 6.1 live 启动工作流

1. CLI 解析参数。
2. 加载配置：default yaml、local yaml、环境变量。
3. 判断模式：dry-run 或 live。
4. live 模式执行强确认检查。
5. 创建 GateIoClient。
6. 执行 preflight。
7. blocked 则退出。
8. 初始化 account snapshot。
9. 初始化 market data、order engine、risk、state、strategy。
10. 启动 WS feed tasks。
11. 启动 Web panel。
12. 启动 Bot 主循环。

### 6.2 tick 工作流

1. 读取 market mid。
2. 读取 account snapshot。
3. 检查 account freshness。
4. 更新 ref price。
5. 检查 spike protection。
6. 生成 risk input。
7. 获取 risk decision。
8. 如果 block，记录 tick 并返回。
9. 更新策略。
10. 生成 desired orders。
11. 执行 order safety。
12. dry-run 记录 would-place；live 提交订单。
13. 更新 markout/toxic。
14. 记录 event log。

### 6.3 对账工作流

1. 周期性调用 `fetch_open_orders(pair)`。
2. 与 `LiveOrderEngine.open_orders(pair)` 比对。
3. exchange 有、本地无：标记 orphan。
4. 本地有、exchange 无：移除 stale。
5. orphan 默认取消或进入 emergency，不能静默忽略。
6. 更新 account snapshot。
7. 记录 reconcile event。

### 6.4 shutdown 工作流

1. 设置 `_running=False`。
2. 禁止新下单。
3. 取消 feed tasks。
4. reconcile exchange orders。
5. cancel current pair/tag orders。
6. 验证残留。
7. 写入 `ShutdownReport`。
8. 关闭 WS 和 API client。
9. 关闭 persistence。
10. 发送 shutdown alert。

### 6.5 Web 面板工作流

1. 请求进入 auth dependency。
2. 调用 `bot.snapshot()`。
3. 返回脱敏 snapshot。
4. 事件流只推送 event logger 中允许公开的字段。
5. DB 查询只使用固定路径。
6. Web 面板不直接访问 bot 私有属性。

## 7. 实盘灰度门槛

以下全部满足前，不应使用真实 API key 运行 `--live`：

- live preflight 已实现并通过测试。
- WebSocket lifecycle 和 dispatch 已修复。
- 风控能读取真实 balances 和 exchange open orders。
- account snapshot stale 时 fail closed。
- order safety 生效。
- shutdown 可验证撤单。
- Web panel 默认本地绑定并有认证。
- systemd 入口可用。
- CI 通过。
- mock live 全链路测试通过。

首次实盘建议：

- 使用子账户。
- API key 禁止提现。
- 开启 IP 白名单。
- 极小资金和极小订单上限。
- 运行 5 到 10 分钟。
- 人工盯盘。
- 停止后检查交易所 open orders 为 0。

## 8. 最终计划结论

这个项目下一阶段不应先优化策略参数，而应先修“失败时不亏钱”的工程边界。最短路径是：先建立 preflight 和 CI，再修 live 数据链路，然后把真实账户状态接入风控，最后补撤单、状态恢复和监控安全。每一步都要用小 PR 合并，每个模块之间用明确的 typed interface 通信，每个模块内部都要有可测试的工作流。

---

签名：Codex · 风控拆解工程师

这份计划以当前仓库 `2e4210a` 为基线，综合 DeepSeek-v4 与 Codex 两轮审计结果生成。
