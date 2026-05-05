# Gate Trade 三份审计综合报告

项目：`https://github.com/poolarge/gate-trade`

报告日期：2026-05-05 UTC

综合来源：

- `AUDIT_deepseek-v4-pro.md`
- `AUDIT_DS.md`
- `AUDIT_CODEX.md`

未纳入来源：

- `UNIFIED_PLAN_deepseek-v4-pro.md`
- 各类 improvement / plan 文档

签名：Codex · 风控拆解工程师

## 1. 执行摘要

Gate Trade 是一个 Python asyncio 架构的 Gate.io 现货单边积累和做市机器人。项目已有较好的模块化基础、Protocol 契约、Mock 测试、结构化日志、状态机、风控、策略、回放和 Web 面板。但三份审计一致认为：当前实现还不适合直接运行实盘。

核心原因是 live 路径的失败模式没有被收紧：

- WebSocket 启动和分发存在阻断性问题，行情可能进不了主循环。
- 风控没有拿到真实账户余额和交易所 open orders。
- shutdown 可能无法取消交易所残留挂单。
- Web 面板默认对外监听且没有认证。
- 订单提交前缺少足够的价格和 notional 安全边界。
- 部署、CI、依赖、测试和 GitHub 治理仍需补齐。

综合结论：项目可以继续迭代，但在完成 live 数据链路、账户状态风控、撤单保护、面板认证、订单安全和 CI 之前，不应使用真实 API key 运行 `--live`。

## 2. 审计范围与证据

本报告综合三份审计结果，并以当前本地仓库状态和已验证问题为优先依据。

主要证据包括：

- 本地代码审查。
- 远端 GitHub 报告同步后的脱敏报告。
- 本地 pytest / mypy / ruff / bandit / pip-audit 运行记录。
- dry-run 真实 SQLite 库验证。
- 本地 WebSocket server 复现 `connect()` 阻塞。
- systemd entrypoint 实际运行验证。

已确认的测试状态：

- 补装 `httpx` 后，`pytest` 可通过：`469 passed`。
- `mypy src scripts` 通过。
- `ruff check .` 存在 14 个 lint 问题。
- `bandit -r src scripts` 报 4 个 medium 和 17 个 low。
- `pip-audit --local` 只命中虚拟环境 pip，不是项目业务依赖。

## 3. 严重问题

### 3.1 live 模式 WebSocket 初始化阻塞

严重度：Critical

位置：

- `scripts/run.py`
- `src/gate_trade/client/ws_manager.py`

`_run_live()` 中执行 `await client.connect()`，而 `WsManager.connect()` 会进入长期 reader loop，导致后续 `LiveMarketData`、`LiveOrderEngine`、`Bot`、Web 面板和 feed tasks 不能继续初始化。

本地复现：

```text
connect_timed_out_blocking
```

影响：

- live 模式无法按预期启动。
- healthcheck 也可能卡住。
- 即使 WebSocket 连接成功，主交易循环也不会进入。

建议：

- `connect()` 只负责建立连接和启动后台 reader task。
- 增加 `wait_connected(timeout)`。
- `close()` 中取消 reader 和 ping task。
- 增加 WebSocket lifecycle 单元测试。

### 3.2 WebSocket 订阅分发 key 不匹配

严重度：Critical

位置：

- `src/gate_trade/client/ws_manager.py`

订阅注册 key 使用 channel + topic，例如：

```text
spot.order_book:BTC_USDT_20_100ms
```

但 reader 分发 key 使用 channel + event，例如：

```text
spot.order_book:update
```

结果是订阅队列收不到消息。

影响：

- `subscribe_orderbook()` 拿不到 order book。
- live 行情无法更新 `LiveMarketData`。
- orders / balances 订阅也可能存在同类问题。

建议：

- 定义 `SubscriptionKey(channel, topic)`。
- 从 Gate.io 消息中解析真实 pair/topic。
- 增加 order book、orders、balances 样例消息测试。

### 3.3 风控未使用真实账户余额

严重度：Critical

位置：

- `src/gate_trade/bot.py`
- `src/gate_trade/risk/risk_manager.py`

Bot tick 中固定传入空余额：

```python
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=[],
    mid_price=mid,
)
```

影响：

- 已持有的 base 资产不进入仓位上限。
- 持仓风险被低估。
- 本地订单缓存丢失时，风险进一步失真。

建议：

- live 模式维护 `AccountStateStore`。
- 启动时 REST 获取 balances 和 open orders。
- 周期性 reconcile。
- 账户状态 stale 时 fail closed。
- 风控只计算目标 pair 的 base currency。

### 3.4 订单价格缺少上下限保护

严重度：Critical

位置：

- `src/gate_trade/order/order_engine.py`

当前订单校验只检查 price 和 size 是否大于 0，没有基于参考价的价格偏离边界。

影响：

