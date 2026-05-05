# Gate Trade v0.2.0 测试方案

**日期**: 2026-05-05
**版本**: 0.2.0 (post-improvement)
**基准审计**: `audit/AUDIT_COMPREHENSIVE.md` (v0.1.0 三方合并审计，发现 3F + 6C + 9H + 9M)
**改进计划**: `docs/IMPROVEMENT_PLAN.md`
**自审计报告**: `audit/AUDIT_SELF_v0.2.0_2026-05-05.md`

---

## 0. 测试目标

验证 v0.1.0 审计发现的 **3 FATAL + 6 CRITICAL + 9 HIGH + 9 MEDIUM** 共 27 个问题已修复，v0.2.0 系统可在 live 模式安全运行。

---

## Phase 1: 静态验证

验证代码质量和类型安全工具链全绿，0 新增问题。

### T1.1 — pytest 全量测试

| 项 | 内容 |
|----|------|
| **测试内容** | 运行全部 469 个单元测试和合约测试 |
| **为什么** | v0.1.0 审计发现多处逻辑错误（cooldown 死锁、价格无边界、余额空传入），对应修复的代码必须通过所有已有测试 + 新增测试。任何失败都意味着回归。 |
| **怎么测试** | `.venv/bin/pytest tests/ -q --timeout=30` |
| **通过标准** | `469 passed, 0 failed` |

### T1.2 — mypy 类型检查

| 项 | 内容 |
|----|------|
| **测试内容** | 63 个源文件的严格类型检查（strict mode） |
| **为什么** | v0.1.0 审计 5.1 指出 Bot 构造函数参数类型标注为 `Any`，多个 Protocol 接口定义不完整。修复后新增了完整的 Protocol 类型标注、公共属性、接口方法签名。mypy 可检测类型不匹配。 |
| **怎么测试** | `.venv/bin/mypy src/ scripts/` |
| **通过标准** | `Success: no issues found in 63 source files` |

### T1.3 — ruff 代码检查

| 项 | 内容 |
|----|------|
| **测试内容** | 全项目代码风格和逻辑 lint |
| **为什么** | v0.1.0 有 4 个预存 ruff 问题（变量名 `l` 模糊、未使用变量）。v0.2.0 应全部修复，且不引入新问题。ruff 也会检测未使用的 import（如 `json` 模块在 httpx 迁移后不再需要）。 |
| **怎么测试** | `.venv/bin/ruff check .` |
| **通过标准** | `All checks passed!`，0 error |

### T1.4 — bandit 安全扫描

| 项 | 内容 |
|----|------|
| **测试内容** | 安全漏洞静态扫描 |
| **为什么** | v0.1.0 审计发现 SQL 字符串拼接（MEDIUM，但来自本地 date 无真实注入风险）、`random.*`（LOW，非加密场景）。v0.2.0 不引入新的 HIGH/MEDIUM 问题。 |
| **怎么测试** | `.venv/bin/bandit -q -r src/ scripts/` |
| **通过标准** | `High: 0, Medium: 4（均为预存 SQL 拼接，输入来自 date.today() 无注入风险）, Low: 17（预存）` |

---

## Phase 2: Dry-run 功能验证

在无 API 密钥、合成行情下验证完整 tick 循环和所有模块协同工作。

### T2.1 — 基本运行与启动流程

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 bot 能否完成启动流程：配置加载 → 模块初始化 → 数据引擎组装 → 主循环启动 → 正常 tick → 优雅关机 |
| **为什么** | v0.1.0 FATAL 2.1：`WsManager.connect()` 阻塞主循环导致 live 模式无法启动。修复后将 `connect()` 改为非阻塞后台 task。Dry-run 也走相同的 Bot 初始化路径，须验证所有模块正确组装。v0.1.0 FATAL 2.3 / CRITICAL 3.6：ping loop 从未启动，修复后在 `_reconnect()` 中 `create_task`。 |
| **怎么测试** | `rm -f data/gate_trade.db && .venv/bin/python scripts/run.py --pair BTC_USDT --duration 120 --tick-interval 0.5 --data-dir data 2>&1` |
| **关键日志检查** | `dry_run_initializing` → `persistence_opened` → `web_panel_starting` → `state_transition: INIT→IDLE` → `state_transition: IDLE→RUNNING` → `bot_started` |
| **通过标准** | 启动日志完整，tick 正常推进（~240 ticks / 120s），无 exception traceback，shutdown 正常 |

### T2.2 — 价格尖峰检测与 cooldown 恢复

| 项 | 内容 |
|----|------|
| **测试内容** | 验证合成行情随机尖峰被正确检测，进入 COOLDOWN_PRICE_SPIKE 后能够自动恢复 RUNNING |
| **为什么** | v0.1.0 CRITICAL 3.5：进入 COOLDOWN_PRICE_SPIKE 后，原代码在 tick 开头 `if state not in (RUNNING, IDLE): return`，导致 cooldown 到期检查永远不可达，形成**永久死锁**。修复：COOLDOWN_* 状态继续执行 tick，检查 `can_place()` 到期后 `transition(RUNNING)`。v0.1.0 CRITICAL 3.4：cooldown 状态进入时调用 `_enter_cooldown()` 直接赋值 `self._state = kind` 绕过转换矩阵验证。修复：改为 `self.transition(kind)` 走完整验证。v0.1.0 HIGH 4.6：闪崩阈值硬编码 5%，需从配置读取。修复：`LiveMarketData.__init__` 接收 `flash_crash_threshold_pct` 参数。 |
| **怎么测试** | 运行 120s dry-run，grep 日志中 `spike_detected` 和 `cooldown` 事件 |
| **关键日志检查** | `spike_detected`（warning 级别）→ `state_transition: RUNNING→COOLDOWN_PRICE_SPIKE` → cooldown 到期 → `state_transition: COOLDOWN_PRICE_SPIKE→RUNNING` |
| **通过标准** | (1) 至少出现 1 次 spike_detected（合成行情随机产生）(2) cooldown 状态在 5s 内恢复 RUNNING（非永久死锁）(3) 转换走了 `state_transition` 日志（非直接赋值绕过） |

