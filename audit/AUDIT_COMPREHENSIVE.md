# Gate Trade 综合审计报告

**审计来源**: Deepseek-v4-pro + DS + Codex（三方审计合并）  
**审计日期**: 2026-05-05  
**项目版本**: 0.1.0  
**项目仓库**: `https://github.com/mudyman/gate-trade`  
**本地路径**: `/home/monero/gate-trade`  
**审计范围**: 全部 Python 源文件（70个）、测试文件（83个，469个测试）、配置、脚本、部署文件

---

## 目录

1. [最终结论](#0-最终结论)
2. [项目概况](#1-项目概况)
3. [致命问题 — live 模式无法启动](#2-致命问题--live-模式无法启动)
4. [严重问题 — 必须立即修复](#3-严重问题--必须立即修复)
5. [高风险问题 — 强烈建议修复](#4-高风险问题--强烈建议修复)
6. [中风险问题 — 建议修复](#5-中风险问题--建议修复)
7. [低风险问题 — 可选改进](#6-低风险问题--可选改进)
8. [工程与供应链](#7-工程与供应链)
9. [测试覆盖分析](#8-测试覆盖分析)
10. [正面评价](#9-正面评价)
11. [修复优先级路线图](#10-修复优先级路线图)
12. [审计方法论与命令记录](#11-审计方法论与命令记录)

---

## 0. 最终结论

> **当前版本不建议直接运行实盘。**
>
> 项目的 dry-run 和单元测试基础较完整，但 live 路径存在多处实盘级风险：
> - WebSocket 初始化阻塞主循环，live 模式根本跑不起来
> - WebSocket 分发 key 不匹配，行情永远无法到达策略层
> - 真实余额没有进入风控计算，仓位上限检查形同虚设
> - 退出时无法取消交易所挂单，残留资金风险
> - 监控面板默认对外暴露且无认证
>
> 这些问题修完前，**不应使用真实 API key 运行 `--live`**。

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
| `state` | `src/gate_trade/state/` | 10 状态机 + 3 通道独立冷却计时器 |
| `strategy` | `src/gate_trade/strategy/` | 积累器 (棘轮) + 深度维持 (3 层) |
| `markout` | `src/gate_trade/markout/` | 成交质量分析 + 毒性检测 |
| `smasher` | `src/gate_trade/smasher/` | 冰山/探针攻击检测与反制 |
| `replay` | `src/gate_trade/replay/` | 历史回放引擎 |
| `web` | `src/gate_trade/web/` | FastAPI 实时监控面板 |
| `alert` | `src/gate_trade/alert/` | Telegram/Email 多渠道告警 |

---

## 2. 致命问题 — live 模式无法启动

> 以下问题由 **Codex 实际运行 bot 后**发现，静态审查无法识别。

### 2.1 WebSocket `connect()` 阻塞主循环

- **文件**: `scripts/run.py:156` + `src/gate_trade/client/ws_manager.py:36`
- **严重程度**: FATAL

`WsManager.connect()` 调用 `_reconnect()` → `_reader_loop()`，后者是一个无限循环。`_run_live()` 中后续的 `LiveMarketData`、`LiveOrderEngine`、`Bot`、Web 面板和 feed tasks 全部无法初始化。

```text
# Codex 本地复现结果
connect_timed_out_blocking
```

**修复**: `WsManager.connect()` 只建立连接并创建后台 reader task，不阻塞调用方。

---

### 2.2 WebSocket 分发 key 不匹配

- **文件**: `src/gate_trade/client/ws_manager.py:48` + `:121`
- **严重程度**: FATAL

订阅注册 key：`spot.order_book:BTC_USDT_20_100ms`  
分发 key：`spot.order_book:update`  
结果：handler 永远匹配不到。

```text
handler_keys ['spot.order_book:BTC_USDT_20_100ms']
dispatch_key spot.order_book:update
registered_for_dispatch False
```

**修复**: 按 Gate.io 实际消息结构解析 `channel`/`event`/`result.s`。为 order book、orders、balances 分别加集成级单测。

---

## 3. 严重问题 — 必须立即修复

### 3.1 [SECURITY] API 密钥明文存储

- **文件**: `config/local.yaml:3-4`
- **严重程度**: CRITICAL
- **来源**: Deepseek / DS

实盘 API 密钥以明文形式存储在配置文件中。虽已 `.gitignore`，但文件系统被其他进程读取、误操作 `git add --force`、磁盘备份/快照等场景仍会导致泄露。

**修复**:
1. 立即在 Gate.io 后台撤销当前 API 密钥对
2. 生成新密钥，通过环境变量 `GATE_EXCHANGE__API_KEY` / `GATE_EXCHANGE__API_SECRET` 注入
3. 将 `local.yaml` 中的密钥替换为占位符
4. 检查 `.bash_history` 是否记录了密钥

---

### 3.2 [BUG] 风控传入空余额 — 仓位检查完全失效

- **文件**: `src/gate_trade/bot.py:190-192`
- **严重程度**: CRITICAL
- **来源**: 三方一致

```python
self._risk.evaluate(
    open_orders=self._oe.open_orders(),
    balances=[],      # <-- 恒为空列表
    mid_price=mid,
)
```

`RiskManager._check_position()` 中 `base_held = sum(b.total for b in balances ...)` 恒为 0。仓位上限检查形同虚设，实盘存在爆仓风险。

额外问题（Codex）：`_check_position` 不应把所有非零余额相加，需按交易对拆分 base/quote。

**修复**: live 模式定期调用 `client.fetch_balances()` 或订阅余额 WS，传入真实余额。

---

### 3.3 [BUG] 状态机冷却态绕过 `transition()` 验证

- **文件**: `src/gate_trade/state/state_machine.py:140-149`
- **严重程度**: CRITICAL
- **来源**: Deepseek / DS

```python
def _enter_cooldown(self, kind: BotState, duration_ms: int) -> None:
    if self._state in (BotState.EMERGENCY, BotState.SHUTDOWN):
        return
    old = self._state
    self._state = kind  # <-- 直接赋值，绕过 _VALID_TRANSITIONS
```

`transition()` 有严格的转换矩阵，但 `_enter_cooldown` 直接设值。

**修复**: 改为 `self.transition(kind)`。

---

### 3.4 [RISK] 订单价格无上限/下限保护

- **文件**: `src/gate_trade/order/order_engine.py:254-261`
- **严重程度**: CRITICAL
- **来源**: Deepseek / DS

```python
def _validate(self, order: Order) -> None:
    if order.price <= 0: ...
    if order.size <= 0: ...
    # 无 max_price / min_price 检查
```

参考价格异常时 bot 可能以极端价格（如 $0.01 卖单或 $100 买单）下单。

**修复**: 基于 TWAP 或配置阈值添加 ±20% 价格边界。

---

### 3.5 [BUG] 价格尖峰 cooldown 导致永久死锁

- **文件**: `src/gate_trade/bot.py:158-179` + `state_machine.py:127`
- **严重程度**: CRITICAL
- **来源**: Codex

进入 `COOLDOWN_PRICE_SPIKE` 后，下一 tick 开头因状态不是 `RUNNING`/`IDLE` 直接 return。`can_place()` 不再被执行，cooldown 到期判断永远不可达，bot 永久卡在冷却态。

**修复**: 主循环应允许 cooldown 状态继续执行恢复检查，到期后显式 transition 回 RUNNING。

---

### 3.6 [BUG] WebSocket ping loop 从未启动

- **文件**: `src/gate_trade/client/ws_manager.py:129-136`
- **严重程度**: CRITICAL
- **来源**: Deepseek / DS

`_ping_loop` 方法已定义（while 循环发送 ping），但 `connect()` 中从未 `asyncio.create_task(self._ping_loop())`。WS 长时间无消息时会被中间代理断开。

**修复**: 在 `connect()` 中添加 `self._ping_task = asyncio.create_task(self._ping_loop())`。

---

## 4. 高风险问题 — 强烈建议修复

### 4.1 [SECURITY] Web 面板绑定 0.0.0.0 且无认证

- **文件**: `scripts/run.py:88`
- **严重程度**: HIGH
- **来源**: 三方一致

```python
async def _start_web_panel(bot: Bot, host: str = "0.0.0.0", port: int = 39120)
```

`/api/snapshot` 暴露 bot 状态、订单、策略状态、价格与风险状态。部署在云服务器上时任何人可访问。

**修复**: 默认 `host="127.0.0.1"`，远程访问通过 SSH 隧道或反向代理+TLS+认证。

---

### 4.2 [BUG] 关机 `cancel_all` 传空交易对

- **文件**: `src/gate_trade/bot.py:330-334`
- **严重程度**: HIGH
- **来源**: 三方一致

```python
await self._oe.cancel_all("")  # 空字符串
```

`LiveOrderEngine.cancel_all(pair)` 按 pair 筛选本地 open orders（`o.pair == pair`），空字符串通常匹配不到任何订单，交易所挂单不会被取消。

**修复**: 传入 `self._pair`。shutdown 前先 reconcile exchange open orders，再按 tag 或 pair 撤单。

---

### 4.3 [BUG] `load_state` 对未知状态字符串抛出 ValueError

- **文件**: `src/gate_trade/persistence/sqlite.py:191-197`
- **严重程度**: HIGH
- **来源**: Deepseek / DS

```python
return (BotState(row[0]), row[1])  # ValueError 如果 row[0] 已废弃/损坏
```

DB 中出现废弃或损坏的状态值时 bot 无法启动。

**修复**: 用 try/except 捕获，降级到 `BotState.INIT`，记录 warning 日志。

---

### 4.4 [CONFIG] `run.py` 和 `healthcheck.py` 配置加载路径不一致

- **文件**: `scripts/run.py:59` vs `scripts/healthcheck.py:27-37`
- **严重程度**: HIGH
- **来源**: Deepseek / DS

`run.py` 使用 `from_yaml()` 不加载 `local.yaml`；`healthcheck.py` 使用 `from_yaml_merged()` 加载 `local.yaml`。同一个 bot 在不同入口看到不同配置。

**修复**: 统一使用 `from_yaml_merged()`。

---

### 4.5 [RISK] 风控状态崩溃重启后丢失

- **文件**: `src/gate_trade/risk/risk_manager.py`
- **严重程度**: HIGH
- **来源**: 三方一致

`LiveRiskManager._halted`、`_position_breached`、`_flash_crash` 等纯内存标志不持久化。如果 bot 在风控暂停期间崩溃，重启后立即恢复交易，实际仓位可能已严重超标。

**修复**: 启动时检查 `bot_state` 表最新状态，若为 EMERGENCY 或 COOLDOWN_*，需人工确认后恢复。

---

### 4.6 [DATA] 闪崩检测阈值硬编码

- **文件**: `src/gate_trade/market/market_data.py:200`
- **严重程度**: HIGH
- **来源**: Deepseek / DS

```python
return (high - low) / high >= 0.05  # 固定 5%
```

配置中已有 `risk.flash_crash_threshold_pct` 但 `market_data.py` 未读取。DOGE（波动大）和 BTC（波动小）同一阈值效果截然不同。

**修复**: 从 `RiskConfig.flash_crash_threshold_pct` 读取阈值，支持按交易对设置。

---

### 4.7 [BUG] SQLite schema 与 Web 面板、日报查询不一致

- **文件**: `sqlite.py:31` / `panel.py:207` / `daily_report.py:39`
- **严重程度**: HIGH
- **来源**: Codex

`fills` 表定义字段：`order_id, pair, fill_price, filled_size, created_at_ms`  
面板和日报查询使用：`side, price, created_at`  
Codex 实际验证：`OperationalError no such column: side`

**修复**: 在 fills 表中保存 side/price/created_at，或修正查询 join orders 表。

---

### 4.8 [DEPLOY] systemd unit 启动入口不存在

- **文件**: `systemd/gate-trade.service:17`
- **严重程度**: HIGH
- **来源**: Codex

```text
ExecStart=%h/gate-trade/.venv/bin/python -m gate_trade.main
```

但仓库没有 `src/gate_trade/main.py`。Codex 验证：`No module named gate_trade.main`。

**修复**: 改为 `python scripts/run.py ...` 或新增 `gate_trade.main` 模块。同步 README、Makefile、systemd unit。

---

### 4.9 [ALERT] alert webhook 配置没有真正接线

- **文件**: `scripts/run.py:194` + `alert/manager.py:35`
- **严重程度**: HIGH
- **来源**: Codex

当 `monitoring.alert_webhook_url` 非空时，代码添加的是空 token 的 TelegramChannel：
```python
alert.add(TelegramChannel(bot_token="", chat_id=""))
```

风控 halt、fatal error、shutdown 等关键告警不可达。

**修复**: 明确配置项结构，Telegram token/chat_id、webhook、email 分开建模。启动时校验告警配置。

---

## 5. 中风险问题 — 建议修复

### 5.1 [ARCH] Bot 构造参数类型为 `Any` 而非 Protocol

- **文件**: `src/gate_trade/bot.py:49-66`
- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

所有注入参数标注为 `Any`，丧失编译期类型检查。错误传入不匹配对象运行时才报错。

**修复**: 导入对应的 Protocol 类并标注参数类型。

---

### 5.2 [ENCAP] Web Panel 直接访问私有属性

- **文件**: `src/gate_trade/web/panel.py:136-151`
- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

```python
md = bot._md          # 直接访问私有属性
sm = bot._sm
oe = bot._oe
bot.events._on_record = lambda evt: _broadcast(...)
```

破坏封装性，IDE 无法提供补全和类型检查。

**修复**: 在 `Bot` 类中添加公共只读属性或 getter 方法。

---

### 5.3 [TEST] `GateIoClient` 和 `WsManager` 零单元测试

- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

实盘客户端的 HTTP 解析、WebSocket 重连、消息分发等关键逻辑无测试覆盖。仅通过契约测试的 Mock 验证了接口形状。

**修复**: 使用 `aioresponses` 或 `pytest-httpx` mock HTTP 层，为关键解析方法添加测试。

---

### 5.4 [DEDUP] `_flatten` 方法重复

- **文件**: `config/schema.py:116-126` 和 `config/watcher.py:180-188`
- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

两处有几乎相同的 `_flatten` 实现。修改一处容易遗漏另一处。

**修复**: 提取为 `config/schema.py` 中的公共函数。

---

### 5.5 [DATA] `MarkoutRecorder` 关闭时未清理 pending 记录

- **文件**: `src/gate_trade/markout/recorder.py:77-93`
- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

Bot 关闭时 `_pending` deque 中未完成的 markout 记录静默丢弃。

**修复**: shutdown 时调用 flush 方法将剩余记录写入日志或 DB。

---

### 5.6 [CONFIG] `.gitignore` 缺少 `data/` 目录

- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

运行时生成的 `data/bot.log` 和 `data/gate_trade.db` 未被 `.gitignore` 排除，容易误提交含敏感信息的日志和数据库。

**修复**: 在 `.gitignore` 中添加 `data/`。

---

### 5.7 [INTEGRATION] Smasher 模块未集成到主循环

- **文件**: `src/gate_trade/bot.py:_tick()`
- **严重程度**: MEDIUM
- **来源**: DS

`smasher/` 下 4 个模块（冰山检测、探针攻击、执行、验证）已有 10 个测试，但 `_tick()` 未调用它们。

**修复**: 将 Smasher 检测纳入主循环。

---

### 5.8 [PERF] `TelegramChannel` 使用同步 `urllib`

- **文件**: `alert/manager.py:55`
- **严重程度**: MEDIUM
- **来源**: DS

```python
await asyncio.to_thread(urllib.request.urlopen, req, timeout=10)
```

告警频繁时会创建多个线程。

**修复**: 改用 `httpx` 或 `aiohttp`。

---

### 5.9 [DATA] Web Panel SQLite 路径存在路径遍历风险

- **文件**: `src/gate_trade/web/panel.py:201-202`
- **严重程度**: MEDIUM
- **来源**: Deepseek / DS

```python
async def api_fills(db: str = Query(default=DEFAULT_DB), ...)
```

允许通过查询参数指定任意数据库路径，面板暴露在公网时有读取任意 SQLite 文件风险。

**修复**: 限制 db 参数为预定义路径或验证路径位于允许目录内。

---

## 6. 低风险问题 — 可选改进

| # | 问题 | 文件 | 来源 |
|---|------|------|------|
| 6.1 | API 错误响应日志可能泄露信息 | `gate_client.py:248-259` | Deepseek |
| 6.2 | `save_fill` 并发安全依赖单线程假设 | `sqlite.py:155-166` | Deepseek |
| 6.3 | `cancel` 的 `_by_tag` 清理可能残留悬挂引用 | `order_engine.py:125-148` | Deepseek |
| 6.4 | `place` 和 `reconcile` 之间竞态窗口 | `order_engine.py:95-123` | Deepseek |
| 6.5 | 连续 tick 可能生成重复订单 | `strategy/depth_keeper.py` | Deepseek |
| 6.6 | 令牌桶等待超时是硬错误 | `rate_limiter.py:41-51` | Deepseek |
| 6.7 | GitHub no license, no branch protection, no CI | 仓库配置 | Codex |
| 6.8 | `httpx` 未声明为 dev dependency | `pyproject.toml` | Codex |

---

## 7. 工程与供应链

- **GitHub**: 公开仓库，默认分支 `main`，无分支保护，无 GitHub Actions，无 license，community health 14%
- **ruff**: Codex 实际运行 `ruff check .` 结果 **14 errors**（import 排序、未使用变量、变量名模糊）
- **bandit**: 4 medium, 17 low（Web 面板绑定 `0.0.0.0`、SQL 字符串拼接）
- **pip-audit**: 仅命中 `pip 24.0` CVE，非项目声明业务依赖
- **dev 依赖**: 缺少 `httpx`，需手动安装后 pytest 才能运行

**建议**: 增加 `.github/workflows/ci.yml`（pytest + ruff + mypy + bandit）。开启分支保护。增加 Dependabot 或 pip-audit 定期扫描。明确 license。

---

## 8. 测试覆盖分析

### 已覆盖

MarketData, OrderEngine, SqlitePersistence, RefPriceEngine, RiskManager, StateMachine, CooldownManager, Accumulator, DepthKeeper, MarkoutRecorder, ToxicDetector, ToxicResponse, IcebergDetector, ProbeDetector, SmasherVerifier, ReplayEngine, Config, Bot, Web Panel, Alert, Attack Scenarios

### 未覆盖

| 模块 | 风险 |
|------|------|
| `GateIoClient` (gate_client.py, 260行) | 关键解析逻辑无测试 |
| `WsManager` (ws_manager.py, 84行) | 重连/分发逻辑无测试 |
| `scripts/run.py` | 启动流程无测试 |
| `scripts/gate_admin.py` | 管理工具无测试 |
| TelegramChannel / EmailChannel | 实际发送逻辑无测试 |
| ConfigWatcher + ConfigGuard 集成 | 热更新全流程无测试 |
| Bot 长时间运行场景 | 仅测试 50ms 片段 |

---

## 9. 正面评价

以下是项目中值得肯定的设计和实现：

1. **Protocol/契约架构** — 8 个子系统全部先定义 Protocol 接口，Mock 和实现分离，依赖注入清晰，每个模块可独立开发和测试
2. **测试覆盖** — 469 个测试，83 个测试文件，覆盖所有 8 个 Protocol 接口。状态机有参数化转换矩阵测试
3. **Smasher 子系统** — 冰山检测用 Welch's t-test 做统计验证，设计专业
4. **状态机设计** — 10 状态 + 严格转换矩阵 + 3 通道独立冷却计时器
5. **结构化日志** — `structlog` + `RotatingFileHandler`，所有日志级别可动态配置，支持 JSON 输出
6. **令牌桶限速器** — 符合交易所 API 限速要求的通用限速组件
7. **配置分层** — `default.yaml → local.yaml → 环境变量` 三层覆盖，环境变量优先级最高
8. **代码质量** — `mypy strict` 零错误，完整类型标注，命名规范一致
9. **参考价格引擎** — 自成交排除、TWAP 平滑、尖峰保护等设计考虑周全
10. **Markout 分析** — 成交后 5 个时间窗口的 markout 追踪 + 毒性检测 + 分级响应
11. **API 错误分类** — 7 种自定义异常，区分超时、限速、认证等不同错误类型
12. **SSE 实时面板** — 事件广播 + 自动重连 + 快照轮询
13. **BotEventLogger** — 内存环形缓冲 + SQLite 持久化，兼顾性能与可审计性
14. **Replay 引擎** — 历史数据回放，可独立验证策略表现

---

## 10. 修复优先级路线图

### 第 0 批: 禁止危险实盘路径（今天，先修再跑）

| # | 问题 | 文件 |
|---|------|------|
| 0.1 | 重构 `WsManager.connect()` 为后台 reader task，避免阻塞主循环 | `ws_manager.py` |
| 0.2 | 修正 WebSocket 分发 key 匹配逻辑 | `ws_manager.py` |
| 0.3 | 启动 ping loop task | `ws_manager.py` |
| 0.4 | live 启动前增加完整 preflight（WS 可用、balances 获取、orders reconcile） | `run.py` |

### 第 1 批: 安全 + 正确性（今天）

| # | 问题 | 文件 |
|---|------|------|
| 1.1 | 撤销 local.yaml 中的 API 密钥，改用环境变量 | `config/local.yaml` |
| 1.2 | `Bot._tick()` 传入真实 balances | `bot.py:190` |
| 1.3 | `_enter_cooldown` 调用 `transition()` | `state_machine.py:146` |
| 1.4 | 订单价格边界保护 | `order_engine.py:254` |
| 1.5 | 修复价格尖峰 cooldown 永久死锁 | `bot.py:158` |

### 第 2 批: 风控 + 数据闭环（本周）

| # | 问题 | 文件 |
|---|------|------|
| 2.1 | Web panel 默认 `127.0.0.1` + 认证 | `scripts/run.py` |
| 2.2 | `cancel_all` 传入真实 pair | `bot.py:332` |
| 2.3 | `load_state` 容错处理 | `sqlite.py:195` |
| 2.4 | `run.py`/`healthcheck` 配置加载统一 | `scripts/run.py` |
| 2.5 | 崩溃重启后风控状态恢复 | `bot.py` + `risk/` |
| 2.6 | 闪崩阈值从配置读取 | `market_data.py` |
| 2.7 | SQLite schema 与面板/日报查询一致 | `sqlite.py` + `panel.py` |

### 第 3 批: 质量 + 工程化（本月）

| # | 问题 | 文件 |
|---|------|------|
| 3.1 | Bot 参数类型标注 Protocol | `bot.py:49` |
| 3.2 | Web panel 解耦私有属性访问 | `panel.py` + `bot.py` |
| 3.3 | `GateIoClient` / `WsManager` 单元测试 | `gate_client.py` |
| 3.4 | `_flatten` 去重 | `schema.py` / `watcher.py` |
| 3.5 | `.gitignore` 添加 `data/` | `.gitignore` |
| 3.6 | systemd unit 修正入口 | `systemd/` |
| 3.7 | Smasher 集成到主循环 | `bot.py` |
| 3.8 | `TelegramChannel` 改为 `httpx` | `alert/manager.py` |
| 3.9 | 修复 al1ert webhook 配置接线 | `scripts/run.py` |
| 3.10 | GitHub Actions CI + 分支保护 + license | 仓库设置 |
| 3.11 | 补全 `httpx` dev dependency | `pyproject.toml` |

---

## 11. 审计方法论与命令记录

### Codex 实际运行命令

```bash
git clone https://github.com/mudyman/gate-trade.git .
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pip install httpx bandit pip-audit
.venv/bin/pytest -q                          # 469 passed
.venv/bin/ruff check .                       # 14 errors
.venv/bin/mypy src scripts                   # Success
.venv/bin/bandit -q -r src scripts           # 4M, 17L
.venv/bin/pip-audit --local
.venv/bin/python scripts/run.py --pair BTC_USDT --duration 2 --data-dir /tmp/gate-trade-audit-data
.venv/bin/python -m gate_trade.main          # No module named gate_trade.main
```

### 静态审查覆盖

- Deepseek-v4-pro: 逐行审查 29 个源文件全部代码路径
- DS: 审查 70 个 Python 源文件 + 83 个测试文件
- 手工验证 SQLite schema、Web API 端点、配置加载路径

---

> **审计签名**: Deepseek-v4-pro + DS + Codex  
> *审计于 2026-05-05*  
> *此报告由三方 AI 审计合并生成，建议人工复核关键发现*
