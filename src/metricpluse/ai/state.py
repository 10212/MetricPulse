"""LangGraph Agent 状态定义。

AgentState 作为 LangGraph 图的共享状态，
承载对话消息、监控配置、拓扑图谱、查询结果等上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import MessagesState

from ..monitor.config import MetricConfig
from ..topology.graph import DependencyGraph


class AgentState(MessagesState):
    """运维 AI Agent 的 LangGraph 状态。

    继承 MessagesState，自动包含 messages 字段。
    额外扩展运维专属上下文。
    """

    # ---- 配置上下文（只读，运行时注入） ----
    metric_configs: list[MetricConfig]
    """已加载的指标配置列表。"""

    dependency_graph: DependencyGraph
    """业务拓扑图谱。"""

    prometheus_url: str
    """Prometheus 端点地址。"""

    # ---- 运行时上下文（逐轮累积） ----
    query_results: dict[str, Any]
    """已完成的 Prometheus 查询结果，key = metric_id。"""

    topology_analysis: dict[str, Any]
    """已执行的拓扑分析结果。"""

    agent_report_summary: str
    """最近一次 OpsAgent.run 的摘要。"""

    # ---- 迭代控制 ----
    iteration_count: int
    """当前迭代次数，防止无限循环。"""

    @classmethod
    def create(
        cls,
        metric_configs: list[MetricConfig],
        dependency_graph: DependencyGraph,
        prometheus_url: str,
    ) -> dict[str, Any]:
        """工厂方法：创建初始状态字典。"""
        return {
            "messages": [],
            "metric_configs": metric_configs,
            "dependency_graph": dependency_graph,
            "prometheus_url": prometheus_url,
            "query_results": {},
            "topology_analysis": {},
            "agent_report_summary": "",
            "iteration_count": 0,
        }


# ---------------------------------------------------------------------------
# LangGraph 状态注解（TypedDict 风格，供 graph.py 使用）
# ---------------------------------------------------------------------------

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentStateDict(TypedDict, total=False):
    """AgentState 的 TypedDict 表示，用于 LangGraph StateGraph 类型标注。"""

    messages: Annotated[list, add_messages]
    metric_configs: list[MetricConfig]
    dependency_graph: DependencyGraph
    prometheus_url: str
    query_results: dict[str, Any]
    topology_analysis: dict[str, Any]
    agent_report_summary: str
    iteration_count: int
