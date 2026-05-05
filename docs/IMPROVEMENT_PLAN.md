# Gate Trade 项目改进计划

**基准审计报告**: `audit/AUDIT_COMPREHENSIVE.md`（Deepseek-v4-pro + DS + Codex 三方合并审计）
**计划日期**: 2026-05-05
**开发原则**: 小步快跑 / 敏捷迭代 / 功能模块化 / 阶段性测试 / 易维护升级

---

## 目录

1. [架构总览与模块通信接口](#1-架构总览与模块通信接口)
2. [迭代 0: 禁止危险实盘路径](#2-迭代-0-禁止危险实盘路径)
3. [迭代 1: 安全与正确性修复](#3-迭代-1-安全与正确性修复)
4. [迭代 2: 风控与数据闭环](#4-迭代-2-风控与数据闭环)
5. [迭代 3: 质量与工程化](#5-迭代-3-质量与工程化)
6. [迭代 4: 集成与加固](#6-迭代-4-集成与加固)
7. [迭代 5: CI/部署/灰度发布](#7-迭代-5-cideploy灰度发布)
8. [模块内部工作流详细设计](#8-模块内部工作流详细设计)

---

## 1. 架构总览与模块通信接口

### 1.1 系统架构图

```
                        ┌─────────────────────────────┐
                        │       scripts/run.py         │
                        │   启动入口 / 依赖组装 / 生命周期  │
                        └─────────────┬───────────────┘
                                      │ 创建并注入
                                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            Bot (bot.py)                              │
│                       主循环编排器 (_tick 每 500ms)                    │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬─────────┘
   │      │      │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────────┐
│ MD  ││Ref  ││State││Risk ││OE   ││Strat││Mark ││Alert││Persist  │
│行情  ││价格  ││状态  ││风控  ││订单  ││策略  ││成交  ││告警  ││持久化   │
│     ││引擎  ││机    ││引擎  ││引擎  ││引擎  ││质量  ││     ││        │
└──┬──┘└─────┘└──┬──┘└──┬──┘└──┬──┘└─────┘└─────┘└─────┘└───────┘
   │             │      │      │
   │      ┌──────┘      │      │
   ▼      ▼             ▼      ▼
┌──────────────────────────────────────┐
│           GateIoClient              │
│     REST API + WebSocket 封装        │
│  ┌─────────────┐  ┌──────────────┐  │
│  │ gate_client  │  │  ws_manager   │  │
│  │ REST 调用    │  │  WS 连接管理  │  │
│  └─────────────┘  └──────────────┘  │
└──────────────────────────────────────┘
         │
         ▼
   Gate.io Exchange
```

### 1.2 模块间接口协议（Protocol）

所有模块间通信通过 Protocol 定义，由 `Bot.__init__` 依赖注入组装。以下是变更涉及的接口规范：

#### 1.2.1 WsManager → 各消费者的分发接口

```
┌──────────────────┐
│    WsManager     │
│                  │
│ subscribe(       │
│   channel: str,  │  订阅注册 key
│   topic: str,    │  格式: "spot.order_book:BTC_USDT_20_100ms"
│   queue_size=256 │
│ ) → asyncio.Queue │  返回异步队列，消费者从中取消息
│                  │
│ ── 内部分发规则 ──│
│ dispatch_key =   │  从消息 JSON 解析 channel + event 字段
│   "{channel}:    │  格式: "spot.order_book:update"
│    {event}"      │  匹配规则: handler key 的 channel:part 前缀匹配
│                  │
│ connect() → None │  非阻塞: 只建立连接 + 创建后台 reader/ping task
│ close() → None   │  关闭连接 + 取消后台 task
│ connected: bool  │  属性
└──────────────────┘
```

**修复后 dispatch_key 构建规则**: 从 Gate.io WS 消息中解析 `channel` 和 `event` 字段，组成 `"{channel}:{event}"`。对于 order_book 消息，event 为 `"update"`，handler 注册时使用完整订阅 key `"spot.order_book:BTC_USDT_20_100ms"`，分发时按 channel 前缀匹配 `"spot.order_book"`。

#### 1.2.2 Bot → RiskManager 接口

```
Bot._tick() 调用:
  risk.evaluate(
    open_orders: list[Order],     # 当前挂单列表
    balances: list[Balance],      # [修复] 真实余额，非空列表
    mid_price: float,             # 当前市场中间价
  )

RiskManager 返回状态:
  risk.halted: bool               # 是否已暂停
  risk.halt_reason: str           # 暂停原因 (position_limit|order_count|flash_crash)
  risk.can_trade: bool            # 是否可以交易
  risk.should_resume(): bool      # 是否可以恢复
  risk.position_limit_breached: bool
  risk.order_count_breached: bool
  risk.flash_crash_detected: bool
```

#### 1.2.3 Bot → StateMachine 接口

```
StateMachine:
  state: BotState                          # 当前状态
  sub_state: RunSubState | None            # 运行子状态

  transition(target: BotState) → bool      # 状态转换（验证转换矩阵）
  set_sub_state(target: RunSubState)       # 设置运行子状态

  # Cooldown 管理
  start_cooldown_fill(duration_ms)         # 成交冷却
  start_cooldown_cancel(duration_ms)       # 撤单冷却
  start_cooldown_self_trade(duration_ms)   # 自成交冷却
  start_cooldown_price_spike(duration_ms)  # 价格尖峰冷却

  # 查询
  can_place() → bool                       # 是否允许下单
  can_cancel() → bool                      # 是否允许撤单
  is_emergency() → bool                    # 是否紧急状态
  cooldown_remaining_ms() → int            # 剩余冷却时间
```

#### 1.2.4 Bot → OrderEngine 接口

```
OrderEngine:
  place(req: OrderRequest) → Order         # 下单（含验证+限速+价格对齐）
  cancel(order_id: str) → bool             # 撤单
  cancel_all(pair: str) → int              # [修复] pair 参数必填
  open_orders(pair?: str) → list[Order]    # 查询挂单
  reconcile(pair: str) → set[str]          # 对账（返回孤儿 tag 集合）
```

#### 1.2.5 Bot → AlertManager 接口

```
AlertManager:
  add(channel: AlertChannel)               # 添加告警通道
  critical(title, msg)                     # 致命告警
  warn(title, msg)                         # 警告
  info(title, msg)                         # 信息

AlertChannel (Protocol):
  async send(level: str, title: str, msg: str) → bool
```

#### 1.2.6 Config 加载接口

```
AppConfig:
  from_yaml_merged(base, local?) → AppConfig     # [统一] 加载 base + local 合并
  from_env_overlay(path) → AppConfig             # 加载 YAML + 环境变量覆盖

run.py 和 healthcheck.py 统一调用 from_yaml_merged()
```

#### 1.2.7 Persistence → Bot 接口

```
SqlitePersistence:
  open() → None                             # 打开数据库连接
  close() → None                            # 关闭连接
  save_order(order)                         # 保存订单
  save_fill(fill)                           # 保存成交
  save_state(state, timestamp)              # 保存状态
  load_state() → (BotState, float)          # [修复] 容错加载
  get_orders(pair?) → list[Order]           # 查询订单
  get_fills(pair?, start_ms?, end_ms?) → list[Fill]  # 查询成交
```

---

## 2. 迭代 0: 禁止危险实盘路径

**目标**: 修复 WebSocket 模块，使 bot 可以正常启动并完成连接，行情数据可到达策略层。
**测试策略**: 集成测试验证 WS 连接 → 订阅 → 分发的完整链路，逐模块验收。

### 2.0.0 WebSocket 基础设施集成测试（前置）

**工作流**:
1. 搭建 WS mock server（基于 `websockets` 或 `asyncio`）
2. 模拟 Gate.io WS 行为: 连接 → 接收 subscribe → 返回 order_book snapshot → 持续推送 update
3. 验证 WsManager 连接非阻塞、订阅注册、消息分发全链路
4. 验证 ping/pong 生命周期

**验收标准**: WS 集成测试通过，mock server 记录到的订阅消息格式正确，consumer 队列收到行情数据。

### 2.0.1 重构 `WsManager.connect()` 为非阻塞模式

**文件**: `src/gate_trade/client/ws_manager.py`
**问题**: `connect()` 调用 `_reconnect()` → `_reader_loop()`，后者是无限循环，阻塞主协程。

**内部工作流（修复后）**:

```
connect() 调用流程:
  1. self._running = True
  2. self._conn_task = asyncio.create_task(self._reconnect())
     - _reconnect() 在后台运行，负责连接建立 + 断线重连
     - 连接成功后创建 _reader_task 和 _ping_task
  3. 立即返回（非阻塞）

_reconnect() 内部流程:
  while self._running:
    1. 尝试 websockets.connect(url)
    2. 连接成功: self._conn = conn, attempt = 0
    3. await _resubscribe()  -- 重新发送所有订阅请求
    4. self._reader_task = asyncio.create_task(_reader_loop(conn))
    5. self._ping_task = asyncio.create_task(_ping_loop())
    6. 等待 _reader_task 完成（阻塞在 reader loop 直到断开）
    7. 断开后: self._conn = None, attempt++
    8. 检查 max_reconnect_attempts, 等待 backoff 后重试
```

**接口变更**: `connect()` 签名不变，行为从同步阻塞改为创建后台 task 后立即返回。新增 `self._conn_task`, `self._reader_task`, `self._ping_task` 三个内部属性用于生命周期管理。

**验收标准**: `connect()` 在 5 秒内返回；bot 主循环可正常进入 tick。

### 2.0.2 修正 WebSocket 分发 key 匹配逻辑

**文件**: `src/gate_trade/client/ws_manager.py`
**问题**: 订阅注册 key = `"spot.order_book:BTC_USDT_20_100ms"`，分发 key = `"spot.order_book:update"`，无法匹配。

**内部工作流（修复后）**:

```
消息分发流程 _reader_loop():
  对每条 WS 消息 msg:
    1. 解析 JSON
    2. 提取 channel = msg.get("channel", "")      # e.g. "spot.order_book"
    3. 提取 event = msg.get("event", "")          # e.g. "update"
    4. 提取 result.s = msg.get("result", {}).get("s", "")  # e.g. "BTC_USDT"

    5. 构造分发 key:
       - 精确匹配: f"{channel}:{result_s}"  → "spot.order_book:BTC_USDT"
       - 回退匹配: f"{channel}:{event}"     → "spot.order_book:update"
       - 前缀匹配: channel                  → "spot.order_book"

    6. handler 注册 key 也相应简化:
       subscribe(channel="spot.order_book", topic="BTC_USDT")
       → 内部存储 key = "spot.order_book:BTC_USDT"

    7. 按优先级匹配:
       for handler_key in handlers:
         if handler_key == exact_key or handler_key.startswith(channel):
           分发到对应队列
```

**接口变更**:
- `subscribe(channel, topic)` 的 topic 参数改为交易对标识（如 `"BTC_USDT"`），而非完整的 `"BTC_USDT_20_100ms"`
- 内部分发采用三级匹配: 精确(channel:pair) > 事件(channel:event) > 前缀(channel)

**验收标准**:
- `subscribe("spot.order_book", "BTC_USDT")` 注册后，实际 WS 推送的 order_book update 消息能到达 handler 队列
- 单元测试覆盖: 构造假消息验证分发正确

### 2.0.3 启动 ping loop task

**文件**: `src/gate_trade/client/ws_manager.py`
**问题**: `_ping_loop` 方法已定义但从未被 `create_task` 启动。

**修复**: 在 `_reconnect()` 连接成功后添加:
```python
self._ping_task = asyncio.create_task(self._ping_loop())
```

**接口**: 无新增接口，内部生命周期管理。`close()` 时取消 `_ping_task`。
**验收标准**: mock server 收到周期性 ping 消息（间隔 = `config.ws.ping_interval_sec`）。

### 2.0.4 添加 live 模式启动前 preflight 检查

**文件**: `scripts/run.py`（`_run_live` 函数）
**问题**: 无启动前检查，WS 未就绪时 bot 已开始 tick。

**内部工作流（新增 `_preflight` 函数）**:

```
_preflight(client, pair, timeout_sec=30) 流程:
  1. 日志: "preflight_start"
  2. await client.connect()                    # 非阻塞，后台重连
  3. 等待 WS 连接就绪:
     deadline = time.monotonic() + timeout_sec
     while not client.ws.connected:
       if time.monotonic() > deadline:
         raise PreflightError("WS connection timeout")
       await asyncio.sleep(0.5)
  4. 等待首批行情数据到达:
     while md.mid_price() <= 0:
       if time.monotonic() > deadline:
         raise PreflightError("No market data received")
       await asyncio.sleep(0.5)
  5. 获取余额:
     balances = await client.fetch_all_balances()
     if not balances:
       logger.warning("preflight_no_balances")
  6. 对账:
     orphans = await oe.reconcile(pair)
     if orphans:
       logger.warning("preflight_orphans", count=len(orphans))
  7. 日志: "preflight_passed", balances=len(balances), mid=md.mid_price()
```

**验收标准**: preflight 任一阶段失败时 bot 不启动并给出明确错误信息。

---

## 3. 迭代 1: 安全与正确性修复

**目标**: 修复实盘安全漏洞、逻辑错误和死锁。
**测试策略**: 每个修复至少一个单元测试。

### 3.1.1 API 密钥改为环境变量注入

**文件**: `config/local.yaml`, `scripts/run.py`
**问题**: API 密钥明文存储在配置文件中。

**工作流**:
1. `local.yaml` 中 `exchange.api_key` / `exchange.api_secret` 替换为占位符 `"REPLACE_ME"`
2. `run.py:build_config()` 已支持 `GATE_EXCHANGE__API_KEY` / `GATE_EXCHANGE__API_SECRET` 环境变量覆盖（`from_yaml` → `_apply_overrides`）
3. 添加启动检查: 若 `--live` 且 `api_key == "REPLACE_ME" or ""` 则报错退出
4. 文档更新: 移除任何包含真实密钥的命令示例

**验收标准**: `local.yaml` 中无真实密钥；live 模式下空密钥启动被拒绝。

### 3.1.2 Bot._tick() 传入真实 balances

**文件**: `src/gate_trade/bot.py:190`
**问题**: `risk.evaluate(balances=[])` 恒为空，仓位检查形同虚设。

**修复方案**:

```
Bot 新增属性:
  self._balances: list[Balance] = []      # 缓存最新余额

Bot 新增方法:
  async def _refresh_balances(self):
    if hasattr(self, '_client') and self._client:
      try:
        self._balances = await self._client.fetch_all_balances()
      except Exception:
        logger.warning("balance_fetch_failed")

_tick() 变更:
  # 每 N 个 tick（如 N=10，即 5 秒）刷新一次余额
  if self._tick_count % 10 == 0:
    await self._refresh_balances()

  # 5. Risk evaluation
  self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=self._balances,              # [修复] 使用真实余额
    mid_price=mid,
  )
```

**RiskManager._check_position 修复**: 按交易对拆分 base/quote 余额，而不是把所有非零余额相加。

```
_check_position(open_orders, balances, mid_price, pair) 修复后:
  1. 从 balances 中筛选货币与 pair 的 base 币种匹配的余额
     例如 pair="BTC_USDT" → base_currency = "BTC"
  2. base_held = 匹配余额的 total 值
  3. pending_buys = open_orders 中 BUY 侧的未成交金额
  4. total_notional = (base_held + pending_buys) * mid_price
  5. breached = total_notional > self._max_position
```

**接口变更**: `RiskManager.evaluate()` 新增可选参数 `pair: str`。

### 3.1.3 _enter_cooldown 调用 transition() 验证

**文件**: `src/gate_trade/state/state_machine.py:146`
**问题**: `_enter_cooldown` 直接赋值 `self._state = kind`，绕过转换矩阵。

**修复**:
```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
        return
    self.transition(kind)   # [修复] 走完整转换验证
    self._cooldown_until = time.monotonic() + duration_ms / 1000.0
    self._cooldown_type = kind
```

**验收标准**: 从 EMERGENCY 状态调用 `_enter_cooldown` 时抛出 `IllegalTransition` 或静默忽略。

### 3.1.4 订单价格边界保护

**文件**: `src/gate_trade/order/order_engine.py:254`
**问题**: `_validate` 仅检查 `price > 0`，无上下限保护。

**修复**:
```python
def _validate(self, req: OrderRequest, ref_price: float = 0.0) -> None:
    if req.price <= 0:
      raise ValueError(f"Invalid price: {req.price}")
    if req.size <= 0:
      raise ValueError(f"Invalid size: {req.size}")

    # [新增] 价格边界保护: ref_price ± 20%
    if ref_price > 0:
      max_price = ref_price * 1.20
      min_price = ref_price * 0.80
      if req.price > max_price or req.price < min_price:
        raise ValueError(
          f"Price {req.price} outside bounds [{min_price:.2f}, {max_price:.2f}]"
        )
```

**接口变更**: `OrderEngine.place(req)` 中的 `_validate` 新增 `ref_price` 参数。`Bot._refresh_orders()` 传入当前参考价格。

### 3.1.5 修复价格尖峰 cooldown 永久死锁

**文件**: `src/gate_trade/bot.py:158-179`
**问题**: 进入 `COOLDOWN_PRICE_SPIKE` 后，下个 tick 因状态检查 `state not in (RUNNING, IDLE)` 直接 return，cooldown 到期永远不可达。

**修复方案**:

```
_tick() 修复后的状态检查逻辑:
  1. EMERGENCY / SHUTDOWN → return (保持不变)
  2. [修复] COOLDOWN_* 状态 → 不 return，继续执行恢复检查:
     a. if self._sm.can_place():
          # cooldown 到期，显式 transition 回 RUNNING
          self._sm.transition(BotState.RUNNING)
          logger.info("cooldown_expired_resume")
        else:
          # 仍在 cooldown 中，看是否需要合规深度单
          if self._cooldown.compliance_depth_required():
            await self._place_compliance_orders()
          self._record_tick(mid, ref, strat_states)
          return
  3. RUNNING / IDLE → 正常执行

  # 原逻辑:
  # if self._sm.state not in (BotState.RUNNING, BotState.IDLE):
  #     return   <-- 这会跳过 cooldown 恢复检查

  # 修复为:
  if self._sm.is_emergency():
      return
  if self._sm.state == BotState.SHUTDOWN:
      return
  # COOLDOWN_* 状态允许继续执行以便检查到期恢复
```

**验收标准**: 模拟价格尖峰触发 cooldown → cooldown 到期后自动恢复 RUNNING。

---

## 4. 迭代 2: 风控与数据闭环

**目标**: 修复风控漏洞、关机撤单、配置一致性、数据一致性。
**测试策略**: 端到端场景测试 + 单元测试。

### 4.2.1 Web Panel 安全加固

**文件**: `scripts/run.py:88`, `src/gate_trade/web/panel.py`
**问题**: host="0.0.0.0" 且无认证。

**修复**:
1. `_start_web_panel()` 默认参数改为 `host="127.0.0.1"`；`0.0.0.0` 需显式传参或环境变量 `GATE_WEB_HOST` 控制
2. Panel 添加可选 token 认证中间件:
   ```
   请求 → check: GATE_WEB_TOKEN 环境变量是否设定了?
     - 未设定 → 直接放行 (本地开发)
     - 已设定 → 检查请求 Header: Authorization: Bearer <token>
       - 匹配 → 放行
       - 不匹配 → 401
   ```
3. **SQLite 路径遍历修复**: `api_fills(db=Query(...))` 校验 `db` 路径是否在 `data_dir` 内

### 4.2.2 shutdown cancel_all 传入正确 pair

**文件**: `src/gate_trade/bot.py:332`, `order_engine.py:151`
**问题**: `cancel_all("")` 空字符串无法匹配，挂单残留。

**修复**:
```
Bot._shutdown() 修复后流程:
  1. logger.info("bot_shutting_down")
  2. sm.transition(BotState.SHUTDOWN)
  3. if not self._dry_run:
     a. [新增] await oe.reconcile(self._pair)  -- 先对账获取交易所真实挂单
     b. await oe.cancel_all(self._pair)        -- [修复] 传入真实 pair
     c. [新增] 轮询确认: 每 1s 检查 open_orders(pair) 是否为空，最多等 10s
     d. if 仍有残留 → logger.warning("shutdown_unclosed_orders", count=N)
  4. await alert_info(...)
```

### 4.2.3 load_state 容错处理

**文件**: `src/gate_trade/persistence/sqlite.py:195`
**问题**: 未知状态值直接 `BotState(row[0])` 抛 ValueError。

**修复**:
```python
def load_state(self) -> tuple[BotState, float]:
    row = self._fetch_one("SELECT state, updated_at FROM bot_state ORDER BY updated_at DESC LIMIT 1")
    if row is None:
        return (BotState.INIT, 0.0)
    try:
        state = BotState(row[0])
    except ValueError:
        logger.warning("unknown_bot_state_db", raw=row[0])
        state = BotState.INIT    # [修复] 降级到 INIT
    return (state, row[1])
```

### 4.2.4 统一 run.py 和 healthcheck.py 配置加载

**文件**: `scripts/run.py:59`, `scripts/healthcheck.py`
**修复**: `run.py:build_config()` 替换 `from_yaml()` → `from_yaml_merged(config_path, local_config_path)`，默认 local 路径为 `config/local.yaml`。

**接口**: `build_config()` 新增 `local_config` 参数，默认值 `config/local.yaml`。

### 4.2.5 崩溃重启后风控状态恢复

**文件**: `src/gate_trade/bot.py` + `src/gate_trade/risk/risk_manager.py`
**问题**: `_halted` 等标志纯内存，崩溃后重启丢失。

**修复**:
```
Bot.__init__() 启动流程新增:
  1. if persistence:
       last_state, last_ts = persistence.load_state()
  2. if last_state in (BotState.EMERGENCY, BotState.COOLDOWN_FILL,
                        BotState.COOLDOWN_CANCEL, BotState.COOLDOWN_SELF_TRADE,
                        BotState.COOLDOWN_PRICE_SPIKE):
       logger.warning("recovery_risk_state", state=last_state.value)
       # 保持 cooldown 状态，等待人工确认或到期自动恢复
       sm._state = last_state
       sm._cooldown_until = last_ts + cooldown_duration_ms / 1000
       # [关键] 不自动恢复交易，等待 cooldown 到期
  3. if last_state == BotState.EMERGENCY:
       # EMERGENCY 需要人工确认
       logger.critical("recovery_emergency_requires_manual_clear")
       # 可选: 发送告警通知
```

### 4.2.6 闪崩检测阈值从配置读取

**文件**: `src/gate_trade/market/market_data.py:200`
**问题**: 硬编码 5% 阈值，配置中的 `flash_crash_threshold_pct` 未使用。

**修复**:
```python
class LiveMarketData:
    def __init__(self, flash_crash_threshold_pct: float = 5.0):
        ...
        self._flash_threshold = flash_crash_threshold_pct / 100.0

    def _detect_flash_crash(self) -> bool:
        ...
        return (high - low) / high >= self._flash_threshold  # [修复] 使用配置值
```

**接口变更**: `LiveMarketData.__init__()` 新增 `flash_crash_threshold_pct` 参数。`run.py` 中从 `config.risk.flash_crash_threshold_pct` 传入。

### 4.2.7 SQLite schema 与查询一致性修复

**文件**: `src/gate_trade/persistence/sqlite.py`, `src/gate_trade/web/panel.py`
**问题**: `fills` 表缺少 `side` 列，面板查询失败。

**修复**:
1. `sqlite.py` — `fills` 表新增 `side TEXT NOT NULL`, `price REAL NOT NULL`, `created_at REAL NOT NULL`
2. 数据库迁移: 对已有数据库执行 `ALTER TABLE fills ADD COLUMN side TEXT NOT NULL DEFAULT ''` 等
3. `panel.py` — 验证所有查询字段与 schema 一致

---

## 5. 迭代 3: 质量与工程化

**目标**: 代码质量提升、测试补齐、目录结构规范。
**测试策略**: 补齐缺失的单元测试，确保新增测试通过。

### 5.3.1 Bot 参数类型标注 Protocol

**文件**: `src/gate_trade/bot.py:49-66`
**修复**:
```python
from gate_trade.client.contract import GateClient
from gate_trade.market.contract import MarketData
from gate_trade.price.contract import RefPriceEngine
from gate_trade.order.contract import OrderEngine
from gate_trade.risk.contract import RiskManager
from gate_trade.state.contract import StateMachine
from gate_trade.strategy.contract import Strategy
from gate_trade.persistence.contract import Persistence
from gate_trade.alert.manager import AlertManager

def __init__(
    self,
    state_machine: StateMachine,
    market_data: MarketData,
    ref_price: RefPriceEngine,
    strategies: list[Strategy],
    order_engine: OrderEngine,
    risk_manager: RiskManager,
    ...
):
```

### 5.3.2 Web Panel 解耦私有属性访问

**文件**: `src/gate_trade/web/panel.py:136-151` → `src/gate_trade/bot.py`

**修复**: 在 `Bot` 类中新增公共只读属性:
```python
@property
def sm(self) -> StateMachine:
    return self._sm

@property
def md(self) -> MarketData:
    return self._md

@property
def oe(self) -> OrderEngine:
    return self._oe

@property
def ref(self) -> RefPriceEngine:
    return self._ref

@property
def risk(self) -> RiskManager:
    return self._risk
```

Panel 中 `bot._md` → `bot.md` 等。

### 5.3.3 GateIoClient / WsManager 单元测试补齐

**文件**: 新增 `tests/test_client/test_gate_client.py`, `tests/test_client/test_ws_manager.py`

**测试内容**:
- `GateIoClient`: HTTP 请求签名、响应解析、错误分类
- `WsManager`: 连接/断线/重连逻辑、订阅注册与分发、ping/pong

**Mock 策略**:
- HTTP: 使用 `aioresponses` mock
- WS: 使用内嵌 asyncio server 模拟 Gate.io WS 行为

### 5.3.4 _flatten 去重

**文件**: `src/gate_trade/config/schema.py` + `src/gate_trade/config/watcher.py`
**修复**: `watcher.py` 中的 `_flatten` 删除，改为 `from gate_trade.config.schema import AppConfig` 后调用 `AppConfig._flatten()`。

### 5.3.5 .gitignore 添加 data/

**文件**: `.gitignore`
**修复**: 添加 `data/` 行。

### 5.3.6 systemd unit 修正入口

**文件**: `systemd/gate-trade.service`
**修复**:
```
ExecStart=%h/gate-trade/.venv/bin/python scripts/run.py --live --pair BTC_USDT --data-dir %h/gate-trade/data
```

### 5.3.7 Smasher 集成到主循环

**文件**: `src/gate_trade/bot.py:_tick()`
**修复**: 在 `_tick()` 中第 7 步之后插入:
```
# 7.5 Smasher 检测
if self._smasher:
    attack = self._smasher.detect(
        open_orders=self._oe.open_orders(),
        order_book=self._md.book,
        recent_fills=self._markout.recent_completed(),
    )
    if attack.detected:
        await self._smasher.respond(attack, self._oe)
        self._events.record(BotEventType.ATTACK, type=attack.type.value)
```

### 5.3.8 TelegramChannel 改为 httpx

**文件**: `src/gate_trade/alert/manager.py:55`
**修复**: `urllib.request.urlopen` + `asyncio.to_thread` → `httpx.AsyncClient.post()`

### 5.3.9 Alert Webhook 配置接线修复

**文件**: `scripts/run.py:194`
**问题**: 添加空 token 的 TelegramChannel。

**修复**:
```python
alert = AlertManager()
if config.monitoring.telegram_bot_token and config.monitoring.telegram_chat_id:
    alert.add(TelegramChannel(
        bot_token=config.monitoring.telegram_bot_token,
        chat_id=config.monitoring.telegram_chat_id,
    ))
if config.monitoring.alert_webhook_url:
    alert.add(WebhookChannel(url=config.monitoring.alert_webhook_url))
```

**Schema 变更**: `MonitoringConfig` 新增 `telegram_bot_token`, `telegram_chat_id` 字段。

---

## 6. 迭代 4: 集成与加固

**目标**: 功能模块集成、边界条件加固、性能优化。

### 6.4.1 MarkoutRecorder 关闭时 flush pending

**文件**: `src/gate_trade/markout/recorder.py`
**修复**: 新增 `flush()` 方法，`Bot._shutdown()` 中调用 `self._markout.flush()`。

### 6.4.2 修复 alert 重连/状态恢复

**文件**: `src/gate_trade/bot.py` + `src/gate_trade/state/state_machine.py`

**风险控制状态持久化**:
```
Bot 启动时:
  1. 从 persistence 读取上次 bot_state
  2. 若为 EMERGENCY → 要求人工确认（通过 CLI 或环境变量 GATE_RESUME=1）
  3. 若为 COOLDOWN_* → 起始状态设为 IDLE，保留 cooldown
```

### 6.4.3 低风险问题批处理

| # | 修复 | 文件 |
|---|------|------|
| 6.1 | API 错误日志脱敏 | `gate_client.py:248` |
| 6.2 | save_fill 并发安全（加锁） | `sqlite.py:155` |
| 6.3 | cancel _by_tag 悬挂引用清理 | `order_engine.py:125` |
| 6.4 | place/reconcile 竞态窗口 | `order_engine.py:95` |
| 6.5 | 连续 tick 重复订单去重 | `strategy/depth_keeper.py` |
| 6.6 | 令牌桶等待超时降级为警告+跳过 | `rate_limiter.py:41` |

---

## 7. 迭代 5: CI/部署/灰度发布

**目标**: 工程基础设施完善，支持安全灰度上线。

### 7.5.1 GitHub Actions CI

**文件**: 新增 `.github/workflows/ci.yml`

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: pip install -e '.[dev]'
      - run: pytest -q
      - run: ruff check .
      - run: mypy src scripts
      - run: bandit -q -r src scripts
```

### 7.5.2 分支保护 + License + Dependabot

- 仓库设置: main 分支保护（require PR + CI pass）
- 添加 MIT License 文件
- 添加 `.github/dependabot.yml` 配置每周 pip 依赖扫描

### 7.5.3 pyproject.toml 补全 dev dependencies

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.30",
    "httpx>=0.28",
    "ruff>=0.8",
    "mypy>=1.14",
    "bandit>=1.8",
]
```

### 7.5.4 灰度发布流程

```
dry-run 7d (本地) → 100U 实盘 7d → 1,000U 实盘 7d → 10,000U 实盘 7d → 100,000U

每阶段升级前的 6 道 Gate Check:
  [ ] 469 个测试全绿
  [ ] ruff / mypy / bandit 零告警
  [ ] 前阶段 dry-run 日志无异常
  [ ] markout 毒性比率 < 30%
  [ ] 无未处理风控事件
  [ ] 运维确认配额充足
```

---

## 8. 模块内部工作流详细设计

### 8.1 Bot 主循环 (_tick) 完整工作流

```
┌──────────────────────────────────────────────────────────────────┐
│                      Bot._tick() 每秒 2 次                       │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ 1. 状态检查      │
                    │ EMERGENCY? → ret│
                    │ SHUTDOWN? → ret │
                    └────────┬────────┘
                             │ RUNNING/IDLE/COOLDOWN
                             ▼
                    ┌─────────────────┐
                    │ 2. 获取行情      │
                    │ mid = md.mid()  │
                    │ mid<=0? → ret   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 3. 更新参考价格  │
                    │ ref.update(bb,  │
                    │   ba, own_bids, │
                    │   own_asks)     │
                    │ ref=ref.price   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 4. 尖峰保护检查  │
                    │ spike_active?   │
                    │ → cooldown_spike│
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 5. 刷新余额      │
                    │ 每 10 tick 调用 │
                    │ fetch_balances()│
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 6. 风控评估      │
                    │ risk.evaluate(  │
                    │  orders,        │
                    │  balances,      │
                    │  mid, pair)     │
                    │ halted? → EMER  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 7. 更新策略      │
                    │ strat.update_   │
                    │   market(ref,   │
                    │   spike_active) │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 8. 下单门控      │
                    │ sm.can_place()  │
                    │ && cooldown.    │
                    │    can_place()  │
                    │ N→compliance?   │
                    └────────┬────────┘
                             │ Y
                             ▼
                    ┌─────────────────┐
                    │ 9. 刷新订单      │
                    │ 收集 desired    │
                    │ 逐一下单/对账   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 10. 更新markout │
                    │ markout.update  │
                    │ completed处理   │
                    │ toxic评估       │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 11. 子状态管理   │
                    │ PLACING/WAITING │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ 12. 记录 tick    │
                    │ events.record   │
                    │ (TICK, mid,     │
                    │  ref, spread,   │
                    │  toxic_level)   │
                    └─────────────────┘
```

### 8.2 WsManager 连接与消息分发完整工作流

```
┌──────────────────────────────────────────────────────────────────┐
│                        WsManager 生命周期                        │
└──────────────────────────────────────────────────────────────────┘

connect() ──→ asyncio.create_task(_reconnect())
                  │
                  ▼
          ┌───────────────────┐
          │  _reconnect()      │
          │                    │
          │  while running:    │
          │    try:            │
          │      connect(url)  │
          │      _resubscribe()│
          │      create_task   │
          │       _reader()    │
          │      create_task   │
          │       _pinger()    │
          │      wait reader   │
          │    except:         │
          │      backoff       │
          │      retry         │
          └───────────────────┘

消息分发 _reader_loop():

  收到 WS 消息 (JSON string)
    │
    ├──→ 解析失败? skip
    │
    ├──→ channel == "spot.pong"? skip
    │
    └──→ 构造 dispatch_key:
         │
         ├── f"{channel}:{result_s}"  (精确: pair 匹配)
         ├── f"{channel}:{event}"     (事件: update/subscribe)
         └── channel                   (前缀: 广播匹配)
              │
              ▼
         在 handlers dict 中查找匹配的队列
              │
              ├──→ 找到 → q.put_nowait(msg)
              │           queue_full?
              │            → pop oldest → put new
              │
              └──→ 未找到 → 丢弃 (未订阅的频道)

订阅注册 subscribe(channel, topic):

  key = f"{channel}:{topic}"
    e.g. "spot.order_book:BTC_USDT"
          │
          ├──→ self._handlers[key].append(asyncio.Queue(256))
          └──→ self._subscriptions.add(key)

重订阅 _resubscribe():

  for key in self._subscriptions:
    channel, topic = key.split(":", 1)
    send({channel, event: "subscribe", payload: [topic]})

Ping 心跳 _ping_loop():

  while running and connected:
    sleep(ping_interval_sec)  # 默认 15s
    try:
      send({"channel": "spot.ping"})
    except:
      return  # 连接已断开，退出让 _reconnect 处理
```

### 8.3 StateMachine 状态转换完整工作流

```
                    ┌──────┐
                    │ INIT │
                    └──┬───┘
                       │ transition(IDLE)
                       ▼
                    ┌──────┐
              ┌─────│ IDLE │◄──────────────────────────┐
              │     └──┬───┘                           │
              │        │ transition(RUNNING)            │
              │        ▼                               │
              │     ┌─────────┐                        │
              │     │ RUNNING │────────────────────────┤
              │     └────┬────┘                        │
              │          │                             │
              │     ┌────┴────────────────────┐        │
              │     │  Cooldown Transitions    │        │
              │     │  (via _enter_cooldown    │        │
              │     │   → transition())        │        │
              │     └────┬────────────────────┘        │
              │          │                             │
              │     ┌────┴──────────────────────┐      │
              │     ▼          ▼          ▼     │      │
              │ ┌────────┐┌──────────┐┌───────┐│      │
              │ │COOLDOWN││COOLDOWN  ││COOLDOWN│      │
              │ │_FILL   ││_CANCEL   ││_PRICE  │......│
              │ │        ││          ││_SPIKE  │      │
              │ └───┬────┘└────┬─────┘└───┬───┘│      │
              │     │          │           │    │      │
              │     └──────────┴───────────┘    │      │
              │          cooldown 到期           │      │
              │          transition(RUNNING)     │      │
              │         或 transition(IDLE) ─────┘      │
              │                                        │
              ├────────────────────────────────────────┘
              │
              │     ┌───────────┐
              ├─────│ EMERGENCY │  (risk halt / fatal)
              │     └─────┬─────┘
              │           │ transition(IDLE)
              │           │ (人工确认后)
              │           ▼
              │          IDLE
              │
              │     ┌──────────┐
              ├─────│ RECONNECT│  (WS disconnect)
              │     └─────┬────┘
              │           │ transition(RUNNING)
              │           │ (WS 恢复后)
              │           ▼
              │          RUNNING
              │
              │     ┌──────────┐
              └─────│ SHUTDOWN │  (graceful exit)
                    └──────────┘

转换矩阵 _VALID_TRANSITIONS:
  INIT          → {IDLE}
  IDLE          → {RUNNING, EMERGENCY, SHUTDOWN}
  RUNNING       → {IDLE, COOLDOWN_FILL, COOLDOWN_CANCEL,
                   COOLDOWN_SELF_TRADE, COOLDOWN_PRICE_SPIKE,
                   EMERGENCY, RECONNECT, SHUTDOWN}
  COOLDOWN_*    → {IDLE, RUNNING, EMERGENCY, SHUTDOWN}
  EMERGENCY     → {IDLE, SHUTDOWN}
  RECONNECT     → {IDLE, RUNNING, EMERGENCY, SHUTDOWN}
  SHUTDOWN      → {}  (终态)

Cooldown 恢复检查 (每 tick):
  if state in COOLDOWN_STATES:
    if cooldown_remaining_ms() <= 0:
      transition(RUNNING)  # 自动恢复
```

### 8.4 RiskManager 风控评估完整工作流

```
evaluate(open_orders, balances, mid_price, pair):

  ┌─ _check_position(open_orders, balances, mid_price, pair)
  │  1. 从 balances 筛选 base_currency (根据 pair 拆分)
  │  2. base_held = sum(b.total for b in matched_balances)
  │  3. pending_buys = sum(o.size - o.filled for BUY orders)
  │  4. total_notional = (base_held + pending_buys) * mid_price
  │  5. _position_breached = total_notional > _max_position
  │  6. if breached → _cap_breached = True
  │
  ├─ _check_order_count(open_orders)
  │  1. _order_count_breached = len(open_orders) >= _max_orders
  │
  └─ _check_flash_crash(mid_price)
     1. if mid > _peak_mid → _peak_mid = mid
     2. drop = (peak_mid - mid) / peak_mid
     3. _flash_crash = drop >= _flash_threshold

  汇总判断:
    if ANY(_position_breached, _order_count_breached, _flash_crash):
      if NOT _halted:
        _enter_halt()
          → _halted = True
          → _halt_reason = "position_limit|order_count|flash_crash"
          → logger.warning("risk_halt")
    else:
      if _halted:
        _clear_halt()
          → _halted = False
          → if _cap_breached:
              _enter_cap_cooldown()  # 启动 HIT_CAP_COOLDOWN
                → _cap_cooldown_until = now + cooldown_duration
                → _cap_breached = False
```

### 8.5 OrderEngine 下单完整工作流

```
place(req: OrderRequest) → Order:

  1. _validate(req, ref_price)
     ├── price <= 0? → ValueError
     ├── size <= 0? → ValueError
     ├── price > ref*1.20? → ValueError  [新增]
     └── price < ref*0.80? → ValueError  [新增]

  2. 价格对齐
     aligned = round(round(price / tick_size) * tick_size, 8)
     aligned_size = round(size, 6)

  3. 生成 client_order_id (tag)
     tag = req.client_order_id or f"gt:{pair}:{nonce}"

  4. 限速检查
     await rl.acquire()
     RateLimitExceeded? → 日志告警, raise

  5. 标记 pending
     self._pending[tag] = _Pending(tag, pair, side, price, size)

  6. 提交到交易所
     order = await client.submit_order(aligned_req)
     ExchangeError? → 清理 pending, raise

  7. 确认
     self._pending.pop(tag)
     self._open[order.order_id] = order
     self._by_tag[tag] = order.order_id
     return order

cancel_all(pair: str) → int:   [修复: pair 非空]

  1. 筛选本地挂单: oids = [id for id, o in _open.items() if o.pair == pair]
  2. if not oids → return 0
  3. count = await client.cancel_all_orders(pair)
  4. 清理本地状态: 遍历 oids 删除 _open 和 _by_tag
  5. return count

reconcile(pair: str) → set[str]:

  1. exchange_orders = await client.fetch_open_orders(pair)
  2. exchange_ids = {o.order_id for o in exchange_orders}
  3. local_ids = {id for id, o in _open.items() if o.pair == pair}
  4. orphans = exchange_ids - local_ids   # 交易所有，本地无
  5. stale = local_ids - exchange_ids     # 本地有，交易所无 → 清理
  6. 更新本地状态: 用 exchange_orders 覆盖
  7. return {o.client_order_id for o in exchange_orders if o.order_id in orphans}
```

### 8.6 配置加载统一工作流

```
AppConfig 加载层级 (优先级从高到低):

  ┌─────────────────────────────────────┐
  │ 3. 环境变量 GATE_EXCHANGE__API_KEY  │  ← 最高优先级
  ├─────────────────────────────────────┤
  │ 2. config/local.yaml (可选覆盖)     │  ← 本地敏感配置
  ├─────────────────────────────────────┤
  │ 1. config/default.yaml              │  ← 默认配置
  └─────────────────────────────────────┘

  统一入口: AppConfig.from_yaml_merged(default.yaml, local.yaml)
           → AppConfig.from_env_overlay() (环境变量覆盖)

  run.py 和 healthcheck.py 均使用 from_yaml_merged()
```

---

## 附录 A: 迭代执行顺序与依赖关系

```
Iter 0: WS基础设施 ──────┐
  ├── 2.0.0 WS集成测试   │ (前置依赖)
  ├── 2.0.1 非阻塞connect│──── 依赖 2.0.0
  ├── 2.0.2 分发key修复  │──── 依赖 2.0.0
  ├── 2.0.3 ping loop    │──── 依赖 2.0.1
  └── 2.0.4 preflight    │──── 依赖 2.0.1, 2.0.2
                         │
Iter 1: 安全+正确性 ─────┤
  ├── 3.1.1 API密钥      │ (独立)
  ├── 3.1.2 balances     │──── 依赖 Iter 0 (WS可用才能取余额)
  ├── 3.1.3 cooldown     │ (独立)
  ├── 3.1.4 价格边界     │ (独立)
  └── 3.1.5 死锁修复     │──── 依赖 3.1.3
                         │
Iter 2: 风控+数据闭环 ────┤
  ├── 4.2.1 Panel安全    │ (独立)
  ├── 4.2.2 cancel_all   │──── 依赖 Iter 0
  ├── 4.2.3 load_state   │ (独立)
  ├── 4.2.4 配置统一     │ (独立)
  ├── 4.2.5 崩溃恢复     │──── 依赖 4.2.3
  ├── 4.2.6 闪崩阈值     │ (独立)
  └── 4.2.7 SQLite修复   │ (独立)
                         │
Iter 3: 质量+工程化 ──────┤
  ├── 5.3.1~5.3.9        │ (相互独立，可并行)
                         │
Iter 4: 集成+加固 ────────┤
  └── 6.4.1~6.4.3        │──── 依赖 Iter 0-3
                         │
Iter 5: CI/部署 ──────────┤
  └── 7.5.1~7.5.4        │──── 依赖 Iter 0-4
```

## 附录 B: 每个迭代的测试策略

| 迭代 | 测试类型 | 覆盖率目标 | 关键测试 |
|------|---------|-----------|---------|
| Iter 0 | 集成测试 + 单元测试 | WS 模块 > 80% | WS 连接/分发/重连 |
| Iter 1 | 单元测试 | 每个修复 ≥ 1 个测试 | 状态转换矩阵/价格边界 |
| Iter 2 | 单元测试 + 场景测试 | 风控模块 > 85% | shutdown 撤单/崩溃恢复 |
| Iter 3 | 单元测试 + lint | 行覆盖率 > 80% | GateIoClient/WS 测试 |
| Iter 4 | 回归测试 | 全量 469 个测试 | 端到端场景 |
| Iter 5 | CI 自动执行 | CI 门禁 | ruff/mypy/bandit/pytest |

## 附录 C: 验收检查清单

每个迭代完成时:

- [ ] `pytest -q` 全量通过（含新增测试）
- [ ] `ruff check .` 零告警
- [ ] `mypy src scripts` 零错误
- [ ] `bandit -q -r src scripts` 零 high/medium
- [ ] dry-run 模式运行 60 秒无异常
- [ ] live 模式 preflight 通过（Iter 0 后）
- [ ] CHANGELOG.md 条目更新

---

> **基准**: 以 `audit/AUDIT_COMPREHENSIVE.md` 为准，上述计划覆盖审计报告中所有 FATAL/CRITICAL/HIGH 问题及大部分 MEDIUM/LOW 问题。每个迭代独立可交付、可测试、可回滚。
