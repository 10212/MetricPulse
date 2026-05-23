# MetricPluse — 运维 Agent

基于 Python 的运维 Agent，整合 **Prometheus 监控查询** 与 **业务拓扑图谱引擎**，
提供灵活可扩展的语义化指标配置与依赖链故障发现能力。

## 架构

```
MetricPluse/
├── src/metricpluse/
│   ├── agent.py              # OpsAgent 编排层
│   ├── config_loader.py      # YAML 配置加载
│   ├── monitor/
│   │   ├── config.py         # MetricConfig 语义化配置模型
│   │   ├── client.py         # Prometheus HTTP API 客户端
│   │   └── query.py          # PromQL 查询构建器
│   └── topology/
│       ├── model.py          # Node / Edge 数据模型
│       ├── graph.py          # DependencyGraph 图引擎 (networkx)
│       └── discovery.py      # FaultDiscovery 故障传播分析
├── config/
│   ├── metrics.yaml          # 指标配置示例
│   └── topology.yaml         # 业务拓扑配置示例
└── examples/
    └── demo.py               # 命令行演示入口
```

## 两大核心模块

### 1. Monitor — 监控查询

MetricConfig 是核心抽象，将 Prometheus 指标查询包装为**携带业务语义**的配置对象：

```python
from metricpluse import MetricConfig, MetricCategory, Threshold, Severity

MetricConfig(
    id="gateway_latency_p99",
    category=MetricCategory.LATENCY,
    metric_name="http_request_duration_seconds",
    description="网关 P99 延迟",      # 人类可读
    service="api-gateway",            # 关联拓扑节点
    labels={"job": "api-gateway"},
    thresholds=[
        Threshold(operator="gt", value=0.5, severity=Severity.WARNING),
        Threshold(operator="gt", value=1.0, severity=Severity.CRITICAL),
    ],
)
```

- `category` 驱动默认 PromQL 模板（latency → histogram_quantile, error_rate → rate...）
- `labels` 映射为 Prometheus 标签过滤器
- `extra.promql_fragment` 支持注入自定义 PromQL 片段（如 `/ redis_memory_max_bytes * 100`）
- `thresholds` 定义多级告警阈值

### 2. Topology — 图谱引擎

基于 networkx 的有向依赖图引擎，边方向 `from → to` 表示 `from` 依赖 `to`：

```python
from metricpluse import DependencyGraph, Node, Edge, EdgeWeight, FaultDiscovery

graph = DependencyGraph().build(nodes, edges)
discovery = FaultDiscovery(graph)

# 单节点故障分析
report = discovery.analyze("postgres-primary")
print(report.impacted_services)   # 所有受影响的上游服务
print(report.possible_root_causes) # 下游根因候选

# 多节点联合根因定位
joint = discovery.joint_analyze(["order-service", "payment-service"])
print(joint.possible_root_causes)  # 共同依赖 → 最可疑根因
```

故障发现算法：
- **爆炸半径**：BFS 沿上游遍历，找出所有受影响的消费者，按依赖权重分组
- **根因定位**：BFS 沿下游遍历依赖链，最深层的共同依赖即为候选根因

## 快速开始

```bash
pip install -e .

# 演示拓扑分析（不需要 Prometheus）
python examples/demo.py --topology

# 完整 Agent 巡检（需要可访问的 Prometheus）
python examples/demo.py http://your-prometheus:9090
```

## 编程 API

```python
import asyncio
from metricpluse import OpsAgent
from metricpluse.config_loader import load_metric_configs, load_topology

async def main():
    configs = load_metric_configs("config/metrics.yaml")
    graph = load_topology("config/topology.yaml")

    agent = OpsAgent(prometheus_url="http://localhost:9090", graph=graph)
    report = await agent.run(configs)

    print(report.summary)
    # 指标总数: 7, 正常: 5, 异常: 2
    # [critical] 支付服务错误率 = 0.06 (阈值: >0.5%)
    # 故障分析: 支付服务
    #   爆炸半径: 2 个受影响服务 [critical] gateway, order
    #   候选根因: Postgres

asyncio.run(main())
```

## 扩展性

- **MetricConfig.extra**：任意扩展字段，注入自定义 PromQL、附加元数据
- **MetricCategory.CUSTOM**：完全自定义的指标类型
- **Node.metadata**：节点级扩展元数据
- **EdgeWeight**：四级依赖权重，驱动故障影响量化
