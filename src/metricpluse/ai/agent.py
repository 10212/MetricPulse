"""AIChatAgent — 运维 AI 对话入口。

基于 LangGraph 的多轮对话 Agent，集成 Prometheus 监控查询
与业务拓扑分析能力，支持流式输出。
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from ..monitor.config import MetricConfig
from ..topology.graph import DependencyGraph
from .graph import build_graph
from .state import AgentStateDict


class AIChatAgent:
    """运维 AI 对话 Agent。

    用法:
        from langchain_openai import ChatOpenAI
        from metricpluse.ai import AIChatAgent

        agent = AIChatAgent(
            llm=ChatOpenAI(model="gpt-4o"),
            metric_configs=configs,
            graph=topology_graph,
            prometheus_url="http://localhost:9090",
        )
        response = await agent.chat("支付服务状态如何？")
        print(response)

        # 流式输出
        async for chunk in agent.stream("全面巡检"):
            print(chunk, end="", flush=True)
    """

    def __init__(
        self,
        llm: BaseChatModel,
        metric_configs: list[MetricConfig],
        graph: DependencyGraph,
        prometheus_url: str,
        *,
        max_iterations: int = 10,
    ) -> None:
        self.llm = llm
        self.metric_configs = metric_configs
        self.graph = graph
        self.prometheus_url = prometheus_url
        self.max_iterations = max_iterations

        self._langgraph = build_graph(
            llm=llm,
            metric_configs=metric_configs,
            graph=graph,
            prometheus_url=prometheus_url,
        )
        self._thread_state: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def chat(self, message: str, *, reset: bool = False) -> str:
        """发送消息并获取完整回复。

        Args:
            message: 用户消息
            reset: 是否重置对话历史
        """
        if reset or self._thread_state is None:
            self.reset()

        self._thread_state["messages"].append(HumanMessage(content=message))

        result = await self._langgraph.ainvoke(
            self._thread_state,
            config={"recursion_limit": self.max_iterations * 2},
        )

        self._thread_state = result
        last_msg = result["messages"][-1]
        return last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    async def stream(self, message: str, *, reset: bool = False) -> AsyncIterator[str]:
        """发送消息并以流式方式逐 token 返回回复。

        Args:
            message: 用户消息
            reset: 是否重置对话历史
        """
        if reset or self._thread_state is None:
            self.reset()

        self._thread_state["messages"].append(HumanMessage(content=message))

        final_state = self._thread_state
        async for event in self._langgraph.astream_events(
            self._thread_state,
            version="v2",
            config={"recursion_limit": self.max_iterations * 2},
        ):
            kind = event.get("event", "")
            # 流式输出 LLM token
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    yield content
            # 工具调用开始
            elif kind == "on_tool_start":
                name = event.get("name", "unknown")
                input_str = str(event["data"].get("input", ""))[:100]
                yield f"\n\n> 🔧 调用工具: `{name}({input_str})`\n\n"
            # 图执行结束时保存状态
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                final_state = event["data"].get("output", final_state)

        self._thread_state = final_state

    def reset(self) -> None:
        """重置对话历史。"""
        self._thread_state = {
            "messages": [],
            "metric_configs": self.metric_configs,
            "dependency_graph": self.graph,
            "prometheus_url": self.prometheus_url,
            "query_results": {},
            "topology_analysis": {},
            "agent_report_summary": "",
            "iteration_count": 0,
        }

    @property
    def history(self) -> list:
        """返回当前对话历史。"""
        if self._thread_state:
            return self._thread_state.get("messages", [])
        return []