### T2.3 — Web Panel 可访问性与安全

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 Web 面板绑定 127.0.0.1、API 返回完整 JSON、panel 访问 bot 公共属性（非私有属性） |
| **为什么** | v0.1.0 HIGH 4.1：Panel 绑定 0.0.0.0 且无认证，存在安全风险。修复：默认绑定 127.0.0.1，支持 `GATE_WEB_TOKEN` 可选认证。v0.1.0 MEDIUM 5.2：Panel 直接访问 `bot._md` 等私有属性。修复：Bot 新增公共属性 `md`、`sm`、`oe`、`risk`、`toxic_response`、`strategies`。 |
| **怎么测试** | 启动后 `curl -s http://127.0.0.1:39120/api/snapshot \| python3 -m json.tool` |
| **通过标准** | (1) 返回 200 (2) JSON 包含 `state, mid, best_bid, best_ask, spread_bps, open_orders, strategies, can_place, toxic_level, dry_run` (3) 所有字段值非 null |

### T2.4 — SSE 实时流

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 Server-Sent Events 端点能建立连接并推送实时事件 |
| **为什么** | Web Panel 的实时事件流是监控的核心通道。验证 SSE 连接正常建立、keepalive 机制工作、事件 JSON 格式正确。 |
| **怎么测试** | `timeout 5 curl -s http://127.0.0.1:39120/api/stream 2>&1 \| head -5` |
| **关键输出检查** | `data: {"type": "connected"}` |
| **通过标准** | (1) 返回 text/event-stream (2) 第一条消息为 connected 事件 (3) 5 秒内至少收到 1 个 tick 事件 |

### T2.5 — 数据库写入与 Schema 一致性

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 SQLite 数据库文件创建、schema 创建（含新增列）、运行中数据写入 |
| **为什么** | v0.1.0 HIGH 4.7：fills 表缺少 `side` 和 `price` 列，面板查询失败。修复：fills 表新增 `side TEXT NOT NULL DEFAULT ''` 和 `price REAL NOT NULL DEFAULT 0.0` 列。v0.1.0 HIGH 4.3：`load_state()` 在遇到未知状态值时直接 `BotState(row[0])` 抛 ValueError 崩溃。修复：try/except 降级到 INIT。 |
| **怎么测试** | 120s dry-run 结束后：`sqlite3 data/gate_trade.db ".schema"` 检查 fills 表结构；`sqlite3 data/gate_trade.db "SELECT COUNT(*) FROM fills"` 检查写入 |
| **通过标准** | (1) fills 表包含 `side TEXT` 和 `price REAL` 列 (2) bot_state 表有记录 (3) event_log 表有 tick 事件记录 (4) bot_state 的 state 列值为最后一次写入的状态 |

### T2.6 — 优雅关机与撤单流程

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 duration 到期或 Ctrl+C 后，bot 能否完整执行关机流程 |
| **为什么** | v0.1.0 HIGH 4.2：`cancel_all("")` 传入空字符串，无法匹配任何交易对，挂单残留。修复：`cancel_all(self._pair)` 传入真实 pair，且先 reconcile 再撤单。 |
| **怎么测试** | 观察 duration 到期后的关机日志 |
| **关键日志检查** | `bot_shutting_down` → `state_transition: *→SHUTDOWN` → `markout_flushed` → `persistence_closed` |
| **通过标准** | (1) 关机日志完整有序 (2) 无未处理的 exception (3) `DRY-RUN SESSION COMPLETE` 打印摘要 (4) 进程正常退出 code 0 |

### T2.7 — 配置合并与环境变量覆盖

| 项 | 内容 |
|----|------|
| **测试内容** | 验证多层配置合并（default.yaml → local.yaml → 环境变量）的正确性 |
| **为什么** | v0.1.0 HIGH 4.4：`run.py` 和 `healthcheck.py` 使用不同的配置加载方法，导致配置不一致。修复：统一使用 `from_yaml_merged()`。v0.1.0 HIGH 4.8：systemd 入口指向不存在的 `gate_trade.main` 模块。修复：改为 `scripts/run.py`。 |
| **怎么测试** | `GATE_RISK__FLASH_CRASH_THRESHOLD_PCT=7.0 .venv/bin/python scripts/run.py --pair BTC_USDT --duration 5 --data-dir data 2>&1 \| grep -i "config\|flash"` |
| **关键日志检查** | config 文件中 `flash_crash_threshold_pct=7.0` 被正确读取 |
| **通过标准** | 环境变量覆盖生效，配置日志显示合并后的最终值 |

---

## Phase 3: 审计修复定向回归

针对 v0.1.0 审计报告中每个 FATAL/CRITICAL/HIGH 问题，逐一验证修复。

### T3.1 — FATAL 2.1: WsManager.connect() 非阻塞验证

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 `connect()` 不阻塞调用方，调用后立即返回 |
| **为什么** | v0.1.0：`connect()` 内部调用了无限循环的 `_reader_loop()`，导致其后所有初始化代码无法执行。修复：`connect()` 创建后台 `_conn_task = asyncio.create_task(self._reconnect())` 后立即返回。 |
| **怎么测试** | 检查 `ws_manager.py` 源码：`connect()` 方法体应为 `self._conn_task = asyncio.create_task(self._reconnect())`，无直接调用 `_reader_loop()` |
| **通过标准** | 源码确认 + dry-run 120s 中后续模块正常初始化（间接证明） |

### T3.2 — FATAL 2.2: WS 分发 key 三级匹配

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 WebSocket 消息分发使用三级匹配策略 |
| **为什么** | v0.1.0：订阅注册 key 是 `spot.order_book:BTC_USDT`，分发时用 `spot.order_book:update`，永远匹配不上，行情数据无法到达策略层。修复：三级匹配——精确 `channel:pair` → 事件 `channel:event` → 前缀 `channel`。 |
| **怎么测试** | 检查 `ws_manager.py` 中的 `_dispatch()` 或分发逻辑，验证三种 key 的构造和匹配 |
| **通过标准** | 源码中有三级匹配逻辑 + dry-run 中 market data 正常到达（mid_price > 0） |

### T3.3 — FATAL 2.3 / CRITICAL 3.6: ping loop 启动

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 ping 心跳 loop 在连接建立后被创建 |
| **为什么** | v0.1.0：`_ping_loop` 方法存在但从未被调用（无 `create_task`），WS 连接会因为 Gate.io 的超时策略而断开。修复：在 `_reconnect()` 中添加 `self._ping_task = asyncio.create_task(self._ping_loop())`。 |
| **怎么测试** | 检查 `ws_manager.py` 中 `_reconnect()` 或等效方法是否创建了 ping task |
| **通过标准** | 源码确认 ping task 被创建 |

