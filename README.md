# MetricPulse — 运维 Agent

基于 Python 的智能运维 Agent，整合 **Prometheus 监控查询** + **业务拓扑图谱引擎** + **LangGraph AI 对话**，
支持语义化指标配置、依赖链故障发现、自然语言运维交互。

## 架构

```
MetricPulse/
├── src/metricpulse/
│   ├── agent.py              # OpsAgent 编排层
│   ├── config_loader.py      # YAML 配置 + .env 加载
│   ├── monitor/              # 监控查询模块
│   │   ├── config.py         #   MetricConfig 语义化配置模型
│   │   ├── client.py         #   Prometheus HTTP API 客户端
│   │   └── query.py          #   PromQL 查询构建器
│   ├── topology/             # 拓扑图谱引擎
│   │   ├── model.py          #   Node / Edge 数据模型
│   │   ├── graph.py          #   DependencyGraph 图引擎 (networkx)
│   │   └── discovery.py      #   FaultDiscovery 故障传播分析
│   └── ai/                   # AI Agent 扩展层 (LangGraph)
│       ├── state.py          #   LangGraph 状态定义
│       ├── tools.py          #   5 个 LangChain Tool
│       ├── graph.py          #   推理-行动循环图
│       └── agent.py          #   AIChatAgent 对话入口
├── config/
│   ├── metrics.yaml          # 指标配置示例
│   └── topology.yaml         # 业务拓扑配置示例
├── examples/
│   ├── demo.py               # 核心引擎演示
│   └── demo_ai.py            # AI 对话演示
├── .env.example              # 环境变量模板
├── .gitignore
├── pyproject.toml
└── README.md
```

## 三大模块

### 1. Monitor — 语义化监控查询

`MetricConfig` 将 Prometheus 指标查询包装为携带业务语义的配置对象，`QueryBuilder` 自动编译为标准 PromQL：

```python
from metricpulse import MetricConfig, MetricCategory, Threshold, Severity

MetricConfig(
    id="gateway_latency_p99",
    category=MetricCategory.LATENCY,           # 驱动默认 PromQL 模板
    metric_name="http_request_duration_seconds",
    description="网关 P99 延迟",
    service="api-gateway",                     # 关联拓扑节点
    labels={"job": "api-gateway"},
    thresholds=[
        Threshold(operator="gt", value=0.5, severity=Severity.WARNING),
        Threshold(operator="gt", value=1.0, severity=Severity.CRITICAL),
    ],
    extra={"promql_fragment": "* 100"},        # 注入自定义 PromQL 片段
)
```

| `category` | 默认聚合模板 |
|---|---|
| `latency` | `histogram_quantile(0.99, rate(...))` |
| `error_rate` | `rate(...) > 0` |
| `throughput` | `rate(...)` |
| `saturation` | `avg(...)` |
| `custom` | 裸指标名 |

### 2. Topology — 图谱引擎

基于 networkx 的有向依赖图。边方向 `from → to` = `from` 依赖 `to`：

- **Predecessors** → 上游消费者（爆炸半径）
- **Successors** → 下游依赖（候选根因）

```python
from metricpulse import DependencyGraph, Node, Edge, EdgeWeight, FaultDiscovery

graph = DependencyGraph().build(nodes, edges)
discovery = FaultDiscovery(graph)

# 单节点故障分析
report = discovery.analyze("postgres-primary")
print(report.impacted_services)    # ['api-gateway', 'order-service', 'payment-service', ...]
print(report.possible_root_causes) # 下游依赖链最深节点

# 多节点联合根因定位 — 下游交集 → 最可疑根因
joint = discovery.joint_analyze(["order-service", "payment-service"])
print(joint.possible_root_causes)  # ['Postgres']
```

### 3. AI Agent — LangGraph 对话 (可选)

在核心模块之上叠加 LLM 推理层，支持自然语言运维交互。**底层 Monitor/Topology 完全不受影响**，纯扩展。

```python
from langchain_openai import ChatOpenAI
from metricpulse import load_env, load_metric_configs, load_topology
from metricpulse.ai import AIChatAgent

load_env()  # 自动加载 .env → OPENAI_API_KEY / OPENAI_API_BASE / OPENAI_MODEL
configs = load_metric_configs("config/metrics.yaml")
graph   = load_topology("config/topology.yaml")

agent = AIChatAgent(
    llm=ChatOpenAI(model="gpt-4o", base_url=..., api_key=...),
    metric_configs=configs,
    graph=graph,
    prometheus_url="http://localhost:9090",
)

# 多轮对话
print(await agent.chat("支付服务状态如何？"))
print(await agent.chat("postgres-primary 故障会影响哪些服务？"))

# 流式输出
async for token in agent.stream("全面巡检"):
    print(token, end="")
```

**5 个 LLM 可调用工具：**

| 工具 | 能力 |
|---|---|
| `query_metric(id)` | 查询单个指标当前值 + 阈值判定 |
| `query_service_metrics(svc)` | 查询某服务全部指标，带告警状态 |
| `analyze_service_topology(svc)` | 拓扑分析：爆炸半径 + 依赖链 + 候选根因 |
| `list_services()` | 列出所有拓扑节点及类型 |
| `list_metrics()` | 列出所有指标配置及阈值 |

## 快速开始

```bash
# 1. 基础安装
pip install -e .

# 2. (可选) AI 对话能力
cp .env.example .env          # 编辑 .env 填入 API Key
pip install -e ".[ai]"

# 3. 运行
python examples/demo.py                          # 核心引擎演示（无需外部服务）
python examples/demo.py http://localhost:9090    # 对接真实 Prometheus
python examples/demo_ai.py                       # AI 对话演示
python examples/demo_ai.py --offline             # AI 离线演示（仅工具调用）
```

## .env 配置

```bash
# 支持 OpenAI / 智谱 / DeepSeek 等兼容 API
OPENAI_API_KEY=sk-your-key
OPENAI_API_BASE=https://api.openai.com/v1/   # 自定义端点
OPENAI_MODEL=gpt-4o                           # 模型选择
PROMETHEUS_URL=http://localhost:9090          # Prometheus 地址
```
