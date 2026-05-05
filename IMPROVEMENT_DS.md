# Gate Trade 改进建议

**贡献代码的DS**

**基于**: `AUDIT_DS.md` — 2026-05-05 审计报告

---

## 第 1 批: 本周必须修复 (安全 + 正确性)

### 1. Bot._tick 传入真实余额

```
文件: src/gate_trade/bot.py:190
```

Bot 构造时添加余额缓存属性：

```python
# __init__
self._balances_cache: list[Balance] = []
self._balances_ticks: int = 0
self._client: Any = None  # GateIoClient 引用，live 模式设置
```

在 `_tick()` 中每 5 tick 刷新一次：

```python
# _tick
self._balances_ticks += 1
if self._balances_ticks % 5 == 0 and self._client is not None:
    self._balances_cache = await self._client.fetch_balances()

self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=self._balances_cache,
    mid_price=mid,
)
```

注意：需要将 `_client` 引用传入 Bot 构造器。

---

### 2. _enter_cooldown 使用 transition() 验证

```
文件: src/gate_trade/state/state_machine.py:146
```

```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
        logger.debug("cooldown_blocked", state=self._state.value)
        return
    try:
        self.transition(kind)
    except InvalidTransitionError:
        logger.warning("cooldown_invalid", from_state=self._state.value, to=kind.value)
        return
    self._cooldown_until = time.monotonic() + duration_ms / 1000.0
    self._cooldown_type = kind
    logger.info("cooldown_start", kind=kind.value, duration_ms=duration_ms)
```

确保 `_VALID_TRANSITIONS` 中包含所有合法冷却路径（ACTIVE → COOLDOWN_*）。

---

### 3. 订单价格边界保护

```
文件: src/gate_trade/order/order_engine.py:254
```

在 `_validate` 添加可选 ref_price 参数：

```python
def _validate(self, req: OrderRequest, ref_price: float | None = None) -> None:
    if req.price <= 0:
        raise ValueError(f"Invalid price: {req.price}")
    if req.size <= 0:
        raise ValueError(f"Invalid size: {req.size}")
    if ref_price and ref_price > 0:
        max_price = ref_price * 1.20
        min_price = ref_price * 0.80
        if req.price > max_price:
            raise ValueError(f"Price {req.price} exceeds max {max_price:.2f}")
        if req.price < min_price:
            raise ValueError(f"Price {req.price} below min {min_price:.2f}")
```

在 `bot.py` 的 `_refresh_orders()` 调用时传入 `mid` 作为 ref_price。

---

### 4. WebSocket ping loop 启动

```
文件: src/gate_trade/client/ws_manager.py
```

在 `connect()` 方法中：

```python
async def connect(self) -> None:
    # ... 现有连接逻辑后
    self._ping_task = asyncio.create_task(self._ping_loop())
```

在 `__init__` 添加：

```python
self._ping_task: asyncio.Task | None = None
```

在断开连接时取消 ping task。

---

### 5. cancel_all 传入真实交易对

```
文件: src/gate_trade/bot.py:332
```

将 `self._oe.cancel_all("")` 改为 `self._oe.cancel_all(self._pair)`。

需要在 Bot 中存储 pair 引用。Bot 已有 `_pair` 吗？检查 `bot.py:__init__` — 需要添加该属性：

```python
self._pair = pair
```

---

## 第 2 批: 2 周内修复 (风控 + 可靠性)

### 6. Web panel 改为 127.0.0.1 + 认证

```
文件: scripts/run.py:88
```

```python
async def _start_web_panel(bot: Bot, host: str = "127.0.0.1", port: int = 39120)
```

可选的简单 token 认证 — 在 `panel.py` 中：

```python
import os
from fastapi import HTTPException, Header

_WEB_TOKEN = os.getenv("GATE_WEB_TOKEN", "")

async def _auth(x_token: str = Header(default="")):
    if _WEB_TOKEN and x_token != _WEB_TOKEN:
        raise HTTPException(403)
```

在需要保护的端点添加 `dependencies=[Depends(_auth)]`。

---

### 7. load_state 容错处理

```
文件: src/gate_trade/persistence/sqlite.py:197
```