### T3.4 — CRITICAL 3.1: API 密钥空值拒绝

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 live 模式启动时，若 API key 为空或为默认值 `REPLACE_ME`，程序拒绝启动并打印错误信息 |
| **为什么** | v0.1.0：不检查密钥有效性，密钥为空或默认值时仍然尝试连接交易所，可能导致无意义的网络请求或错误难以排查。修复：`run.py` 的 `_run_live()` 入口处检查 `api_key` 是否为空或 `REPLACE_ME`，不满足则 `sys.exit(1)`。 |
| **怎么测试** | 不设环境变量运行：`.venv/bin/python scripts/run.py --live --pair BTC_USDT --duration 5 2>&1; echo "exit=$?"` |
| **通过标准** | (1) 打印 `ERROR: API key not configured` (2) exit code = 1 (3) 不发起任何网络请求 |

### T3.5 — CRITICAL 3.2: 风控使用真实余额

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 Bot 能将真实余额传入 RiskManager.evaluate()，并按 base currency 拆分 |
| **为什么** | v0.1.0：余额未获取（`_balances` 为空），风控的 `_check_position()` 传入空列表，仓位上限检查形同虚设。v0.1.0：`_check_position` 把所有非零余额相加（不按交易对拆分），计算错误。修复：`Bot._refresh_balances()` 每 10 tick 调用 `fetch_all_balances()`；`RiskManager._check_position()` 按 pair 的 base currency 筛选余额（BTC_USDT → BTC）。 |
| **怎么测试** | 检查 `bot.py: _refresh_balances()` 存在（源码）；dry-run 是 mock client 无真实余额，live 模式下通过 preflight 日志验证 `preflight_balances` 日志输出 count > 0 |
| **通过标准** | (1) 源码确认 `_refresh_balances()` 存在 (2) 源码确认 `_check_position()` 按 base currency 过滤 (3) dry-run 无 crash（mock 兼容） |

### T3.6 — CRITICAL 3.3: cooldown 走 transition() 验证

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 `_enter_cooldown()` 调用 `self.transition(kind)` 而非直接赋值 `self._state = kind` |
| **为什么** | v0.1.0：`_enter_cooldown` 直接赋值绕过转换矩阵，允许从 EMERGENCY 等非法状态进入 cooldown。修复：改为调用 `transition(kind)` 走完整验证，非法转换抛出 `IllegalTransition`。 |
| **怎么测试** | 检查 `state_machine.py:_enter_cooldown()` 方法体 |
| **通过标准** | 源码中使用 `self.transition(kind)` 而非 `self._state = kind` |

### T3.7 — CRITICAL 3.4: 价格边界 ±20% 保护

| 项 | 内容 |
|----|------|
| **测试内容** | 验证订单价格超出 ref_price ±20% 时被拒绝 |
| **为什么** | v0.1.0：`_validate()` 只检查 `price > 0`，无误价保护。若 ref_price = 50000，订单价格 100000（翻倍）或 1（接近归零）仍能通过。修复：`_validate()` 新增 ±20% 边界检查，price < ref*0.8 或 > ref*1.2 时 raise ValueError。 |
| **怎么测试** | 检查 `order_engine.py:_validate()` 方法中的边界逻辑 + dry-run 日志中所有 `dry_run_would_place` 的价格在 40000-60000 范围内（mid ≈ 50000 ±20%） |
| **通过标准** | (1) 源码确认边界检查存在 (2) dry-run 中下单价格均在 ref_price ±20% 内 |

### T3.8 — CRITICAL 3.5: cooldown 死锁修复

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 COOLDOWN 状态下 tick 继续执行（不死锁），cooldown 到期后自动恢复 |
| **为什么** | v0.1.0：最关键的死锁 bug——tick 开头 `if state not in (RUNNING, IDLE): return` 让 cooldown 到期检查不可达。修复：COOLDOWN_* 状态允许继续执行 tick，检查 `can_place()` → `transition(RUNNING)`。 |
| **怎么测试** | 同 T2.2，dry-run 120s 后 grep 日志验证 cooldown 恢复链条 |
| **通过标准** | (1) 至少 1 次 COOLDOWN_PRICE_SPIKE 状态 (2) 对应的恢复 `state_transition: COOLDOWN_PRICE_SPIKE→RUNNING` 在合理时间内出现 (3) 无永久卡在 COOLDOWN 状态超过 10s |

### T3.9 — HIGH 4.1: Web Panel 安全绑定

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 Panel 默认绑定 127.0.0.1（仅本机可访问），且支持可选 token 认证 |
| **为什么** | v0.1.0：Panel 绑定 0.0.0.0，无需认证，任何能访问 39120 端口的人都能看到交易状态和操作面板。修复：默认 host="127.0.0.1"，通过环境变量 `GATE_WEB_TOKEN` 可选启用 Bearer token 认证。 |
| **怎么测试** | `ss -tlnp \| grep 39120` 检查监听地址；`curl -s http://127.0.0.1:39120/api/snapshot` 验证本机可访问 |
| **通过标准** | (1) ss 输出显示 `127.0.0.1:39120` 而非 `0.0.0.0:39120` (2) 本机 curl 正常返回 |

### T3.10 — HIGH 4.2: cancel_all 传入正确 pair

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 `cancel_all()` 接收非空 pair 参数 |
| **为什么** | v0.1.0：`cancel_all("")` 空字符串，无法匹配任何挂单，shutdown 后挂单残留交易所。修复：`cancel_all(self._pair)` 传入真实交易对，且先 reconcile 再撤单。 |
| **怎么测试** | 检查 `bot.py` 关机流程中 `cancel_all(self._pair)` 的 pair 参数 |
| **通过标准** | 源码中 `cancel_all` 调用传入的是 `self._pair` 而非空字符串 |

### T3.11 — HIGH 4.5: 风控状态持久化恢复

