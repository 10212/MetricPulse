"""metricpulse — 运维 Agent。

整合 Prometheus 监控查询 + 业务拓扑图谱引擎，
提供灵活可扩展的语义化指标配置与依赖链故障发现能力。

内置 AI Agent 扩展层（基于 LangGraph），支持自然语言运维对话。
支持 .env 文件管理环境变量（OPENAI_API_KEY 等）。

Usage:
    from metricpulse import load_env, load_metric_configs, load_topology

    load_env()                          # 自动加载 .env
    configs = load_metric_configs("config/metrics.yaml")
    graph = load_topology("config/topology.yaml")
"""

from .agent import AgentReport, MetricAlert, OpsAgent
from .config_loader import load_env, load_metric_configs, load_topology
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
    # Config
    "load_env",
    "load_metric_configs",
    "load_topology",
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
