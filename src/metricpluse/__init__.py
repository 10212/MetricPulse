"""metricpluse — 运维 Agent。

整合 Prometheus 监控查询 + 业务拓扑图谱引擎，
提供灵活可扩展的语义化指标配置与依赖链故障发现能力。

Usage:
    import asyncio
    from metricpluse import OpsAgent, MetricConfig, MetricCategory, DependencyGraph

    agent = OpsAgent(prometheus_url="http://localhost:9090", graph=graph)
    report = asyncio.run(agent.run(configs))
"""

from .agent import AgentReport, MetricAlert, OpsAgent
from .monitor.config import MetricCategory, MetricConfig, Severity, Threshold
from .monitor.client import PrometheusClient, QueryResult
from .topology import (
    DependencyGraph,
    Edge,
    EdgeWeight,
    FaultDiscovery,
    FaultReport,
    Node,
    NodeType,
)

__all__ = [
    # Agent
    "OpsAgent",
    "AgentReport",
    "MetricAlert",
    # Monitor
    "MetricConfig",
    "MetricCategory",
    "Threshold",
    "Severity",
    "PrometheusClient",
    "QueryResult",
    # Topology
    "DependencyGraph",
    "Node",
    "NodeType",
    "Edge",
    "EdgeWeight",
    "FaultDiscovery",
    "FaultReport",
]
