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

## Phase 4: Live 灰度假值测试

> **前置**: Phase 1-3 全部通过后，且 API 密钥已就绪，才进入此阶段。
> **原则**: 规模逐级放大，每阶段通过后才进入下一阶段。

### 4.0 前置确认清单

| # | 检查项 | 确认方式 |
|---|--------|---------|
| 4.0.1 | Gate.io API Key 已创建，有交易权限 | Gate.io Web → API Management |
| 4.0.2 | API Key 已绑定 IP 白名单 | Gate.io Web → API Management → IP Whitelist |
| 4.0.3 | API Secret 仅通过环境变量注入 | `env \| grep GATE_EXCHANGE__API` 确认存在 |
| 4.0.4 | 交易对已确定 | 用户确认（如 BTC_USDT） |
| 4.0.5 | 可用余额充足（USDT） | Gate.io Wallet 页面 |
| 4.0.6 | 止损方案已确认 | 手动盯盘 / 脚本自动撤单 |
| 4.0.7 | 紧急撤单方式已确认 | Gate.io Web 一键撤单 / API 撤单命令 |

### 4.1 阶段 4A: Preflight Only（10 秒，不挂单）

| 项 | 内容 |
|----|------|
| **测试内容** | 验证 WS 连接 → 行情接收 → 余额获取 → 订单对账流程全部通过，但不产生实际挂单 |
| **为什么** | 这是实盘的第一道防线。preflight 成功说明网络、鉴权、行情、余额全链路通。duration=10s 和 tick_interval=0.5s 约 20 个 tick，但由于 tick 中 dry_run=False 才会下单，我们需确认 duration 足够短不至于积累大量订单。实际上下单条件取决于 strategy desired orders 是否为空。缩短 duration 降低风险。 |
| **怎么测试** | ```bash<br>GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \<br>.venv/bin/python scripts/run.py --live --pair BTC_USDT --duration 10 --tick-interval 0.5 --data-dir data 2>&1<br>``` |
| **关键日志检查** | `preflight_ws_ready` → `preflight_market_data_ready` → `preflight_balances (count>0)` → `preflight_reconcile` → `preflight_passed` |
| **通过标准** | (1) 四个 preflight 阶段全部打印成功日志 (2) mid 价格合理（非 0 非负数）(3) balances 返回正确的余额 (4) 无 API 错误 |

### 4.2 阶段 4B: 极小单测试（30 秒，$0.001 BTC ≈ $50）

| 项 | 内容 |
|----|------|
| **测试内容** | 以最小 notional 挂单，验证完整的 下单→成交/撤单 闭环 |
| **为什么** | 验证下单路径完全正常：价格对齐、tag 生成、限速检查、价格边界、提交到交易所、本地状态跟踪、关机撤单。这是从 0 到 1 的关键一步。 |
| **参数配置** | `config/local.yaml`：<br>```yaml<br>risk:<br>  max_order_size_notional: 1.0<br>  max_position_notional: 10.0<br>  max_open_orders: 2<br>``` |
| **怎么测试** | ```bash<br>GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \<br>.venv/bin/python scripts/run.py --live --pair BTC_USDT --duration 30 --tick-interval 0.5 --data-dir data 2>&1<br>``` |
| **验证点** |  |
| 通过标准 | (1) 至少 1 个 `order_placed` 日志 (2) 订单价格在合理范围 (3) `bot_shutting_down` 后 `order_cancelled` 或 `all_cancelled` 日志 (4) 交易所挂单列表为空（登录 Gate.io 确认）(5) 无 error 级别日志 |

### 4.3 阶段 4C: 常规规模测试（10 分钟，多单）

| 项 | 内容 |
|----|------|
| **测试内容** | 以常规规模运行 10 分钟，验证多单管理、风控行为、长时间稳定性 |
| **为什么** | 验证系统在真实场景下的表现：风控是否产生假阳性、cooldown 机制是否正常工作、是否有内存泄漏。 |
| **参数配置** | ```yaml<br>risk:<br>  max_order_size_notional: 10.0<br>  max_position_notional: 50.0<br>  max_open_orders: 5<br>``` |
| **怎么测试** | ```bash<br>GATE_EXCHANGE__API_KEY=$KEY GATE_EXCHANGE__API_SECRET=$SECRET \<br>.venv/bin/python scripts/run.py --live --pair BTC_USDT --duration 600 --tick-interval 0.5 --data-dir data 2>&1 \| tee /tmp/gate_live_4c.log<br>``` |
| **通过标准** | (1) 运行满 10 分钟无 crash (2) 风控无假阳性 halt（检查无 `risk_halt` 或若出现则检查原因是否合理）(3) 如有 spike → cooldown 在 5s 内恢复 (4) fills 表有成交或 markout 数据 (5) 无 429 rate limit 错误 (6) shutdown 撤单干净 |

