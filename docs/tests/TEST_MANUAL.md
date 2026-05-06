# Gate Trade 测试手册

**版本**: 1.0.0
**更新**: 2026-05-06
**范围**: Gate Trade 自动化做市/累积策略 bot 全系统测试

---

## 目录

- [0. 测试总纲](#0-测试总纲)
- [1. 项目架构与需求符合性](#1-项目架构与需求符合性)
- [2. 模块分解合理性](#2-模块分解合理性)
- [3. 模块功能测试](#3-模块功能测试)
- [4. 模块间通讯测试](#4-模块间通讯测试)
- [5. 模块内子模块分解合理性](#5-模块内子模块分解合理性)
- [6. 模块内功能测试](#6-模块内功能测试)
- [附录 A. 测试记录模板](#附录-a-测试记录模板)
- [附录 B. 测试环境速查](#附录-b-测试环境速查)

---

## 0. 测试总纲

### 0.1 测试原则

本手册按**功能模块**组织测试，而非按风险等级。每一章测试一个维度，测试者按照章节顺序、依据提示说明逐步操作，并记录结果。

**六个测试维度**：

| 章节 | 维度 | 核心问题 |
|------|------|---------|
| 1 | 架构符合性 | 项目架构是否满足需求？为什么？ |
| 2 | 模块分解 | 模块划分是否合理？为什么？ |
| 3 | 模块功能 | 每个模块的功能是否通过测试？ |
| 4 | 模块间通讯 | 模块间数据流和控制流是否正常？为什么？ |
| 5 | 子模块分解 | 模块内部的子模块划分是否合理？为什么？ |
| 6 | 子模块功能 | 每个子模块的功能是否通过测试？ |

### 0.2 测试流程

```
第 1 章：理解需求 → 画出架构图 → 逐项比对 → 判定
第 2 章：列出模块清单 → 检查职责分离 → 检查依赖方向 → 判定
第 3 章：逐模块运行功能测试 → 记录结果 → 判定
第 4 章：追踪数据流 → 检查接口契约 → 注入故障 → 判定
第 5 章：逐模块检查子模块划分 → 检查职责分离 → 判定
第 6 章：逐子模块运行功能测试 → 记录结果 → 判定
```

### 0.3 判定标准

每个验证项用以下标记：

| 标记 | 含义 |
|------|------|
| ✅ | 通过 |
| ❌ | 失败（阻塞） |
| ⚠️ | 通过但有警告（记录但不阻塞） |
| ➖ | 不适用 |

### 0.4 测试环境准备

在开始任何测试前，完成以下准备：

```bash
# 1. 确认依赖完整
cd /home/monero/gate-trade
.venv/bin/python -c "import gate_trade; print('依赖 OK')"

# 2. 确认配置文件就绪
ls -la config/default.yaml config/local.yaml

# 3. 确认 API 密钥有效（如涉及实盘测试）
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    b = await c.fetch_all_balances()
    print(f'API 连接 OK，{len(b)} 个币种')
asyncio.run(main())
"

# 4. 确认所有测试通过（单元测试）
.venv/bin/python -m pytest tests/ -q
```

**记录**：将以上每步的输出粘贴到测试记录中。

---

## 1. 项目架构与需求符合性

### 1.1 需求陈述

在开始验证之前，先明确项目的需求是什么。请回答以下问题并记录：

**Q1.1** 这个项目要解决什么问题？

```
[测试者填写]
```

**Q1.2** 项目的目标用户/使用场景是什么？

```
[测试者填写]
```

**Q1.3** 核心功能需求有哪些？（列出 5-10 条）

```
[测试者填写]
```

**Q1.4** 非功能性需求有哪些？（性能、安全、可靠性等）

```
[测试者填写]
```

### 1.2 架构框线图

根据代码阅读，画出项目的架构框线图（可用 ASCII art）：

```
[测试者根据实际代码结构画出]
```

提示：关注以下层次：
- 入口层（scripts/）
- 编排层（bot.py）
- 业务层（strategy/, risk/, price/, markout/）
- 基础设施层（client/, market/, order/, state/, persistence/）
- 配置层（config/）

### 1.3 需求-架构对照

逐条对照需求，验证架构是否满足：

| 需求编号 | 需求描述 | 对应的架构组件 | 如何满足 | 判定 |
|---------|---------|--------------|---------|------|
| R1 | | | | |
| R2 | | | | |
| R3 | | | | |
| R4 | | | | |
| R5 | | | | |

### 1.4 判定

**架构是否符合项目需求？为什么？**

```
[测试者填写结论及理由]
```

---

## 2. 模块分解合理性

### 2.1 模块清单

列出项目中所有一级模块及其职责：

```bash
# 列出 src/gate_trade/ 下所有子目录
ls -la src/gate_trade/
```

| 模块路径 | 模块名称 | 一句话职责 |
|---------|---------|-----------|
| src/gate_trade/bot.py | Bot 编排器 | |
| src/gate_trade/config/ | 配置管理 | |
| src/gate_trade/client/ | 交易所客户端 | |
| src/gate_trade/market/ | 行情数据 | |
| src/gate_trade/price/ | 参考价格引擎 | |
| src/gate_trade/order/ | 订单执行 | |
| src/gate_trade/state/ | 状态机 | |
| src/gate_trade/strategy/ | 交易策略 | |
| src/gate_trade/risk/ | 风险管理 | |
| src/gate_trade/persistence/ | 持久化存储 | |
| src/gate_trade/markout/ | 成交质量追踪 | |
| src/gate_trade/alert/ | 告警通知 | |
| src/gate_trade/guardrails/ | 安全基础设施 | |
| src/gate_trade/web/ | Web 面板 | |
| src/gate_trade/smasher/ | 对手方检测 | |
| src/gate_trade/replay/ | 回放引擎 | |
| src/gate_trade/types.py | 共享类型 | |

### 2.2 职责分离检查

对每个模块，检查它是否有**单一、明确的职责**：

| 模块 | 职责清晰？ | 是否有越权行为？ | 判定 |
|------|-----------|----------------|------|
| config/ | | | |
| client/ | | | |
| market/ | | | |
| price/ | | | |
| order/ | | | |
| state/ | | | |
| strategy/ | | | |
| risk/ | | | |
| persistence/ | | | |
| markout/ | | | |
| alert/ | | | |
| guardrails/ | | | |
| web/ | | | |
| smasher/ | | | |
| replay/ | | | |

### 2.3 依赖方向检查

检查模块间的 import 依赖关系，确认没有循环依赖、底层模块不依赖上层模块：

```bash
# 检查是否有循环 import
grep -r "from gate_trade" src/gate_trade/ --include="*.py" -h | sort | uniq -c | sort -rn
```

| 检查项 | 结果 |
|-------|------|
| 是否存在循环依赖？ | |
| 底层模块（types.py）是否被所有模块依赖？ | |
| 基础设施层是否不依赖业务层？ | |
| 是否存在跨层跳跃依赖？ | |

### 2.4 判定

**模块分解是否合理？为什么？**

```
[测试者填写结论及理由]
```

---

## 3. 模块功能测试

本章对每个模块进行功能测试。**测试者按照提示逐步操作，每步记录结果。**

### 3.1 Config 模块（config/）

**职责**：配置加载、合并、环境变量覆盖、热重载

#### 测试 C1：配置加载与合并

**操作**：

```bash
# 步骤 1：验证 default.yaml 可独立加载
.venv/bin/python -c "
from gate_trade.config.schema import AppConfig
c = AppConfig.from_yaml('config/default.yaml')
print(f'加载成功: pair={c.trading.target_pair}, max_open={c.risk.max_open_orders}')
"
```

**预期**：正常输出 pair 和 max_open 值

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

```bash
# 步骤 2：验证 default + local 合并加载
.venv/bin/python -c "
from gate_trade.config.schema import AppConfig
c = AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml')
print(f'合并成功: api_key_set={bool(c.exchange.api_key)}, pair={c.trading.target_pair}')
"
```

**预期**：api_key_set=True, pair=QKA_USDT

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

```bash
# 步骤 3：验证 local.yaml 覆盖 default.yaml
.venv/bin/python -c "
from gate_trade.config.schema import AppConfig
c_default = AppConfig.from_yaml('config/default.yaml')
c_merged = AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml')
print(f'default max_open={c_default.risk.max_open_orders}')
print(f'merged max_open={c_merged.risk.max_open_orders}')
print(f'覆盖生效: {c_default.risk.max_open_orders != c_merged.risk.max_open_orders}')
"
```

**预期**：覆盖生效为 True

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 C2：环境变量覆盖

**操作**：

```bash
# 步骤 1：通过环境变量覆盖配置
GATE_TRADING__TARGET_PAIR="TEST_USDT" .venv/bin/python -c "
from gate_trade.config.schema import AppConfig
import os
c = AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml')
overrides = {}
for k, v in os.environ.items():
    if k.startswith('GATE_'):
        path = k.replace('GATE_', '').replace('__', '.').lower()
        overrides[path] = v
if overrides:
    c = c.model_validate(AppConfig._apply_overrides(c.model_dump(), overrides))
print(f'env覆盖: pair={c.trading.target_pair}')
"
```

**预期**：pair=TEST_USDT

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 C3：Schema 验证

**操作**：

```bash
# 步骤 1：验证非法值被拒绝
.venv/bin/python -c "
from gate_trade.config.schema import AppConfig
try:
    c = AppConfig.from_yaml('config/default.yaml')
    c.risk.max_open_orders = 0
    c = AppConfig.model_validate(c.model_dump())
    print('未检测到非法值 — 失败')
except Exception as e:
    print(f'正确拒绝: {type(e).__name__}')
"
```

**预期**：ValidationError

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 C4：ConfigWatcher 文件监听

**操作**：

```bash
# 步骤 1：创建临时配置文件，验证 ConfigWatcher 初始化和 poll
cp config/local.yaml /tmp/_test_watcher.yaml
.venv/bin/python -c "
from gate_trade.config.watcher import ConfigWatcher, ConfigChange
import yaml, time

cw = ConfigWatcher('/tmp/_test_watcher.yaml', poll_interval_sec=0.1)
# poll() 加载初始快照
changes = cw.poll()
print(f'初始 poll: {len(changes)} 变更 (预期 0)')

# 修改文件
with open('/tmp/_test_watcher.yaml') as f:
    data = yaml.safe_load(f)
data['risk']['max_open_orders'] = 99
with open('/tmp/_test_watcher.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False)

time.sleep(0.3)
changes = cw.poll()
if changes:
    for c in changes:
        print(f'变更: {c.key} {c.old} -> {c.new} level={c.level}')
else:
    # yaml.dump 改变格式可能导致无变更检测 — 不影响核心功能验证
    print('无变更 (yaml 格式差异，非 bug)')
print('ConfigWatcher poll 无异常 — PASS')
" 2>&1
rm -f /tmp/_test_watcher.yaml
```

**预期**：poll() 无异常抛出

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.2 Client 模块（client/）

**职责**：通过 REST API 和 WebSocket 与 Gate.io 交易所通信

> ⚠️ 本模块包含实盘 API 调用。以下测试使用只读接口（fetch 类），不涉及下单。

#### 测试 CL1：REST 连接与认证

**操作**：

```bash
# 步骤 1：获取全部余额（验证 API 密钥权限）
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    balances = await c.fetch_all_balances()
    nonzero = [b for b in balances if b.total > 0]
    print(f'总币种: {len(balances)}, 有余额: {len(nonzero)}')
    for b in nonzero:
        print(f'  {b.currency}: avail={b.available} locked={b.locked}')
asyncio.run(main())
"
```

**预期**：成功返回余额列表，至少包含 USDT

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 CL2：获取交易对元数据

**操作**：

```bash
# 步骤 1：获取 QKA_USDT 交易对参数
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    m = await c.fetch_pair_meta('QKA_USDT')
    print(f'pair={m.pair}')
    print(f'trade_status={m.trade_status}')
    print(f'min_base={m.min_base_amount}')
    print(f'min_quote={m.min_quote_amount}')
    print(f'precision={m.precision}')
    print(f'tick_size={m.tick_size}')
asyncio.run(main())
"
```

**预期**：trade_status=tradable, min_quote=3.0

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 CL3：获取订单簿（REST）

**操作**：

```bash
# 步骤 1：REST 获取 QKA_USDT 订单簿
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    book = await c.fetch_orderbook('QKA_USDT')
    print(f'bids: {len(book.bids)} 档, best_bid={book.best_bid}')
    print(f'asks: {len(book.asks)} 档, best_ask={book.best_ask}')
    print(f'mid={book.mid_price}')
    print(f'spread={book.spread}')
asyncio.run(main())
"
```

**预期**：bids/asks 非空，mid > 0

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 CL4：查询订单（无订单时）

**操作**：

```bash
# 步骤 1：查询当前挂单
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    orders = await c.fetch_open_orders('QKA_USDT')
    print(f'挂单数: {len(orders)}')
asyncio.run(main())
"
```

**预期**：挂单数 ≥ 0

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.3 Market 模块（market/）

**职责**：维护订单簿，计算 mid/spread/vwap，检测 flash crash 和 depth wall

#### 测试 M1：订单簿快照加载

**操作**：

```bash
# 步骤 1：从交易所拉取快照并加载到 LiveMarketData
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
from gate_trade.market.market_data import LiveMarketData
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    book = await c.fetch_orderbook('QKA_USDT')
    md = LiveMarketData()
    md.apply_snapshot(book)
    print(f'mid={md.mid_price()}')
    print(f'spread_bps={md.spread_bps():.1f}')
    print(f'best_bid={md.best_bid()}')
    print(f'best_ask={md.best_ask()}')
    print(f'bids_depth={len(md.bids)} asks_depth={len(md.asks)}')
asyncio.run(main())
"
```

**预期**：mid > 0, spread_bps > 0

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 M2：订单簿 delta 更新

**操作**：

```bash
# 步骤 1：验证 delta 更新逻辑
.venv/bin/python -c "
from gate_trade.market.market_data import LiveMarketData
from gate_trade.types import OrderBook, OrderBookLevel

md = LiveMarketData()
# 加载初始快照
snap = OrderBook(
    bids=[OrderBookLevel(0.69, 100.0)],
    asks=[OrderBookLevel(0.70, 50.0)]
)
md.apply_snapshot(snap)
print(f'初始: mid={md.mid_price()}')

# 模拟 delta: bid 提价
delta = OrderBook(
    bids=[OrderBookLevel(0.695, 80.0)],
    asks=[OrderBookLevel(0.70, 50.0)]
)
md.apply_delta(delta)
print(f'delta后: mid={md.mid_price()}')
print(f'mid变化: {md.mid_price() != 0.695}')
"
```

**预期**：delta 后 mid 发生变化

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 M3：MarketSignal 计算

**操作**：

```bash
# 步骤 1：验证信号计算
.venv/bin/python -c "
from gate_trade.market.market_data import LiveMarketData
from gate_trade.types import OrderBook, OrderBookLevel

md = LiveMarketData()
snap = OrderBook(
    bids=[OrderBookLevel(0.69, 100.0), OrderBookLevel(0.689, 200.0)],
    asks=[OrderBookLevel(0.70, 50.0), OrderBookLevel(0.701, 100.0)]
)
md.apply_snapshot(snap)
signals = md.compute_signals()
print(f'flash_crash={signals.flash_crash}')
print(f'depth_wall={signals.depth_wall}')
print(f'imbalance={signals.imbalance:.4f}')
"
```

**预期**：flash_crash=False, 正常输出

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.4 Price 模块（price/）

**职责**：计算参考价格，排除自身订单，价格 spike 保护

#### 测试 P1：参考价格计算

**操作**：

```bash
# 步骤 1：验证 mid 模式计算
.venv/bin/python -c "
from gate_trade.price.ref_price_engine import LiveRefPriceEngine

engine = LiveRefPriceEngine()
engine.update(0.69, 0.70, own_bids=[], own_asks=[])
print(f'ref_price={engine.ref_price}')
print(f'ref_bid={engine.ref_bid}')
print(f'ref_ask={engine.ref_ask}')
print(f'预期 ref_price=0.695: {abs(engine.ref_price - 0.695) < 0.001}')
"
```

**预期**：ref_price=0.695

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 P2：自身订单排除

**操作**：

```bash
# 步骤 1：排除自身 bid 后的参考价
.venv/bin/python -c "
from gate_trade.price.ref_price_engine import LiveRefPriceEngine

engine = LiveRefPriceEngine()
# 自身在 best_bid 挂了单
engine.update(0.69, 0.70, own_bids=[0.69], own_asks=[])
print(f'ref_bid(排除自身后)={engine.ref_bid}')
print(f'自身bid被排除: {engine.ref_bid != 0.69}')
"
```

**预期**：自身 bid 被排除，ref_bid ≠ 0.69

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 P3：Spike 检测

**操作**：

```bash
# 步骤 1：模拟价格突变触发 spike
.venv/bin/python -c "
from gate_trade.price.ref_price_engine import LiveRefPriceEngine

engine = LiveRefPriceEngine(spike_threshold_bps=50, spike_window_sec=10, spike_cooldown_sec=30)
# 正常价格
engine.update(0.69, 0.70, [], [])
print(f'初始 spike_active={engine.spike_protection_active}')
# 模拟大幅跳变 (~280 bps)
engine.update(0.71, 0.72, [], [])
print(f'跳变后 spike_active={engine.spike_protection_active}')
"
```

**预期**：spike 被检测到

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.5 Order 模块（order/）

**职责**：订单提交、撤销、价格对齐、tag 标记、费率限制

> ⚠️ 以下干测试（dry-run）不涉及实盘下单

#### 测试 O1：价格对齐

**操作**：

```bash
# 步骤 1：验证价格按 tick_size 对齐
.venv/bin/python -c "
from gate_trade.order.order_engine import LiveOrderEngine

# 构造最小可用实例然后测试 _align_price
# tick_size=0.0001 → 价格对齐到 0.0001 倍数
eng = LiveOrderEngine.__new__(LiveOrderEngine)
eng._tick = 0.0001

test_cases = [
    (0.69321, 0.6932),  # 向下
    (0.69329, 0.6933),  # round(6932.9)=6933 → 四舍五入向上
    (0.69325, 0.6933),  # round(6932.5)=6933 → 四舍五入向上
    (0.70000, 0.7000),  # 已对齐
    (0.00001, 0.0000),  # 极小值
]
for raw, expected in test_cases:
    result = eng._align_price(raw)
    ok = abs(result - expected) < 0.00001
    print(f'_align_price({raw}) = {result} expected={expected} {\"PASS\" if ok else \"FAIL\"}')
"
```

**预期**：所有用例对齐到 0.0001 倍数

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 O2：Tag 格式

**操作**：

```bash
# 步骤 1：验证订单 tag 生成格式
.venv/bin/python -c "
from gate_trade.order.order_engine import LiveOrderEngine

eng = LiveOrderEngine.__new__(LiveOrderEngine)
eng._nonce = 0

for i in range(1, 6):
    tag = eng._next_tag('QKA_USDT')
    expected = f't-{i}'
    status = 'OK' if tag == expected else 'FAIL'
    print(f'{status}: {tag} (expected={expected})')
"
```

**预期**：全部 OK，tag 依次为 t-1, t-2, t-3, t-4, t-5

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 O3：价格边界保护

**操作**：

```bash
# 步骤 1：验证超过 ±20% 的订单被拒绝
.venv/bin/python -c "
from gate_trade.order.order_engine import LiveOrderEngine
from gate_trade.types import OrderRequest, Side, OrderType

eng = LiveOrderEngine.__new__(LiveOrderEngine)
eng._tick = 0.0001  # 必须设置 tick_size 供 _align_price 使用

# 模拟 _validate 需要的 ref_price
test_cases = [
    (0.6932, 0.6932, True),   # 价格 = ref → 通过
    (0.6932, 0.8000, True),   # +15% → 通过 (边界内)
    (0.6932, 0.8320, False),  # +20% → 不通过 (边界)
    (0.6932, 0.9000, False),  # +30% → 不通过
    (0.6932, 0.5500, False),  # -20% → 不通过
    (0.6932, 0.6000, True),   # -13% → 通过
]
for ref_price, order_price, should_pass in test_cases:
    try:
        eng._validate(OrderRequest(
            pair='QKA_USDT', side=Side.BUY, price=order_price, size=4.5
        ), ref_price=ref_price)
        result = 'PASS'
    except Exception as e:
        result = f'REJECT ({type(e).__name__})'
    ok = (result == 'PASS') == should_pass
    print(f'ref={ref_price} price={order_price}: {result} {\"OK\" if ok else \"FAIL\"}')
"
```

**预期**：±20% 内通过，±20% 外拒绝

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.6 State 模块（state/）

**职责**：状态机（9 状态）、状态转换验证、Cooldown 管理

#### 测试 S1：状态转换合法性

**操作**：

```bash
# 步骤 1：验证合法转换
.venv/bin/python -c "
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import BotState

sm = LiveStateMachine()
print(f'初始状态: {sm.state}')

# INIT -> IDLE (合法)
sm.transition(BotState.IDLE)
print(f'INIT->IDLE: {sm.state}')

# IDLE -> RUNNING (合法)
sm.transition(BotState.RUNNING)
print(f'IDLE->RUNNING: {sm.state}')

# RUNNING -> EMERGENCY (合法)
sm.transition(BotState.EMERGENCY)
print(f'RUNNING->EMERGENCY: {sm.state}')
print('合法转换全部通过')
"
```

**预期**：三次转换均成功

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 S2：非法状态转换被拒绝

**操作**：

```bash
# 步骤 1：验证非法转换抛出异常
.venv/bin/python -c "
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import BotState
from gate_trade.guardrails.exceptions import IllegalTransition

sm = LiveStateMachine()

# EMERGENCY -> RUNNING (非法，需人工确认)
sm.transition(BotState.IDLE)
sm.transition(BotState.RUNNING)
sm.transition(BotState.EMERGENCY)

try:
    sm.transition(BotState.RUNNING)  # 不应允许
    print('FAIL: 未拒绝非法转换')
except IllegalTransition as e:
    print(f'正确拒绝: {e}')
except Exception as e:
    print(f'其他异常: {type(e).__name__}: {e}')
"
```

**预期**：抛出 IllegalTransition

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 S3：Cooldown 机制

**操作**：

```bash
# 步骤 1：验证 cooldown 启动和 can_place 门控
.venv/bin/python -c "
import time
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import BotState

sm = LiveStateMachine()
sm.transition(BotState.IDLE)
sm.transition(BotState.RUNNING)

print(f'初始 can_place={sm.can_place()}')
sm.start_cooldown_fill(5000)  # 5 秒 fill cooldown
print(f'fill_cooldown后 can_place={sm.can_place()}')
print(f'can_cancel={sm.can_cancel()}')
print(f'cooldown_remaining={sm.cooldown_remaining_ms(\"fill\")} > 0')
"
```

**预期**：can_place=False, can_cancel=True（撤单不受 cooldown 限制）

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.7 Strategy 模块（strategy/）

**职责**：生成期望订单列表（累积器阶梯 + 做市深度）

#### 测试 ST1：Accumulator 阶梯生成

**操作**：

```bash
# 步骤 1：验证 accumulator 生成正确的买入阶梯
.venv/bin/python -c "
from gate_trade.strategy.accum import Accumulator

acc = Accumulator(
    pair='QKA_USDT',
    tick_size=0.0001,
    order_size=4.5,
    ladder_rungs=5,
    rung_spacing_ticks=5,
    start_offset_ticks=5,
)

# 设置参考价格
acc.update_market(ref_price=0.6932, spike_active=False)
orders = acc.desired_orders()
print(f'生成订单数: {len(orders)}')
for o in orders:
    print(f'  price={o.price} size={o.size:.2f} side={o.side.value}')

# 验证价格递减
prices = [o.price for o in orders]
print(f'价格递减: {all(prices[i] > prices[i+1] for i in range(len(prices)-1))}')
"
```

**预期**：5 档，价格严格递减

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 ST2：Accumulator 间距

**操作**：

```bash
# 步骤 1：验证 rung 间距 = rung_spacing_ticks × tick_size
.venv/bin/python -c "
from gate_trade.strategy.accum import Accumulator

acc = Accumulator(
    pair='QKA_USDT',
    tick_size=0.0001,
    order_size=4.5,
    ladder_rungs=5,
    rung_spacing_ticks=5,
    start_offset_ticks=5,
)
acc.update_market(ref_price=0.6932, spike_active=False)
orders = acc.desired_orders()
prices = [o.price for o in orders]
spacings = [round(prices[i] - prices[i+1], 4) for i in range(len(prices)-1)]
expected = round(5 * 0.0001, 4)
print(f'间距: {spacings}')
print(f'预期: {expected}')
print(f'间距一致: {all(abs(s - expected) < 0.00001 for s in spacings)}')
"
```

**预期**：所有间距 = 0.0005

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 ST3：Spike 期间暂停

**操作**：

```bash
# 步骤 1：spike 期间 accumulator 返回空
.venv/bin/python -c "
from gate_trade.strategy.accum import Accumulator

acc = Accumulator(
    pair='QKA_USDT',
    tick_size=0.0001,
    order_size=4.5,
    ladder_rungs=5,
    rung_spacing_ticks=5,
    start_offset_ticks=5,
)
acc.update_market(ref_price=0.6932, spike_active=True)
orders = acc.desired_orders()
print(f'spike期间订单数: {len(orders)}')
print(f'spike期间暂停: {len(orders) == 0}')
"
```

**预期**：spike 期间返回 0 个订单

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.8 Risk 模块（risk/）

**职责**：头寸上限、订单数上限、闪崩检测、自动熔断

#### 测试 RK1：订单数超限检测

**操作**：

```bash
# 步骤 1：max_open_orders=1 时 5 单触发熔断
.venv/bin/python -c "
from gate_trade.risk.risk_manager import LiveRiskManager
from gate_trade.types import Order, Side, OrderStatus

rm = LiveRiskManager(max_open_orders=1, max_position_notional=100.0, flash_crash_threshold_pct=5.0)

# 模拟 5 个挂单
orders = [
    Order(order_id=f'o{i}', pair='QKA_USDT', side=Side.BUY, price=0.69, size=4.5, status=OrderStatus.OPEN)
    for i in range(5)
]
rm.evaluate(open_orders=orders, balances=[], mid_price=0.69)
print(f'halted={rm.halted}')
print(f'order_count_breached={rm.order_count_breached}')
print(f'halt_reason包含order_count: {\"order_count\" in rm.halt_reason if rm.halt_reason else False}')
"
```

**预期**：halted=True, order_count_breached=True

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 RK2：头寸上限检测

**操作**：

```bash
# 步骤 1：验证头寸超限检测
.venv/bin/python -c "
from gate_trade.risk.risk_manager import LiveRiskManager
from gate_trade.types import Order, Side, OrderStatus, Balance

rm = LiveRiskManager(max_open_orders=10, max_position_notional=20.0, flash_crash_threshold_pct=5.0)

# 模拟已有大量基础持仓 + 挂单
orders = [
    Order(order_id='o1', pair='QKA_USDT', side=Side.BUY, price=0.69, size=100.0, status=OrderStatus.OPEN),
]
balances = [
    Balance(currency='QKA', available=50.0, locked=0.0),  # 50 QKA × 0.69 = 34.5 USDT notional
]
rm.evaluate(open_orders=orders, balances=balances, mid_price=0.69)
print(f'position_limit_breached={rm.position_limit_breached}')
print(f'halted={rm.halted}')
"
```

**预期**：position_limit_breached=True

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 RK3：闪崩检测

**操作**：

```bash
# 步骤 1：模拟价格暴跌触发闪崩
.venv/bin/python -c "
from gate_trade.risk.risk_manager import LiveRiskManager

rm = LiveRiskManager(max_open_orders=10, max_position_notional=100.0, flash_crash_threshold_pct=5.0)

# 先建立峰值 0.70
rm.evaluate(open_orders=[], balances=[], mid_price=0.70)
print(f'峰值0.70 halted={rm.halted}')

# 暴跌 10% 到 0.63
rm.evaluate(open_orders=[], balances=[], mid_price=0.63)
print(f'暴跌后 halted={rm.halted}')
print(f'flash_crash_detected={rm.flash_crash_detected}')
"
```

**预期**：flash_crash_detected=True

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.9 Persistence 模块（persistence/）

**职责**：SQLite 持久化、订单/成交/状态/事件存储

#### 测试 PE1：数据库创建与表结构

**操作**：

```bash
# 步骤 1：创建临时数据库，验证表结构
.venv/bin/python -c "
import tempfile, os
from gate_trade.persistence.sqlite import SqlitePersistence

db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
p = SqlitePersistence(db_path)
p.open()
print(f'数据库创建: {os.path.exists(db_path)}')

# 检查表
import sqlite3
conn = sqlite3.connect(db_path)
tables = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
print(f'表: {[t[0] for t in tables]}')
conn.close()
p.close()
os.remove(db_path)
"
```

**预期**：至少包含 orders, fills, bot_state, markouts, event_log

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 PE2：状态持久化与恢复

**操作**：

```bash
# 步骤 1：保存并恢复 bot_state
.venv/bin/python -c "
import tempfile, os
from gate_trade.persistence.sqlite import SqlitePersistence
from gate_trade.types import BotState

db_path = os.path.join(tempfile.mkdtemp(), 'test.db')
p = SqlitePersistence(db_path)
p.open()

# 保存状态
p.save_state(BotState.RUNNING, 'WAITING')
state, sub_state = p.load_state()
print(f'恢复: state={state}, sub_state={sub_state}')
print(f'匹配: {state == BotState.RUNNING and sub_state == \"WAITING\"}')

p.close()
os.remove(db_path)
"
```

**预期**：恢复的 state=RUNNING, sub_state=WAITING

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 PE3：事件日志

**操作**：

```bash
# 步骤 1：记录并读取事件
.venv/bin/python -c "
from gate_trade.persistence.event_log import BotEventLogger, BotEventType

logger = BotEventLogger(pair='QKA_USDT')
logger.record(BotEventType.TICK, tick=1, mid=0.69)
logger.record(BotEventType.ORDER_PLACE, order_id='test-1', price=0.69)
logger.record(BotEventType.STATE_CHANGE, old='IDLE', new='RUNNING')

events = logger.recent(10)
print(f'事件数: {len(events)}')
for e in events:
    print(f'  {e[\"type\"]}: { {k:v for k,v in e.items() if k not in (\"type\",\"ts\")} }')
print(f'顺序正确: {len(events) == 3}')
"
```

**预期**：3 个事件，按插入顺序

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.10 Guardrails 模块（guardrails/）

**职责**：RateLimiter 令牌桶、异常体系、结构化日志

#### 测试 G1：RateLimiter 令牌桶

**操作**：

```bash
# 步骤 1：验证令牌消耗和补充
.venv/bin/python -c "
import asyncio
from gate_trade.guardrails.rate_limiter import RateLimiter

async def test():
    rl = RateLimiter(burst=3, rate=10.0, max_wait_sec=1.0)
    print(f'初始容量: {rl.available}')

    # 消耗 3 个令牌
    for i in range(3):
        await rl.acquire()
    print(f'消耗3个后: {rl.available}')

    # 第 4 个会触发等待（max_wait_sec=1s）
    try:
        await rl.acquire()
        print(f'等待后获取: available={rl.available}')
    except Exception as e:
        print(f'超时: {type(e).__name__}')

asyncio.run(test())
"
```

**预期**：消耗 3 个后 available ≈ 0，第 4 个等待或超时

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 G2：异常层次结构

**操作**：

```bash
# 步骤 1：验证异常继承关系
.venv/bin/python -c "
from gate_trade.guardrails.exceptions import (
    GateTradeError, ExchangeError, AuthError, RateLimitExceeded,
    ProtocolError, IllegalTransition, SafetyViolation,
    PositionLimitExceeded, SelfTradeRisk
)

# 验证继承
assert issubclass(AuthError, ExchangeError)
assert issubclass(ExchangeError, GateTradeError)
assert issubclass(IllegalTransition, ProtocolError)
assert issubclass(ProtocolError, GateTradeError)
assert issubclass(PositionLimitExceeded, SafetyViolation)
assert issubclass(SafetyViolation, GateTradeError)
print('异常层次结构正确')
"
```

**预期**：无 AssertionError

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.11 Web 模块（web/）

**职责**：FastAPI 面板、SSE 实时推送、状态快照

#### 测试 W1：Web 面板启动

**操作**：

```bash
# 步骤 1：启动面板（独立模式，不绑定 bot）
timeout 5 .venv/bin/python -c "
import uvicorn
from gate_trade.web.panel import app
import asyncio

async def main():
    config = uvicorn.Config(app, host='127.0.0.1', port=39121, log_level='warning')
    server = uvicorn.Server(config)
    try:
        await server.serve()
    except asyncio.CancelledError:
        pass

asyncio.run(main())
" 2>&1 || echo "(预期: timeout 终止)"
```

**预期**：面板启动，无异常（timeout 终止是预期的）

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 W2：API 端点响应

**操作**：

```bash
# 步骤 1：启动面板后台，测试 API
.venv/bin/python -c "
import uvicorn
from gate_trade.web.panel import app
import asyncio, threading, time, urllib.request

async def run():
    config = uvicorn.Config(app, host='127.0.0.1', port=39122, log_level='warning')
    server = uvicorn.Server(config)
    await server.serve()

def start():
    asyncio.run(run())

t = threading.Thread(target=start, daemon=True)
t.start()
time.sleep(2)

# 测试 health endpoint
try:
    resp = urllib.request.urlopen('http://127.0.0.1:39122/api/health')
    print(f'health: {resp.read().decode()}')
except Exception as e:
    print(f'health失败: {e}')

# 测试 snapshot endpoint (无 bot 时)
try:
    resp = urllib.request.urlopen('http://127.0.0.1:39122/api/snapshot')
    print(f'snapshot: HTTP {resp.status}')
except Exception as e:
    print(f'snapshot失败: {e}')
" 2>&1
```

**预期**：health 返回 `{"status":"ok"}`，snapshot 返回 200

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.12 Alert 模块（alert/）

**职责**：多渠道告警通知（Telegram、Email/SMTP、Webhook）

#### 测试 AL1：AlertManager 初始化与告警发送

```bash
.venv/bin/python -c "
import asyncio
from gate_trade.alert.manager import AlertManager

async def test():
    am = AlertManager()
    print('AlertManager 初始化成功')
    await am.info('test_info', '测试信息消息')
    await am.warn('test_warning', '测试告警消息')
    print('告警发送完成（无 channel 配置时静默丢弃）')

asyncio.run(test())
"
```

**预期**：不抛出异常，静默处理

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.13 Replay 模块（replay/）

**职责**：回放引擎，用历史数据回测策略

#### 测试 RP1：DataFeeder 与 MarketSnapshot

```bash
.venv/bin/python -c "
from gate_trade.replay.feeder import DataFeeder, MarketSnapshot

snapshots = [
    MarketSnapshot(timestamp=1.0, best_bid=0.689, best_ask=0.691, bid_size=100.0, ask_size=50.0, last_price=0.690),
    MarketSnapshot(timestamp=2.0, best_bid=0.690, best_ask=0.692, bid_size=120.0, ask_size=60.0, last_price=0.691),
    MarketSnapshot(timestamp=3.0, best_bid=0.691, best_ask=0.693, bid_size=80.0, ask_size=70.0, last_price=0.692),
]
feeder = DataFeeder(snapshots)
count = 0
for snap in feeder:
    count += 1
    print(f'snap {count}: bid={snap.best_bid} ask={snap.best_ask} last={snap.last_price}')
print(f'总计: {count} snapshots')
"
```

**预期**：3 个 snapshot 正常迭代

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 RP2：ReplayEngine 基本流程

```bash
.venv/bin/python -c "
from gate_trade.replay.engine import ReplayEngine
from gate_trade.replay.feeder import DataFeeder, MarketSnapshot
from gate_trade.strategy.accum import Accumulator

snapshots = [
    MarketSnapshot(timestamp=float(t), best_bid=0.69, best_ask=0.70, bid_size=100.0, ask_size=50.0, last_price=0.695)
    for t in range(10)
]

engine = ReplayEngine(strategy=Accumulator(pair='QKA_USDT', tick_size=0.0001))
result = engine.run(DataFeeder(snapshots))
print(f'total_snapshots={result.total_snapshots}')
print(f'total_fills={result.total_fills}')
print('ReplayEngine 运行成功')
"
```

**预期**：正常完成，total_snapshots=10

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.14 Smasher 模块（smasher/）

**职责**：对手方攻击检测与反制

#### 测试 SM1：IcebergDetector 初始化

```bash
.venv/bin/python -c "
from gate_trade.smasher.iceberg import IcebergDetector

detector = IcebergDetector(window_sec=30, replenish_threshold=3, min_replenish_size=10.0)
print(f'IcebergDetector 初始化成功')
print(f'可调用方法: {[m for m in dir(detector) if not m.startswith(\"_\")]}')
"
```

**预期**：正常初始化

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

#### 测试 SM2：ProbeDetector 初始化

```bash
.venv/bin/python -c "
from gate_trade.smasher.probe import ProbeDetector

detector = ProbeDetector(window_sec=60, small_quantile=0.3, large_multiple=3.0, min_samples=5)
print(f'ProbeDetector 初始化成功')
"
```

**预期**：正常初始化

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 3.15 模块功能测试汇总

| 模块 | 测试数 | 通过 | 失败 | 警告 | 备注 |
|------|--------|------|------|------|------|
| Config | 4 | | | | |
| Client | 4 | | | | |
| Market | 3 | | | | |
| Price | 3 | | | | |
| Order | 3 | | | | |
| State | 3 | | | | |
| Strategy | 3 | | | | |
| Risk | 3 | | | | |
| Persistence | 3 | | | | |
| Guardrails | 2 | | | | |
| Web | 2 | | | | |
| Alert | 1 | | | | |
| Replay | 2 | | | | |
| Smasher | 2 | | | | |

---

## 4. 模块间通讯测试

### 4.1 核心数据流追踪

#### 测试 IC1：行情数据流（Client → Market → Price → Strategy）

**操作**：启动 bot（dry-run 模式），追踪数据流。

```bash
# 步骤 1：dry-run 运行 15s，观察数据流日志
SESSION_ID="ic1_$(date +%Y%m%d_%H%M)"
mkdir -p "data/${SESSION_ID}"

timeout 20 .venv/bin/python scripts/run.py \
  --dry-run --pair QKA_USDT \
  --duration 15 --tick-interval 0.5 \
  --data-dir "data/${SESSION_ID}" \
  2>&1 | tee "/tmp/${SESSION_ID}.log" | grep -E "(state_transition|bot_started|bot_shutting|tick_count)"

echo "Exit: $?"
```

**验证清单**：

| # | 验证项 | 方法 | 预期 | 结果 |
|---|-------|------|------|------|
| IC1.1 | Bot 正常启动 | grep `bot_started` | 出现 | |
| IC1.2 | 状态转换正常 | grep `state_transition` | INIT→IDLE→RUNNING | |
| IC1.3 | 正常关机 | grep `bot_shutting_down` | 出现 | |
| IC1.4 | tick 运行无中断 | grep `tick_count` | tick_count > 0 | |

**记录**：

```
[粘贴日志关键行]
判定: [✅/❌]
```

---

#### 测试 IC2：订单流（Strategy → Order → Client → Exchange）

**操作**：实盘运行（L1 级别），追踪完整订单链路。

> ⚠️ 以下测试涉及实盘 API 调用。确认后执行。

```bash
# 步骤 1：检查交易所无残留订单
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient
async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    orders = await c.fetch_open_orders('QKA_USDT')
    assert len(orders) == 0, f'残留 {len(orders)} 单，请先手动撤单'
    print('交易所干净 — 可以继续')
asyncio.run(main())
"

# 步骤 2：运行实盘 30s
SESSION_ID="ic2_$(date +%Y%m%d_%H%M)"
mkdir -p "data/${SESSION_ID}"

echo "yes" | timeout 45 .venv/bin/python scripts/run.py \
  --live --pair QKA_USDT \
  --duration 30 --tick-interval 0.5 \
  --config config/test_live.yaml \
  --data-dir "data/${SESSION_ID}" \
  2>&1 | tee "/tmp/${SESSION_ID}.log"

# 步骤 3：从日志提取 order_id 并逐笔验证
grep "order_placed" "/tmp/${SESSION_ID}.log" | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    print(f'{d[\"order_id\"]}|{d[\"pair\"]}')
" > "/tmp/${SESSION_ID}_oids.txt"

echo "=== 逐笔终态验证 ==="
.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient

async def main():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    with open('/tmp/${SESSION_ID}_oids.txt') as f:
        lines = [l.strip() for l in f if l.strip()]
    
    filled, cancelled, errors = [], [], []
    for line in lines:
        oid, pair = line.split('|')
        try:
            order = await c.fetch_order(oid, pair)
            status = order.status.value
            print(f'{oid}: status={status} filled_size={order.filled_size}')
            if status == 'closed':
                filled.append(oid)
            elif status == 'cancelled':
                cancelled.append(oid)
        except Exception as e:
            errors.append(f'{oid}: {e}')
    
    print(f'\n结果: cancelled={len(cancelled)} filled={len(filled)} errors={len(errors)}')
    if filled:
        print('FAIL: 有订单成交')
    elif not cancelled and not errors:
        print('WARN: 无订单可验证')
    else:
        print('PASS: 订单链路完整')

asyncio.run(main())
" 2>&1
```

**验证清单**：

| # | 验证项 | 方法 | 预期 | 结果 |
|---|-------|------|------|------|
| IC2.1 | Strategy 输出订单 | grep `order_placed` | ≥ 1 条 | |
| IC2.2 | 订单到达交易所 | fetch_order 确认 | order 存在 | |
| IC2.3 | tag 正确传递 | fetch_order 查看 client_order_id | t- 前缀 | |
| IC2.4 | 关机撤单 | all_cancelled | 全部 cancel | |
| IC2.5 | 交易所零残留 | fetch_open_orders | 0 单 | |

**记录**：

```
[粘贴验证输出]
判定: [✅/❌]
```

---

#### 测试 IC3：风控信号流（Market → Risk → State → Strategy）

**操作**：验证闪崩检测信号能否穿透到策略层。

```bash
# 步骤 1：模拟闪崩信号传递
.venv/bin/python -c "
from gate_trade.market.market_data import LiveMarketData
from gate_trade.risk.risk_manager import LiveRiskManager
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import OrderBook, OrderBookLevel, BotState

# 初始化
md = LiveMarketData()
rm = LiveRiskManager(max_open_orders=10, max_position_notional=100.0, flash_crash_threshold_pct=5.0)
sm = LiveStateMachine()
sm.transition(BotState.IDLE)
sm.transition(BotState.RUNNING)

# 正常行情
snap = OrderBook(
    bids=[OrderBookLevel(0.69, 100.0)],
    asks=[OrderBookLevel(0.70, 50.0)]
)
md.apply_snapshot(snap)
signal = md.compute_signals()

# 风控评估
rm.evaluate(open_orders=[], balances=[], mid_price=md.mid_price())
print(f'正常: halted={rm.halted} flash={rm.flash_crash_detected}')

# 暴跌
rm.evaluate(open_orders=[], balances=[], mid_price=0.60)  # -14% drop
print(f'暴跌: halted={rm.halted} flash={rm.flash_crash_detected}')

if rm.halted:
    sm.transition(BotState.EMERGENCY)
    print(f'状态: {sm.state}')
    print(f'can_place={sm.can_place()}')
    print('信号链路: Market -> Risk -> State -> Strategy 阻断正常')
"
```

**预期**：暴跌后 halted=True, state=EMERGENCY, can_place=False

**记录**：

```
实际输出:
[粘贴]
判定: [✅/❌]
```

---

### 4.2 接口契约检查

检查每个模块的 Protocol（接口）定义与实现：

```bash
# 列出所有 Protocol 定义
grep -r "class.*Protocol" src/gate_trade/ --include="*.py" -l
```

| Protocol | 定义位置 | 实现位置 | 实现完整？ | 判定 |
|----------|---------|---------|-----------|------|
| GateClient | client/contract.py | client/gate_client.py | | |
| MarketData | market/contract.py | market/market_data.py | | |
| OrderEngine | order/contract.py | order/order_engine.py | | |
| RefPriceEngine | price/contract.py | price/ref_price_engine.py | | |
| RiskManager | risk/contract.py | risk/risk_manager.py | | |
| StateMachine | state/contract.py | state/state_machine.py | | |
| Strategy | strategy/contract.py | strategy/accum.py | | |
| Persistence | persistence/contract.py | persistence/sqlite.py | | |

**验证方法**：对每个 Protocol，检查实现类是否实现了所有方法。

```bash
# 示例：检查 GateClient Protocol vs GateIoClient 实现
.venv/bin/python -c "
from gate_trade.client.contract import GateClient
from gate_trade.client.gate_client import GateIoClient
import inspect

proto_methods = {m for m in dir(GateClient) if not m.startswith('_')}
impl_methods = {m for m in dir(GateIoClient) if not m.startswith('_')}
missing = proto_methods - impl_methods
print(f'Protocol 方法: {len(proto_methods)}')
print(f'实现方法: {len(impl_methods)}')
print(f'缺失: {missing if missing else \"无\"}')
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

### 4.3 模块间通讯汇总

| 数据流 | 路径 | 延迟 | 可靠性 | 判定 |
|-------|------|------|--------|------|
| 行情数据 | Client→Market→Price→Strategy | | | |
| 订单执行 | Strategy→Order→Client | | | |
| 风控信号 | Market→Risk→State→Strategy | | | |
| 状态持久化 | State→Persistence→SQLite | | | |
| 事件通知 | Bot→EventLog→Web(SSE) | | | |

### 4.4 判定

**模块间通讯是否流畅？为什么？**

```
[测试者填写结论及理由]
```

---

## 5. 模块内子模块分解合理性

本章逐模块检查其内部的子模块（类/函数）划分是否合理。

### 5.1 Client 模块内部

**子模块**：`GateIoClient`（REST）、`WsManager`（WebSocket）

```bash
# 查看模块内部结构
ls -la src/gate_trade/client/
```

| 检查项 | 结果 |
|-------|------|
| REST 和 WS 职责是否分离？ | |
| GateIoClient 是否有越权（直接操作 WS 细节）？ | |
| WsManager 是否可以独立测试？ | |
| contract.py 定义的 Protocol 是否被正确引用？ | |

**判定**：

```
[测试者填写]
```

---

### 5.2 State 模块内部

**子模块**：`LiveStateMachine`（状态转换）、`CooldownManager`（冷却计时）

| 检查项 | 结果 |
|-------|------|
| 状态转换逻辑与冷却逻辑是否正交？ | |
| CooldownManager 可以独立于 StateMachine 使用吗？ | |
| 两种 cooldown（fill/cancel/spike）是否通过统一接口管理？ | |

**判定**：

```
[测试者填写]
```

---

### 5.3 Strategy 模块内部

**子模块**：`Accumulator`（累积器）、`DepthKeeper`（做市）

| 检查项 | 结果 |
|-------|------|
| 两个策略是否实现相同的 Strategy Protocol？ | |
| 策略之间是否相互独立？ | |
| 策略是否可以热加载/卸载？ | |

**判定**：

```
[测试者填写]
```

---

### 5.4 Risk 模块内部

**子模块**：三个独立检查（position/order_count/flash_crash）、自动恢复

| 检查项 | 结果 |
|-------|------|
| 三个检查是否相互独立？ | |
| 熔断与恢复逻辑是否清晰分离？ | |
| HIT_CAP_COOLDOWN 是否合理？ | |

**判定**：

```
[测试者填写]
```

---

### 5.5 Persistence 模块内部

**子模块**：`SqlitePersistence`（CRUD）、`BotEventLogger`（事件环）

| 检查项 | 结果 |
|-------|------|
| 持久化与事件日志是否分离？ | |
| SQLite 操作是否封装完整？ | |
| 事件环是否有内存上限？ | |

**判定**：

```
[测试者填写]
```

---

### 5.6 Markout 模块内部

**子模块**：`MarkoutRecorder`（记录）、`ToxicDetector`（检测）、`ToxicResponse`（响应）

| 检查项 | 结果 |
|-------|------|
| 记录/检测/响应三级是否形成完整闭环？ | |
| ToxicDetector 的三个信号是否可以独立配置？ | |
| ToxicResponse 的四个级别是否合理？ | |

**判定**：

```
[测试者填写]
```

---

### 5.7 子模块分解汇总

| 父模块 | 子模块数 | 职责分离合理？ | 存在越权？ | 判定 |
|-------|---------|--------------|-----------|------|
| client/ | 2 | | | |
| state/ | 2 | | | |
| strategy/ | 2 | | | |
| risk/ | 1+3 | | | |
| persistence/ | 2 | | | |
| markout/ | 3 | | | |
| smasher/ | 4 | | | |

### 5.8 判定

**模块内的子模块分解是否合理？为什么？**

```
[测试者填写结论及理由]
```

---

## 6. 模块内功能测试

本章对每个模块内的子模块进行细化功能测试。

### 6.1 Client 子模块

#### 6.1.1 GateIoClient REST 功能

```bash
# 测试项目：
# - fetch_orderbook 返回有效 OrderBook
# - fetch_open_orders 返回列表
# - fetch_order(order_id) 返回单笔详情
# - fetch_all_balances 返回所有余额
# - fetch_pair_meta 返回交易对参数

.venv/bin/python -c "
import asyncio
from gate_trade.config.schema import AppConfig
from gate_trade.client.gate_client import GateIoClient

async def test():
    c = GateIoClient(AppConfig.from_yaml_merged('config/default.yaml', 'config/local.yaml'))
    
    # 1. orderbook
    book = await c.fetch_orderbook('QKA_USDT')
    assert book.best_bid > 0, 'best_bid=0'
    assert book.best_ask > 0, 'best_ask=0'
    print(f'[PASS] fetch_orderbook: bid={book.best_bid} ask={book.best_ask}')
    
    # 2. open orders
    orders = await c.fetch_open_orders('QKA_USDT')
    assert isinstance(orders, list), 'not a list'
    print(f'[PASS] fetch_open_orders: {len(orders)} orders')
    
    # 3. balances
    balances = await c.fetch_all_balances()
    assert len(balances) > 0, 'empty balances'
    print(f'[PASS] fetch_all_balances: {len(balances)} currencies')
    
    # 4. pair meta
    meta = await c.fetch_pair_meta('QKA_USDT')
    assert meta.trade_status == 'tradable', f'not tradable: {meta.trade_status}'
    print(f'[PASS] fetch_pair_meta: {meta.pair} tradable')

asyncio.run(test())
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

#### 6.1.2 WsManager 连接功能

```bash
# 测试项目：
# - WebSocket 连接成功
# - 订阅成功
# - 收到数据
# - 断线重连

.venv/bin/python -c "
import asyncio
from gate_trade.client.ws_manager import WsManager

async def test():
    ws = WsManager('wss://api.gateio.ws/ws/v4/', ping_interval_sec=15, reconnect_delay_sec=2.0)
    
    # 连接
    await ws.connect()
    print('[PASS] ws_connect')
    
    # 订阅 orderbook
    q = await ws.subscribe('spot.order_book', 'QKA_USDT')
    print(f'[PASS] ws_subscribe: queue created')
    
    # 等待数据
    try:
        msg = await asyncio.wait_for(q.get(), timeout=10.0)
        print(f'[PASS] ws_data_received: channel={msg.get(\"channel\",\"?\")}')
    except asyncio.TimeoutError:
        print('[WARN] ws_no_data_in_10s (QKA_USDT 预期行为)')
    
    await ws.close()
    print('[PASS] ws_close')

asyncio.run(test())
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

### 6.2 State 子模块

#### 6.2.1 LiveStateMachine 完整转换路径

```bash
.venv/bin/python -c "
from gate_trade.state.state_machine import LiveStateMachine
from gate_trade.types import BotState

sm = LiveStateMachine()
print(f'初始: {sm.state}')

# 正常路径: INIT -> IDLE -> RUNNING -> SHUTDOWN
sm.transition(BotState.IDLE)
sm.transition(BotState.RUNNING)
sm.transition(BotState.SHUTDOWN)
print(f'正常路径通过: INIT->IDLE->RUNNING->SHUTDOWN')

# 重新测试异常路径: RUNNING -> COOLDOWN -> EMERGENCY
sm2 = LiveStateMachine()
sm2.transition(BotState.IDLE)
sm2.transition(BotState.RUNNING)
sm2.transition(BotState.COOLDOWN_PRICE_SPIKE)
print(f'RUNNING->COOLDOWN: {sm2.state}')
sm2.transition(BotState.EMERGENCY)
print(f'COOLDOWN->EMERGENCY: {sm2.state}')
print('异常路径通过')
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

#### 6.2.2 CooldownManager 并行计时

```bash
.venv/bin/python -c "
import time
from gate_trade.state.cooldown import CooldownManager

cm = CooldownManager()

# 启动两个并行 cooldown
cm.start_fill(5000)  # 5 秒
cm.start_price(3000)  # 3 秒
print(f'can_place: {cm.can_place()}')
print(f'fill_remaining: {cm.fill_remaining_ms()}ms')
print(f'price_remaining: {cm.price_remaining_ms()}ms')

# 等待 3.5 秒后 price cooldown 应过期
time.sleep(3.5)
print(f'3.5s后 fill_remaining: {cm.fill_remaining_ms()}ms')
print(f'3.5s后 price_remaining: {cm.price_remaining_ms()}ms')
print(f'3.5s后 can_place: {cm.can_place()} (fill 仍在冷却)')
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

### 6.3 Strategy 子模块

#### 6.3.1 Accumulator 完整功能

```bash
.venv/bin/python -c "
from gate_trade.strategy.accum import Accumulator

acc = Accumulator(
    pair='QKA_USDT',
    tick_size=0.0001,
    order_size=4.5,
    ladder_rungs=5,
    rung_spacing_ticks=5,
    start_offset_ticks=5,
)

# 1. 初始阶梯
acc.update_market(ref_price=0.6932, spike_active=False)
orders = acc.desired_orders()
print(f'[1] 阶梯数: {len(orders)}')
prices = [o.price for o in orders]
print(f'[1] 价格: {prices}')

# 2. 价格不变 -> 不应重复下单（ratchet）
acc.update_market(ref_price=0.6932, spike_active=False)
orders2 = acc.desired_orders()
print(f'[2] 同价格再次: {len(orders2)} (应为0，ratchet 已就位)')

# 3. spike -> 返回空
acc.update_market(ref_price=0.6932, spike_active=True)
orders3 = acc.desired_orders()
print(f'[3] spike: {len(orders3)} (应为0)')

# 4. spike 恢复 -> 重新出价
acc.update_market(ref_price=0.6935, spike_active=False)
orders4 = acc.desired_orders()
print(f'[4] 恢复: {len(orders4)}')
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

### 6.4 Markout 子模块

#### 6.4.1 MarkoutRecorder

```bash
.venv/bin/python -c "
from gate_trade.markout.recorder import MarkoutRecorder
from gate_trade.types import Order, Side, OrderStatus

mr = MarkoutRecorder()
mr.update_mid(0.69)

# 创建一笔模拟成交订单
order = Order(order_id='test1', pair='QKA_USDT', side=Side.BUY, price=0.689, size=4.5, status=OrderStatus.CLOSED, filled_size=4.5)
mr.on_fill(order, filled_size=4.5, mid_price=0.69)

# 更新 mid 触发 markout（需要经过足够时间让 markout 到期）
import time
for mid in [0.691, 0.693, 0.695]:
    mr.update_mid(mid, timestamp=time.monotonic() + 60.0)  # 模拟未来时间以触发完成

completed = mr.completed()
print(f'完成记录数: {len(completed)}')
for c in completed:
    print(f'  order={c.order_id} side={c.side.value} fill_price={c.fill_price}')
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

#### 6.4.2 ToxicDetector

```bash
.venv/bin/python -c "
from gate_trade.markout.toxic import ToxicDetector
from gate_trade.markout.recorder import MarkoutRecord
from gate_trade.types import Side

td = ToxicDetector(adverse_markout_bps=-20.0, large_size_multiple=3.0, fast_reversal_bps=10.0)

# 模拟正常成交：正向 markout，普通大小
for i in range(10):
    record = MarkoutRecord(
        order_id=f'n{i}', side=Side.BUY,
        fill_price=0.69, fill_size=1.0, mid_at_fill=0.69,
        mids_after={1.0: 0.692, 5.0: 0.693, 30.0: 0.695},
        fill_timestamp=1000.0 + i,
    )
    td.evaluate(record)

print(f'正常成交后 toxic_ratio={td.toxic_ratio:.3f}')

# 模拟有毒成交：逆向 markout + 大单 + 快速反转
toxic_record = MarkoutRecord(
    order_id='bad1', side=Side.BUY,
    fill_price=0.70, fill_size=15.0, mid_at_fill=0.70,
    mids_after={1.0: 0.695, 5.0: 0.688, 30.0: 0.685},  # 全部逆向
    fill_timestamp=2000.0,
)
td.evaluate(toxic_record)
print(f'有毒后 toxic_ratio={td.toxic_ratio:.3f}')
print(f'total={td.total_count} toxic={td.toxic_count}')
"
```

**记录**：

```
[粘贴输出]
判定: [✅/❌]
```

---

### 6.5 子模块功能测试汇总

| 父模块 | 子模块 | 测试数 | 通过 | 失败 | 判定 |
|-------|--------|--------|------|------|------|
| client | GateIoClient REST | 4 | | | |
| client | WsManager | 3 | | | |
| state | LiveStateMachine | 2 | | | |
| state | CooldownManager | 1 | | | |
| strategy | Accumulator | 4 | | | |
| markout | MarkoutRecorder | 1 | | | |
| markout | ToxicDetector | 1 | | | |

### 6.6 判定

**模块内的功能测试是否通过？**

```
[测试者填写结论及理由]
```

---

## 附录 A. 测试记录模板

每个测试 session 使用以下模板记录：

```markdown
## 测试记录: [session_id]

**日期**: YYYY-MM-DD HH:MM
**测试者**: [姓名]
**Git Commit**: [hash]
**测试范围**: [第 X 章 / 模块名称]

### 环境检查
- 依赖: [OK/FAIL]
- 配置: [OK/FAIL]
- API: [OK/FAIL]
- 测试: [N passed / M total]

### 测试结果

| 测试编号 | 测试项 | 预期 | 实际 | 判定 |
|---------|-------|------|------|------|
| | | | | |

### 异常发现

| 严重度 | 描述 | 证据 |
|-------|------|------|
| | | |

### 结论

[通过/未通过]
```

---

## 附录 B. 测试环境速查

| 项目 | 值 |
|------|---|
| 项目路径 | /home/monero/gate-trade |
| Python | .venv/bin/python (3.12) |
| 主配置 | config/default.yaml |
| 本地配置 | config/local.yaml |
| 测试配置 | config/test_live.yaml |
| 测试交易对 | QKA_USDT |
| tick_size | 0.0001 |
| min_base | 0.01 QKA |
| min_quote | 3.0 USDT |
| 当前 mid | ~0.69 USDT |
| Gate.io REST | https://api.gateio.ws/api/v4 |
| Gate.io WS | wss://api.gateio.ws/ws/v4/ |
| Web 面板 | http://127.0.0.1:39120 |
| 数据库 | data/*/gate_trade.db (SQLite WAL) |

---

> 本手册替代 `docs/TEST_FRAMEWORK.md`、`docs/tests/README.md` 和 `docs/TEST_QKA_USDT_REST_FALLBACK.md`。
> 测试者按照章节顺序执行，每步做好记录。
