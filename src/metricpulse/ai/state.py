"""LangGraph Agent state definition.

AgentState serves as shared state across the LangGraph execution,
carrying conversation messages, monitoring configs, topology graphs,
and loop-prevention metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages

from ..monitor.config import MetricConfig
from ..topology.graph import DependencyGraph


class AgentState(MessagesState):
    """SRE AI Agent LangGraph state.

    Inherits MessagesState (auto-manages messages via add_messages reducer).
    Extended with ops-specific context.
    """

    # ---- configuration context (read-only, injected at runtime) ----
    metric_configs: list[MetricConfig]
    dependency_graph: DependencyGraph
    prometheus_url: str

    # ---- runtime context (accumulated per turn) ----
    query_results: dict[str, Any]
    topology_analysis: dict[str, Any]
    agent_report_summary: str

    # ---- loop prevention ----
    iteration_count: int
    tool_call_history: list[str]
    max_iterations: int

    @classmethod
    def create(
        cls,
        metric_configs: list[MetricConfig],
        dependency_graph: DependencyGraph,
        prometheus_url: str,
        *,
        max_iterations: int = 10,
    ) -> dict[str, Any]:
        """Factory: create initial state dict."""
        return {
            "messages": [],
            "metric_configs": metric_configs,
            "dependency_graph": dependency_graph,
            "prometheus_url": prometheus_url,
            "query_results": {},
            "topology_analysis": {},
            "agent_report_summary": "",
            "iteration_count": 0,
            "tool_call_history": [],
            "max_iterations": max_iterations,
        }


# ---------------------------------------------------------------------------
# TypedDict form for LangGraph StateGraph type annotations
# ---------------------------------------------------------------------------

class AgentStateDict(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    metric_configs: list[MetricConfig]
    dependency_graph: DependencyGraph
    prometheus_url: str
    query_results: dict[str, Any]
    topology_analysis: dict[str, Any]
    agent_report_summary: str
    iteration_count: int
    tool_call_history: list[str]
    max_iterations: int