| 项 | 内容 |
|----|------|
| **测试内容** | 验证崩溃重启后能从 persistence 恢复风控状态 |
| **为什么** | v0.1.0：风控状态 `_halted` 等标志纯内存，进程崩溃后丢失，重启后可能在风控已触发的情况下重新交易。修复：`Bot` 构造函数中调用 `_load_recovery_state()` 从 DB 恢复上次状态，EMERGENCY 状态要求人工确认。 |
| **怎么测试** | 检查 `bot.py` 中 `_load_recovery_state()` 方法存在且被调用 |
| **通过标准** | (1) 源码确认恢复逻辑 (2) bot_state 表有持久化记录 |

### T3.12 — HIGH 4.7: SQLite fills 表 schema 一致

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 fills 表结构与面板查询一致 |
| **为什么** | v0.1.0：fills 表缺少 `side` 列，panel.py 的 SELECT 查询失败。修复：fills 表新增 `side` / `price` 列。 |
| **怎么测试** | `sqlite3 data/gate_trade.db "PRAGMA table_info(fills)"` 检查列名 |
| **通过标准** | 列名包含：`order_id, pair, side, fill_price, price, filled_size, created_at_ms` |

### T3.13 — HIGH 4.9: 告警通道正确接线

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 AlertManager 的 channel 注册逻辑：空 token 不注册 TelegramChannel，空 URL 不注册 WebhookChannel |
| **为什么** | v0.1.0：无论 token 是否为空都创建 TelegramChannel，导致空 token 告警失败。WebhookChannel 不存在（缺少实现）。修复：`_build_alert()` 检查 token/url 非空才注册 channel；新增 `WebhookChannel` 实现。 |
| **怎么测试** | 检查 `run.py:_build_alert()` 逻辑 |
| **通过标准** | (1) `telegram_bot_token` 为空时不创建 TelegramChannel (2) `alert_webhook_url` 为空时不创建 WebhookChannel (3) 两个 channel 存在且使用 httpx 异步 |

### T3.14 — MEDIUM 5.8: Telegram/Webhook 使用 httpx 异步

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 TelegramChannel 和 WebhookChannel 使用 `httpx.AsyncClient` 而非同步 `urllib` + `asyncio.to_thread` |
| **为什么** | v0.1.0：使用同步 urllib 包在 `asyncio.to_thread` 线程池中执行 HTTP 请求，效率低下且阻塞线程池。修复：改用原生异步 `httpx.AsyncClient`。 |
| **怎么测试** | 检查 `alert/manager.py` 中 `TelegramChannel.send()` 和 `WebhookChannel.send()` 方法 |
| **通过标准** | (1) 导入 `httpx` 而非 `urllib.request` (2) 使用 `async with httpx.AsyncClient() as client:` 模式 (3) 使用 `await client.post()` 异步调用 |

### T3.15 — MEDIUM 5.9: SQLite 路径遍历防护

| 项 | 内容 |
|----|------|
| **测试内容** | 验证面板 API 的 `db` 参数不能通过 `..` 遍历到其他目录 |
| **为什么** | v0.1.0：`/api/status?db=../etc/passwd` 可能造成路径遍历。修复：`_validate_db_path()` 检查 `..` 并返回 403。 |
| **怎么测试** | 启动面板后执行：`curl -s http://127.0.0.1:39120/api/status?db=../etc/passwd \| python3 -m json.tool` |
| **通过标准** | HTTP 403，body 包含 `"Database path not allowed"` |

---

## Phase 4: 实盘测试方案

> **准入条件**: Phase 1-3 全部通过，API 密钥已就绪。
> **核心原则**: 规模逐级放大，每阶段通过后才进入下一阶段。每笔订单金额可控、可追溯、可立即撤单。
> **测试账户**: Gate.io 现货账户，建议单独创建 API Key 专用于测试。

---

### 4.0 前置准备

#### 4.0.1 环境变量配置

| 变量 | 说明 | 设置方式 |
|------|------|---------|
| `GATE_EXCHANGE__API_KEY` | Gate.io API Key | `export`，**禁止写入文件** |
| `GATE_EXCHANGE__API_SECRET` | Gate.io API Secret | `export`，**禁止写入文件** |
| `GATE_WEB_TOKEN` | Panel 认证 token | `export`，可选但建议 |
| `GATE_WEB_HOST` | Panel 绑定地址 | 默认 127.0.0.1 |

```bash
# 设置示例（不要直接在命令行输入，通过密码管理器或安全方式导入）
export GATE_EXCHANGE__API_KEY="your_api_key_here"
export GATE_EXCHANGE__API_SECRET="your_api_secret_here"
export GATE_WEB_TOKEN="$(openssl rand -hex 16)"
```

#### 4.0.2 风控参数配置

创建实盘专用配置 `config/live.yaml`：

```yaml
# config/live.yaml — 实盘测试配置（gitignore，不提交）
exchange:
  api_key: ""    # 留空，通过环境变量注入
  api_secret: "" # 留空，通过环境变量注入

trading:
  target_pair: BTC_USDT
  base_inventory: 0.0
  quote_inventory: 0.0

risk:
  max_position_notional: 10.0       # 初始极小值，逐阶段放大
  max_order_size_notional: 1.0      # 初始极小值
  max_open_orders: 2                # 初始极小值
  cooldown_fill_ms: 2000
  cooldown_cancel_ms: 1000
  cooldown_self_trade_ms: 5000
  flash_crash_threshold_pct: 5.0

rate_limit:
  burst: 10
  rate: 8.0
  max_wait_sec: 5.0
```

#### 4.0.3 前置确认清单

| # | 检查项 | 确认方式 | 状态 |
|---|--------|---------|------|
| E1 | API Key 已创建，有 Spot 交易权限 | Gate.io → API Management → 权限列表 | [ ] |
| E2 | API Key 已绑定 IP 白名单 | Gate.io → API Management → IP Whitelist | [ ] |
| E3 | API Secret 仅通过环境变量注入，不在任何文件明文 | `grep -r "$SECRET" config/ src/` 无输出 | [ ] |
| E4 | 交易对存在且有足够流动性 | Gate.io 市场页面确认 BTC_USDT 日成交量 | [ ] |
| E5 | 账户有足够 USDT 余额（≥ $100 用于测试） | Gate.io Wallet 页面 | [ ] |
| E6 | 面板认证 token 已设置 | `echo $GATE_WEB_TOKEN` 非空 | [ ] |
| E7 | 紧急撤单方式已确认并测试 | 登录 Gate.io Web → 手动撤单功能可用 | [ ] |
| E8 | 监控面板可访问 | 浏览器打开 http://127.0.0.1:39120 | [ ] |
| E9 | `config/live.yaml` 中风险参数已设为最小值 | 检查 max_position=10, max_order=1, max_orders=2 | [ ] |

