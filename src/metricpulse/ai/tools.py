"""LangChain Tools — 将 Monitor/Topology 能力封装为 LLM 可调用工具。

每个 Tool 是对底层 Monitor/Topology 模块的语义化封装，
提供清晰的输入/输出签名，便于 LLM 理解和调用。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from langchain_core.tools import tool

from ..monitor.client import PrometheusClient
from ..monitor.config import MetricConfig, Severity
from ..topology.discovery import FaultDiscovery
from ..topology.graph import DependencyGraph


# ---------------------------------------------------------------------------
# 工具工厂 — 每个工具需要运行时 context（configs, graph, url），
# 通过闭包注入而非每次传参，保持 tool 签名简洁。
# ---------------------------------------------------------------------------

def create_tools(
    metric_configs: list[MetricConfig],
    graph: DependencyGraph,
    prometheus_url: str,
) -> list:
    """创建所有运维工具，注入运行时上下文。"""

    config_map: dict[str, MetricConfig] = {c.id: c for c in metric_configs}
    discovery = FaultDiscovery(graph)

    # =====================================================================
    # Tool 1: 查询单个指标
    # =====================================================================
    @tool
    async def query_metric(metric_id: str) -> str:
        """查询指定指标的最新值。

        参数 metric_id 是指标配置的唯一标识，例如 'gateway_latency_p99'。
        返回该指标的 PromQL 查询结果，包含当前值及是否触发告警阈值。
        可多次调用以查询不同指标。
        """
        config = config_map.get(metric_id)
        if config is None:
            available = ", ".join(config_map.keys())
            return f"未找到指标 '{metric_id}'。可用指标: {available}"

        async with PrometheusClient(prometheus_url) as client:
            result = await client.instant_query(config)

        if result.error:
            return f"查询失败 [{config.id}]: {result.error}"

        # 阈值评估
        triggered = []
        for t in config.thresholds:
            if result.value is not None and _check_threshold(result.value, t):
                triggered.append(f"[{t.severity.value}] {t.description or f'{t.operator}{t.value}'}")

        lines = [
            f"指标: {config.description or config.id}",
            f"  服务: {config.service}",
            f"  PromQL: {result.promql}",
            f"  当前值: {result.value}",
        ]
        if triggered:
            lines.append(f"  告警: {', '.join(triggered)}")
        else:
            lines.append("  状态: 正常")

        return "\n".join(lines)

    # =====================================================================
    # Tool 2: 查询某服务的所有指标
    # =====================================================================
    @tool
    async def query_service_metrics(service_name: str) -> str:
        """查询指定服务的所有关联指标。

        参数 service_name 是拓扑中的服务名，例如 'payment-service'。
        返回该服务所有指标的最新值及告警状态。
        """
        service_configs = [c for c in metric_configs if c.service == service_name]
        if not service_configs:
            all_services = sorted({c.service for c in metric_configs if c.service})
            return f"未找到服务 '{service_name}' 的指标配置。已配置指标的服务: {', '.join(all_services)}"

        async with PrometheusClient(prometheus_url) as client:
            results = await client.query_many(service_configs)

        lines = [f"=== {service_name} 指标概览 ==="]
        for result in results:
            config = config_map.get(result.config_id)
            if not config:
                continue
            if result.error:
                lines.append(f"  [{config.id}] 查询失败: {result.error}")
                continue

            status = "正常"
            triggered = []
            if result.value is not None:
                for t in config.thresholds:
                    if _check_threshold(result.value, t):
                        triggered.append(f"[{t.severity.value}]{t.description or t.operator + str(t.value)}")
            if triggered:
                status = f"告警: {', '.join(triggered)}"

            lines.append(
                f"  [{config.category.value}] {config.description}: "
                f"value={result.value:.4f} — {status}"
            )

        return "\n".join(lines)

    # =====================================================================
    # Tool 3: 分析服务拓扑
    # =====================================================================
    @tool
    def analyze_service_topology(service_name: str) -> str:
        """分析某服务在业务拓扑中的依赖关系。

        参数 service_name 是拓扑节点 ID，例如 'postgres-primary'。
        返回该服务的上游消费者（受影响范围）和下游依赖（潜在根因）。
        """
        node = graph.get_node(service_name)
        if node is None:
            all_nodes = sorted([n.id for n in graph.nodes])
            return f"未找到节点 '{service_name}'。拓扑中的节点: {', '.join(all_nodes)}"

        report = discovery.analyze(service_name)

        lines = [
            f"=== {node.name} 拓扑分析 ===",
            f"类型: {node.node_type.value}",
            f"描述: {node.description}",
            f"",
            f"上游消费者 (依赖此服务，爆炸半径 {report.blast_radius}):",
        ]
        if report.impacted_services:
            for svc in report.impacted_services:
                n = graph.get_node(svc)
                edge = graph.get_edge(svc, service_name)
                weight = edge.weight.value if edge else "unknown"
                lines.append(f"  - {n.name if n else svc} [{weight}]")
        else:
            lines.append("  (无上游消费者)")

        lines.append("")
        lines.append("下游依赖 (此服务依赖的基础设施):")
        downstream = graph.downstream_of(service_name)
        if downstream:
            for n in downstream:
                edge = graph.get_edge(service_name, n.id)
                weight = edge.weight.value if edge else "unknown"
                lines.append(f"  - {n.name} [{weight}]")
        else:
            lines.append("  (无下游依赖)")

        if report.possible_root_causes:
            lines.append(f"\n候选根因: {', '.join(report.possible_root_causes)}")

        return "\n".join(lines)

    # =====================================================================
    # Tool 4: 列出所有服务
    # =====================================================================
    @tool
    def list_services() -> str:
        """列出拓扑中所有已注册的服务及其类型。"""
        lines = ["=== 已注册服务 ==="]
        for node in graph.nodes:
            metrics_count = sum(1 for c in metric_configs if c.service == node.id)
            lines.append(
                f"  {node.name} (id={node.id})"
                f" | 类型={node.node_type.value}"
                f" | 指标数={metrics_count}"
                f" | {node.description}"
            )
        return "\n".join(lines)

    # =====================================================================
    # Tool 5: 列出所有指标
    # =====================================================================
    @tool
    def list_metrics() -> str:
        """列出所有已配置的监控指标及其阈值。"""
        lines = ["=== 已配置指标 ==="]
        for c in metric_configs:
            thresholds = ", ".join(
                f"[{t.severity.value}]{t.operator}{t.value}" for t in c.thresholds
            ) or "无"
            lines.append(
                f"  [{c.category.value}] {c.id}"
                f" | 服务={c.service}"
                f" | {c.description}"
                f" | 阈值: {thresholds}"
            )
        return "\n".join(lines)

    return [
        query_metric,
        query_service_metrics,
        analyze_service_topology,
        list_services,
        list_metrics,
    ]


def _check_threshold(value: float, t: Any) -> bool:
    ops = {
        "gt":  lambda v, tv: v >  tv,
        "lt":  lambda v, tv: v <  tv,
        "gte": lambda v, tv: v >= tv,
        "lte": lambda v, tv: v <= tv,
        "eq":  lambda v, tv: v == tv,
    }
    fn = ops.get(t.operator)
    return fn(value, t.value) if fn else False
