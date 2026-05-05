# 三份审计报告差异对比

**对比日期**: 2026-05-05

| 属性 | AUDIT_deepseek-v4-pro.md | AUDIT_DS.md | Codex (web) |
|------|--------------------------|-------------|-------------|
| 审计模型 | Deepseek-v4-pro | DS | Codex |
| 审计对象 | `/home/monero/gate-trade` | `/home/monero/gate-trade` | `/home/ubuntu/gate-trade-DeepSeek` (GitHub clone) |
| 源文件数 | 29 | 70 | 未统计 |
| 测试数 | 156 | 469 | 469 |
| 审计方式 | 纯静态代码审查 | 纯静态代码审查 | **实际运行 + 静态分析** |
| ruff 结果 | 零警告 | 零警告 | **14 errors** (实际运行) |
| 严重等级 | 5 级 (CRITICAL→LOW) | 3 级 (CRITICAL→MEDIUM) | 2 级 (HIGH→MEDIUM) |
| 问题总数 | 20 | 16 | 9 |

---

## 三份报告共同发现

以下 **8 个问题** 在三份报告中均被识别：

| # | 问题 | Deepseek | DS | Codex |
|---|------|:---:|:---:|:---:|
| 1 | 风控传入 `balances=[]`，仓位上限检查完全失效 | CRITICAL | CRITICAL | HIGH |
| 2 | Web 面板默认 `0.0.0.0` 无认证，公网可访问 | HIGH | HIGH | HIGH |
| 3 | `cancel_all("")` 传空字符串，关机时无法撤单 | HIGH | HIGH | HIGH |
| 4 | WebSocket ping loop 未启动 / WS 架构问题 | CRITICAL | CRITICAL | HIGH* |
| 5 | `_enter_cooldown` 绕过 `transition()` 状态验证 | CRITICAL | CRITICAL | (相关) |
| 6 | 订单价格无上下限边界保护 | CRITICAL | CRITICAL | -- |
| 7 | `load_state` 对损坏状态字符串抛 ValueError | HIGH | HIGH | -- |
| 8 | 闪崩检测阈值硬编码 5% | HIGH | HIGH | -- |

> *Codex 发现的是更底层的 WebSocket 架构问题（见下文）

---

## Codex 独有的关键发现

Deepseek/DS 纯静态审查**完全遗漏**了以下动态运行问题：

| # | 问题 | 严重性 | 说明 |
|---|------|--------|------|
| 1 | **WebSocket `connect()` 阻塞主循环** | 致命 | `_reader_loop()` 是无限循环，bot 后续初始化（MarketData、OrderEngine、Web面板）全部卡住。live 模式根本跑不起来。本地复现：`connect_timed_out_blocking` |
| 2 | **WebSocket 分发 key 不匹配** | 致命 | 订阅注册 key 为 `spot.order_book:BTC_USDT_20_100ms`，但 reader 分发 key 为 `spot.order_book:update`，行情永远无法到达 LiveMarketData |
| 3 | **价格尖峰 cooldown 导致永久死锁** | HIGH | 进入 `COOLDOWN_PRICE_SPIKE` 后主循环直接 return，cooldown 到期判断永远不可达，bot 不再恢复交易 |
| 4 | **SQLite schema 与面板不一致** | HIGH | `fills` 表缺少 `side`/`price`/`created_at` 列。实际验证：`OperationalError no such column: side` |
| 5 | **systemd unit 入口不存在** | MEDIUM | 配置 `gate_trade.main` 但模块不存在。验证：`No module named gate_trade.main` |
| 6 | **告警配置未接线** | MEDIUM | webhook URL 非空时添加的是空 token 的 TelegramChannel，不会发送任何告警 |
| 7 | **GitHub Actions / 分支保护 / License 缺失** | LOW | 公开仓库无 CI、无分支保护、无 license |
| 8 | **httpx dev 依赖缺失** | LOW | `pip install -e '.[dev]'` 后 pytest 因缺 httpx 而失败 |

