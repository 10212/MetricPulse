"""LangGraph 图编排 — 运维 Agent 的推理-行动循环。

图结构:
    START → agent (LLM 推理)
              ├─ 有 tool_calls → tools → agent (循环)
              └─ 无 tool_calls → END

每个节点都是纯函数：接收 state dict，返回 state 更新的 dict。
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from ..monitor.config import MetricConfig
from ..topology.graph import DependencyGraph
from .state import AgentStateDict
from .tools import create_tools


# ---------------------------------------------------------------------------
# 系统提示词
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """你是一个运维 AI Agent，负责分析和诊断分布式系统的运行状态。

你的能力：
1. 查询 Prometheus 指标 —— 使用 query_metric / query_service_metrics
2. 分析业务拓扑 —— 使用 analyze_service_topology / list_services / list_metrics

工作原则：
- 收到告警类问题时，先查询相关指标，再分析拓扑依赖，综合给出诊断结论
- 多步推理：如果发现指标异常，主动检查上下游依赖找出根因
- 回答要简洁专业，直击要点，不要过度解释
- 如果没有发现异常，如实告知当前状态正常
- 当用户问"当前状态如何"时，先 list_services，再逐服务检查 query_service_metrics

当前环境包含以下上下文，你可以在需要时直接使用："""


# ---------------------------------------------------------------------------
# 节点函数
# ---------------------------------------------------------------------------

def _build_system_message(state: AgentStateDict) -> str:
    """从 state 构建注入上下文的系统消息。"""
    configs: list[MetricConfig] = state.get("metric_configs", [])
    graph: DependencyGraph = state.get("dependency_graph", DependencyGraph())

    services = ", ".join(n.name for n in graph.nodes) if graph.node_count > 0 else "(未配置)"
    metrics = ", ".join(c.id for c in configs) if configs else "(未配置)"

    return (
        f"{SYSTEM_PROMPT}\n"
        f"- 拓扑服务 ({graph.node_count}个): {services}\n"
        f"- 监控指标 ({len(configs)}个): {metrics}\n"
    )


def create_agent_node(llm: BaseChatModel):
    """创建 agent 推理节点（闭包注入 LLM）。"""

    async def agent_node(state: AgentStateDict) -> dict[str, Any]:
        messages = state.get("messages", [])
        iteration = state.get("iteration_count", 0)

        # 首轮注入 system message
        if iteration == 0:
            system_msg = SystemMessage(content=_build_system_message(state))
            messages = [system_msg] + list(messages)

        response: AIMessage = await llm.ainvoke(messages)
        return {
            "messages": [response],
            "iteration_count": iteration + 1,
        }

    return agent_node


# ---------------------------------------------------------------------------
# 条件边
# ---------------------------------------------------------------------------

def should_continue(state: AgentStateDict) -> Literal["tools", "__end__"]:
    """决定下一步：继续调用工具 or 结束。"""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last = messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "__end__"


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------

MAX_ITERATIONS = 10


def build_graph(
    llm: BaseChatModel,
    metric_configs: list[MetricConfig],
    graph: DependencyGraph,
    prometheus_url: str,
) -> StateGraph:
    """构建并编译运维 Agent 的 LangGraph 图。

    返回编译后的 StateGraph，可直接 .ainvoke() / .astream()。
    """
    tools = create_tools(metric_configs, graph, prometheus_url)
    llm_with_tools = llm.bind_tools(tools)

    # 构建图
    workflow = StateGraph(AgentStateDict)

    workflow.add_node("agent", create_agent_node(llm_with_tools))
    workflow.add_node("tools", ToolNode(tools))

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", "__end__": END})
    workflow.add_edge("tools", "agent")

    return workflow.compile()
