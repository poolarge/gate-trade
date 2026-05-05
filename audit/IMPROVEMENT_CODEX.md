# Gate Trade 改进建议

项目：`https://github.com/poolarge/gate-trade`

建议对象：`/home/ubuntu/gate-trade-DeepSeek`

生成时间：2026-05-05 UTC

签名：Codex · Practical Risk Engineer

## 改进目标

这份建议的目标不是把项目一次性重写，而是把当前原型推进到“可以谨慎准备实盘”的工程状态。核心原则是：先阻断真实资金风险，再补齐 live 数据闭环，最后完善监控、部署和 GitHub 工程治理。

当前最重要的判断：

1. `--live` 在修复前应默认视为不可用。
2. 没有真实余额和交易所 open orders 的风控，不应允许下单。
3. shutdown 撤单必须成为强保证，而不是 best effort。
4. 监控面板不能裸露公网。
5. 每个实盘保护都要有自动化测试覆盖。

## P0：立即阻断实盘风险

### 1. 为 live 模式增加强制 preflight

建议在 `scripts/run.py` 的 live 分支中加入启动前检查，检查不通过直接退出。

必须检查：

- API key 和 secret 均存在。
- WebSocket 能在有限时间内连接。
- REST 能获取交易对 metadata。
- REST 能获取余额。
- REST 能获取当前 open orders。
- 本地风险参数合法。
- Web 面板未绑定公网，除非显式传入 `--web-host 0.0.0.0 --allow-public-panel`。

建议验收标准：

- 未配置 API key 时，`--live` 直接失败。
- `fetch_all_balances()` 失败时，`--live` 直接失败。
- `fetch_open_orders(pair)` 失败时，`--live` 直接失败。
- 预检失败不会创建任何订单。

### 2. live 模式默认禁用真实下单

建议增加第二层开关，例如：

```bash
python scripts/run.py --live --pair BTC_USDT --i-understand-real-money
```

当前只输入 `yes` 的交互确认不适合 systemd 或自动化环境，也不够明确。

建议验收标准：

- 只有 `--live` 不会下单。
- 必须同时给出强确认参数才会进入真实下单路径。
- systemd unit 中不能默认开启真实下单。

### 3. shutdown 必须按交易对撤单

当前 `cancel_all("")` 应改为传入真实 pair。更稳妥的做法是让 `Bot` 初始化时保存 `pair`，shutdown 时：

1. 先 reconcile 交易所 open orders。
2. 只取消当前策略 tag 或当前 pair 的订单。
3. 记录撤单数量。
4. 撤单失败时发 critical alert。

建议验收标准：

- live bot shutdown 时会调用 `cancel_all(pair)`。
- 当交易所残留订单存在时，shutdown 能发现并撤单。
- 撤单失败会进入 error event 和 alert。

## P1：修复 live 数据闭环

### 4. 重构 WebSocket 生命周期

`WsManager.connect()` 不应阻塞到 reader loop 结束。建议改成：

- `connect()` 建立连接并启动 reader task。
- `close()` 取消 reader task 和 ping task。
- reader task 异常要能被主循环感知。
- reconnect 成功后自动 resubscribe。

建议结构：

```python
async def connect(self) -> None:
    self._running = True
    self._reader_task = asyncio.create_task(self._run_forever())
    await self._connected_event.wait()
```

建议验收标准：

- `await client.connect()` 能在连接成功后返回。
- 断线后能自动重连。
- close 后没有悬挂 task。
- healthcheck 不会永久卡在 WS connect。

### 5. 修复 WebSocket 订阅分发 key

当前注册 key 和分发 key 不一致。建议按 channel 和 topic/pair 建索引。

建议：

- `subscribe("spot.order_book", "BTC_USDT_20_100ms")` 注册到 `spot.order_book:BTC_USDT_20_100ms`。
- reader 从消息中解析交易对或 topic，再分发到同一个 key。
- 对 `spot.orders` 和 `spot.balances` 分别处理。

建议验收标准：

- 使用 Gate.io order book 样例消息时，订阅队列能收到消息。
- `GateIoClient.subscribe_orderbook()` 能产出 `OrderBook`。
- 分发测试覆盖 `event=update`、`event=subscribe`、异常消息和队列满。

### 6. 接入真实余额和交易所 open orders

