"""AI Agent 演示 — 基于 LangGraph 的运维对话 Agent。

前置条件:
    pip install -e ".[ai]"
    复制 .env.example 为 .env 并填入 OPENAI_API_KEY

用法:
    python examples/demo_ai.py
    python examples/demo_ai.py --offline
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ---- 自动加载 .env ----
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

from metricpluse.config_loader import load_metric_configs, load_topology


async def demo_ai_agent(offline: bool = False):
    """演示 AI Agent 对话流程。"""

    # ---- 加载配置 ----
    configs = load_metric_configs("config/metrics.yaml")
    graph = load_topology("config/topology.yaml")

    print("=" * 60)
    print("MetricPluse AI Agent — LangGraph 运维对话")
    print("=" * 60)
    print(f"  指标: {len(configs)} 个")
    print(f"  拓扑: {graph.node_count} 节点, {graph.edge_count} 边")

    # ---- 初始化 LLM ----
    from langchain_openai import ChatOpenAI

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("\n[ERROR] 未找到 OPENAI_API_KEY")
        print("  请复制 .env.example 为 .env 并填入你的 API Key")
        return

    api_base = os.getenv("OPENAI_API_BASE", "").strip()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    print(f"  API: {api_base if api_base else '(默认 OpenAI)'}")
    print(f"  Model: {model}")

    llm_kwargs = dict(model=model, temperature=0, api_key=api_key)
    if api_base:
        llm_kwargs["base_url"] = api_base

    llm = ChatOpenAI(**llm_kwargs)

    # ---- 创建 Agent ----
    from metricpluse.ai import AIChatAgent

    prometheus_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    print(f"  Prometheus: {prometheus_url}")

    agent = AIChatAgent(
        llm=llm,
        metric_configs=configs,
        graph=graph,
        prometheus_url=prometheus_url,
    )

    # ---- 交互演示 ----
    questions = [
        "请列出当前系统中所有注册的服务和指标。",
        "支付服务 (payment-service) 的当前状态如何？请查询它的所有指标。",
        "分析 postgres-primary 在拓扑中的依赖关系，它的上游消费者有哪些？",
        "如果 postgres-primary 故障，爆炸半径是多少？对哪些 critical 级别的服务有影响？",
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n{'─' * 50}")
        print(f"[Q{i}] {question}")
        print(f"{'─' * 50}")

        if offline:
            _offline_answer(question, configs, graph, prometheus_url)
            continue

        print()
        async for chunk in agent.stream(question):
            print(chunk, end="", flush=True)
        print()


def _offline_answer(question, configs, graph, prometheus_url):
    """离线模式用工具直接回答，不连 Prometheus / LLM。"""
    print("  (离线模式: 不连接 Prometheus / LLM)")
    from metricpluse.topology import FaultDiscovery
    from metricpluse.ai.tools import create_tools

    discovery = FaultDiscovery(graph)
    tools = create_tools(configs, graph, prometheus_url)

    if "postgres" in question.lower() or "拓扑" in question or "依赖" in question:
        report = discovery.analyze("postgres-primary")
        print(f"\n  {report.summary}")
    elif "支付" in question and "状态" in question:
        svc_tool = next(t for t in tools if t.name == "list_services")
        print(f"\n{svc_tool.invoke({})}")
    else:
        for tool in tools:
            if tool.name in ("list_services", "list_metrics"):
                print(f"\n{tool.invoke({})}")


def main():
    offline = "--offline" in sys.argv
    asyncio.run(demo_ai_agent(offline=offline))


if __name__ == "__main__":
    main()
