# Gate Trade 统一改进计划

**审计来源**: Deepseek-v4-pro + Codex  
**日期**: 2026-05-05  
**项目**: `https://github.com/mudyman/gate-trade`  
**状态**: 不建议直接运行实盘，先完成本计划

---

## 两个审计的发现对照

| 问题 | Deepseek-v4-pro | Codex | 严重度 |
|------|:---:|:---:|:---:|
| local.yaml 明文 API 密钥 | ✅ | ✅ | CRITICAL |
| Bot._tick 风控传入空 balances | ✅ | ✅ | CRITICAL |
| 订单价格无上下界保护 | ✅ | — | CRITICAL |
| _enter_cooldown 绕过 transition() 验证 | ✅ | — | CRITICAL |
| WsManager connect() 阻塞主流程 | ✅ | ✅ | CRITICAL |
| WS 订阅分发 key 不匹配 | — | ✅ | CRITICAL |
| cooldown 可能让主循环永久卡死 | — | ✅ | CRITICAL |
| cancel_all("") 撤单失败 | ✅ | ✅ | HIGH |
| Web 面板默认 0.0.0.0 无认证 | ✅ | ✅ | HIGH |
| SQLite fills schema 与面板/日报查询不一致 | — | ✅ | HIGH |
| systemd unit 入口不存在 | — | ✅ | HIGH |
| alert webhook 配置虚接 | — | ✅ | MEDIUM |
| run.py/healthcheck 配置加载不一致 | ✅ | — | HIGH |
| load_state 对未知状态抛异常 | ✅ | — | MEDIUM |
| Bot 参数类型为 Any | ✅ | — | MEDIUM |
| Web panel 直接访问私有属性 | ✅ | — | MEDIUM |
| GateIoClient / WsManager 零测试 | ✅ | — | MEDIUM |
| _flatten 重复 | ✅ | — | LOW |
| 闪崩阈值硬编码 | ✅ | — | MEDIUM |
| 风控状态崩溃重启后丢失 | ✅ | — | HIGH |
| GitHub 缺少 CI/branch protection/license | ✅ | ✅ | MEDIUM |
| dev dependencies 缺失 httpx | — | ✅ | MEDIUM |
| ruff 14 errors, bandit 4 medium | — | ✅ | MEDIUM |

✅ = 该审计发现了此问题 &nbsp;&nbsp; — = 未提及

---

## 统一修复路线

### P0: 阻断实盘风险 (第 1-2 天)

目标：即使误输入 `--live`，也不会造成资金损失。

#### P0-1: live preflight 强制检查

**文件**: `scripts/run.py`（新增 `_preflight()` 函数）

检查清单：
- [x] API key/secret 存在且非空
- [x] WS 连接在超时内成功
- [x] REST 可获取交易对 metadata
- [x] REST 可获取余额
- [x] REST 可获取当前 open orders
- [x] 风险参数合法（max_position > 0 等）
- [x] Web panel 未绑定公网（除非显式传入 `--allow-public-panel`）

任一失败 → 退出，不创建任何订单。

#### P0-2: live 模式双重确认

**文件**: `scripts/run.py`

```bash
# 只传 --live 拒绝启动
python scripts/run.py --live --pair BTC_USDT

# 必须同时传强确认参数
python scripts/run.py --live --pair BTC_USDT --confirm-real-money
```

#### P0-3: 订单价格上下界保护

**文件**: `src/gate_trade/order/order_engine.py:254-261`

基于参考价的 `max_price_deviation`（默认 20%）做边界检查。超出范围的订单拒绝提交。

#### P0-4: 状态机 _enter_cooldown 走 transition()

**文件**: `src/gate_trade/state/state_machine.py:146`

`self._state = kind` → `self.transition(kind)`，确保所有冷却状态转换都走验证矩阵。

#### P0-5: Web 面板默认 127.0.0.1 + token 认证

**文件**: `scripts/run.py:88` + `src/gate_trade/web/panel.py`

- 默认 host 改为 `127.0.0.1`
- 可选 `GATE_WEB_TOKEN` 环境变量做 Bearer token 认证
- README 明确禁止公网裸端口

#### P0-6: shutdown 按交易对撤单

**文件**: `src/gate_trade/bot.py:330-332`

```
cancel_all("")  →  cancel_all(self._pair)
```

Bot 初始化时保存 `_pair`，shutdown 时：reconcile → cancel → 记录数量 → 失败则 critical alert。

