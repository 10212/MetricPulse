"""YAML 配置加载器。

从 config/metrics.yaml 和 config/topology.yaml 构建运行时对象。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from metricpluse.monitor.config import MetricCategory, MetricConfig, Severity, Threshold
from metricpluse.topology import DependencyGraph, Edge, EdgeWeight, Node, NodeType


def load_metric_configs(path: str | Path) -> list[MetricConfig]:
    """从 YAML 加载 MetricConfig 列表。"""
    data = _read_yaml(path)
    configs: list[MetricConfig] = []
    for item in data.get("metrics", []):
        thresholds = [
            Threshold(
                operator=t["operator"],
                value=float(t["value"]),
                severity=Severity(t.get("severity", "warning")),
                description=t.get("description", ""),
            )
            for t in item.get("thresholds", [])
        ]
        configs.append(MetricConfig(
            id=item["id"],
            category=MetricCategory(item["category"]),
            metric_name=item["metric_name"],
            description=item.get("description", ""),
            service=item.get("service", ""),
            labels=item.get("labels", {}),
            thresholds=thresholds,
            extra=item.get("extra", {}),
        ))
    return configs


def load_topology(path: str | Path) -> DependencyGraph:
    """从 YAML 加载 DependencyGraph。"""
    data = _read_yaml(path)
    nodes = [
        Node(
            id=n["id"],
            name=n.get("name", n["id"]),
            node_type=NodeType(n.get("node_type", "service")),
            description=n.get("description", ""),
            service=n.get("service", n["id"]),
        )
        for n in data.get("nodes", [])
    ]
    edges = [
        Edge(
            from_id=e["from_id"],
            to_id=e["to_id"],
            weight=EdgeWeight(e.get("weight", "medium")),
            description=e.get("description", ""),
        )
        for e in data.get("edges", [])
    ]
    return DependencyGraph().build(nodes, edges)


def _read_yaml(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
