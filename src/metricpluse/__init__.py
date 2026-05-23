"""metricpluse — 运维 Agent。

整合 Prometheus 监控查询 + 业务拓扑图谱引擎，
提供灵活可扩展的语义化指标配置与依赖链故障发现能力。

内置 AI Agent 扩展层（基于 LangGraph），支持自然语言运维对话。

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

# AI 扩展（可选依赖 langgraph / langchain）
try:
    from .ai import AIChatAgent as _AIChatAgent
    AIChatAgent = _AIChatAgent
    _has_ai = True
except ImportError:
    AIChatAgent = None  # type: ignore[assignment]
    _has_ai = False

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
    # AI (optional)
    "AIChatAgent",
]