---

### 4.1 阶段 A: API 密钥验证

验证密钥有效性和基本连通性，**不启动 bot 主循环**。

| 项 | 内容 |
|----|------|
| **测试内容** | 密钥格式验证 + 空密钥拒绝 + 交易所 API 连通性 |
| **为什么** | v0.1.0 CRITICAL 3.1：API 密钥明文存储，空密钥或默认值 `REPLACE_ME` 不拒绝，导致启动后全是认证错误。修复后 (1) 密钥通过环境变量注入 (2) 空密钥启动立即 `sys.exit(1)` (3) 不向日志输出密钥内容。 |
| **怎么测试** | |

**T4A.1 — 空密钥拒绝**

```bash
# 确认环境变量未设置
unset GATE_EXCHANGE__API_KEY
unset GATE_EXCHANGE__API_SECRET
.venv/bin/python scripts/run.py --live --pair BTC_USDT --duration 5 2>&1; echo "exit=$?"
```

| 通过标准 | (1) 打印 `ERROR: API key not configured` (2) exit code = 1 (3) 无任何网络请求 |

**T4A.2 — 密钥格式检查**

```bash
# 检查密钥不为默认值
[ "$GATE_EXCHANGE__API_KEY" != "REPLACE_ME" ] && echo "OK: key set" || echo "FAIL: key is default"
[ -n "$GATE_EXCHANGE__API_SECRET" ] && echo "OK: secret set" || echo "FAIL: secret empty"
```

| 通过标准 | (1) key 非空 (2) key 非 REPLACE_ME (3) secret 非空 |

**T4A.3 — 交易所连通性**

```bash
# 用 curl 测试连通（不通过 bot 代码）
curl -s -H "KEY: $GATE_EXCHANGE__API_KEY" \
  "https://api.gateio.ws/api/v4/spot/accounts" 2>&1 | head -5
```

| 通过标准 | 返回 JSON 数组，包含账户余额数据，无 401/403 |

---

### 4.2 阶段 B: Preflight 全链路（无挂单，15 秒）

| 项 | 内容 |
|----|------|
| **测试内容** | 走完完整 preflight 流程（WS 连接 → 行情数据 → 余额获取 → 订单对账），在 bot 进入主循环后马上停止，**确保不产生任何挂单** |
| **为什么** | v0.1.0 FATAL 2.1：`WsManager.connect()` 阻塞导致 preflight 之前的代码都跑不到。修复后 connect 非阻塞 + preflight 四步检查。15 秒内 strategy 可能下发 1-2 个 desired order，需关注。 |
| **怎么测试** | |

```bash
GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \
  .venv/bin/python scripts/run.py \
  --live --pair BTC_USDT \
  --duration 15 --tick-interval 0.5 \
  --config config/live.yaml \
  --data-dir data/live_test \
  2>&1 | tee /tmp/gate_4b.log
```

**关键日志逐条检查**:

| 序号 | 预期日志 | 验证点 |
|------|---------|--------|
| 1 | `live_mode_initializing` | 启动流程开始 |
| 2 | `preflight_start` | preflight 进入 |
| 3 | `preflight_ws_ready` | WS 连接成功（非阻塞 connect 修复） |
| 4 | `preflight_market_data_ready, mid=XXXXX` | 行情数据到达（dispatch key 匹配修复） |
| 5 | `preflight_balances, count=N (N>0)` | 余额获取成功（真实余额传入风控） |
| 6 | `preflight_orders_clean` 或 `preflight_orphans` | reconcile 完成 |
| 7 | `preflight_passed` | 四步全过 |
| 8 | `bot_started` | Bot 进入主循环 |

**通过标准**:
- [ ] 7 条关键日志全部出现
- [ ] mid 价格与交易所实时价格一致（偏差 < 0.5%）
- [ ] balances count ≥ 1
- [ ] 无 `error` 级别日志（`spike_detected` warning 除外）
- [ ] 日志中无 `order_placed`（无实际下单）
- [ ] 进程正常退出 code 0

---

### 4.3 阶段 C: 单订单生命周期（30 秒，最小金额）

| 项 | 内容 |
|----|------|
| **测试内容** | 下发**单笔最小金额订单**，验证 下单→交易所确认→本地跟踪→撤单 完整闭环 |
| **为什么** | 这是从 0 到 1 的关键一步。验证：(1) Gate.io 下单 API 正确调用 (2) 订单在交易所可见 (3) 本地状态与交易所一致 (4) client_order_id tag 正确设置 (5) 关机撤单生效 (6) 价格在 ref_price ±20% 保护范围内 (7) 限速令牌桶正常工作。 |
| **风控参数** | `max_order_size_notional: 1.0`（≈ $1 极小单），`max_open_orders: 1` |
| **怎么测试** | |

**配置调整**: 修改 `config/live.yaml`：
```yaml
risk:
  max_order_size_notional: 1.0    # $1 极小单
  max_position_notional: 5.0
  max_open_orders: 1
```

```bash
GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \
  .venv/bin/python scripts/run.py \
  --live --pair BTC_USDT \
  --duration 30 --tick-interval 0.5 \
  --config config/live.yaml \
  --data-dir data/live_test \
  2>&1 | tee /tmp/gate_4c.log
```

**运行中操作**（另一个终端）:

```bash
# 实时查看 bot 状态
watch -n 2 'curl -s http://127.0.0.1:39120/api/snapshot | python3 -m json.tool'

# 查看挂单
watch -n 2 "curl -s -H 'KEY: $GATE_EXCHANGE__API_KEY' \
  'https://api.gateio.ws/api/v4/spot/open_orders?currency_pair=BTC_USDT' | python3 -m json.tool"
```

**关机后验证**:

