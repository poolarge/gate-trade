# Gate Trade 审计报告

**日期**: 2026-05-05
**范围**: 全部 70 个 Python 源文件、83 个测试文件、脚本、配置
**测试**: 469 个测试全部通过
**静态检查**: ruff 零警告、mypy 零错误 (56 个源文件)

---

## 一、严重问题 (CRITICAL)

### 1.1 风控传入空余额 — 仓位检查完全失效

**文件**: `src/gate_trade/bot.py:190`

```python
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=[],      # <-- 永远为空
    mid_price=mid,
)
```

`LiveRiskManager._check_position()` 中的 `base_held = sum(b.total for b in balances ...)` 恒为 0。仓位上限检查形同虚设，实盘存在爆仓风险。

**修复**: 每 N 个 tick 调用 `client.fetch_balances()` 或从 WebSocket 账户频道获取余额，传入风控。

---

### 1.2 冷却态绕过状态机转换验证

**文件**: `src/gate_trade/state/state_machine.py:146`

```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    ...
    self._state = kind    # 直接赋值，绕过 transition() 的转换矩阵验证
```

`transition()` 方法有严格的 `_VALID_TRANSITIONS` 字典，但 `_enter_cooldown` 直接设值。任何非 EMERGENCY/SHUTDOWN 状态都可进入冷却态。

**修复**: 改为 `self.transition(kind)`。

---

### 1.3 订单价格无上下限边界保护

**文件**: `src/gate_trade/order/order_engine.py:254-258`

```python
def _validate(self, req: OrderRequest) -> None:
    if req.price <= 0: ...
    if req.size <= 0: ...
    # 无 max_price / min_price 检查
```

参考价格异常时（API 错误、闪崩未检测到），bot 可能以极其不合理价格下单。

**修复**: 基于参考价添加 ±20% 价格边界。

---

### 1.4 WebSocket ping loop 从未启动

**文件**: `src/gate_trade/client/ws_manager.py:129`

`_ping_loop` 已定义，但 `connect()` 中从未调用 `asyncio.create_task(self._ping_loop())`。长时间无消息时中间代理会断开连接，导致市场数据中断且无感知。

---

### 1.5 风控状态崩溃重启后永久丢失

**文件**: `src/gate_trade/risk/risk_manager.py`

`LiveRiskManager._halted`、`_position_breached`、`_flash_crash` 等纯内存标志不持久化。如果 bot 在风控暂停期间崩溃，重启后立即恢复交易，而实际仓位可能已严重超标。

**修复**: 启动时检查 `bot_state` 表最新状态，若为 EMERGENCY 或 COOLDOWN_*，需人工确认后恢复。

---

## 二、高风险问题 (HIGH)

### 2.1 Web 面板默认监听 0.0.0.0，无认证

**文件**: `scripts/run.py:88`

```python
async def _start_web_panel(bot: Bot, host: str = "0.0.0.0", port: int = 39120)
```

部署在云服务器上时，任何人可访问持仓、订单和策略。面板无任何认证。

**修复**: 默认 `host="127.0.0.1"`，外部访问通过 SSH 隧道。或添加 API key 认证。

---

### 2.2 Bot 关机时 cancel_all 传空交易对

**文件**: `src/gate_trade/bot.py:330-334`

```python
await self._oe.cancel_all("")   # 空字符串
```

Gate.io API 中 `currency_pair` 为可选参数，传空字符串语义不明确 — 可能取消全部订单也可能因参数无效返回错误。

**修复**: 传入 `self._pair`。

---

### 2.3 load_state 对损坏状态字符串直接崩溃

**文件**: `src/gate_trade/persistence/sqlite.py:197`

```python
return (BotState(row[0]), row[1])  # ValueError 如果 row[0] 无效
```

DB 中出现废弃/损坏的状态值时抛 ValueError，bot 无法启动。

**修复**: 用 try/except 捕获，降级到 `BotState.INIT`。

---

### 2.4 run.py 配置加载不合并 local.yaml

**文件**: `scripts/run.py:59`

`run.py` 调用 `AppConfig.from_yaml()` 只加载单个文件；`schema.py:80` 提供了 `from_yaml_merged()` 方法可合并 `local.yaml`。运行时和其他脚本看到的配置可能不同。

**修复**: 统一使用 `from_yaml_merged()`。

---

### 2.5 闪崩阈值硬编码为 5%

**文件**: `src/gate_trade/market/market_data.py:200`

```python
return (high - low) / high >= 0.05   # 写死的 5%
```