---

### P1: 修复 live 数据闭环 (第 3-4 天)

目标：行情、订单、余额进入同一个可信状态模型。

#### P1-1: WsManager 重构为后台 task

**文件**: `src/gate_trade/client/ws_manager.py`

```python
async def connect(self) -> None:
    self._running = True
    self._reader_task = asyncio.create_task(self._run_forever())
    self._ping_task = asyncio.create_task(self._ping_loop())
    await self._connected_event.wait()  # 连接成功后返回

async def close(self) -> None:
    self._running = False
    for task in [self._reader_task, self._ping_task]:
        if task and not task.done():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
```

#### P1-2: 修复 WS 订阅分发 key

**文件**: `src/gate_trade/client/ws_manager.py:48,121`

注册 key 是 `spot.order_book:BTC_USDT_20_100ms`，分发的 key 是 `spot.order_book:update`。

修复：从消息中解析真实的 channel + pair，以 `<channel>:<pair>` 作为分发 key。订阅和分发使用同一套 key 规则。

#### P1-3: 接入真实余额和交易所 open orders

**文件**: `src/gate_trade/bot.py:190-192`

维护 `AccountState`:
- 启动时 REST snapshot
- 周期性 REST reconcile
- 传入风控的 balances 从真实数据获取
- 数据超期时禁止下单（fail closed）

#### P1-4: 修正 position notional 计算

**文件**: `src/gate_trade/risk/risk_manager.py:141`

```
# 当前（错误）：把所有非零余额相加
base_held = sum(b.total for b in balances if b.total > 0)

# 正确：只取目标 pair 的 base 资产
base_held = sum(b.total for b in balances if b.asset == self._cfg.base)
```

---

### P2: 修复状态机与风控语义 (第 5-6 天)

#### P2-1: cooldown 到期后自动恢复

**文件**: `src/gate_trade/bot.py:158,179`

当前主循环在非 RUNNING/IDLE 状态直接 return，cooldown 到期检查不可达。

修复：主循环允许 cooldown 状态执行恢复检查，到期后 `transition(RUNNING)`。

#### P2-2: max_order_size_notional 实际生效

**文件**: `src/gate_trade/bot.py:_refresh_orders()` 或 `order_engine.py:place()`

配置有 `max_order_size_notional` 但下单路径未检查。添加 `price * size <= max_order_size_notional` 校验。

#### P2-3: 风控状态持久化与恢复

**文件**: `src/gate_trade/bot.py` + `src/gate_trade/persistence/sqlite.py`

启动时检查上次持久化状态。若为 EMERGENCY/COOLDOWN_*，需人工确认后方可恢复交易。

#### P2-4: load_state 容错处理

**文件**: `src/gate_trade/persistence/sqlite.py:195`

`BotState(row[0])` 抛 ValueError 时降级为 `INIT` + warning 日志。

#### P2-5: run.py / healthcheck 配置加载统一

**文件**: `scripts/run.py:59`, `scripts/healthcheck.py:27`

统一使用 `from_yaml_merged()`，确保 `local.yaml` 在两个入口都生效。

---

### P3: 修监控、持久化与告警 (第 7-8 天)

#### P3-1: 统一 SQLite fills schema

**文件**: `src/gate_trade/persistence/sqlite.py:31`, `web/panel.py:207`, `scripts/daily_report.py`

fills 表缺少 `side`, `price`, `created_at`，面板和日报查询这些列时报错。

方案：fills 表增加这三个列，与 orders 表同步写入。

#### P3-2: 告警配置真实接线

**文件**: `src/gate_trade/alert/manager.py:35`, `scripts/run.py:194`

拆分配置：
```yaml
monitoring:
  telegram_bot_token: ""
  telegram_chat_id: ""
  webhook_url: ""
```

配置不完整时启动 warning；critical alert 在测试 channel 中可验证。

#### P3-3: Web 面板解耦私有属性访问

**文件**: `src/gate_trade/web/panel.py:136-151`

Bot 类添加公共只读属性（`market_data`, `order_engine`, `state_machine`, `strategies`, `events`），面板不再访问 `_md`, `_oe` 等私有字段。

---

### P4: CI、部署与工程治理 (第 9-10 天)

#### P4-1: 修正 systemd unit

**文件**: `systemd/gate-trade.service`