```bash
# 1. 确认交易所挂单已全部取消
curl -s -H "KEY: $GATE_EXCHANGE__API_KEY" \
  "https://api.gateio.ws/api/v4/spot/open_orders?currency_pair=BTC_USDT"

# 2. 检查数据库中的订单记录
sqlite3 data/live_test/gate_trade.db \
  "SELECT order_id, side, price, size, status FROM orders"

# 3. 检查事件日志
sqlite3 data/live_test/gate_trade.db \
  "SELECT event_type, json_extract(event_data, '$.side') as side FROM event_log WHERE event_type='order_place'"
```

**通过标准**:
- [ ] 至少 1 条 `order_placed` 日志
- [ ] order_placed 日志中 `price` 在 ref_price ±20% 范围内
- [ ] 订单在交易所可见（curl 返回非空列表）
- [ ] shutdown 日志中 `all_cancelled, count=1` 或逐个 `order_cancelled`
- [ ] shutdown 后交易所 open_orders 返回空数组 `[]`
- [ ] DB orders 表中订单状态为 `cancelled`
- [ ] 无 `error` 级别日志
- [ ] `rate_limit_skip` 出现不超过 2 次（限频为正常行为）

---

### 4.4 阶段 D: Accumulator 阶梯挂单（2 分钟，多单管理）

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 Accumulator 策略的多档阶梯挂单：正确的 rung 数量、价格间距、订单大小，以及价格变动后的阶梯调整（取消旧单 + 放置新单） |
| **为什么** | Accumulator 是核心策略。验证：(1) 5 档阶梯正确放置 (2) 每档价格间距 = rung_spacing_ticks * tick_size (3) 当 ref_price 变化时旧阶梯被取消、新阶梯被放置 (4) 订单数不超过 max_open_orders 上限 (5) reconcile 正确跟踪订单状态变化。v0.1.0 HIGH 4.2：cancel_all 空字符串无法撤单，修复后必须传入正确 pair。 |
| **风控参数** | `max_order_size_notional: 2.0`，`max_open_orders: 5` |
| **怎么测试** | |

**配置调整**:
```yaml
risk:
  max_order_size_notional: 2.0
  max_position_notional: 10.0
  max_open_orders: 5
```

```bash
GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \
  .venv/bin/python scripts/run.py \
  --live --pair BTC_USDT \
  --duration 120 --tick-interval 0.5 \
  --config config/live.yaml \
  --data-dir data/live_test \
  2>&1 | tee /tmp/gate_4d.log
```

**运行中检查**:

```bash
# 每隔 10 秒抓一次快照，观察订单列表变化
for i in $(seq 1 12); do
  echo "=== Tick $i ==="
  curl -s http://127.0.0.1:39120/api/snapshot | python3 -c "
import sys, json
s = json.load(sys.stdin)
print(f'state={s[\"state\"]} open_orders={s[\"open_orders\"]}')
for o in s.get('order_list', []):
    print(f'  {o[\"side\"]} @ {o[\"price\"]} x{o[\"size\"]}')
"
  sleep 10
done
```

**日志分析**:

```bash
# 统计阶梯放置情况
grep "order_placed" /tmp/gate_4d.log | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        print(f'{d[\"side\"]} @ {d[\"price\"]:.2f} x{d[\"size\"]}')
    except: pass
"

# 检查每次阶梯调整是否先取消旧单
grep -E "order_cancelled|all_cancelled|order_placed" /tmp/gate_4d.log | head -30
```

**通过标准**:
- [ ] 至少 1 轮完整的阶梯放置（5 档买单）
- [ ] 每档价格严格递减（rung_spacing_ticks=5 * tick_size=0.01 = 0.05）
- [ ] 价格波动后旧阶梯被 cancel、新阶梯被 place（cancel 先于 place）
- [ ] 任意时刻 open_orders ≤ max_open_orders (5)
- [ ] 所有挂单价格在 ref_price ±20% 范围内
- [ ] shutdown 后交易所无残留挂单
- [ ] `all_cancelled` 的 pair 参数为 `BTC_USDT`（非空字符串）

---

### 4.5 阶段 E: 风控行为验证（5 分钟，模拟触发）

| 项 | 内容 |
|----|------|
| **测试内容** | 验证三类风控触发和恢复：(1) 订单数上限 (2) 仓位上限 (3) 价格闪崩 cooldown |
| **为什么** | v0.1.0 CRITICAL 3.2：余额空传入导致风控虚设。v0.1.0 CRITICAL 3.5：cooldown 永久死锁。v0.1.0 HIGH 4.6：闪崩阈值硬编码。修复后 (1) 余额按 base currency 拆分传入 (2) cooldown 到期自动恢复 (3) 阈值从配置读取。此项测试需要设置极低的风控参数来主动触发。 |
| **风控参数** | 极低值以确保触发 |
| **怎么测试** | |

**配置调整**（故意设低以触发风控）:
```yaml
risk:
  max_order_size_notional: 2.0
  max_position_notional: 5.0     # 极低，容易触发
  max_open_orders: 2             # 极低，容易触发
  cooldown_fill_ms: 3000
  flash_crash_threshold_pct: 1.0 # 极低，容易触发闪崩检测
```

**T4E.1 — 订单数上限触发**

```bash
# 设置 max_open_orders=1，Accumulator 尝试放置 5 档 → 第 2 档起应被拒绝
```

| 通过标准 | (1) 日志出现 `risk_halt` 或 order count 相关 warning (2) 实际挂单数 ≤ max_open_orders (3) 不会因此 crash |

**T4E.2 — 价格尖峰 cooldown 恢复**

```bash
# 在真实行情中等待自然波动触发 spike，或通过观察日志确认
grep -E "spike_detected|cooldown|COOLDOWN_PRICE_SPIKE" /tmp/gate_4e.log
```

| 通过标准 | (1) 若触发 spike_detected → state 变为 COOLDOWN_PRICE_SPIKE (2) cooldown 到期后 state 恢复 RUNNING（非永久卡住）(3) 状态转换走 `state_transition` 日志（非直接赋值） |

**T4E.3 — 闪崩检测阈值配置化**

| 通过标准 | 日志中 `flash_crash_threshold_pct` 的值与 `config/live.yaml` 一致（1.0），非硬编码 5.0 |

---

