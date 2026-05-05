# Gate Trade 三份审计报告对比结论

项目：`https://github.com/poolarge/gate-trade`

对比日期：2026-05-05 UTC

对比对象：

- `AUDIT_deepseek-v4-pro.md`
- `AUDIT_DS.md`
- `AUDIT_CODEX.md`

未纳入范围：

- `UNIFIED_PLAN_deepseek-v4-pro.md`
- `IMPROVEMENT_deepseek-v4-pro.md`
- `IMPROVEMENT_DS.md`
- `IMPROVEMENT_CODEX.md`

签名：Codex · 风控拆解工程师

## 1. 总体判断

三份审计报告在核心结论上高度一致：当前项目适合作为策略原型和测试骨架继续推进，但不应直接运行实盘。三份报告都认为，当前最重要的工作不是优化策略参数，而是补齐 live 数据链路、真实账户风控、撤单保护、面板访问控制和实盘客户端测试。

三份报告的侧重点不同：

- `AUDIT_deepseek-v4-pro.md` 覆盖面最广，列出较多中低风险和架构维护问题，但部分描述与当前代码存在偏差。
- `AUDIT_DS.md` 更精炼，问题优先级清晰，测试数量口径更接近当前实测结果。
- `AUDIT_CODEX.md` 更偏实证审计，包含本地复现、命令验证和当前环境下的实际运行结果。

## 2. 三份报告共同确认的问题

| 问题 | Deepseek-v4-pro | AUDIT_DS | Codex | 综合判断 |
|------|:---:|:---:|:---:|------|
| 当前不建议直接实盘 | 是 | 隐含是 | 是 | 共识最高 |
| `Bot._tick()` 风控传入空 `balances` | 是 | 是 | 是 | 必须优先修复 |
| 真实账户余额未进入持仓上限计算 | 是 | 是 | 是 | 实盘资金风险 |
| Web 面板默认 `0.0.0.0` 且无认证 | 是 | 是 | 是 | 信息暴露风险 |
| shutdown 时 `cancel_all("")` 风险 | 是 | 是 | 是 | 可能残留交易所挂单 |
| `GateIoClient` / `WsManager` 缺关键测试 | 是 | 是 | 是 | live 路径不可放心 |
| 需要补齐 live 风控闭环 | 是 | 是 | 是 | 实盘前置条件 |

这些问题应进入第一批修复范围。其中风控空余额、Web 面板暴露、shutdown 撤单问题属于跨报告强共识，优先级应高于策略层优化。

## 3. Deepseek-v4-pro 与 AUDIT_DS 共同提到，但 Codex 未重点展开的点

| 问题 | 说明 | 建议处理 |
|------|------|----------|
| `_enter_cooldown()` 绕过 `transition()` | 两份 DS 报告都认为冷却状态直接赋值破坏状态机契约。 | 纳入状态机修复批次。 |
| 订单价格缺少上下限保护 | 两份 DS 都建议基于参考价限制价格偏离。 | 纳入订单安全模块。 |
| WebSocket ping loop 定义但未启动 | 两份 DS 都提到。 | 与 WebSocket 生命周期重构一起修。 |
| 风控状态崩溃重启后丢失 | 两份 DS 都认为 unsafe state 不应自动恢复交易。 | 纳入恢复策略。 |
| `load_state()` 遇到损坏状态会崩溃 | 两份 DS 都提到。 | 加 try/except 和降级日志。 |
| `run.py` 与 `healthcheck.py` 配置加载不一致 | 两份 DS 都提到。 | 统一配置加载入口。 |
| 闪崩阈值硬编码 5% | 两份 DS 都提到。 | 改为配置项并按交易对覆盖。 |
| `Any` 类型和 Web 面板访问私有属性 | 两份 DS 都提到维护性问题。 | 用 Protocol 和 `Bot.snapshot()` 解耦。 |
| `_flatten` 重复、`.gitignore` 缺 `data/`、Markout pending 丢失 | 两份 DS 都有。 | 作为中风险维护项处理。 |

这些点多数成立，但实施时要按当前仓库的实际状态名、异常类和类型定义校正。例如当前状态名是 `RUNNING`、`COOLDOWN_PRICE_SPIKE`，不能直接照搬报告中出现的 `ACTIVE`、`COOLDOWN_FLASH_CRASH` 等名称。

## 4. Codex 独有或验证更充分的点

