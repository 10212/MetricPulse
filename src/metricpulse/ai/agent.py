"""AIChatAgent — AI-powered ops dialogue entry point.

Multi-round conversation agent based on LangGraph, integrating
Prometheus monitoring and dependency topology analysis.
Supports streaming output and MCP service calling.

Loop prevention (built into graph.py):
    1. Hard cap:  iteration_count >= max_iterations -> END
    2. Loop detection: same tool+args >= 3 times in 5 calls -> END
    3. Near-limit warning: system message warns agent at 3 remaining
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from ..monitor.config import MetricConfig
from ..topology.graph import DependencyGraph
from .graph import build_graph


class AIChatAgent:
    """Ops AI dialogue agent.

    Usage:
        from langchain_openai import ChatOpenAI
        from metricpulse.ai import AIChatAgent

        agent = AIChatAgent(
            llm=ChatOpenAI(model="gpt-4o", base_url=..., api_key=...),
            metric_configs=configs,
            graph=graph,
            prometheus_url="http://localhost:9090",
            mcp_config=mcp_config,   # optional
            max_iterations=10,        # optional, default 10
        )
        response = await agent.chat("How is the payment service?")
    """

    def __init__(
        self,
        llm: BaseChatModel,
        metric_configs: list[MetricConfig],
        graph: DependencyGraph,
        prometheus_url: str,
        mcp_config: dict | None = None,
        *,
        max_iterations: int = 10,
    ) -> None:
        self.llm = llm
        self.metric_configs = metric_configs
        self.graph = graph
        self.prometheus_url = prometheus_url
        self.mcp_config = mcp_config
        self.max_iterations = max_iterations

        self._langgraph = build_graph(
            llm=llm,
            metric_configs=metric_configs,
            graph=graph,
            prometheus_url=prometheus_url,
            mcp_config=mcp_config,
            max_iterations=max_iterations,
        )
        self._thread_state: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def chat(self, message: str, *, reset: bool = False) -> str:
        """Send a message and get the full reply."""
        if reset or self._thread_state is None:
            self.reset()

        self._thread_state["messages"].append(HumanMessage(content=message))

        result = await self._langgraph.ainvoke(
            self._thread_state,
            config={"recursion_limit": self.max_iterations * 3},
        )

        self._thread_state = result
        last_msg = result["messages"][-1]
        return last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    async def stream(self, message: str, *, reset: bool = False) -> AsyncIterator[str]:
        """Send a message and yield tokens as they arrive."""
        if reset or self._thread_state is None:
            self.reset()

        self._thread_state["messages"].append(HumanMessage(content=message))

        final_state = self._thread_state
        async for event in self._langgraph.astream_events(
            self._thread_state,
            version="v2",
            config={"recursion_limit": self.max_iterations * 3},
        ):
            kind = event.get("event", "")
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield content
            elif kind == "on_tool_start":
                name = event.get("name", "unknown")
                input_str = str(event["data"].get("input", ""))[:100]
                yield f"\n\n> [tool] {name}({input_str})\n\n"
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                final_state = event["data"].get("output", final_state)

        self._thread_state = final_state

    def reset(self) -> None:
        """Reset conversation history."""
        self._thread_state = {
            "messages": [],
            "metric_configs": self.metric_configs,
            "dependency_graph": self.graph,
            "prometheus_url": self.prometheus_url,
            "mcp_config": self.mcp_config,
            "query_results": {},
            "topology_analysis": {},
            "agent_report_summary": "",
            "iteration_count": 0,
            "tool_call_history": [],
            "max_iterations": self.max_iterations,
        }

    @property
    def history(self) -> list:
        """Return current conversation history."""
        if self._thread_state:
            return self._thread_state.get("messages", [])
        return []