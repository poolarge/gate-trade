# Gate Trade 改进建议

**审计模型**: Deepseek-v4-pro  
**日期**: 2026-05-05  
**基于**: `AUDIT_deepseek-v4-pro.md` 审计报告

---

## 目录

1. [第 1 批: 安全+正确性 (今天)](#1-第-1-批安全正确性-今天)
2. [第 2 批: 风控加固 (本周)](#2-第-2-批风控加固-本周)
3. [第 3 批: 质量提升 (本月)](#3-第-3-批质量提升-本月)
4. [测试补充清单](#4-测试补充清单)

---

## 1. 第 1 批: 安全+正确性 (今天)

### 1.1 撤销 local.yaml 中的 API 密钥

**文件**: `config/local.yaml`

**当前状态**:
```yaml
exchange:
  api_key: "<REDACTED>"
  api_secret: "<REDACTED>"
```

**步骤**:
1. 登录 Gate.io → API 管理 → 删除当前密钥对
2. 生成新密钥对，勾选「现货交易」权限，禁止提现
3. 删除 `local.yaml` 中的密钥字段，改为:
   ```yaml
   exchange:
     # api_key / api_secret 通过环境变量注入
   ```
4. 启动 bot 时设置环境变量:
   ```bash
   export GATE_EXCHANGE__API_KEY="new_key"
   export GATE_EXCHANGE__API_SECRET="new_secret"
   ```
5. 检查 `.bash_history` 中是否有残留的密钥字符串:
   ```bash
   grep -r "<KEY_FRAGMENT>" ~/.bash_history || true
   ```

**环境变量命名规则** (已在 `schema.py:from_env_overlay` 实现): 用 `__` 分隔嵌套键，如 `GATE_EXCHANGE__API_KEY` 对应 `config["exchange"]["api_key"]`。

---

### 1.2 Bot._tick 传入真实余额

**文件**: `src/gate_trade/bot.py:190-192`

**当前**:
```python
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=[],
    mid_price=mid,
)
```

**改为**:
```python
balances = await self._client.fetch_balances()
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=balances,
    mid_price=mid,
)
```

**注意**: `fetch_balances()` 是一次 API 调用。如果担心每 tick 都调用太频繁，可以缓存，每 N 个 tick 刷新一次:

```python
# __init__ 中
self._balances_cache: list[Balance] = []
self._balances_ticks = 0

# _tick 中
self._balances_ticks += 1
if self._balances_ticks % 5 == 0:  # 每 5 个 tick 刷新
    self._balances_cache = await self._client.fetch_balances()
```

---

### 1.3 _enter_cooldown 调用 transition() 验证

**文件**: `src/gate_trade/state/state_machine.py:140-149`

**当前**:
```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
        logger.debug("cooldown_blocked", state=self._state.value)
        return
    old = self._state
    self._state = kind
    self._cooldown.start(kind, duration_ms)
    logger.info("cooldown_enter", kind=kind.value, old=old.value, duration_ms=duration_ms)
```

**改为**:
```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
        logger.debug("cooldown_blocked", state=self._state.value)
        return
    try:
        self.transition(kind)
    except InvalidTransitionError:
        logger.warning("cooldown_transition_invalid", from_state=self._state.value, to=kind.value)
        return
    self._cooldown.start(kind, duration_ms)
    logger.info("cooldown_enter", kind=kind.value, duration_ms=duration_ms)
```

**副作用检查**: 确认 `_VALID_TRANSITIONS` 中包含所有合法的冷却目标状态条目。当前冷却态有:
- `COOLDOWN_FLASH_CRASH`
- `COOLDOWN_TOXIC`
- `COOLDOWN_MAX_ORDERS`

需要在 `_VALID_TRANSITIONS` 中确认 `BotState.ACTIVE → BotState.COOLDOWN_*` 等路径存在。

---

### 1.4 订单价格边界保护

**文件**: `src/gate_trade/order/order_engine.py:254-261`

**当前**:
```python
def _validate(self, order: Order) -> None:
    if order.price <= 0:
        raise OrderValidationError(...)
    if order.size <= 0:
        raise OrderValidationError(...)
```

**改为** (新增一个可选的 ref_price 参数):
```python
def _validate(self, order: Order, ref_price: float | None = None) -> None:
    if order.price <= 0:
        raise OrderValidationError(order, "price must be positive")
    if order.size <= 0:
        raise OrderValidationError(order, "size must be positive")
    if ref_price and ref_price > 0:
        max_dev = self._cfg.max_price_deviation  # 例如 0.2 = 20%
        max_price = ref_price * (1 + max_dev)
        min_price = ref_price * (1 - max_dev)
        if order.price > max_price:
            raise OrderValidationError(order, f"price {order.price} > max {max_price}")
        if order.price < min_price:
            raise OrderValidationError(order, f"price {order.price} < min {min_price}")
```

**配套**: 在 `config/default.yaml` 添加:
```yaml
order:
  max_price_deviation: 0.20
```

---

### 1.5 WebSocket ping loop 启动

**文件**: `src/gate_trade/client/ws_manager.py`

**当前**: `_ping_loop` 定义了但从未启动

**在 `connect()` 方法中添加**:
```python
async def connect(self) -> None:
    ...
    self._ping_task = asyncio.create_task(self._ping_loop())
    ...

async def disconnect(self) -> None:
    self._running = False
    if self._ping_task and not self._ping_task.done():
        self._ping_task.cancel()
        try:
            await self._ping_task
        except asyncio.CancelledError:
            pass
    ...
```

**同时**在 `__init__` 初始化:
```python
self._ping_task: asyncio.Task | None = None
```

---

## 2. 第 2 批: 风控加固 (本周)

### 2.1 Web 面板默认绑定 127.0.0.1

**文件**: `scripts/run.py:88`

**改为**:
```python
async def _start_web_panel(bot: Bot, host: str = "127.0.0.1", port: int = <REDACTED_PORT>)
```

如果确实需要外部访问，通过配置文件 `web.host` 显式设置，或在 `run.py` 读取 `GATE_WEB__HOST` 环境变量。

**额外建议** — 添加简单 token 认证:
```python
# web/panel.py
from fastapi import HTTPException, Header

EXPECTED_TOKEN = os.getenv("GATE_WEB_TOKEN", "")

async def _auth(x_token: str = Header(None)):
    if EXPECTED_TOKEN and x_token != EXPECTED_TOKEN:
        raise HTTPException(403)
```

---

### 2.2 cancel_all 传入真实交易对

**文件**: `src/gate_trade/bot.py:330-334`

**当前**:
```python
await self._oe.cancel_all("")
```

**改为** — 从配置获取交易对:
```python
pair = self._cfg.exchange.pair  # 例如 "XMC_USDT"
await self._oe.cancel_all(pair)
```

如果 bot 配置中有多个交易对，遍历取消:
```python
for pair in self._cfg.exchange.pairs:
    await self._oe.cancel_all(pair)
```

---

### 2.3 load_state 容错处理

**文件**: `src/gate_trade/persistence/sqlite.py:191-197`

**当前**:
```python
def load_state(self) -> tuple[BotState, str | None]:
    row = self._db.execute("SELECT state, state_reason FROM bot_state LIMIT 1").fetchone()
    if row is None:
        return (BotState.INIT, None)
    return (BotState(row[0]), row[1])
```

**改为**:
```python
def load_state(self) -> tuple[BotState, str | None]:
    row = self._db.execute("SELECT state, state_reason FROM bot_state LIMIT 1").fetchone()
    if row is None:
        return (BotState.INIT, None)
    try:
        return (BotState(row[0]), row[1])
    except ValueError:
        logger.warning("unknown_persisted_state", state=row[0], defaulting_to="INIT")
        return (BotState.INIT, f"unknown state recovered: {row[0]}")
```

---

### 2.4 run.py 和 healthcheck.py 配置加载统一

**文件**: `scripts/run.py:59`, `scripts/healthcheck.py:27`

**当前 `run.py`**:
```python
config = GateConfig.from_yaml(CFG_PATH)
```

**改为与 healthcheck.py 一致**:
```python
config = GateConfig.from_yaml_merged(
    default_path=CFG_PATH,
    local_path=CFG_PATH.replace("default", "local"),  # config/local.yaml
)
```

或者反过来，让 `from_yaml` 内部自动合并 `local.yaml`（推荐）。

---

### 2.5 崩溃重启后风控状态恢复

**文件**: `src/gate_trade/bot.py` 初始化部分

**在 `start()` 或初始化流程中**:
```python
async def start(self) -> None:
    saved_state, reason = self._persistence.load_state()
    
    # 如果上次退出时处于紧急/冷却状态，要求人工确认
    if saved_state in (
        BotState.EMERGENCY,
        BotState.COOLDOWN_FLASH_CRASH,
        BotState.COOLDOWN_TOXIC,
        BotState.COOLDOWN_MAX_ORDERS,
    ):
        logger.warning(
            "recovery_from_unsafe_state",
            state=saved_state.value,
            reason=reason,
            action="manual_intervention_required",
        )
        # 发送告警
        await self._alerts.send_alert(
            f"Bot 从非安全状态恢复: {saved_state.value}, 原因: {reason}. 需要手动确认。"
        )
        # 如需自动恢复，至少等待 cooldown 时间
        await self._state_machine.transition(BotState.INIT)
    
    await super().start()
```

---

## 3. 第 3 批: 质量提升 (本月)

### 3.1 Bot 参数使用 Protocol 类型

**文件**: `src/gate_trade/bot.py:49-56`

**改为**:
```python
from gate_trade.market.contract import MarketData
from gate_trade.order.contract import OrderEngine
from gate_trade.price.contract import RefPriceEngine
from gate_trade.risk.contract import RiskManager
from gate_trade.state.contract import StateMachine
from gate_trade.strategy.contract import Strategy
from gate_trade.persistence.contract import Persistence
from gate_trade.client.contract import GateClient

class Bot:
    def __init__(
        self,
        cfg: GateConfig,
        market_data: MarketData | None = None,
        order_engine: OrderEngine | None = None,
        price_engine: RefPriceEngine | None = None,
        risk: RiskManager | None = None,
        state_machine: StateMachine | None = None,
        strategies: list[Strategy] | None = None,
        persistence: Persistence | None = None,
        client: GateClient | None = None,
        ...
    ):
```

---

### 3.2 解耦 Web Panel 对私有属性的访问

**文件**: `src/gate_trade/bot.py` — 添加公共属性

```python
class Bot:
    @property
    def market_data(self) -> MarketData:
        return self._md

    @property
    def order_engine(self) -> OrderEngine:
        return self._oe

    @property
    def state_machine(self) -> StateMachine:
        return self._sm

    @property
    def strategies(self) -> list[Strategy]:
        return self._strategies

    @property
    def events(self) -> BotEventLogger:
        return self._events
```

**文件**: `src/gate_trade/web/panel.py:136-151` — 改为使用公共属性

```python
md = bot.market_data
sm = bot.state_machine
oe = bot.order_engine
strategies = bot.strategies
events = bot.events
```

---

### 3.3 GateIoClient 和 WsManager 单元测试

**新建文件**: `tests/test_client/test_gate_client.py`

建议覆盖:
- `_parse_orderbook()` — 正常/空/格式异常的 API 响应
- `_parse_orders()` — 含/不含 client_order_id 的订单
- `_parse_balances()` — 零余额/多资产场景
- `_handle_api_error()` — 限速/认证失败/超时/未知错误

使用 `aioresponses` mock HTTP:
```python
import pytest
from aioresponses import aioresponses

@pytest.mark.asyncio
async def test_parse_orderbook():
    mock_raw = {"bids": [["0.95", "1000"]], "asks": [["1.05", "500"]]}
    client = GateIoClient(cfg, rate_limiter=MockRateLimiter())
    with aioresponses() as m:
        m.get("https://api.gateio.ws/api/v4/spot/order_book?limit=50&currency_pair=XMC_USDT",
              payload=mock_raw)
        ob = await client.fetch_orderbook("XMC_USDT", depth=50)
        assert ob.bids[0].price == 0.95
        assert ob.bids[0].size == 1000.0
```

---

### 3.4 _flatten 去重

**提取到 `config/schema.py`**:
```python
@staticmethod
def _flatten_dict(d: dict, parent_key: str = "", sep: str = "__") -> dict:
    items: dict = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items
```

**在 `config/watcher.py` 中导入**:
```python
from gate_trade.config.schema import GateConfig

# 替换 _flatten 为 GateConfig._flatten_dict
```

---

### 3.5 .gitignore 添加 data/

**文件**: `.gitignore`

添加:
```
data/
*.db
*.db-journal
*.db-wal
```

---

### 3.6 systemd 单元文件

**新建文件**: `systemd/gate-trade.service`

```ini
[Unit]
Description=Gate Trade Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=monero
WorkingDirectory=/home/monero/gate-trade
Environment="GATE_EXCHANGE__API_KEY="
Environment="GATE_EXCHANGE__API_SECRET="
ExecStart=/home/monero/gate-trade/.venv/bin/python scripts/run.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

**安装**:
```bash
mkdir -p ~/.config/systemd/user
cp systemd/gate-trade.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gate-trade.service
```

---

### 3.7 闪崩阈值可配置

**文件**: `config/default.yaml` — 添加:
```yaml
market:
  flash_crash_threshold: 0.05  # 5%, 可按交易对覆盖
```

**文件**: `src/gate_trade/market/market_data.py:200`

**改为**:
```python
@property
def flash_crash_threshold(self) -> float:
    return self._cfg.market.flash_crash_threshold  # 从配置读取

def _is_flash_crash(self, ...) -> bool:
    return (high - low) / high >= self.flash_crash_threshold
```

---

## 4. 测试补充清单

| 优先级 | 测试文件 | 覆盖内容 | 预估工作量 |
|--------|----------|----------|-----------|
| P0 | `tests/test_client/test_gate_client.py` | API 响应解析、错误处理 | 半天 |
| P0 | `tests/test_client/test_ws_manager.py` | WS 连接/重连/消息分发 | 一天 |
| P1 | `tests/test_bot_integration.py` | Bot 完整生命周期、多 tick | 一天 |
| P1 | `tests/test_config/test_integration.py` | Watcher + Guard 集成 | 半天 |
| P2 | `tests/test_alert/test_channels.py` | Telegram/Email 发送 | 半天 |
| P2 | `tests/test_scripts/test_run.py` | 启动流程验证 | 半天 |
| P3 | `tests/test_bot/test_long_running.py` | 模拟长时间运行 | 一天 |

---

> **Deepseek-v4-pro**  
> *2026-05-05*  
> *此文档为 AI 模型生成的改进建议，实施前请根据实际业务逻辑复核*
