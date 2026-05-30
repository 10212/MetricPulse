# AI Agent

LangGraph 运维 AI 对话层。可选扩展，核心 Monitor/Topology 可独立运行。

## 文件

| 文件 | 职责 |
|---|---|
| state.py | AgentState — LangGraph 共享状态定义 |
| tools.py | 5 个 LangChain Tool，封装 Monitor/Topology 能力供 LLM 调用 |
| graph.py | 推理-行动循环图：agent -> tools -> agent -> END |
| agent.py | AIChatAgent — 对话入口，支持多轮对话和流式输出 |

## 5 个 LLM 工具

| 工具 | 能力 |
|---|---|
| query_metric(id) | 查询单个指标当前值 + 阈值判定 |
| query_service_metrics(svc) | 查询某服务全部指标，带告警状态 |
| analyze_service_topology(svc) | 拓扑分析：爆炸半径 + 依赖链 + 候选根因 |
| list_services() | 列出所有拓扑节点及类型 |
| list_metrics() | 列出所有指标配置及阈值 |

## 使用

```python
from langchain_openai import ChatOpenAI
from metricpulse.ai import AIChatAgent

agent = AIChatAgent(
    llm=ChatOpenAI(model="gpt-4o"),
    metric_configs=configs,
    graph=graph,
    prometheus_url="http://localhost:9090",
)
print(await agent.chat("支付服务状态如何？"))

# 流式输出
async for token in agent.stream("postgres-primary 故障影响哪些服务？"):
    print(token, end="")
```

## 依赖

```bash
pip install -e ".[ai]"
```