- 参考价异常、订单簿异常或攻击行情下，bot 可能提交极端价格订单。

建议：

- 新增 `OrderSafety` 模块。
- 基于 ref price、TWAP 或配置阈值限制价格偏离。
- 同时检查单笔 notional、最小交易金额、tick size 和 size precision。

### 3.5 shutdown 可能无法取消交易所挂单

严重度：Critical / High

位置：

- `src/gate_trade/bot.py`
- `src/gate_trade/order/order_engine.py`

shutdown 中调用：

```python
await self._oe.cancel_all("")
```

`LiveOrderEngine.cancel_all(pair)` 会按 pair 筛选本地 open orders。传空字符串通常匹配不到任何订单。

影响：

- 进程退出后交易所可能残留挂单。
- systemd 重启、异常退出时风险更高。

建议：

- Bot 保存当前 pair。
- shutdown 前 reconcile exchange open orders。
- 按 pair 和 bot tag 取消订单。
- 再次 fetch open orders 验证撤单结果。
- 残留时发 critical alert。

### 3.6 Web 面板默认对外暴露且无认证

严重度：High

位置：

- `scripts/run.py`
- `src/gate_trade/web/panel.py`

内嵌 Web 面板默认监听：

```python
host = "0.0.0.0"
```

且 API 无认证。

影响：

- 云主机上任何可访问端口的人都能查看交易状态、订单、策略、价格和风险状态。

建议：

- 默认改为 `127.0.0.1`。
- 增加 bearer token 或 basic auth。
- 公网访问必须经反向代理、TLS 和认证。
- README 明确禁止裸露公网端口。

## 4. 高风险问题

### 4.1 spike cooldown 可能永久卡住主循环

位置：

- `src/gate_trade/bot.py`
- `src/gate_trade/state/state_machine.py`

当 ref price spike protection 激活后，状态进入 `COOLDOWN_PRICE_SPIKE`。后续 tick 可能在开头因为状态不是 `RUNNING` 或 `IDLE` 直接返回，导致 cooldown 到期判断不可达。

建议：

- 主循环允许 cooldown 状态继续执行恢复检查。
- cooldown 到期后显式 transition 回 `RUNNING`。
- 增加 spike cooldown 到期恢复测试。

### 4.2 `_enter_cooldown()` 绕过 `transition()`

位置：

- `src/gate_trade/state/state_machine.py`

`_enter_cooldown()` 直接赋值 `self._state = kind`，绕过状态机转换矩阵。

建议：

- 改为调用 `transition(kind)` 或抽象出内部受控 transition。
- 保证非法状态转换不可发生。

### 4.3 WebSocket ping loop 未启动

位置：

- `src/gate_trade/client/ws_manager.py`

`_ping_loop()` 已定义但未被创建为 task。

建议：

- WebSocket 生命周期重构时启动 ping task。
- close 时取消 ping task。

### 4.4 风控状态崩溃重启后丢失

位置：

- `src/gate_trade/risk/risk_manager.py`
- `src/gate_trade/persistence/sqlite.py`

风控 halt、position breach、flash crash 等状态只在内存中。崩溃后重启可能绕过上一轮 unsafe state。

建议：

- 持久化 unsafe runtime state。
- 启动时如果上次状态是 `EMERGENCY` 或 `COOLDOWN_*`，要求人工确认或 preflight block。

### 4.5 配置加载路径不一致

位置：

- `scripts/run.py`
- `scripts/healthcheck.py`

`run.py` 和 `healthcheck.py` 的配置加载逻辑不同，可能导致健康检查通过但实际运行用的是另一份配置。

建议：

- 新增统一函数 `load_app_config()`。
- default yaml、optional local yaml、env overlay 统一处理。

### 4.6 SQLite schema 与 Web / 日报查询不一致

位置：

- `src/gate_trade/persistence/sqlite.py`
- `src/gate_trade/web/panel.py`
- `scripts/daily_report.py`

`fills` 表字段为 `fill_price`、`created_at_ms` 等，但 Web 和日报查询使用 `side`、`price`、`created_at`。

本地验证：

```text
OperationalError no such column: side
```

建议：

- 统一 fills schema。
- Web API 和 daily report 使用同一字段。
- README 中 SQLite 示例同步修正。

### 4.7 systemd unit 入口不存在

位置：

- `systemd/gate-trade.service`

unit 使用：

```text
python -m gate_trade.main
```

但仓库没有 `src/gate_trade/main.py`。

建议：

- 新增 `gate_trade.main`。
- 或将 systemd entrypoint 改为 `scripts/run.py`。

### 4.8 API 密钥残留风险

位置：

- `config/local.yaml`
- shell history / backup / snapshot

当前 Git 跟踪文件和当前可达历史已脱敏，但本机非跟踪文件、shell history、备份或旧快照中仍可能残留真实 key。

建议：