### 4.6 阶段 F: 持久化与状态恢复（跨进程）

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 (1) 运行中状态实时持久化 (2) 正常关机后状态正确保存 (3) 重新启动后状态恢复 (4) 异常 kill 后重启不丢失风控状态 |
| **为什么** | v0.1.0 HIGH 4.3：`load_state()` 对未知状态值直接崩溃。v0.1.0 HIGH 4.5：风控状态纯内存、崩溃后丢失。修复：(1) load_state 容错降级 INIT (2) `_load_recovery_state()` 从 DB 恢复 cooldown/emergency 状态 (3) shutdown 持久化最终状态。 |
| **怎么测试** | |

**T4F.1 — 正常关机状态保存**

```bash
# 1. 运行 60 秒 dry-run
.venv/bin/python scripts/run.py --pair BTC_USDT --duration 60 --data-dir data/live_test 2>&1

# 2. 检查 bot_state 表
sqlite3 data/live_test/gate_trade.db "SELECT * FROM bot_state"
```

| 通过标准 | bot_state 表包含 `SHUTDOWN` 状态 |

**T4F.2 — 异常 kill 后重启恢复**

```bash
# 1. 启动 dry-run 后台运行
.venv/bin/python scripts/run.py --pair BTC_USDT --duration 300 --data-dir data/live_test &
PID=$!
sleep 5

# 2. 模拟崩溃
kill -9 $PID
sleep 2

# 3. 重新启动
.venv/bin/python scripts/run.py --pair BTC_USDT --duration 30 --data-dir data/live_test 2>&1 | grep -i "recovery\|load_state\|restored"

# 4. 检查恢复的状态
sqlite3 data/live_test/gate_trade.db "SELECT state, sub_state FROM bot_state"
```

| 通过标准 | (1) 重启后从 DB 读取了上次状态 (2) 若是 COOLDOWN/EMERGENCY 状态则保留不自动恢复交易 (3) 若是 INIT/IDLE/RUNNING 则正常启动 |

**T4F.3 — orders 表持久化**

```bash
# 检查 orders 表在多次运行间的数据完整性
sqlite3 data/live_test/gate_trade.db "SELECT COUNT(*), status FROM orders GROUP BY status"
```

| 通过标准 | orders 表保留历史订单记录，跨进程不丢失 |

---

### 4.7 阶段 G: 告警通道验证

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 AlertManager 在风控事件时能正确发送告警 |
| **为什么** | v0.1.0 HIGH 4.9：alert webhook 接线错误，channel 未正确初始化。修复：(1) `_build_alert()` 检查 token/url 非空才注册 (2) WebhookChannel 已实现 (3) 改用 httpx 异步。 |
| **怎么测试** | |

**T4G.1 — Webhook 通道**

```yaml
# config/live.yaml 中配置测试 webhook（如 Slack/Discord 或 webhook.site）
monitoring:
  alert_webhook_url: "https://webhook.site/your-test-url"
```

```bash
# 触发风控事件（如设置极低 max_open_orders），观察 webhook 是否收到 POST
```

| 通过标准 | (1) webhook 收到 JSON POST 请求 (2) JSON 包含 `level, subject, body` 字段 (3) 日志中 `alert_sent, channels=1` |

**T4G.2 — 空 URL 不创建 Channel**

| 通过标准 | 若 `alert_webhook_url` 为空，日志不出现 `alert_sent`（因为 _channels 列表为空），只出现 `alert_no_channels` |

---

### 4.8 阶段 H: 常规规模运行（30 分钟）

| 项 | 内容 |
|----|------|
| **测试内容** | 以生产参数运行 30 分钟，验证长时间稳定性 |
| **为什么** | 验证系统在接近生产环境配置下的长时间行为：内存稳定、DB 不膨胀、无累积错误。 |
| **风控参数** | 恢复正常值 |
| **怎么测试** | |

```yaml
risk:
  max_order_size_notional: 10.0
  max_position_notional: 100.0
  max_open_orders: 10
  flash_crash_threshold_pct: 5.0
```

```bash
GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \
  .venv/bin/python scripts/run.py \
  --live --pair BTC_USDT \
  --duration 1800 --tick-interval 0.5 \
  --config config/live.yaml \
  --data-dir data/live_test \
  2>&1 | tee /tmp/gate_4h.log
```

**每 5 分钟检查**:

```bash
# 内存使用
ps aux | grep run.py | awk '{print "RSS:", $6/1024, "MB"}'

# 订单统计
grep -c "order_placed" /tmp/gate_4h.log
grep -c "order_cancelled" /tmp/gate_4h.log

# 错误统计
grep -c '"level": "error"' /tmp/gate_4h.log
grep -c '"level": "warning"' /tmp/gate_4h.log

# 状态分布
grep "state_transition" /tmp/gate_4h.log | tail -20
```

**通过标准**:
- [ ] 运行满 30 分钟无 crash
- [ ] 内存使用稳定（波动 < 20%）
- [ ] error 日志数 = 0
- [ ] warning 日志仅为 spike_detected / rate_limit_skip（预期行为）
- [ ] 风控无假阳性 halt
- [ ] 每轮 cooldown 在 5s 内恢复
- [ ] shutdown 后交易所无残留
- [ ] DB 文件大小合理（< 50MB）

---

### 4.9 阶段 I: 异常场景（逐个执行，谨慎操作）

> **警告**: 以下测试会主动引入故障，每次只执行一个，确认恢复后再执行下一个。

**T4I.1 — WS 断线重连**

| 测试内容 | 阻断到 ws.gateio.ws 的连接，观察重连 |
|----------|--------------------------------------|
| 为什么 | 生产环境中 WS 断线是最常见的故障。v0.1.0 FATAL 2.3：ping loop 从未启动导致连接静默断开。修复后后台 reconnect task + ping loop + 自动 resubscribe。 |
| 怎么测试 | `sudo iptables -A OUTPUT -d $(dig +short ws.gateio.ws) -j DROP` 阻断 30s 后 `iptables -D ...` 恢复 |
| 通过标准 | RECONNECT 状态 → 自动重连 → 恢复 RUNNING → 行情数据恢复 → 策略继续下单 |

**T4I.2 — API 限频降级**

| 测试内容 | 设置 burst=1, rate=0.5 极低限速，观察 order engine 行为 |
|----------|---------------------------------------------------------|
| 为什么 | v0.2.0 改进：令牌桶超时返回 False 而非 raise，order engine 记录 warning 跳过 |
| 怎么测试 | 修改 rate_limit 配置为 burst=1, rate=0.5, max_wait_sec=1 |
| 通过标准 | `rate_limit_skip` warning 日志 → 不 crash → 后续 tick 正常下单 |

