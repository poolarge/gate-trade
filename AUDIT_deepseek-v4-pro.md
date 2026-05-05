# Gate Trade 项目审计报告

**审计模型**: Deepseek-v4-pro  
**审计日期**: 2026-05-05  
**项目版本**: 0.1.0  
**项目路径**: `/home/monero/gate-trade`  
**审计范围**: 全部源码 (29 个源文件)、配置、Mock、测试 (156 个)、脚本、部署文件

---

## 目录

1. [项目概况](#1-项目概况)
2. [严重问题 — 必须立即修复](#2-严重问题--必须立即修复)
3. [高风险问题 — 强烈建议修复](#3-高风险问题--强烈建议修复)
4. [中风险问题 — 建议修复](#4-中风险问题--建议修复)
5. [低风险问题 — 可选改进](#5-低风险问题--可选改进)
6. [正面评价](#6-正面评价)
7. [测试覆盖分析](#7-测试覆盖分析)
8. [修复优先级路线图](#8-修复优先级路线图)

---

## 1. 项目概况

Python 3.11+ asyncio 架构的 Gate.io 现货单边积累 + 做市机器人。基于 Protocol 接口契约设计，8 个子系统独立可测试，通过依赖注入组装。

### 模块结构

| 模块 | 路径 | 职责 |
|------|------|------|
| `client` | `src/gate_trade/client/` | Gate.io REST + WebSocket API 封装 |
| `config` | `src/gate_trade/config/` | 多层配置加载、热更新、变更守卫 |
| `guardrails` | `src/gate_trade/guardrails/` | 结构化日志、令牌桶限速、异常层次 |
| `market` | `src/gate_trade/market/` | 订单簿维护、VWAP、闪崩检测 |
| `order` | `src/gate_trade/order/` | 下单/撤单/对账引擎 |
| `persistence` | `src/gate_trade/persistence/` | SQLite WAL 持久化、事件日志 |
| `price` | `src/gate_trade/price/` | 参考价格引擎 (自成交排除+尖峰保护) |
| `risk` | `src/gate_trade/risk/` | 仓位/订单数/闪崩风控 |
| `state` | `src/gate_trade/state/` | 9 状态机 + 3 通道独立冷却计时器 |
| `strategy` | `src/gate_trade/strategy/` | 积累器 (棘轮) + 深度维持 (3 层) |
| `markout` | `src/gate_trade/markout/` | 成交质量分析 + 毒性检测 |
| `smasher` | `src/gate_trade/smasher/` | 冰山/探针攻击检测与反制 |
| `replay` | `src/gate_trade/replay/` | 历史回放引擎 |
| `web` | `src/gate_trade/web/` | FastAPI 实时监控面板 |
| `alert` | `src/gate_trade/alert/` | Telegram/Email 多渠道告警 |

---

## 2. 严重问题 — 必须立即修复

### 2.1 [SECURITY] API 密钥明文存储

- **文件**: `config/local.yaml:3-4`
- **严重程度**: CRITICAL

```yaml
exchange:
  api_key: "<REDACTED>"
  api_secret: "<REDACTED>"
```

实盘 API 密钥以明文形式存储在配置文件中。虽已 `.gitignore` 排除，但以下场景仍会导致泄露：
- 文件系统被其他进程读取
- 误操作 `git add --force` 提交到 Git 历史
- 磁盘备份、快照、克隆
- 日志中意外打印配置内容

**修复建议**:
1. 立即在 Gate.io 后台撤销当前 API 密钥对
2. 生成新密钥，通过环境变量 `GATE_EXCHANGE__API_KEY` / `GATE_EXCHANGE__API_SECRET` 注入
3. 将 `local.yaml` 中的密钥替换为占位符或直接删除该文件
4. 检查 `.bash_history` 等是否记录了密钥信息

---

### 2.2 [BUG] 风控从不使用真实账户余额

- **文件**: `src/gate_trade/bot.py:190-192`
- **严重程度**: CRITICAL

```python
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=[],      # <-- 恒为空列表
    mid_price=mid,
)
```

`Bot._tick()` 每 tick 都传入空的 `balances` 列表给风控。`RiskManager._check_position()` 中：

```python
base_held = sum(b.total for b in balances if b.asset == self._cfg.base)
```

这一行永远返回 0。仓位上限检查完全失效，风控形同虚设。

**修复建议**: 在 `_tick()` 中调用 `self._client.fetch_balances()` 获取真实余额后传入风控。

---

### 2.3 [BUG] 状态机冷却态绕过 transition() 验证

- **文件**: `src/gate_trade/state/state_machine.py:140-149`
- **严重程度**: CRITICAL

```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
        return
    old = self._state
    self._state = kind  # <-- 直接赋值，绕过 transition() 验证
```

`transition()` 方法有 `_VALID_TRANSITIONS` 字典严格限制合法状态转换，但 `_enter_cooldown` 直接设置 `self._state`，允许任何状态（除 EMERGENCY/SHUTDOWN）直接进入冷却态，违反了状态机契约。

**修复建议**: 将 `self._state = kind` 改为 `self.transition(kind)`。

---

### 2.4 [RISK] 订单价格无上限/下限保护

- **文件**: `src/gate_trade/order/order_engine.py:254-261`
- **严重程度**: CRITICAL

```python
def _validate(self, order: Order) -> None:
    if order.price <= 0:
        raise OrderValidationError(...)
    if order.size <= 0:
        raise OrderValidationError(...)
    # 无 max_price / min_price 检查
```

如果参考价格出现异常（API 返回错误数据、订单簿被操纵、闪崩未检测到），bot 可能以极端价格下单。例如一个市价 $1.00 的 token，bot 可能因数据错误而下 $0.01 的卖单或 $100 的买单。

**修复建议**: 基于 TWAP 或配置阈值添加 `max_price` / `min_price` 边界检查，例如不超过参考价的 ±20%。

---

### 2.5 [BUG] WebSocket ping loop 从未启动

- **文件**: `src/gate_trade/client/ws_manager.py:129-136`
- **严重程度**: CRITICAL

```python
async def _ping_loop(self) -> None:
    while self._running and self._conn:
        await asyncio.sleep(self._cfg.ping_interval_sec)
        ...
```

`_ping_loop` 方法定义了但从未被 `asyncio.create_task()` 调用。WebSocket 连接缺少心跳维持，在长时间无消息时可能被中间代理/网关断开，导致市场数据中断。

**修复建议**: 在 `connect()` 方法中添加 `self._ping_task = asyncio.create_task(self._ping_loop())`。

---

## 3. 高风险问题 — 强烈建议修复

### 3.1 [SECURITY] Web 面板绑定 0.0.0.0 且无认证

- **文件**: `scripts/run.py:88`
- **严重程度**: HIGH

```python
async def _start_web_panel(bot: Bot, host: str = "0.0.0.0", port: int = <REDACTED_PORT>)
```

监控面板默认监听所有网络接口，无任何认证机制。部署在云服务器上时，任何人都可通过公网 IP 访问交易机器人的持仓、订单、策略状态。

**修复建议**: 默认 `host` 改为 `"127.0.0.1"`，需要外部访问时通过 SSH 隧道或显式配置。同时考虑添加简单的 API key 认证。

---

### 3.2 [BUG] 关机 cancel_all 传递空交易对

- **文件**: `src/gate_trade/bot.py:330-334`
- **严重程度**: HIGH

```python
if not self._dry_run:
    try:
        await self._oe.cancel_all("")  # 空字符串
```

`cancel_all("")` 传递空字符串作为 pair 参数给 Gate.io API。`cancel_all_orders` 的 pair 参数语义未定义——可能是取消所有交易对的所有订单，也可能因参数无效而返回错误，导致关机时订单未被取消。

**修复建议**: 传入实际的交易对参数，或修改 `cancel_all` 不依赖 pair 过滤。

---

### 3.3 [BUG] load_state 对未知状态字符串抛出 ValueError

- **文件**: `src/gate_trade/persistence/sqlite.py:191-197`
- **严重程度**: HIGH

```python
def load_state(self) -> tuple[BotState, str | None]:
    row = self._db.execute(...).fetchone()
    if row is None:
        return (BotState.INIT, None)
    return (BotState(row[0]), row[1])
```

如果 DB 中存储了已废弃或损坏的状态值，`BotState(row[0])` 直接抛出 `ValueError`，bot 无法启动。

**修复建议**: 用 try/except 捕获，降级到 `BotState.INIT`，并记录 warning 日志。

---

### 3.4 [CONFIG] run.py 和 healthcheck.py 配置加载路径不一致

- **文件**: `scripts/run.py:59` vs `scripts/healthcheck.py:27-37`
- **严重程度**: HIGH

`run.py` 使用 `from_yaml()` 不加载 `local.yaml`；`healthcheck.py` 使用 `from_yaml_merged()` 加载 `local.yaml`。同一个 bot 在不同入口看到不同的配置，可能导致：
- 健康检查通过的配置与实际运行的配置不同
- `local.yaml` 中的覆盖在运行时被忽略

**修复建议**: 统一使用 `from_yaml_merged()` 或确保两个入口的加载逻辑一致。

---

### 3.5 [RISK] 风控状态在崩溃重启后丢失

- **严重程度**: HIGH

`SqlitePersistence` 保存 `bot_state`，但风控内部标志（`_halted`, `_position_breached` 等）不持久化。如果 bot 在风控暂停期间崩溃重启，重启后可能立即恢复交易，而实际仓位已经超标。

**修复建议**: 启动时检查最后持久化的状态，如果是 `EMERGENCY` 或 `COOLDOWN_*`，则需要人工确认后才恢复交易。

---

### 3.6 [DATA] 闪崩检测阈值硬编码

- **文件**: `src/gate_trade/market/market_data.py:200`
- **严重程度**: HIGH

```python
return (high - low) / high >= 0.05  # 固定 5%
```

5% 的固定阈值对 DOGE（波动大）和 BTC（波动小）意义完全不同。对低波动资产可能漏检闪崩，对高波动资产可能频繁误报。

**修复建议**: 将阈值改为可配置参数，支持按交易对设置。

---

## 4. 中风险问题 — 建议修复

### 4.1 [ARCH] Bot 构造参数类型为 Any 而非 Protocol

- **文件**: `src/gate_trade/bot.py:49-56`
- **严重程度**: MEDIUM

```python
def __init__(
    self,
    market_data: Any = None,      # 应为 MarketData
    order_engine: Any = None,     # 应为 OrderEngine
    price_engine: Any = None,     # 应为 RefPriceEngine
    ...
```

使用 `Any` 丧失了编译期类型检查。错误传入不匹配的对象在运行时才会被发现。

**修复建议**: 导入对应的 Protocol 类并用其标注参数类型。

---

### 4.2 [ENCAP] Web Panel 直接访问私有属性

- **文件**: `src/gate_trade/web/panel.py:136-151`
- **严重程度**: MEDIUM

```python
md = bot._md          # 私有属性直接访问
sm = bot._sm
oe = bot._oe
strategies = bot._strategies
events = bot.events
bot.events._on_record = lambda evt: _broadcast(...)  # 直接修改私有回调
```

这破坏了封装性，且所有属性类型为 `Any`，IDE 无法提供补全和类型检查。

**修复建议**: 在 `Bot` 类中添加公共只读属性或 getter 方法。

---

### 4.3 [TEST] GateIoClient 和 WsManager 零测试覆盖

- **严重程度**: MEDIUM

实盘客户端 `GateIoClient`（`gate_client.py`）和 `WsManager`（`ws_manager.py`）完全没有单元测试。所有集成测试都使用 `MockGateClient`，以下方法未被验证：
- `_handle_api_error`
- `_parse_orderbook`
- `_parse_orders`
- `_parse_balances`
- WebSocket 重连逻辑
- 消息分发和订阅管理

**修复建议**: 使用 `aioresponses` 或 `pytest-httpx` mock HTTP 层，为关键解析方法添加测试。

---

### 4.4 [DEDUP] _flatten 方法重复

- **文件**: `config/schema.py:116-126` 和 `config/watcher.py:180-188`
- **严重程度**: MEDIUM

两处有几乎相同的 `_flatten` 实现。未来只修改一处会导致行为不一致。

**修复建议**: 提取为 `config/schema.py` 中的公共函数或工具方法。

---

### 4.5 [DATA] MarkoutRecorder 关闭时未清理 pending 记录

- **文件**: `src/gate_trade/markout/recorder.py:77-93`
- **严重程度**: MEDIUM

`update_mid` 仅将 `mids_after` 填满的记录移入 `_completed`。bot 关闭时 `_pending` deque 中尚未完成的记录直接丢失，不会被持久化或清理。

**修复建议**: shutdown 时调用 flush 方法将剩余记录写入日志或 DB。

---

### 4.6 [CONFIG] .gitignore 缺少 data/ 目录

- **严重程度**: MEDIUM

运行时生成的 `data/bot.log` 和 `data/gate_trade.db` 未被 `.gitignore` 排除。如果该目录已生成，容易误提交含敏感信息的日志和数据库。

**修复建议**: 在 `.gitignore` 中添加 `data/`。

---

### 4.7 [DEPLOY] 缺少进程管理配置

- **严重程度**: MEDIUM

项目没有 systemd 单元文件、Dockerfile 或 supervisor 配置。bot 作为前台进程运行，SSH 断开或机器重启后不会自动恢复。

---

## 5. 低风险问题 — 可选改进

### 5.1 [LOG] API 错误响应可能泄露信息

- **文件**: `src/gate_trade/client/gate_client.py:248-259`

```python
logger.error("exchange_error", body=str(exc.body), **extra)
```

API 错误响应体被完整记录，可能包含部分账户信息。

---

### 5.2 [WEB] SQLite 路径存在路径遍历风险

- **文件**: `src/gate_trade/web/panel.py:201-202`

```python
async def api_fills(db: str = Query(default=DEFAULT_DB), ...):
```

允许通过查询参数指定数据库路径。如果面板暴露在公网，存在读取任意 SQLite 文件的风险。

---

### 5.3 [ORDER] save_fill 的并发安全依赖单线程假设

- **文件**: `src/gate_trade/persistence/sqlite.py:155-166`

`save_fill` 分步执行 INSERT + UPDATE + COMMIT，之间如果有协程切换可能导致数据不一致。当前单线程 bot 不会触发，但架构上存在脆弱性。

---

### 5.4 [ORDER] cancel 的 _by_tag 清理可能残留悬挂引用

- **文件**: `src/gate_trade/order/order_engine.py:125-148`

如果订单没有 `client_order_id`（如对账时从 exchange 加载），`_by_tag` 不会被清理。

---

### 5.5 [ORDER] place 和 reconcile 之间存在竞态窗口

- **文件**: `src/gate_trade/order/order_engine.py:95-123`

pending 订单在获得 exchange 确认前就被记录，此时 `reconcile()` 可能将其误判为孤儿订单。

---

### 5.6 [STRATEGY] 连续 tick 可能生成重复订单

`DepthKeeper._compute_quotes()` 每 tick 生成新订单。如果多 tick 间参考价不变，将重复生成相同订单集。当前缺少去重逻辑。

---

### 5.7 [TOKEN] 令牌桶等待超时是硬错误

- **文件**: `src/gate_trade/guardrails/rate_limiter.py:41-51`

`max_wait_sec` 超时后直接抛异常，bot 在该 tick 周期内无法下单。

---

## 6. 正面评价

以下是项目中值得肯定的设计和实现：

1. **Protocol/契约架构** — 8 个子系统全部先定义 Protocol 接口，Mock 和实现分离，依赖注入清晰，每个模块可独立开发和测试。

2. **测试覆盖** — 156 个测试（84 个契约测试 + 72 个单元/场景测试），覆盖所有 8 个 Protocol 接口。状态机有参数化转换矩阵测试。

3. **结构化日志** — 使用 `structlog`，所有日志级别可动态配置，支持 JSON 文件输出。

4. **令牌桶限速器** — 符合交易所 API 限速要求的通用限速组件，设计合理。

5. **状态机设计** — 9 状态 + 严格转换矩阵 + 3 通道独立冷却计时器，避免 bot 在异常状态下继续交易。

6. **配置分层** — `default.yaml → local.yaml → 环境变量` 三层覆盖，环境变量优先级最高。

7. **代码质量** — `mypy strict` + `ruff` 零警告，完整类型标注，命名规范一致。

8. **参考价格引擎** — 自成交排除（排除 bot 自己的买单/卖单）、TWAP 平滑、尖峰保护等设计考虑周全。

9. **Markout 分析** — 成交后 5 个时间窗口的 markout 追踪 + 毒性检测 + 分级响应，专业级的交易质量评估。

10. **API 错误分类** — 7 种自定义异常，区分超时、限速、认证等不同错误类型，便于分类处理。

---

## 7. 测试覆盖分析

### 已测试 ✅

| 模块 | 测试文件数 | 关键覆盖 |
|------|-----------|----------|
| MarketData | 1 | snapshot/delta/depth/VWAP/signals |
| OrderEngine | 1 | place/cancel/reconcile/rate-limit |
| SqlitePersistence | 1 | orders/fills/state/markout/lifecycle |
| RefPriceEngine | 1 | self-fill exclusion/spike/TWAP |
| RiskManager | 1 | position/order-count/flash-crash/halt-resume |
| StateMachine | 1 | 状态转换矩阵 (参数化) |
| CooldownManager | 1 | 3 通道独立计时器 |
| Accumulator | 1 | ratchet/collapse/spike/active |
| DepthKeeper | 1 | tier/ACTIVE-DORMANT/anti-spoof/spike |
| MarkoutRecorder | 1 | 成交追踪 |
| ToxicDetector | 1 | 毒性检测 |
| ToxicResponse | 1 | 分级响应 |
| Smasher 模块 | 4 | 探测/冰山/执行/验证 |
| Replay 引擎 | 3 | 回放/数据/指标 |
| Config 模块 | 3 | schema/guard/watcher |
| Bot 编排器 | 1 | 基础生命周期 |
| Web 面板 | 1 | 基础端点 |
| Alert | 1 | 基础通知 |
| 攻击场景 | 1 | 概念测试 |

### 未测试 ❌

| 模块 | 风险 |
|------|------|
| `GateIoClient` (gate_client.py) | 关键解析逻辑无测试 |
| `WsManager` (ws_manager.py) | 重连/分发逻辑无测试 |
| `scripts/run.py` | 启动流程无测试 |
| `scripts/gate_admin.py` | 管理工具无测试 |
| TelegramChannel / EmailChannel | 实际发送逻辑无测试 |
| ConfigWatcher + ConfigGuard 集成 | 热更新全流程无测试 |
| Bot 长时间运行场景 | 仅测试 50ms 片段 |

---

## 8. 修复优先级路线图

### 第 1 批: 安全 + 正确性 (今天完成)

| # | 问题 | 文件 |
|---|------|------|
| 1 | 撤销 local.yaml 中的 API 密钥，改用环境变量 | `config/local.yaml` |
| 2 | Bot._tick 传入真实 balances | `bot.py:191` |
| 3 | _enter_cooldown 调用 transition() | `state_machine.py:146` |
| 4 | 订单价格边界保护 | `order_engine.py:254` |
| 5 | WS ping loop 启动 | `ws_manager.py:129` |

### 第 2 批: 风控加固 (本周)

| # | 问题 | 文件 |
|---|------|------|
| 6 | Web panel 默认 127.0.0.1 | `scripts/run.py:88` |
| 7 | cancel_all 传入真实 pair | `bot.py:332` |
| 8 | load_state 容错处理 | `sqlite.py:195` |
| 9 | run.py/healthcheck 配置加载统一 | `scripts/run.py` |
| 10 | 崩溃重启后风控状态恢复 | `bot.py` + `risk/` |

### 第 3 批: 质量提升 (本月)

| # | 问题 | 文件 |
|---|------|------|
| 11 | Bot 参数类型标注 Protocol | `bot.py:49-56` |
| 12 | Web panel 解耦私有属性访问 | `panel.py` + `bot.py` |
| 13 | GateIoClient / WsManager 单元测试 | `gate_client.py` |
| 14 | _flatten 去重 | `schema.py` / `watcher.py` |
| 15 | .gitignore 添加 data/ | `.gitignore` |
| 16 | systemd 单元文件 | `systemd/` |
| 17 | 闪崩阈值可配置 | `market_data.py` |

---

> **Deepseek-v4-pro**  
> *审计于 2026-05-05*  
> *此报告由 AI 模型生成，建议人工复核关键发现*
