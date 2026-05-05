# AUDIT_COMPREHENSIVE vs AUDIT_COMPREHENSIVE_CODEX 对比

**日期**: 2026-05-05  
**对比文件**:
- `audit/AUDIT_COMPREHENSIVE.md` — Deepseek-v4-pro + DS + Codex 三方合并
- `audit/AUDIT_COMPREHENSIVE_CODEX.md` — Codex 视角的综合报告

---

## 相同点

两份报告在 **21 个核心发现** 上完全一致：

| 问题 | COMPREHENSIVE | COMPREHENSIVE_CODEX |
|------|:---:|:---:|
| WS `connect()` 阻塞主循环 | FATAL | Critical |
| WS 分发 key 不匹配 → 行情收不到 | FATAL | Critical |
| 风控传入空余额 → 仓位检查失效 | CRITICAL | Critical |
| 订单价格无上下限保护 | CRITICAL | Critical |
| `cancel_all("")` → 关机撤单失败 | HIGH | Critical/High |
| Web 面板 `0.0.0.0` 无认证 | HIGH | High |
| `_enter_cooldown` 绕过 transition() | CRITICAL | High |
| WS ping loop 未启动 | CRITICAL | High |
| spike cooldown 永久死锁 | CRITICAL | High |
| 风控状态崩溃重启后丢失 | HIGH | High |
| 配置加载路径不一致 | HIGH | High |
| SQLite schema 与面板/日报不一致 | HIGH | High |
| systemd entrypoint 不存在 | HIGH | High |
| load_state 损坏状态抛 ValueError | HIGH | Medium |
| 闪崩阈值硬编码 5% | HIGH | Medium |
| Bot 参数类型 Any | MEDIUM | Medium |
| Web Panel 访问私有属性 | MEDIUM | Medium |
| .gitignore 缺 data/ | MEDIUM | Medium |
| _flatten 重复 | MEDIUM | Medium |
| MarkoutRecorder pending 关闭丢失 | MEDIUM | Medium |

**最终结论一致**：当前版本不建议直接运行实盘，应在完成 live 数据链路、风控、撤单、面板认证修复后再考虑 `--live`。

---

## 不同点

### 1. 覆盖广度

| 维度 | COMPREHENSIVE | COMPREHENSIVE_CODEX |
|------|:---:|:---:|
| 问题总数 | **35** | **28** |
| 低风险条目 | 8 个逐项列出 | 整合为一段 |
| API 密钥明文存储 | 独立 CRITICAL | 归入"密钥残留风险" |

**COMPREHENSIVE 多出的细节**：`save_fill` 并发安全、`_by_tag` 清理残留、place/reconcile 竞态、连续 tick 重复订单、令牌桶硬错误、API 日志泄露、Smasher 未集成、TelegramChannel 同步 urllib

### 2. 严重度标定差异

| 问题 | COMPREHENSIVE | COMPREHENSIVE_CODEX |
|------|:---:|:---:|
| WS connect 阻塞 | FATAL | Critical |
| cancel_all("") | HIGH | Critical / High |
| _enter_cooldown 绕过验证 | CRITICAL | High |
| ping loop 未启动 | CRITICAL | High |
| spike cooldown 死锁 | CRITICAL | High |
| load_state | HIGH | Medium |
| 闪崩阈值 | HIGH | Medium |

COMPREHENSIVE 整体评级更严格，尤其是在状态机和 WebSocket 相关问题上。

### 3. 结构风格

| 维度 | COMPREHENSIVE | COMPREHENSIVE_CODEX |
|------|--------------|---------------------|
| 定位 | 三方审计事实清单 | 叙事性综合报告 |
| 每问题格式 | 文件 + 行号 + 代码 + 修复 | 位置 + 影响 + 建议 |
| 来源标注 | 每个问题标注来源 | 仅表格标注 |
| 正面评价 | 14 条逐一列出 | 段落概述 |
| 修复路线 | 4 批（0-3），按时间 | P0-P3，按风险等级 |
| 代码引用 | 精确到行号 | 文件名为主 |

### 4. 各有所长

**COMPREHENSIVE 更强**:
- 模块结构表格（15 模块路径+职责）
- 测试覆盖详细分析（已覆盖/未覆盖分表）
- 可复现的审计命令记录
- 精确行号引用便于逐条修复

**COMPREHENSIVE_CODEX 更强**:
- **"实盘前最低门槛"清单**（10 条硬性 Gate，Go/No-Go 决策用）
- 建议使用子账户 + 禁提现 API key + IP 白名单（更实务）
- 结论强调"首要目标从策略功能更多 → 失败模式更安全"
- 判断"项目不是推倒重来，而是在现有模块边界上补齐 live 安全闭环"

### 5. 审计签名

- **COMPREHENSIVE**: Deepseek-v4-pro + DS + Codex 三方并列，每问题标注具体来源
- **COMPREHENSIVE_CODEX**: 单一署名 Codex · 风控拆解工程师，融合后第一人称叙事

---

## 使用建议

- **逐条修复跟踪** → 用 `AUDIT_COMPREHENSIVE.md`（有行号、有来源、有优先级批次）
- **Go/No-Go 实盘决策** → 用 `AUDIT_COMPREHENSIVE_CODEX.md`（有准入清单）
- 两份互补，合并形成完整的审计视图
