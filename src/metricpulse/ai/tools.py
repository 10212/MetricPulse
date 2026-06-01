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
from ..monitor.config import MetricConfig, Severity, Threshold
from ..monitor.sliding_window import evaluate_sustained
from ..topology.discovery import FaultDiscovery
from ..topology.graph import DependencyGraph
from ..mcp.client import MCPClient
from ..mcp.tools import create_mcp_tools


# ---------------------------------------------------------------------------
# 工具工厂 — 每个工具需要运行时 context（configs, graph, url），通过闭包注入而非每次传参，保持 tool 签名简洁。
# ---------------------------------------------------------------------------

def create_tools(
    metric_configs: list[MetricConfig],
    graph: DependencyGraph,
    prometheus_url: str,
    mcp_config: dict | None = None,
) -> list:
    """创建所有运维工具，注入运行时上下文。

    Args:
        metric_configs: 指标配置列表
        graph: 拓扑图
        prometheus_url: Prometheus URL
        mcp_config: MCP 配置（可选）
    """
    config_map: dict[str, MetricConfig] = {c.id: c for c in metric_configs}
    discovery = FaultDiscovery(graph)

    # 初始化 MCP 客户端（如果配置了）
    mcp_clients = {}
    if mcp_config:
        for name, config in mcp_config.get("services", {}).items():
            mcp_clients[name] = MCPClient(
                url=config["url"],
                api_key=config.get("api_key"),
            )

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
            has_sustained = any(t.is_sustained for t in config.thresholds)
            if has_sustained:
                result = await client.range_query_sustained(config, config.max_sustained_window)
            else:
                result = await client.instant_query(config)

        if result.error:
            return f"查询失败 [{config.id}]: {result.error}"

        triggered = await _evaluate_metric(result, config)

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
            return (
                f"未找到服务 '{service_name}' 的指标配置。"
                f"已配置指标的服务: {', '.join(all_services)}"
            )

        async with PrometheusClient(prometheus_url) as client:
            instant_cfgs = [c for c in service_configs if not any(t.is_sustained for t in c.thresholds)]
            sustained_cfgs = [c for c in service_configs if any(t.is_sustained for t in c.thresholds)]

            tasks = []
            if instant_cfgs:
                tasks.append(asyncio.ensure_future(client.query_many(instant_cfgs)))
            if sustained_cfgs:
                tasks.append(asyncio.ensure_future(client.query_many_sustained(sustained_cfgs)))

            gathered = await asyncio.gather(*tasks)
            results: list = []
            for g in gathered:
                results.extend(g)

        lines = [f"=== {service_name} 指标概览 ==="]
        for result in results:
            config = config_map.get(result.config_id)
            if not config:
                continue
            if result.error:
                lines.append(f"  [{config.id}] 查询失败: {result.error}")
                continue

            triggered = await _evaluate_metric(result, config)
            status = f"告警: {', '.join(triggered)}" if triggered else "正常"

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
            "",
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
            thresholds_parts: list[str] = []
            for t in c.thresholds:
                base = f"[{t.severity.value}]{t.operator}{t.value}"
                if t.is_sustained:
                    base += f" 持续({t.window_duration}, N>={t.min_samples})"
                thresholds_parts.append(base)
            thresholds = ", ".join(thresholds_parts) or "无"
            lines.append(
                f"  [{c.category.value}] {c.id}"
                f" | 服务={c.service}"
                f" | {c.description}"
                f" | 阈值: {thresholds}"
            )
        return "\n".join(lines)

    # =====================================================================
    # Tool 6: 调用 MCP 服务
    # =====================================================================
    if mcp_config:
        @tool
        async def call_mcp_service(
            service_name: str,
            tool_name: str,
            arguments: dict,
        ) -> str:
            """调用指定的 MCP 服务。

            Args:
                service_name: 在配置中定义的服务名称
                tool_name: MCP 工具名称
                arguments: 工具参数
            """
            if service_name not in mcp_clients:
                return f"未找到 MCP 服务 '{service_name}'"

            client = mcp_clients[service_name]
            try:
                result = await client.call_tool(tool_name, arguments)
                return json.dumps(result, indent=2, ensure_ascii=False)
            except Exception as e:
                return f"调用 MCP 服务失败: {e}"

    # =====================================================================
    # 工具列表
    # =====================================================================
    tools = [
        query_metric,
        query_service_metrics,
        analyze_service_topology,
        list_services,
        list_metrics,
    ]

    if mcp_config:
        tools.append(call_mcp_service)

    return tools


def _evaluate_metric(result, config: MetricConfig) -> list[str]:
    """评估单个查询结果的阈值（兼容即时 + 持续判定）。

    返回触发阈值的可读描述列表。
    """
    triggered: list[str] = []
    for t in config.thresholds:
        label = f"[{t.severity.value}] {t.description or f'{t.operator}{t.value}'}"
        if t.is_sustained:
            if result.values:
                sr = evaluate_sustained(
                    result.values, t.operator, t.value,
                    t.window_duration, t.min_samples,
                )
                if sr.triggered:
                    triggered.append(f"{label} (窗口{t.window_duration}内违反{sr.window_max_count}次, 需>={sr.window_required})")
        else:
            if result.value is not None and _check_threshold(result.value, t):
                triggered.append(label)
    return triggered


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