# Gate Trade 代码审计结论

审计对象：`https://github.com/poolarge/gate-trade`

本地审计目录：`/home/ubuntu/gate-trade-DeepSeek`

审计时间：2026-05-05 UTC

审计签名：Codex

## 总结

当前版本不建议直接运行实盘。项目的 dry-run 和单元测试基础较完整，但 live 路径存在多处实盘级风险：WebSocket 启动和订阅分发不可靠、真实余额没有进入风控计算、退出时可能无法取消交易所挂单、监控面板默认对外暴露且没有认证。

优先级建议：

1. 先修 live WebSocket 启动、订阅分发和行情进入主循环的问题。
2. 接入真实余额与真实 open orders，补齐风控闭环。
3. 修复 shutdown 按交易对撤单，避免进程退出后残留挂单。
4. 将 Web 面板默认绑定改为 `127.0.0.1`，并加入认证。
5. 修复 SQLite schema 与面板、日报查询不一致的问题。
6. 补齐 CI、dev 依赖、license、分支保护和 GitHub 安全扫描。

## 高风险问题

### 1. live 模式 WebSocket 初始化会阻塞，bot 后续不会启动

位置：

- `scripts/run.py:156`
- `src/gate_trade/client/ws_manager.py:36`

`scripts/run.py` 在 live 初始化阶段执行：

```python
await client.connect()
```

但 `WsManager.connect()` 会直接进入 `_reconnect()`，再进入 `_reader_loop()`，这是一个长期运行的读循环。结果是 `_run_live()` 后面的 `LiveMarketData`、`LiveOrderEngine`、`Bot`、Web 面板和 feed tasks 都不会继续初始化。

本地复现结果：

```text
connect_timed_out_blocking
```

影响：

- live 模式无法按预期启动。
- 健康检查中的 WebSocket connect 也可能长期阻塞。
- 即使 WebSocket 连接成功，主交易循环也不会进入。

建议：

- `WsManager.connect()` 只建立连接并创建后台 reader task。
- 增加 `asyncio.Task` 生命周期管理和异常传播。
- `close()` 中取消 reader/ping task，并等待清理完成。

### 2. WebSocket 订阅分发 key 不匹配，行情和订单更新收不到

位置：

- `src/gate_trade/client/ws_manager.py:48`
- `src/gate_trade/client/ws_manager.py:121`

订阅注册 key 形如：

```text
spot.order_book:BTC_USDT_20_100ms
```

但 reader 分发 key 形如：

```text
spot.order_book:update
```

本地验证：

```text
handler_keys ['spot.order_book:BTC_USDT_20_100ms']
dispatch_key spot.order_book:update
registered_for_dispatch False
```

影响：

- `subscribe_orderbook()` 拿不到消息。
- live 行情无法进入 `LiveMarketData`。
- 订单流、余额流也可能存在同类分发问题。

建议：

- 按 Gate.io 实际消息结构解析 `channel`、`event`、`result.s` 或 payload 中的交易对。
- 订阅表建议按 `channel + pair/topic` 建索引，而不是使用 `event` 替代 topic。
- 为 order book、orders、balances 分别加集成级单测，覆盖真实消息样例。

### 3. 实盘风控没有接入真实余额，持仓上限基本失效

位置：

- `src/gate_trade/bot.py:188`
- `src/gate_trade/risk/risk_manager.py:141`

主循环调用风控时固定传入空余额：

```python
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=[],
    mid_price=mid,
)
```

而 `LiveRiskManager` 的持仓上限依赖 `balances` 计算已有 base 持仓：

```python
base_held = sum(b.total for b in balances if b.total > 0) or 0.0
```

影响：

- 已持有的 BTC、ETH、SOL 等 base 资产不会进入持仓上限计算。
- 只有本地 open buy orders 被计入，真实账户风险被低估。
- 如果本地订单状态丢失，风险会进一步低估。

建议：

- live 模式定期调用 `fetch_all_balances()` 或订阅余额流。
- 按交易对拆分 base/quote，只计算目标 pair 的 base 资产，不应把所有非零余额相加。
- 风控输入应包含 exchange open orders，不能只依赖本地缓存。

### 4. shutdown 不会取消实盘挂单

位置：

- `src/gate_trade/bot.py:330`
- `src/gate_trade/order/order_engine.py:151`