风控输入不能只使用本地 `_open`。建议 live 主循环维护一个 `AccountState`：

```text
balances
exchange_open_orders
last_balance_sync_ms
last_order_sync_ms
```

数据来源：

- 启动时 REST snapshot。
- 周期性 REST reconcile。
- WebSocket orders/balances 增量更新。

建议验收标准：

- 风控能看到目标 pair 的 base balance。
- 风控能看到交易所当前 open buy orders。
- 数据超过最大陈旧时间时禁止下单。
- reconcile 发现本地未知订单时，默认取消或进入 emergency，不能忽略。

## P2：补齐风控语义

### 7. 修正 position notional 计算

当前 `base_held = sum(b.total for b in balances if b.total > 0)` 会把所有币种都当作 base 资产。这在多币种账户中是不正确的。

建议：

- 从 `BTC_USDT` 拆出 `base=BTC`、`quote=USDT`。
- 只计算 `BTC` 的 total。
- pending buy 使用 order 剩余 size。
- pending sell 是否抵扣 position 应明确策略，而不是隐式忽略。

建议验收标准：

- BTC_USDT 只计算 BTC，不计算 ETH、SOL、USDT。
- pending buy 会增加潜在 position。
- 余额缺失时 fail closed，禁止交易。

### 8. 使用 `max_order_size_notional`

当前配置有 `max_order_size_notional`，但下单路径没有实际使用。建议在 `Bot._refresh_orders()` 或 `LiveOrderEngine.place()` 前做检查：

```text
req.price * req.size <= max_order_size_notional
```

建议验收标准：

- 超过单笔 notional 上限的订单不会提交。
- 被拒订单记录 risk event。
- 测试覆盖 buy/sell、边界等于上限、超过上限。

### 9. cooldown 到期后必须显式恢复

价格尖峰 cooldown 不应让 bot 卡在非 RUNNING 状态。建议：

- 主循环允许 cooldown 状态执行恢复检查。
- cooldown 到期后 transition 回 `RUNNING`。
- spike active 时停止下单，但继续记录 tick 和状态。

建议验收标准：

- spike 触发后进入 `COOLDOWN_PRICE_SPIKE`。
- cooldown 期间不下单。
- cooldown 到期后自动回到 `RUNNING`。
- 不需要重启进程即可恢复。

## P3：修监控、数据库和日报

### 10. 统一 SQLite schema

当前 `fills` 表和 Web/日报查询字段不一致。建议二选一：

方案 A：扩展 `fills` 表。

```sql
ALTER TABLE fills ADD COLUMN side TEXT;
ALTER TABLE fills ADD COLUMN price REAL;
ALTER TABLE fills ADD COLUMN created_at INTEGER;
```

方案 B：保持 `fills` 表不变，查询时 join `orders`。

建议优先方案 A，因为日报和面板天然需要 fill 侧的 side、price、time。

建议验收标准：

- `/api/fills` 返回真实数据。
- `/api/summary` 可用。
- `scripts/daily_report.py` 可用。
- README 中 SQLite 示例与真实 schema 一致。

### 11. Web 面板默认本地访问

建议修改默认值：

```python
async def _start_web_panel(bot, host="127.0.0.1", port=39120)
```

并添加 CLI 参数：

```bash
--web-host 127.0.0.1
--web-port 39120
--web-token ...
```

建议验收标准：

- 默认不监听公网。
- 未带 token 请求敏感 API 返回 401。
- README 明确说明公网访问必须使用反向代理、TLS 和认证。

### 12. 告警配置真实接线

当前 `alert_webhook_url` 没有真正用于发送告警。建议拆分配置：

```yaml
monitoring:
  telegram_bot_token: ""
  telegram_chat_id: ""
  webhook_url: ""
  email:
    smtp_host: ""
    smtp_port: 587
    username: ""
    password: ""
    to: ""
```

建议验收标准：

- 配置不完整时启动 warning。
- critical alert 可在测试 channel 中验证。
- 风控 halt、fatal error、shutdown 撤单失败都有告警。

## P4：部署和 GitHub 工程治理

### 13. 修 systemd unit

当前 unit 指向不存在的 `gate_trade.main`。建议新增正式入口：

```text
src/gate_trade/main.py
```

或者将 unit 改为：

```text
ExecStart=%h/gate-trade/.venv/bin/python %h/gate-trade/scripts/run.py --pair BTC_USDT
```

