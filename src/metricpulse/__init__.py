"""metricpulse - SRE Agent.

Integrates Prometheus monitoring queries + business topology graph engine.
Provides semantic metric configuration with dependency-chain fault discovery.

Built-in AI Agent extension layer (LangGraph), supports natural language ops dialogue.
Supports .env files for environment variables (OPENAI_API_KEY, etc.).

Usage:
    from metricpulse import load_env, load_metric_configs, load_topology

    load_env()
    configs = load_metric_configs("config/metrics.yaml")
    graph = load_topology("config/topology.yaml")
"""

from .agent import AgentReport, MetricAlert, OpsAgent
from .config_loader import load_env, load_metric_configs, load_topology
from .monitor.config import MetricCategory, MetricConfig, Severity, Threshold
from .monitor.client import PrometheusClient, QueryResult
from .monitor.sliding_window import SustainedResult, evaluate_sustained, parse_duration
from .topology import (
    DependencyGraph,
    Edge,
    EdgeWeight,
    FaultDiscovery,
    FaultReport,
    Node,
    NodeType,
)

# MCP (optional)
try:
    from .mcp import MCPClient, MCPError, create_mcp_tools as _create_mcp_tools
    _has_mcp = True
except ImportError:
    MCPClient = None  # type: ignore[assignment]
    MCPError = None  # type: ignore[assignment]
    _create_mcp_tools = None
    _has_mcp = False

# AI (optional)
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
    "SustainedResult",
    "evaluate_sustained",
    "parse_duration",
    # Topology
    "DependencyGraph",
    "Node",
    "NodeType",
    "Edge",
    "EdgeWeight",
    "FaultDiscovery",
    "FaultReport",
    # MCP (optional)
    "MCPClient",
    "MCPError",
    "create_mcp_tools",
    # AI (optional)
    "AIChatAgent",
]