shutdown 中调用：

```python
await self._oe.cancel_all("")
```

但 `LiveOrderEngine.cancel_all(pair)` 会按 pair 筛选本地 open orders：

```python
oids = [oid for oid, o in self._open.items() if o.pair == pair]
```

传空字符串通常匹配不到任何订单，因此不会调用交易所撤单。

影响：

- 进程退出、异常退出或 systemd 重启时，交易所可能保留挂单。
- 对做市机器人来说，这是实盘资金风险。

建议：

- `Bot` 保存当前交易对并在 shutdown 时传入真实 pair。
- shutdown 前先 reconcile exchange open orders，再按 tag 或 pair 撤单。
- 对 `cancel_all` 加测试：live bot shutdown 必须传入交易对并触发撤单。

### 5. Web 面板默认监听所有网卡且没有认证

位置：

- `scripts/run.py:88`
- `src/gate_trade/web/panel.py:21`
- `src/gate_trade/web/panel.py:129`

内嵌 Web 面板默认：

```python
host: str = "0.0.0.0"
```

FastAPI app 没有任何认证或访问控制。`/api/snapshot` 暴露 bot 状态、订单列表、策略状态、价格与风险状态。

影响：

- 在云主机或公网环境运行时，任何可访问该端口的人都能查看交易状态。
- 虽然目前没有直接下单 API，但运行状态、订单价格、策略行为属于敏感信息。

建议：

- 默认 host 改为 `127.0.0.1`。
- 如需远程访问，使用反向代理加 TLS 与认证。
- 至少增加 bearer token 或 basic auth。
- README 中明确禁止裸露公网端口。

## 中风险问题

### 6. 价格尖峰 cooldown 可能让主循环永久跳过交易逻辑

位置：

- `src/gate_trade/bot.py:158`
- `src/gate_trade/bot.py:179`
- `src/gate_trade/state/state_machine.py:127`

当 ref price spike protection 激活时，bot 进入 `COOLDOWN_PRICE_SPIKE`。下一 tick 开头会因为状态不是 `RUNNING` 或 `IDLE` 直接返回：

```python
if self._sm.state not in (BotState.RUNNING, BotState.IDLE):
    return
```

这会导致后面的 `self._sm.can_place()` 不再执行，cooldown 到期判断不可达。

影响：

- 一次尖峰保护后，bot 可能卡在 cooldown 状态。
- 策略不会恢复，除非外部重启或手动重置状态。

建议：

- 主循环应允许 cooldown 状态继续执行恢复检查。
- cooldown 到期后显式 transition 回 `RUNNING`。
- 增加 spike cooldown 到期恢复测试。

### 7. SQLite schema 与 Web 面板、日报查询不一致

位置：

- `src/gate_trade/persistence/sqlite.py:31`
- `src/gate_trade/web/panel.py:207`
- `scripts/daily_report.py:39`

`fills` 表定义字段：

```text
order_id, pair, fill_price, filled_size, created_at_ms
```

但面板和日报查询使用：

```text
side, price, created_at
```

本地用 dry-run 生成真实库后验证：

```text
OperationalError no such column: side
OperationalError no such column: side
```

影响：

- `/api/fills` 和 `/api/summary` 可能报错。
- `scripts/daily_report.py` 无法针对当前 schema 正常工作。
- README 中的 SQLite 查询示例也与实际表结构不一致。

建议：

- 在 fills 表中保存 side、price、created_at，或修正查询 join orders 表。
- 统一使用 `created_at_ms`，避免秒和毫秒混用。
- 为 Web API 和 daily report 增加基于真实 schema 的测试。

### 8. systemd unit 启动入口不存在

位置：

- `systemd/gate-trade.service:17`

unit 中配置：

```text
ExecStart=%h/gate-trade/.venv/bin/python -m gate_trade.main
```

但仓库没有 `src/gate_trade/main.py`。本地验证：

```text
No module named gate_trade.main
```

影响：

- 按 README 或 systemd 文件部署会启动失败。
- systemd 会不断 restart，产生误导性运行状态。

建议：

- 改成 `ExecStart=%h/gate-trade/.venv/bin/python %h/gate-trade/scripts/run.py ...`。
- 或新增 `gate_trade.main` 模块作为正式入口。
- 同步 README、Makefile、systemd unit 的启动方式。

