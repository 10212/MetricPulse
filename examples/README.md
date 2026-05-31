# Examples

MetricPulse 的演示脚本。

## 脚本

| 文件 | 说明 |
|---|---|
| demo.py | 核心引擎演示 -- 拓扑分析 + MetricConfig->PromQL 编译 + OpsAgent 巡检 |
| demo_ai.py | AI Agent 演示 -- LangGraph 多轮运维对话，支持在线/离线模式 |

## 用法

`ash
# 核心引擎（离线可用）
python examples/demo.py

# 对接真实 Prometheus
python examples/demo.py http://localhost:9090

# AI 对话（需配置 .env）
python examples/demo_ai.py

# AI 离线演示
python examples/demo_ai.py --offline
`
