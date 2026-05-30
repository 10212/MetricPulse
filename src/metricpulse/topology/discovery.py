"""FaultDiscovery — 故障发现与根因分析算法。

基于拓扑图引擎，提供：
- 故障传播分析（blast radius）
- 根因定位（root cause localization）
- 多告警节点的联合分析
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .graph import DependencyGraph
from .model import Node


@dataclass
class FaultReport:
    """故障分析报告。"""

    source_node_id: str
    source_node_name: str = ""
    impacted_services: list[str] = field(default_factory=list)
    """受影响的上下游服务列表。"""

    possible_root_causes: list[str] = field(default_factory=list)
    """可能的根因节点（下游依赖链中的异常节点）。"""

    blast_radius: int = 0
    """影响半径：受影响的节点总数。"""

    dependency_chain: list[list[str]] = field(default_factory=list)
    """依赖链（BFS 分层）。"""

    summary: str = ""


class FaultDiscovery:
    """基于拓扑图的故障发现引擎。

    核心算法：
    1. 炸半径分析：给定告警节点，顺上游找到所有受影响的消费者
    2. 根因定位：沿下游依赖链找到最深的异常节点作为候选根因
    3. 多节点联合：当多个节点告警时，求交集找到共同依赖
    """

    def __init__(self, graph: DependencyGraph) -> None:
        self.graph = graph

    def analyze(self, alerting_node_id: str) -> FaultReport:
        """对单个告警节点执行完整分析。"""
        node = self.graph.get_node(alerting_node_id)
        report = FaultReport(
            source_node_id=alerting_node_id,
            source_node_name=node.name if node else alerting_node_id,
        )

        # 1. 上游影响（谁依赖我？→ 爆炸半径）
        all_upstream = self.graph.all_upstream(alerting_node_id)
        report.impacted_services = sorted(all_upstream)
        report.blast_radius = len(all_upstream)

        # 2. 下游依赖链（我依赖谁？→ 根因候选）
        chain = self.graph.downstream_chain(alerting_node_id)
        report.dependency_chain = [[n.name or n.id for n in layer] for layer in chain]

        # 依赖链最深层的所有节点都是候选根因
        if chain and chain[-1]:
            report.possible_root_causes = [n.name or n.id for n in chain[-1]]

        # 3. 按权重分组的影响范围
        radius = self.graph.impact_radius(alerting_node_id)

        report.summary = self._build_summary(report, radius)
        return report

    def joint_analyze(self, alerting_node_ids: list[str]) -> FaultReport:
        """多告警节点联合分析。

        策略：
        - 爆炸半径 = 所有节点上游影响并集
        - 根因候选 = 所有节点下游依赖的交集（共同依赖的组件最可疑）
        """
        if not alerting_node_ids:
            return FaultReport(source_node_id="", summary="No alerting nodes provided.")

        if len(alerting_node_ids) == 1:
            return self.analyze(alerting_node_ids[0])

        # 上游影响并集
        all_impacted: set[str] = set()
        for nid in alerting_node_ids:
            all_impacted |= self.graph.all_upstream(nid)

        # 下游依赖交集
        downstream_sets: list[set[str]] = []
        for nid in alerting_node_ids:
            downstream_sets.append(self.graph.all_downstream(nid) | {nid})
        common_downstream = set.intersection(*downstream_sets) if downstream_sets else set()

        # 找最深的交集节点
        root_causes: list[str] = []
        for nid in sorted(common_downstream):
            node = self.graph.get_node(nid)
            if node:
                # 如果该节点没有进一步的下游交集依赖，视为末端根因
                deeper = self.graph.all_downstream(nid) & common_downstream
                if not deeper:
                    root_causes.append(node.name or node.id)

        report = FaultReport(
            source_node_id=",".join(alerting_node_ids),
            source_node_name=f"{len(alerting_node_ids)} alerting nodes",
            impacted_services=sorted(all_impacted),
            blast_radius=len(all_impacted),
            possible_root_causes=root_causes if root_causes else sorted(common_downstream),
        )

        # 依赖链使用第一个节点的下游链
        if alerting_node_ids:
            chain = self.graph.downstream_chain(alerting_node_ids[0])
            report.dependency_chain = [[n.name or n.id for n in layer] for layer in chain]

        report.summary = self._build_summary(
            report,
            self._joint_impact_radius(alerting_node_ids),
        )
        return report

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _build_summary(self, report: FaultReport, radius: dict[str, list[str]]) -> str:
        lines = [f"故障分析: {report.source_node_name}"]
        lines.append(f"  爆炸半径: {report.blast_radius} 个受影响服务")

        if radius:
            for sev in ("critical", "high", "medium", "low"):
                if sev in radius:
                    lines.append(f"  [{sev}] {', '.join(radius[sev][:5])}")

        if report.possible_root_causes:
            lines.append(f"  候选根因: {', '.join(report.possible_root_causes[:5])}")

        return "\n".join(lines)

    def _joint_impact_radius(self, alerting_ids: list[str]) -> dict[str, list[str]]:
        combined: dict[str, list[str]] = {}
        for nid in alerting_ids:
            radius = self.graph.impact_radius(nid)
            for sev, nodes in radius.items():
                existing = combined.setdefault(sev, [])
                for n in nodes:
                    if n not in existing:
                        existing.append(n)
        return combined