| 问题 | 证据 | 重要性 |
|------|------|--------|
| live 模式 `await client.connect()` 会阻塞后续启动 | 本地 WS server 复现 `connect_timed_out_blocking`。 | 直接导致 live bot 无法进入主循环。 |
| WebSocket 订阅分发 key 不匹配 | 注册 key 是 topic，分发 key 是 event，队列收不到消息。 | live 行情流进入不了 `LiveMarketData`。 |
| spike cooldown 可能永久卡住主循环 | 从 `bot.py` 与 `state_machine.py` 执行顺序推导。 | 一次尖峰保护后可能不恢复。 |
| SQLite `fills` schema 与 Web/日报查询不一致 | dry-run 生成真实 DB 后复现 `no such column: side`。 | 面板和日报会失效。 |
| systemd unit 指向不存在的 `gate_trade.main` | 本地运行验证 `No module named gate_trade.main`。 | 部署文件不可用。 |
| alert webhook 配置虚接 | 配置非空时实际添加空 Telegram token。 | 关键告警不可达。 |
| dev 依赖缺 `httpx` | 初次跑 pytest 复现收集失败，补装后 `469 passed`。 | CI 和新环境会失败。 |
| GitHub 工程治理缺口 | 查询 GitHub API：无 workflow、无 license、分支未保护等。 | 发布治理风险。 |
| ruff / bandit / pip-audit 实测结果 | 给出实际命令输出。 | 工具链状态明确。 |

这些点更贴近当前本机代码和实测结果，适合作为综合报告中的“已验证问题”。

## 5. AUDIT_DS 独有点

| 问题 | 说明 | 建议 |
|------|------|------|
| Smasher 模块未集成主循环 | `smasher/` 有模块和测试，但 `bot.py` 未调用。 | 在 live 数据链路稳定后评估接入。 |
| TelegramChannel 使用同步 `urllib` | 通过 `asyncio.to_thread` 包装同步请求。 | 低优先级，可后续换 `httpx`。 |
| 正面评价更具体 | 提到 Smasher 统计验证、SSE 面板、Replay 引擎等。 | 可保留为项目优势。 |
| 测试数量口径较新 | 写 469 个测试、83 个测试文件。 | 比 Deepseek-v4-pro 的“156 个测试”更接近实测。 |

AUDIT_DS 的优点是短、准、偏当前状态，但没有覆盖 Codex 复现出的 WS 分发 key、SQLite schema、systemd 入口等问题。

## 6. Deepseek-v4-pro 独有点

| 问题 | 说明 | 校准意见 |
|------|------|----------|
| API 密钥明文存储作为 CRITICAL | 文档已脱敏；当前 Git 跟踪文件没有真实 key。 | 若本机仍有 `config/local.yaml` 且含真实 key，仍需立即轮换。 |
| 项目模块概览更完整 | 列出 client、config、market、order、risk、state 等模块。 | 可用于理解架构。 |
| 低风险清单更长 | 包含 API 错误响应日志、`save_fill` 并发假设、`_by_tag` 残留、place/reconcile 竞态等。 | 可作为后续 backlog。 |
| “缺少进程管理配置” | 当前仓库已有 `systemd/gate-trade.service`。 | 真实问题是 systemd 入口不存在。 |

Deepseek-v4-pro 覆盖面最广，但部分细节与当前代码不一致。综合使用时应先做代码校验。

## 7. 准确性差异

| 维度 | Deepseek-v4-pro | AUDIT_DS | Codex |
|------|-----------------|----------|-------|
| 覆盖面 | 最广 | 中等 | 中等偏深 |
| 当前代码贴合度 | 有偏差 | 较贴合 | 最贴合 |
| 实证复现 | 少 | 少 | 多 |
| 测试/工具命令结果 | 口径偏旧 | 口径较新 | 有实际命令输出 |
| 架构维护建议 | 较多 | 中等 | 聚焦实盘安全 |
| 适合用途 | 发现池 | 精简风险清单 | 优先级和修复依据 |

## 8. 综合优先级

三份报告合并后，最优先的问题应排序如下：

1. 修复 live WebSocket 生命周期和订阅分发，确保行情能进入主循环。
2. 将真实 balances 和 exchange open orders 接入风控。
3. shutdown 使用真实 pair/tag 撤单，并验证交易所残留挂单。
4. Web 面板默认本地绑定并增加认证。
5. 增加订单价格偏离、单笔 notional、最小金额等安全校验。
6. 修复 spike cooldown 恢复逻辑和状态机 transition 语义。
7. 修复 SQLite fills schema 与 Web/日报查询不一致。
8. 修复 systemd entrypoint。
9. 补齐 `GateIoClient`、`WsManager`、`scripts/run.py` 的测试。
10. 补齐 CI、dev dependencies、GitHub 分支保护和 license。

## 9. 最终对比结论

三份报告不是互相替代关系，而是互补关系：

- Deepseek-v4-pro 适合作为“问题池”。
- AUDIT_DS 适合作为“精简风险清单”。
- Codex 审计结论适合作为“当前代码下的实证优先级”。

后续制定修复计划时，应以 Codex 的已验证问题作为 P0/P1 主线，吸收 DS 两份报告中的订单安全、状态机、崩溃恢复、配置加载、测试覆盖等补充项。

---

签名：Codex · 风控拆解工程师