### 9. alert webhook 配置没有真正接线

位置：

- `scripts/run.py:194`
- `src/gate_trade/alert/manager.py:35`

当 `monitoring.alert_webhook_url` 非空时，代码添加的是空 token 的 Telegram channel：

```python
alert.add(TelegramChannel(bot_token="", chat_id=""))
```

影响：

- 用户以为配置了告警，实际不会发送。
- 风控 halt、fatal error、shutdown 等关键告警不可达。

建议：

- 明确配置项结构：Telegram token/chat_id、generic webhook、email 分开建模。
- 启动时校验告警配置，不完整时 warning 或 fail-fast。

## 工程与供应链问题

### GitHub 配置

GitHub API 检查结果：

- 公开仓库。
- 默认分支：`main`。
- `main` 未启用分支保护。
- 无 GitHub Actions workflows。
- 无 open issues 或 pull requests。
- 未声明仓库 license。
- community profile health：14%。

建议：

- 增加 `.github/workflows/ci.yml`，至少运行 pytest、ruff、mypy、bandit。
- 开启分支保护，要求 CI 通过后合并。
- 增加 Dependabot 或 pip-audit 定期扫描。
- 明确 license。
- 增加 issue template 和 PR template。

### dev 依赖缺失

初次运行 `pytest` 失败：

```text
RuntimeError: The starlette.testclient module requires the httpx package to be installed.
```

补装 `httpx` 后：

```text
469 passed in 3.39s
```

建议：

- 将 `httpx` 加入 `pyproject.toml` 的 dev dependencies。

### lint 与安全扫描结果

验证结果：

```text
pytest: 469 passed
mypy src scripts: Success, no issues found
ruff check .: 14 errors
bandit -r src scripts: 4 medium, 17 low
pip-audit --local: pip 24.0 CVE only
```

`ruff` 主要问题：

- import 排序。
- 测试中未使用变量。
- 测试变量名 `l` 过于模糊。

`bandit` 中等问题：

- Web 面板默认绑定 `0.0.0.0`。
- SQL 字符串拼接。

`pip-audit` 只命中虚拟环境自带 `pip 24.0`，不是项目声明业务依赖。

## 修复路线

### 第一阶段：禁止危险实盘路径

目标：避免误跑实盘造成真实资金风险。

- live 启动前增加完整 preflight。
- WebSocket 未进入可用状态时禁止下单。
- balances 未成功获取时禁止下单。
- exchange open orders 未 reconcile 时禁止下单。
- shutdown 必须按 pair 取消挂单。
- Web 面板默认只绑定 localhost。

### 第二阶段：修 live 数据闭环

目标：让行情、订单、余额进入同一个可信状态模型。

- 重构 `WsManager` 为后台 reader task。
- 修正订阅分发 key。
- 加入 ping task。
- 用真实 Gate.io WS 样例补充 parser 测试。
- 定期 REST reconcile open orders。
- 接入 balance snapshot 或余额 WS。

### 第三阶段：修监控与持久化

目标：让面板、日报、数据库 schema 一致。

- 修 `fills` schema 或查询 join。
- 修 `/api/fills` 和 `/api/summary`。
- 修 `scripts/daily_report.py`。
- README 中的 SQLite 查询示例同步更新。

### 第四阶段：CI 与发布工程

目标：让未来改动不会重新引入实盘风险。

- 增加 GitHub Actions。
- 增加 branch protection。
- 增加 `pip-audit` 或 Dependabot。
- 增加 license 和贡献模板。
- systemd unit 改成真实入口。

## 审计命令记录

```bash
git clone https://github.com/poolarge/gate-trade.git .
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pip install httpx bandit pip-audit
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy src scripts
.venv/bin/bandit -q -r src scripts
.venv/bin/pip-audit --local
.venv/bin/python scripts/run.py --pair BTC_USDT --duration 2 --data-dir /tmp/gate-trade-audit-data
.venv/bin/python -m gate_trade.main
```

## 最终判断

该仓库适合作为策略原型和测试骨架继续迭代，但当前实现还没有达到实盘交易机器人的最低安全门槛。下一步应优先修复 live 数据流、真实账户风控、撤单保护和面板访问控制；这些问题修完前，不应使用真实 API key 运行 `--live`。

---

签名：Codex
