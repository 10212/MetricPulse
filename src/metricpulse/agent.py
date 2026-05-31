"""OpsAgent — 运维 Agent 编排层。

整合 Monitor（监控查询）与 Topology（拓扑分析）：
1. 根据 MetricConfig 列表查询 Prometheus
2. 评估阈值（支持即时判定 + 滑动窗口持续判定），识别异常指标
3. 对异常指标关联的服务，通过拓扑图执行故障传播分析
4. 生成结构化分析报告
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from .monitor.client import PrometheusClient, QueryResult
from .monitor.config import MetricConfig, Severity, Threshold
from .monitor.sliding_window import evaluate_sustained
from .topology import DependencyGraph, FaultDiscovery, FaultReport


@dataclass
class MetricAlert:
    """单指标告警。"""

    config: MetricConfig
    result: QueryResult
    triggered: list[Threshold] = field(default_factory=list)
    """被触发的阈值列表。"""

    @property
    def max_severity(self) -> Severity:
        if not self.triggered:
            return Severity.INFO
        order = {Severity.CRITICAL: 3, Severity.WARNING: 2, Severity.INFO: 1}
        return max(self.triggered, key=lambda t: order.get(t.severity, 0)).severity


@dataclass
class AgentReport:
    """运维 Agent 的完整分析报告。"""

    total_metrics: int = 0
    healthy_count: int = 0
    alerts: list[MetricAlert] = field(default_factory=list)
    fault_report: FaultReport | None = None
    """当存在告警时，基于拓扑的故障分析结果。"""

    summary: str = ""

    @property
    def is_healthy(self) -> bool:
        return len(self.alerts) == 0


class OpsAgent:
    """运维 Agent 主入口。

    用法:
        agent = OpsAgent(
            prometheus_url="http://localhost:9090",
            graph=my_dependency_graph,
        )
        report = await agent.run(metric_configs)
    """

    def __init__(
        self,
        prometheus_url: str,
        graph: DependencyGraph | None = None,
        *,
        prometheus_kwargs: dict | None = None,
    ) -> None:
        self.prometheus_url = prometheus_url
        self.graph = graph or DependencyGraph()
        self.prometheus_kwargs = prometheus_kwargs or {}
        self._discovery = FaultDiscovery(self.graph)

    # ------------------------------------------------------------------
    # 主运行入口
    # ------------------------------------------------------------------

    async def run(self, configs: list[MetricConfig]) -> AgentReport:
        """完整巡检流程：查询 → 评估 → 拓扑分析 → 报告。"""
        # 1. 按阈值类型分流查询
        results = await self._query_all(configs)

        # 2. 评估阈值
        alerts = self._evaluate(configs, results)

        # 3. 拓扑故障分析
        fault_report = None
        if alerts and self.graph.node_count > 0:
            fault_report = self._topology_analysis(alerts)

        # 4. 生成报告
        report = AgentReport(
            total_metrics=len(configs),
            healthy_count=len(configs) - len(alerts),
            alerts=alerts,
            fault_report=fault_report,
        )
        report.summary = self._build_summary(report)
        return report

    async def run_once(self, config: MetricConfig) -> QueryResult:
        """快速单指标查询，不经过阈值评估。"""
        async with PrometheusClient(self.prometheus_url, **self.prometheus_kwargs) as client:
            return await client.instant_query(config)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _query_all(self, configs: list[MetricConfig]) -> list[QueryResult]:
        """分流查询：即时阈值走 instant query，持续阈值走 range query。"""
        instant_cfgs: list[MetricConfig] = []
        sustained_cfgs: list[MetricConfig] = []

        for c in configs:
            if any(t.is_sustained for t in c.thresholds):
                sustained_cfgs.append(c)
            else:
                instant_cfgs.append(c)

        async with PrometheusClient(self.prometheus_url, **self.prometheus_kwargs) as client:
            tasks: list[asyncio.Task] = []
            if instant_cfgs:
                tasks.append(asyncio.ensure_future(client.query_many(instant_cfgs)))
            if sustained_cfgs:
                tasks.append(asyncio.ensure_future(client.query_many_sustained(sustained_cfgs)))

            gathered = await asyncio.gather(*tasks)

        # 合并结果
        results: list[QueryResult] = []
        for group in gathered:
            results.extend(group)
        return results

    def _evaluate(
        self,
        configs: list[MetricConfig],
        results: list[QueryResult],
    ) -> list[MetricAlert]:
        """评估每个结果是否触发阈值（兼容即时与持续判定）。"""
        alerts: list[MetricAlert] = []
        config_map = {c.id: c for c in configs}

        for result in results:
            config = config_map.get(result.config_id)
            if config is None or result.error:
                continue

            triggered: list[Threshold] = []
            for t in config.thresholds:
                if t.is_sustained:
                    # 持续判定：滑动窗口评估
                    if not result.values:
                        continue
                    sustained = evaluate_sustained(
                        result.values, t.operator, t.value,
                        t.window_duration, t.min_samples,
                    )
                    if sustained.triggered:
                        triggered.append(t)
                else:
                    # 即时判定
                    if result.value is not None and _check_threshold(result.value, t):
                        triggered.append(t)

            if triggered:
                alerts.append(MetricAlert(config=config, result=result, triggered=triggered))

        # 按严重度排序
        sev_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
        alerts.sort(key=lambda a: sev_order.get(a.max_severity, 99))
        return alerts

    def _topology_analysis(self, alerts: list[MetricAlert]) -> FaultReport | None:
        """基于告警指标关联的服务做拓扑分析。"""
        service_ids: list[str] = []
        for alert in alerts:
            svc = alert.config.service
            if svc and self.graph.has_node(svc):
                service_ids.append(svc)

        if not service_ids:
            return None

        if len(service_ids) == 1:
            return self._discovery.analyze(service_ids[0])
        return self._discovery.joint_analyze(service_ids)

    def _build_summary(self, report: AgentReport) -> str:
        parts = [
            "=== 运维巡检报告 ===",
            f"指标总数: {report.total_metrics}",
            f"正常: {report.healthy_count}",
            f"异常: {len(report.alerts)}",
        ]
        if report.alerts:
            parts.append("")
            parts.append("--- 异常指标 ---")
            for a in report.alerts[:10]:
                parts.append(
                    f"  [{a.max_severity.value}] {a.config.description or a.config.id}"
                    f" = {a.result.value}  (阈值: {', '.join(t.description or f'{t.operator}{t.value}' for t in a.triggered)})"
                )
        if report.fault_report:
            parts.append("")
            parts.append(report.fault_report.summary)

        return "\n".join(parts)


def _check_threshold(value: float, t: Threshold) -> bool:
    ops = {
        "gt":  lambda v, tv: v >  tv,
        "lt":  lambda v, tv: v <  tv,
        "gte": lambda v, tv: v >= tv,
        "lte": lambda v, tv: v <= tv,
        "eq":  lambda v, tv: v == tv,
    }
    fn = ops.get(t.operator)
    if fn is None:
        return False
    return fn(value, t.value)