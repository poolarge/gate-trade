# Gate Trade

Spot unilateral accumulation + market-making bot for Gate.io.

## 部署

```bash
git clone https://github.com/poolarge/gate-trade.git
cd gate-trade
python3 -m venv .venv
.venv/bin/pip install -e .
```

依赖：Python 3.12+，无需数据库服务（SQLite 单文件）。

## 运行

### 1. 模拟盘（默认，安全）

无需 API Key，使用合成行情数据：

```bash
python scripts/run.py --pair BTC_USDT

# 限制运行时长
python scripts/run.py --pair BTC_USDT --duration 60

# 自定义 tick 间隔和数据目录
python scripts/run.py --pair BTC_USDT --tick-interval 0.25 --data-dir /path/to/data
```

### 2. 实盘（真金白银）

```bash
GATE_EXCHANGE__API_KEY=你的key GATE_EXCHANGE__API_SECRET=你的secret \
  python scripts/run.py --live --pair BTC_USDT
```

运行后会要求输入 `yes` 确认。

## 参数一览

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--pair` | BTC_USDT | 交易对 |
| `--live` | 关闭 | 开启实盘（否则模拟盘） |
| `--tick-interval` | 0.5 | 每次 tick 间隔（秒） |
| `--duration` | 0（无限） | 运行多少秒后自动停止 |
| `--config` | config/default.yaml | 配置文件路径 |
| `--data-dir` | data/ | 数据库和日志存放目录 |

## 看数据

### 实时监控面板

启动后浏览器打开 **http://localhost:39120**，可以看到：

- 机器人状态（RUNNING / EMERGENCY / SHUTDOWN）
- 中间价、点差、Toxic Level
- 活跃订单列表、策略状态
- 实时事件流（tick、下单、风控、尖峰保护等）
- 连接状态指示灯（SSE 长连接，自动重连）

### 事后复盘（SQLite）

数据库位置：`data/gate_trade.db`

```bash
# 查看最近事件
sqlite3 data/gate_trade.db "SELECT * FROM event_log ORDER BY id DESC LIMIT 20;"

# 查看今日成交
sqlite3 data/gate_trade.db "SELECT * FROM fills WHERE date(created_at, 'unixepoch') = date('now');"

# 查看成交统计
sqlite3 data/gate_trade.db "SELECT side, COUNT(*), SUM(price*filled_size) FROM fills GROUP BY side;"
```

### 结构化日志

日志文件：`data/bot.log`

```bash
# 实时 tail
tail -f data/bot.log

# 用 jq 过滤
cat data/bot.log | jq 'select(.event == "dry_run_would_place")'
```

## API 接口

面板提供以下 HTTP API（GET 请求，浏览器可直接访问）：

| 接口 | 说明 |
|------|------|
| `/api/health` | 健康检查 |
| `/api/snapshot` | 当前完整状态快照 |
| `/api/events?limit=100` | 最近事件列表 |
| `/api/stream` | SSE 实时事件推送 |
| `/api/fills?limit=50` | 最近成交记录 |
| `/api/summary` | 今日成交汇总 |

## 配置文件

编辑 `config/default.yaml` 调整策略参数、风控阈值等。环境变量 `GATE_xxx__yyy` 格式可覆盖配置项，例如：

```bash
GATE_LOG_FILE=data/bot.log GATE_RISK__MAX_OPEN_ORDERS=10 python scripts/run.py --pair ETH_USDT
```