- 已泄露或疑似泄露的 Gate.io key 必须轮换。
- API key 禁止提现权限。
- 开启 IP 白名单。
- 检查 `.bash_history`、部署日志和备份。

## 5. 中风险问题

| 问题 | 来源 | 说明 |
|------|------|------|
| `load_state()` 遇到未知状态直接抛异常 | DS 两份 | 损坏 DB 会导致启动失败。 |
| 闪崩阈值硬编码 5% | DS 两份 | 不适合不同波动率交易对。 |
| Bot 构造参数大量 `Any` | DS 两份 | 丧失类型检查。 |
| Web 面板访问 bot 私有属性 | DS 两份 | 封装性差，后续维护困难。 |
| `.gitignore` 缺少 `data/` | DS 两份 | 容易误提交 DB 和日志。 |
| `_flatten` 重复 | DS 两份 | 配置工具函数重复。 |
| Markout pending 关闭时丢失 | DS 两份 | 关闭前未完成记录不会落盘。 |
| Smasher 模块未集成主循环 | AUDIT_DS | 已有检测模块但未参与 bot tick。 |
| TelegramChannel 使用同步 `urllib` | AUDIT_DS | 告警频繁时线程化调用不理想。 |
| alert webhook 配置虚接 | Codex | 配置非空时添加空 Telegram token。 |
| dev dependencies 缺 `httpx` | Codex | 新环境 pytest 收集失败。 |
| GitHub 无 CI / license / branch protection | Codex | 工程治理不足。 |

## 6. 低风险与维护项

以下问题不一定阻断实盘，但应进入 backlog：

- API 错误响应体完整写日志，可能包含账户信息。
- Web API 允许 query 参数指定 DB 路径，需限制固定路径。
- `save_fill()` 依赖单线程假设。
- `cancel()` 的 tag 清理可能残留引用。
- `place()` 与 `reconcile()` 存在竞态窗口。
- 策略连续 tick 可能生成重复订单。
- token bucket 等待超时目前作为硬错误处理。
- 文档、README、systemd、Makefile 的启动方式需要统一。

## 7. 项目优点

三份报告也共同认可项目已有较好的工程基础：

- Protocol / 契约式架构清晰。
- Mock 与实现分离，方便测试。
- 状态机设计较完整。
- 有风险管理、参考价格、策略、markout、toxic response、replay 等模块。
- 使用结构化日志。
- 有 SQLite 事件日志和 Web 面板。
- dry-run 和测试基础较好。
- 补装依赖后测试可全部通过。

这些优点说明项目不是推倒重来，而是应在现有模块边界上补齐 live 安全闭环。

## 8. 综合风险排序

### P0：立即阻断实盘风险

1. live preflight。
2. WebSocket connect 非阻塞化。
3. WS 订阅分发修复。
4. 真实 balances / open orders 接入风控。
5. shutdown 按 pair/tag 撤单。
6. Web panel 默认本地绑定和认证。

### P1：风控和订单安全

1. 订单价格上下限保护。
2. 单笔 notional 上限生效。
3. account snapshot stale fail closed。
4. cooldown 恢复语义修复。
5. 风控状态崩溃恢复策略。

### P2：监控、持久化和部署

1. fills schema 修复。
2. Web / 日报查询统一。
3. systemd entrypoint 修复。
4. alert webhook 真实接线。
5. Web panel 解耦私有属性。

### P3：测试和治理

1. `GateIoClient` / `WsManager` 单元测试。
2. `scripts/run.py` preflight 测试。
3. CI workflow。
4. ruff 修复。
5. `httpx` 加入 dev dependencies。
6. license、branch protection、Dependabot。

## 9. 实盘前最低门槛

以下条件全部满足前，不应运行真实 `--live`：

- live preflight 能阻断不安全启动。
- WebSocket lifecycle 和 dispatch 有测试并通过。
- 风控读取真实余额和交易所 open orders。
- 账户状态过期时禁止下单。
- 订单安全边界生效。
- shutdown 后交易所 open orders 为 0。
- Web 面板不裸露公网。
- systemd 入口可用。
- pytest、ruff、mypy、bandit 基线通过。
- 使用子账户、禁提现 API key、启用 IP 白名单。

## 10. 最终审计结论

Gate Trade 的架构方向是可继续投入的，但当前 live 交易路径存在多处实盘阻断问题。三份审计报告的共同结论是：项目的首要目标应从“策略功能更多”转为“失败模式更安全”。

建议下一阶段按小步快跑方式推进：

1. 先建立 live preflight 和 CI。
2. 再修 WebSocket 生命周期和分发。
3. 然后接入真实账户状态和风控。
4. 接着补订单安全、shutdown 撤单和状态恢复。
5. 最后修 Web 面板、持久化、部署和治理。

完成这些之前，不应使用真实 API key 进行无人值守实盘。

---

签名：Codex · 风控拆解工程师