---

## Phase 5: 异常场景测试

测试系统在异常条件下的容错和恢复能力。

### T5.1 — WS 断线重连

| 项 | 内容 |
|----|------|
| **测试内容** | 模拟 WebSocket 连接断开，验证自动重连和状态恢复 |
| **为什么** | 生产环境中 WS 断线是常见现象。v0.1.0：WS 重连逻辑存在但未验证。v0.2.0：后台 reconnect task 应在断线后自动重连并恢复订阅。 |
| **怎么测试** | (仅 live) 运行时用 `iptables` 临时阻断到 `ws.gateio.ws` 的出站连接，30 秒后恢复，观察日志 |
| **预期行为** | RECONNECT 状态 → 自动重连成功 → 恢复 RUNNING → 行情数据恢复 |

### T5.2 — API 限频降级

| 项 | 内容 |
|----|------|
| **测试内容** | 令牌桶耗尽后的行为 |
| **为什么** | v0.1.0：`acquire()` 超时 raise `RateLimitExceeded` 硬错误。v0.2.0：返回 False，order engine 记录 warning 并跳过当前 placement。 |
| **怎么测试** | 检查 `rate_limiter.py: acquire()` 返回 False（非 raise） |
| **通过标准** | 遇到限频时日志 `rate_limit_skip` warning，不 crash |

### T5.3 — 数据库写入失败

| 项 | 内容 |
|----|------|
| **测试内容** | 数据库只读或磁盘满时，主循环不 crash |
| **为什么** | DB 写入失败不应导致交易循环崩溃。错误应被捕获并记录。 |
| **怎么测试** | (dry-run) `chmod 444 data/gate_trade.db` 后运行，观察 behavior |
| **预期行为** | 日志 error，但主循环继续运行，tick 不中断 |

### T5.4 — 进程 crash 后状态恢复

| 项 | 内容 |
|----|------|
| **测试内容** | `kill -9` 后重启，验证从 persistence 恢复上次状态 |
| **为什么** | v0.1.0 HIGH 4.5：崩溃后风控状态丢失，可能在不安全状态下重新交易。修复：`_load_recovery_state()` 从 DB 恢复状态。 |
| **怎么测试** | (dry-run) 运行中 `kill -9`，然后重新启动，检查日志中 recovery 相关信息 |
| **通过标准** | 重启日志包含 `recovery` 或 bot_state 从 DB 加载的记录 |

---

## 测试数据记录表

每个阶段结束后填写：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段:     Phase ___ (___)
时间:     2026-05-05 ___:___
运行时长: ___s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
tick 总数:      ___
下单总数:       ___
成交总数:       ___
撤单总数:       ___
价格尖峰次数:    ___
cooldown 次数:  ___
风控 halt 次数:  ___
WS 重连次数:     ___
error 日志数:    ___
warning 日志数:  ___
最终状态:       ___
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
通过/失败:      [ ]
备注:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 应急终止

遇到意外行为时立即执行：

```bash
# 优雅停止（触发 shutdown 撤单）
kill <PID>

# 强制停止
kill -9 <PID>

# 手动撤掉交易所所有挂单
curl -X DELETE \
  "https://api.gateio.ws/api/v4/spot/orders?currency_pair=BTC_USDT" \
  -H "KEY: $GATE_EXCHANGE__API_KEY" \
  -H "SIGN: $(...)"
# 或直接登录 Gate.io → Orders → Cancel All
```

---

## 通过标准汇总

| 阶段 | 测试数 | 通过条件 |
|------|--------|---------|
| Phase 1 | 4 | 4/4 全部 |
| Phase 2 | 7 | 7/7 全部 |
| Phase 3 | 15 | 15/15 全部 |
| Phase 4A | 1 | preflight 四步全过 |
| Phase 4B | 1 | 下单+撤单干净 |
| Phase 4C | 1 | 10min 无异常 |
| Phase 5 | 4 | 按需执行 |

**Phases 1-3 全部通过后方可进入 Phase 4。Phase 4A→4B→4C 必须顺序通过，不可跳过。**

---

> 测试方案基于 `audit/AUDIT_COMPREHENSIVE.md` 的 27 个问题制定。
> 每个测试用例明确了测试内容、测试原因（映射到具体审计问题）、测试方法和通过标准。