```ini
# 当前：指向不存在的 gate_trade.main
ExecStart=%h/gate-trade/.venv/bin/python -m gate_trade.main

# 修正：指向实际入口
ExecStart=%h/gate-trade/.venv/bin/python %h/gate-trade/scripts/run.py --pair BTC_USDT
```

新建独立 live unit，不共用 dry-run 配置。

#### P4-2: 添加 GitHub Actions CI

**新建**: `.github/workflows/ci.yml`

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
      - run: pip install -e '.[dev]' httpx bandit pip-audit
      - run: pytest -q
      - run: ruff check .
      - run: mypy src scripts
      - run: bandit -q -r src scripts
      - run: pip-audit
```

#### P4-3: 补齐 dev dependencies

**文件**: `pyproject.toml`

```toml
[project.optional-dependencies]
dev = [
    "httpx>=0.28",
    "bandit>=1.7",
    "pip-audit>=2",
]
```

#### P4-4: 添加仓库治理文件

新建：
- `LICENSE`
- `.github/dependabot.yml`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/pull_request_template.md`
- `SECURITY.md`

#### P4-5: 启用 branch protection

- 要求 PR review
- 要求 CI 通过
- 禁止 force push

#### P4-6: 补充测试

| 优先级 | 测试文件 | 覆盖内容 |
|--------|----------|----------|
| P0 | `tests/test_client/test_gate_client.py` | API 解析、错误处理 |
| P0 | `tests/test_client/test_ws_manager.py` | WS 连接/订阅/分发/重连 |
| P1 | `tests/test_bot/test_live_path.py` | preflight、shutdown 撤单 |
| P1 | `tests/test_live_data/test_config_integration.py` | 配置加载一致性 |
| P2 | `tests/test_risk/test_with_real_balances.py` | 真实余额风控 |
| P2 | `tests/test_state/test_cooldown_recovery.py` | cooldown 自动恢复 |

#### P4-7: 修复 ruff 和 bandit 告警

```
ruff check .   → 14 errors（import 排序、未使用变量等）
bandit -r src  → 4 medium, 17 low（0.0.0.0 绑定、SQL 拼接等）
```

---

### P5: 灰度实盘准备 (在 P0-P4 全部完成后)

#### 硬性限制

- [ ] 只使用子账户
- [ ] API key 仅授予现货交易权限，禁止提现
- [ ] `max_position_notional` 设置为极小值
- [ ] `max_order_size_notional` 设置为极小值
- [ ] 交易所端启用 IP 白名单
- [ ] 首次实盘只运行 5-10 分钟
- [ ] 实盘期间人工盯盘

#### 灰度验收清单

- [ ] 启动前 open orders = 0
- [ ] 启动后订单数量 ≤ 配置上限
- [ ] 风控 halt 能停止下单
- [ ] shutdown 后交易所 open orders 回到 0
- [ ] 面板仅从受控网络可访问
- [ ] 日报和 event log 能复盘完整行为

---

## 建议 PR 切分 (共 12 个)

不要用一个巨大 PR 解决所有问题。按以下顺序逐一提交：

| # | PR 标题 | 包含 |
|---|---------|------|
| 1 | `add-live-preflight` | P0-1 启动前检查 |
| 2 | `add-live-confirm-flag` | P0-2 双重确认参数 |
| 3 | `add-order-price-bounds` | P0-3 价格上下界 |
| 4 | `fix-cooldown-transition-validation` | P0-4 状态机验证 |
| 5 | `secure-web-panel-defaults` | P0-5 面板安全 |
| 6 | `fix-shutdown-cancel-by-pair` | P0-6 撤单修复 |
| 7 | `fix-ws-lifecycle-and-dispatch` | P1-1, P1-2 WS 重构 |
| 8 | `wire-real-balances-and-orders` | P1-3, P1-4, P2-2 数据闭环 |
| 9 | `fix-cooldown-auto-resume` | P2-1 冷却恢复 |
| 10 | `fix-fills-schema-and-reporting` | P3-1 数据库修复 |
| 11 | `fix-alert-wiring-and-config` | P3-2 告警接线 |
| 12 | `add-ci-and-governance` | P4 全部 CI/部署 |

每个 PR 必须包含测试和简短风险说明。

---

> **Deepseek-v4-pro × Codex 联合审计**  
> *2026-05-05*  
> *本计划综合两份独立审计报告，按风险优先级排序。P0 修完前不建议运行 `--live`。*
