"""LangGraph agent graph — reasoning-action loop with loop prevention.

Graph structure:
    START -> agent (LLM reasoning)
              |-- has tool_calls -> tools -> agent (loop)
              +-- no tool_calls or loop detected -> END

Loop prevention (three layers):
    1. Hard iteration cap:       iteration_count >= max_iterations -> END
    2. Repeated call detection:   same tool+args >= 3 times in last 5 -> END
    3. Agent awareness:           system prompt warns about near-limit
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from ..monitor.config import MetricConfig
from ..topology.graph import DependencyGraph
from .state import AgentStateDict
from .tools import create_tools


# ---------------------------------------------------------------------------
# loop detection constants
# ---------------------------------------------------------------------------

LOOP_WINDOW = 5       # look back this many recent tool calls
LOOP_THRESHOLD = 3     # same tool+args appearing this many times = loop


# ---------------------------------------------------------------------------
# system prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an SRE AI Agent responsible for diagnosing distributed system health.

Your capabilities:
1. Query Prometheus metrics — use query_metric / query_service_metrics
2. Analyze service topology — use analyze_service_topology / list_services / list_metrics
3. Call MCP services — use call_mcp_service if available

Guidelines:
- Be concise. After 3–4 tool calls you should have enough data to form a conclusion.
- For "current status" queries, call list_services then query_service_metrics once per affected service.
- **IMPORTANT**: You have a limited number of interactions. Do NOT call the same tool with the same
  arguments repeatedly. If you find yourself repeating, summarize what you know and stop.
- If you detect an anomaly, mention the metric, its current value, the violated threshold,
  and the impacted services from topology analysis."""


# ---------------------------------------------------------------------------
# system message builder
# ---------------------------------------------------------------------------

def _build_system_message(state: AgentStateDict) -> str:
    configs = state.get("metric_configs", [])
    dep_graph = state.get("dependency_graph", DependencyGraph())
    mcp_cfg = state.get("mcp_config", {})

    svcs = ", ".join(n.name for n in dep_graph.nodes) if dep_graph.node_count > 0 else "(none)"
    mets = ", ".join(c.id for c in configs) if configs else "(none)"

    mcp_info = ""
    if mcp_cfg:
        names = ", ".join(mcp_cfg.get("services", {}).keys())
        mcp_info = f"\n- MCP services: {names}"

    return (
        f"{SYSTEM_PROMPT}\n"
        f"- Topology ({dep_graph.node_count}): {svcs}\n"
        f"- Metrics ({len(configs)}): {mets}"
        f"{mcp_info}\n"
    )


# ---------------------------------------------------------------------------
# loop detection
# ---------------------------------------------------------------------------

def _detect_loop(history: list[str]) -> bool:
    """Return True if any tool+args signature appears >= LOOP_THRESHOLD times
    within the last LOOP_WINDOW calls."""
    if len(history) < LOOP_THRESHOLD:
        return False
    recent = history[-LOOP_WINDOW:]
    counts = Counter(recent)
    return any(c >= LOOP_THRESHOLD for c in counts.values())


def _tool_call_signature(tool_call) -> str:
    """Create a stable signature from a tool call: 'tool_name::args_json'."""
    try:
        args_str = str(sorted(tool_call.get("args", {}).items()))
    except Exception:
        args_str = str(tool_call)
    return f"{tool_call.get('name', '?')}::{args_str}"


# ---------------------------------------------------------------------------
# agent node
# ---------------------------------------------------------------------------

def create_agent_node(llm: BaseChatModel, max_iterations: int = 10):
    """Create the LLM reasoning node (closure over model and config)."""

    async def agent_node(state: AgentStateDict) -> dict[str, Any]:
        messages = state.get("messages", [])
        iteration = state.get("iteration_count", 0)
        max_iter = state.get("max_iterations", max_iterations)

        # Layer 1: hard cap — don't invoke LLM if already at limit
        if iteration >= max_iter:
            return {
                "messages": [
                    AIMessage(content=(
                        f"[Reached the maximum of {max_iter} iterations. "
                        "Please review the information gathered above and draw conclusions.]"
                    ))
                ],
                "iteration_count": iteration + 1,
            }

        # Build system message on first iteration
        if iteration == 0:
            sys_msg = SystemMessage(content=_build_system_message(state))
            messages = [sys_msg] + list(messages)

        # Warn the agent if approaching the limit
        remaining = max_iter - iteration
        if remaining <= 3:
            warn = SystemMessage(content=(
                f"[System note] You have {remaining} interactions remaining. "
                "Please prioritize drawing a conclusion within the next message."
            ))
            messages = list(messages) + [warn]

        resp: AIMessage = await llm.ainvoke(messages)

        # Track tool call history for loop detection
        history = list(state.get("tool_call_history", []))
        if resp.tool_calls:
            for tc in resp.tool_calls:
                history.append(_tool_call_signature(tc))

        return {
            "messages": [resp],
            "iteration_count": iteration + 1,
            "tool_call_history": history,
        }

    return agent_node


# ---------------------------------------------------------------------------
# conditional edge
# ---------------------------------------------------------------------------

def should_continue(state: AgentStateDict) -> Literal["tools", "__end__"]:
    """Decide next step: call tools, or end (natural stop / loop / cap)."""
    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last = messages[-1]

    # Natural stop: agent produced a reply without tool calls
    if not isinstance(last, AIMessage) or not last.tool_calls:
        return "__end__"

    # Layer 1: hard iteration cap
    iteration = state.get("iteration_count", 0)
    max_iter = state.get("max_iterations", 10)
    if iteration >= max_iter:
        return "__end__"

    # Layer 2: repeated call loop detection
    history = state.get("tool_call_history", [])
    if _detect_loop(history):
        return "__end__"

    return "tools"


# ---------------------------------------------------------------------------
# graph builder
# ---------------------------------------------------------------------------

def build_graph(
    llm: BaseChatModel,
    metric_configs: list[MetricConfig],
    graph: DependencyGraph,
    prometheus_url: str,
    mcp_config: dict | None = None,
    *,
    max_iterations: int = 10,
):
    """Build and compile the SRE Agent LangGraph.

    Args:
        llm:             The language model to use
        metric_configs:   Metric configurations
        graph:            Dependency topology graph
        prometheus_url:   Prometheus endpoint
        mcp_config:       Optional MCP service configuration
        max_iterations:   Max agent→tools→agent cycles (default 10)

    Returns:
        Compiled StateGraph ready for .ainvoke() / .astream()
    """
    tools = create_tools(
        metric_configs=metric_configs,
        graph=graph,
        prometheus_url=prometheus_url,
        mcp_config=mcp_config,
    )
    llm_with_tools = llm.bind_tools(tools)

    workflow = StateGraph(AgentStateDict)

    workflow.add_node("agent", create_agent_node(llm_with_tools, max_iterations))
    workflow.add_node("tools", ToolNode(tools))

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent", should_continue,
        {"tools": "tools", "__end__": END},
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile()