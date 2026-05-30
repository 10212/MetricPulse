"""MetricPulse 运维 Agent — 命令行入口与示例。

用法：
    python examples/demo.py
    或直接 import metricpulse 使用编程 API
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from metricpulse.config_loader import load_metric_configs, load_topology
from metricpulse.agent import OpsAgent
from metricpulse.topology import FaultDiscovery


def demo_topology():
    print("=" * 60)
    print("拓扑图谱引擎 — 演示")
    print("=" * 60)

    graph = load_topology("config/topology.yaml")
    discovery = FaultDiscovery(graph)

    print(f"\n已构建图谱: {graph}")
    print(f"节点列表: {[n.name for n in graph.nodes]}")

    print("\n--- 场景: postgres-primary 故障 ---")
    report = discovery.analyze("postgres-primary")
    print(report.summary)

    print(f"\n  依赖链 (BFS 向上游):")
    for i, layer in enumerate(report.dependency_chain, 1):
        print(f"    第 {i} 层: {layer}")

    print(f"\n  爆炸半径详情:")
    radius = graph.impact_radius("postgres-primary")
    for sev, services in radius.items():
        print(f"    [{sev}] {services}")

    print("\n--- 场景: kafka-broker 故障 ---")
    report = discovery.analyze("kafka-broker")
    print(report.summary)

    print("\n--- 场景: payment-service + order-service 同时告警 ---")
    joint = discovery.joint_analyze(["payment-service", "order-service"])
    print(joint.summary)
    print(f"  共同依赖 (候选根因): {joint.possible_root_causes}")


def demo_metrics():
    print("\n" + "=" * 60)
    print("语义化 MetricConfig -> PromQL 演示")
    print("=" * 60)

    configs = load_metric_configs("config/metrics.yaml")

    for c in configs:
        print(f"\n  [{c.category.value}] {c.description}")
        print(f"    服务: {c.service}")
        print(f"    PromQL: {c.to_promql()}")
        if c.thresholds:
            for t in c.thresholds:
                print(f"    阈值: [{t.severity.value}] {t.operator} {t.value} — {t.description}")


async def demo_agent():
    print("\n" + "=" * 60)
    print("运维 Agent — 完整巡检演示")
    print("=" * 60)

    prometheus_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:9090"

    configs = load_metric_configs("config/metrics.yaml")
    graph = load_topology("config/topology.yaml")

    agent = OpsAgent(prometheus_url, graph)
    print(f"\n连接 Prometheus: {prometheus_url}")

    try:
        report = await agent.run(configs)
        print(f"\n{report.summary}")
        if report.fault_report:
            print(f"\n{report.fault_report.summary}")
    except Exception as exc:
        print(f"\n[WARN] Prometheus 不可达: {exc}")
        print("拓扑分析可离线运行，请运行 demo_topology() 体验。")


def main():
    if "--topology" in sys.argv or "-t" in sys.argv or len(sys.argv) == 1:
        demo_topology()
        demo_metrics()
        print("\n" + "=" * 60)
        print("如需完整 Agent 巡检: python examples/demo.py http://your-prometheus:9090")
        print("=" * 60)
    else:
        demo_topology()
        demo_metrics()
        asyncio.run(demo_agent())


if __name__ == "__main__":
    main()
