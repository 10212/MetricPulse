"""Topology 数据模型 — Node / Edge / DependencyGraph。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    SERVICE = "service"
    DATABASE = "database"
    QUEUE = "queue"
    CACHE = "cache"
    EXTERNAL = "external"


class EdgeWeight(str, Enum):
    """边权重，用于故障影响量化。"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Node:
    """拓扑图中的业务节点。

    每个 Node 代表一个可监控的业务组件，通过 service 名与 MetricConfig 关联。
    """

    id: str
    name: str
    node_type: NodeType = NodeType.SERVICE
    service: str = ""           # 关联 MetricConfig.service
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class Edge:
    """有向边：from_id 依赖 to_id。

    例如：Edge("gateway", "payment") 表示 gateway 依赖 payment 服务。
    当 payment 故障时，gateway 会受影响（upstream impact）。
    """

    from_id: str       # 消费方 / 上游
    to_id: str         # 被依赖方 / 下游
    weight: EdgeWeight = EdgeWeight.MEDIUM
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.from_id, self.to_id))