DOGE 日常波动远超 BTC，同一阈值对不同交易对效果截然不同。配置中已有 `risk.flash_crash_threshold_pct`，但 `market_data.py` 未读取。

**修复**: 从 `RiskConfig.flash_crash_threshold_pct` 读阈值。

---

### 2.6 API 密钥可能残留在 local.yaml

**文件**: `config/local.yaml`

虽已 `.gitignore` 排除，但文件系统中可能仍存有明文密钥。难以审计是否已撤销。

---

## 三、中风险问题 (MEDIUM)

### 3.1 Bot 构造参数和 Web Panel 大量使用 Any 类型

- `bot.py:49-66` — 所有注入参数标注为 `Any`，丧失编译期类型检查
- `web/panel.py:136-141` — `bot._md`、`bot._sm` 等直接访问私有属性，且类型为 `Any`

IDE 无法提供补全和类型检查。如传入错误对象，运行时才报错。

---

### 3.2 .gitignore 缺少 data/ 目录

`data/gate_trade.db` 和 `data/bot.log` 包含完整交易数据和日志，未被 `.gitignore` 排除，容易误提交。

---

### 3.3 _flatten 方法在 schema.py 和 watcher.py 中重复

- `config/schema.py:116` — `AppConfig._flatten()`
- `config/watcher.py:180` — `ConfigWatcher._flatten()`

两个实现几乎相同，修改一处容易遗漏另一处。

---

### 3.4 Web Panel SQLite 路径可任意指定

**文件**: `web/panel.py:201-202`

```python
async def api_fills(db: str = Query(default=DEFAULT_DB), ...)
```

允许通过 URL 参数指定任意数据库路径，存在路径遍历风险。

---

### 3.5 GateIoClient / WsManager 零单元测试

实盘客户端的 HTTP 解析、WebSocket 重连、消息分发等关键逻辑无测试覆盖。仅通过契约测试的 Mock 验证了接口形状。

---

### 3.6 MarkoutRecorder pending 记录关闭时丢失

**文件**: `markout/recorder.py:77-93`

`update_mid` 仅将已完成的记录移入 `_completed`。Bot 关闭时 `_pending` 中尚未完成的 markout 记录静默丢弃。

---

### 3.7 Smasher 模块未集成到主循环

`smasher/` 下的 4 个模块（冰山检测、探针攻击、执行、验证）已编写完成且有 10 个测试，但 `bot.py` 的 `_tick()` 未调用它们。

---

### 3.8 TelegramChannel 使用同步 urllib

**文件**: `alert/manager.py:55`

```python
await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
```

通过 `asyncio.to_thread` 包装同步调用，在告警频繁时会创建多个线程。改为 `httpx` 或 `aiohttp` 更合适。

---

## 四、正面评价

1. **Protocol/契约架构** — 8 个子系统全部先定义 Protocol 接口，依赖注入清晰
2. **测试覆盖** — 469 个测试，83 个测试文件，覆盖所有策略、状态机、风控、订单引擎、markout
3. **Smasher 子系统** — 冰山检测用 Welch's t-test 做统计验证，设计专业
4. **状态机** — 10 状态 + 严格转换矩阵 + 3 通道独立冷却计时器
5. **代码质量** — `mypy` + `ruff` 零警告，完整类型标注，命名一致
6. **SSE 实时面板** — 事件广播 + 自动重连 + 快照轮询，体验完整
7. **BotEventLogger** — 内存环形缓冲 + SQLite 持久化，兼顾性能与可审计性
8. **Config 三层覆盖** — `default.yaml → local.yaml → 环境变量`，环境变量优先级最高
9. **结构化日志** — structlog + RotatingFileHandler，支持 JSON 输出和 jq 过滤
10. **Replay 引擎** — 历史数据回放，可独立验证策略表现

---

## 五、测试覆盖现状

**已覆盖** ✅: MarketData, OrderEngine, SqlitePersistence, RefPriceEngine, RiskManager, StateMachine, CooldownManager, Accumulator, DepthKeeper, MarkoutRecorder, ToxicDetector, ToxicResponse, IcebergDetector, ProbeDetector, SmasherVerifier, ReplayEngine, Config, Bot, Web Panel, Alert, Attack Scenarios

**未覆盖** ❌: GateIoClient (ws_manager.py 84行, gate_client.py 260行), scripts/run.py, ConfigWatcher+ConfigGuard 集成测试

---

> *审计于 2026-05-05*