```python
try:
    return (BotState(row[0]), row[1])
except ValueError:
    logger.warning("unknown_persisted_state", state=row[0])
    return (BotState.INIT, f"recovered from unknown: {row[0]}")
```

---

### 8. 配置加载统一

```
文件: scripts/run.py:59
```

`build_config` 改为使用 `from_yaml_merged`，或在 `run.py` 中调用 `from_env_overlay` 统一流程。

推荐：用 `from_env_overlay` 同时处理 local.yaml 合并和环境变量覆盖。

---

### 9. 风控状态持久化

```
文件: src/gate_trade/risk/risk_manager.py, persistence/sqlite.py
```

每次 `_enter_halt()` 时写入 `bot_state` 表保存当前风控状态。启动时 `load_state()` 检查，若上次退出时处于 halt/emergency 状态，需人工确认或等待冷却。

---

### 10. 闪崩阈值改为可配置

```
文件: src/gate_trade/market/market_data.py:195-200
```

从 `RiskConfig.flash_crash_threshold_pct` 读阈值，或新增 `MarketConfig.flash_crash_threshold`。

默认值可在 `config/default.yaml` 中按交易对覆盖。

---

## 第 3 批: 3-4 周内修复 (质量 + 可维护性)

### 11. Bot 使用 Protocol 类型标注

```
文件: src/gate_trade/bot.py:49-66
```

将 `Any` 替换为对应的 Protocol 类：

```python
from gate_trade.market.contract import MarketData
from gate_trade.order.contract import OrderEngine
from gate_trade.risk.contract import RiskManager
from gate_trade.state.contract import StateMachine
from gate_trade.strategy.contract import Strategy
from gate_trade.persistence.contract import Persistence

class Bot:
    def __init__(
        self,
        state_machine: StateMachine,
        market_data: MarketData,
        ...
    ):
```

---

### 12. Web Panel 通过公共属性访问 Bot

```
文件: src/gate_trade/bot.py — 添加公共属性
```

```python
@property
def mid_price(self) -> float:
    return self._md.mid_price()
```

```
文件: src/gate_trade/web/panel.py — 使用公共属性
```

将 `bot._md.mid_price()` 改为 `bot.mid_price`。

---

### 13. GateIoClient / WsManager 单元测试

新建 `tests/test_client/test_gate_client.py` 和 `tests/test_client/test_ws_manager.py`。

用 `aioresponses` mock HTTP 层测试：
- `_parse_orderbook()` — 正常/空/异常 API 响应
- `_handle_api_error()` — 限速/认证失败/超时
- `subscribe_orderbook()` — 消息分发和 channel 注册

---

### 14. 其他小修

| ID | 问题 | 文件 | 改动 |
|----|------|------|------|
| 14a | `_flatten` 去重 | `schema.py` / `watcher.py` | watcher 复用 schema 的 `_flatten_dict` |
| 14b | `.gitignore` 加 `data/` | `.gitignore` | 添加 `data/` `*.db` `*.db-wal` |
| 14c | Web Panel 限制 db 路径 | `panel.py` | 移除 `db` 查询参数，使用固定路径 |
| 14d | MarkoutRecorder 添加 flush 方法 | `recorder.py` | shutdown 时 flush pending |
| 14e | TelegramChannel 改异步 | `alert/manager.py` | 用 `httpx.AsyncClient` 替代同步 urllib |

---

## 测试补充路线图

| 优先级 | 测试内容 | 文件 | 预估 |
|--------|----------|------|------|
| P0 | GateIoClient 解析逻辑 | `tests/test_client/test_gate_client.py` | 半天 |
| P0 | WsManager 重连/分发 | `tests/test_client/test_ws_manager.py` | 一天 |
| P1 | Bot 完整生命周期 | `tests/test_bot_integration.py` | 一天 |
| P1 | Config Watcher+Guard 集成 | `tests/test_config/test_integration.py` | 半天 |
| P2 | alert channels 发送 | `tests/test_alert/test_channels.py` | 半天 |
| P2 | run.py 启动流程 | `tests/test_scripts/test_run.py` | 半天 |

---

> *2026-05-05*