建议验收标准：

- `systemctl --user start gate-trade` 能启动 dry-run。
- live unit 必须显式独立，不和 dry-run 共用。
- journal 中能看到启动参数和模式。

### 14. 增加 GitHub Actions CI

建议新增 `.github/workflows/ci.yml`：

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install -U pip
      - run: pip install -e '.[dev]' httpx bandit pip-audit
      - run: pytest -q
      - run: ruff check .
      - run: mypy src scripts
      - run: bandit -q -r src scripts
      - run: pip-audit
```

建议验收标准：

- PR 必须通过 CI。
- `main` 开启 branch protection。
- ruff、mypy、pytest、bandit 都是必跑项。

### 15. 补齐 dev dependencies

当前测试需要 `httpx`，但 `pyproject.toml` 没声明。建议加入：

```toml
[project.optional-dependencies]
dev = [
  "httpx>=0.28",
]
```

建议验收标准：

- 全新环境只执行 `pip install -e '.[dev]'` 后即可运行测试。
- 不需要手工补装测试依赖。

### 16. 增加 license 和仓库治理文件

建议增加：

- `LICENSE`
- `.github/dependabot.yml`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/pull_request_template.md`
- `SECURITY.md`

建议验收标准：

- GitHub community profile health 明显提高。
- 安全问题有报告入口。
- 依赖更新有自动提醒。

## 推荐实施顺序

### 第 1 天：关掉危险路径

- live preflight。
- Web 面板默认 localhost。
- shutdown 按 pair 撤单。
- systemd entry 修正。

完成后，dry-run 应保持可运行，live 在不满足预检时应明确失败。

### 第 2 天：修 live 行情和账户状态

- WsManager 后台 reader task。
- WebSocket 分发 key 修复。
- orderbook/orders/balances parser 测试。
- 账户状态 snapshot 和周期 reconcile。

完成后，live 可以稳定拿到行情、余额和 open orders，但仍建议先禁止真实下单。

### 第 3 天：修风控和数据模型

- position notional 只计算目标 base。
- max order size notional 生效。
- cooldown 自动恢复。
- fills schema 修正。
- Web API 和日报修正。

完成后，风险状态、数据库和面板应一致。

### 第 4 天：CI 和上线准备

- GitHub Actions。
- branch protection。
- Dependabot 或 pip-audit。
- README 部署说明更新。
- 增加 live runbook。

完成后，再考虑小额度实盘灰度。

## 灰度实盘建议

实盘前建议设置硬性限制：

- 只使用子账户。
- API key 只授予现货交易权限，不授予提现权限。
- 初始资金限制在可接受损失范围内。
- `max_position_notional` 设置为极小值。
- `max_order_size_notional` 设置为极小值。
- 开启交易所端 IP 白名单。
- 首次实盘只运行 5 到 10 分钟。
- 实盘期间人工盯盘，确认 shutdown 后交易所无残留挂单。

灰度验收清单：

- 启动前 open orders 为 0。
- 启动后订单数量不超过配置上限。
- 风控 halt 能停止下单。
- shutdown 后 open orders 回到 0。
- 面板只能从受控网络访问。
- 日报和 event log 能复盘完整行为。

## 最小可合并 PR 切分

建议不要用一个大 PR 解决所有问题。推荐切成这些小 PR：

1. `fix-live-ws-lifecycle`
2. `fix-ws-dispatch-routing`
3. `add-live-preflight`
4. `fix-shutdown-cancel-pair`
5. `wire-account-balances-into-risk`
6. `enforce-order-notional-limit`
7. `fix-spike-cooldown-resume`
8. `secure-web-panel-defaults`
9. `fix-fills-schema-and-reporting`
10. `add-ci-and-dev-deps`

每个 PR 都应包含测试和一段简短风险说明。

## 最终建议

这个项目的方向是可以继续推进的，但实盘交易机器人不能只依赖“策略看起来合理”。真正需要优先完成的是失败模式设计：连接失败、余额失败、撤单失败、状态过期、面板暴露、配置误用时，系统必须默认停止下单。

把这些边界修好后，再讨论策略收益率、盘口细节和参数优化才有意义。

---

签名：Codex · Practical Risk Engineer

备注：这份建议偏工程落地和实盘安全，不追求一次性重构，而是按风险优先级拆解可验证改动。