**T4I.3 — 交易所 429 限频**

| 测试内容 | 观察真实 429 响应的处理 |
|----------|------------------------|
| 为什么 | Gate.io spot API 限制 200 req/10s，高负载下可能触发 |
| 通过标准 | `rate_limit_exceeded` 日志 → 不 crash → 自动退避 |

**T4I.4 — 手动中断测试**

| 测试内容 | 运行中按 Ctrl+C，验证优雅关机 + 撤单 |
|----------|-------------------------------------|
| 为什么 | 运维人员需要能安全停止 bot。 |
| 怎么测试 | 启动 3 分钟后 `kill <PID>`（SIGTERM） |
| 通过标准 | shutdown 流程完整执行 → 所有挂单被取消 → DB 关闭 |

---

### 4.10 阶段 J: 多交易对扩展（可选）

| 项 | 内容 |
|----|------|
| **测试内容** | 在 BTC_USDT 稳定运行后，添加第二个交易对（如 ETH_USDT） |
| **为什么** | 验证多交易对场景：余额拆分、独立风控、策略隔离。 |
| **注意** | 当前 bot 实例仅支持单交易对。多交易对需要运行多个 bot 实例，共享同一个 persistence。 |

---

## Phase 5: 异常场景补充测试

### T5.1 — 数据库写入失败容错

| 项 | 内容 |
|----|------|
| **测试内容** | DB 只读时主循环不 crash |
| **为什么** | DB 写入失败不应导致交易循环崩溃。 |
| **怎么测试** | (dry-run) `chmod 444 data/gate_trade.db` 后运行 |
| **通过标准** | 日志 error 但主循环继续运行，tick 不中断 |

### T5.2 — 日志脱敏验证

| 项 | 内容 |
|----|------|
| **测试内容** | 确认 API 密钥不出现在任何日志中 |
| **为什么** | v0.2.0 改进：`_handle_api_error` 中 `exc.body` 截断为 200 字符，不输出完整响应体。 |
| **怎么测试** | `grep -i "$GATE_EXCHANGE__API_KEY" /tmp/gate_*.log` 应无匹配 |
| **通过标准** | 所有日志文件中无 API key/secret 出现 |

---

## 测试数据记录表

每个阶段结束后填写：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段:     4___ (_________)
日期:     2026-05-05 ___:___
运行时长:  ___s   交易对: _______
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总 tick:       ___    下单总数: ___
成交总数:      ___    撤单总数: ___
open_orders 峰值: ___    max orders 实际上限: ___
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
价格尖峰:      ___    cooldown 触发: ___
cooldown 恢复:  ___    平均恢复时间: ___s
风控 halt:      ___    halt 原因: _________
WS 重连:       ___    429 次数: ___
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
error:         ___    warning: ___
内存峰值:      ___MB  DB 大小: ___KB
最终状态:      ___    退出码: ___
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
通过/失败:      [ ]
备注:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 应急操作手册

### 立即停止

```bash
# 1. 找到进程
ps aux | grep "scripts/run.py"

# 2. 优雅停止（触发 shutdown → 撤单 → 保存状态 → 关闭 DB）
kill <PID>

# 3. 等待 10 秒，如果仍未退出
sleep 10
kill -9 <PID>
```

### 紧急撤单

```bash
# 方式 1: 通过 Gate.io Web → Orders → Cancel All（最快最可靠）

# 方式 2: 通过 API
PAIR="BTC_USDT"
curl -X DELETE \
  "https://api.gateio.ws/api/v4/spot/orders?currency_pair=$PAIR" \
  -H "KEY: $GATE_EXCHANGE__API_KEY" \
  -H "SIGN: $(echo -n "DELETE\n/api/v4/spot/orders\ncurrency_pair=$PAIR\n$(date +%s)" | openssl dgst -sha512 -hmac "$GATE_EXCHANGE__API_SECRET" | cut -d' ' -f2)"

# 方式 3: 检查残留
curl -s -H "KEY: $GATE_EXCHANGE__API_KEY" \
  "https://api.gateio.ws/api/v4/spot/open_orders?currency_pair=$PAIR"
```

### 恢复正常交易

```bash
# 确认交易所无残留挂单后，重新启动
GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \
  .venv/bin/python scripts/run.py --live --pair BTC_USDT ...
```

---

## 通过标准汇总

| 阶段 | 测试项 | 通过条件 | 依赖 |
|------|--------|---------|------|
| Phase 1 | 4 | 4/4 全部 | - |
| Phase 2 | 7 | 7/7 全部 | Phase 1 |
| Phase 3 | 15 | 15/15 全部 | Phase 1 |
| **4A** | 3 | API 拒绝 + 格式 + 连通 | - |
| **4B** | 1 | 7 条关键日志全过，无下单 | 4A |
| **4C** | 1 | 下单+撤单干净，DB 记录一致 | 4B |
| **4D** | 1 | 阶梯正确，cancel_all pair 非空 | 4C |
| **4E** | 3 | 订单上限 + cooldown 恢复 + 阈值 | 4D |
| **4F** | 3 | 状态持久化 + crash 恢复 + orders | 4B |
| **4G** | 2 | webhook POST + 空 URL 不注册 | 4B |
| **4H** | 1 | 30min 无异常，内存稳定 | 4C-4G |
| **4I** | 4 | WS / 限频 / 429 / Ctrl+C | 4H |
| Phase 5 | 2 | DB 容错 + 日志脱敏 | - |

**Phases 1-3 全部通过后方可进入 Phase 4。**
**Phase 4 阶段 A→B→C→D→E→F→G→H→I 必须顺序通过，不可跳过。**
**每个阶段的"通过标准"全部打勾后才能进入下一个阶段。**

---

> 测试方案基于 `audit/AUDIT_COMPREHENSIVE.md` 的 27 个问题制定。
> 每个测试用例明确了测试内容、测试原因（映射到具体审计问题）、测试方法和通过标准。
> Phase 4 参考了 `docs/IMPROVEMENT_PLAN.md` 中 Phase 5 灰度发布流程。
