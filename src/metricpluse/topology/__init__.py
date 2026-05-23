"""Topology 模块 — 业务拓扑图谱引擎。

提供：
- DependencyGraph: 有向依赖图引擎
- FaultDiscovery: 故障传播分析与根因定位
- Node / Edge: 拓扑数据模型
"""

from .discovery import FaultDiscovery, FaultReport
from .graph import DependencyGraph
from .model import Edge, EdgeWeight, Node, NodeType

__all__ = [
    "DependencyGraph",
    "Edge",
    "EdgeWeight",
    "FaultDiscovery",
    "FaultReport",
    "Node",
    "NodeType",
]