> Codex 是唯一**实际执行了 bot 并记录运行错误**的审计方。以上动态问题静态审查无法发现。

---

## Deepseek / DS 独有的发现

Codex 未涉及（或仅简略提及）的问题：

| # | 问题 | 来源 | 严重性 |
|---|------|------|--------|
| 1 | **API 密钥明文存储** in `config/local.yaml` | 两者 | CRITICAL |
| 2 | Bot 构造参数类型为 `Any` 而非 Protocol | 两者 | MEDIUM |
| 3 | Web Panel 直接访问 `bot._md` 等私有属性 | 两者 | MEDIUM |
| 4 | `GateIoClient` / `WsManager` 零单元测试 | 两者 | MEDIUM |
| 5 | `_flatten` 方法在 `schema.py` 和 `watcher.py` 重复 | 两者 | MEDIUM |
| 6 | `MarkoutRecorder` pending 记录关闭时丢失 | 两者 | MEDIUM |
| 7 | `.gitignore` 缺少 `data/` 目录 | 两者 | MEDIUM |
| 8 | 缺少 systemd / Docker 进程管理配置 | Deepseek | MEDIUM |
| 9 | API 错误响应日志可能泄露信息 | Deepseek | LOW |
| 10 | Web Panel SQLite 路径遍历风险 | 两者 | LOW |
| 11 | `save_fill` 并发安全依赖单线程假设 | Deepseek | LOW |
| 12 | `cancel` 的 `_by_tag` 清理残留 | Deepseek | LOW |
| 13 | `place` 和 `reconcile` 之间竞态窗口 | Deepseek | LOW |
| 14 | 连续 tick 可能生成重复订单 | Deepseek | LOW |
| 15 | 令牌桶等待超时是硬错误 | Deepseek | LOW |
| 16 | **Smasher 模块未集成到主循环** | DS | MEDIUM |
| 17 | **TelegramChannel 使用同步 urllib** | DS | MEDIUM |

---

## 关键分歧点

### ruff 状态
- **Deepseek / DS**: 报告 "ruff 零警告"
- **Codex**: 实际运行 `ruff check .` 结果 **14 errors** (import 排序、未使用变量、变量命名模糊)

### 风控 `_check_position` 分析深度
- **Deepseek / DS**: 指出 `balances=[]` 导致 `base_held` 恒为 0
- **Codex**: 额外指出不应把所有非零余额资产相加，而是按交易对拆分 base/quote

### WebSocket 问题严重程度
- **Deepseek / DS**: 只发现 ping loop 未启动（单点问题）
- **Codex**: 发现 `connect()` 阻塞主循环 + 分发 key 不匹配两个**架构级缺陷**，live 模式完全不可用

### 实际可运行性判断
- **Deepseek / DS**: 未做可运行性判断
- **Codex**: 明确结论 "**当前实现还没有达到实盘交易机器人的最低安全门槛**"

---

## 审计方法论差异总结

| 维度 | Deepseek | DS | Codex |
|------|----------|-----|-------|
| 代码阅读深度 | 最深（29文件逐行） | 深（70文件） | 中（重点路径） |
| 架构/设计评价 | 详尽的正面评价 | 正面评价 | 简略 |
| 低风险/质量问题 | 7 个 LOW | 0 个 | 0 个 |
| 工程/CI/供应链 | 少量 | 无 | 大量（核心关注点） |
| **动态验证** | 无 | 无 | **有（实际运行+真实错误信息）** |
| 代码质量改进建议 | 丰富（typing、封装等） | 中等 | 偏工程化 |
| 适用场景 | 代码质量提升 | 功能完整性检查 | **实盘安全决策** |

---

> 结论：三份报告互补性很强。Deepseek 适合代码质量提升，DS 适合功能完整性检查，Codex 适合实盘安全决策。三者合并可形成完整的审计视图。
