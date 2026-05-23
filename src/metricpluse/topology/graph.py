"""DependencyGraph — 基于 networkx 的有向依赖图引擎。

边方向：from -> to 表示 from 依赖 to。
- predecessors(X): 依赖 X 的节点（X 故障时这些受影响）
- successors(X):   X 依赖的节点（X 的潜在故障根因）
"""

from __future__ import annotations

from typing import Iterator

import networkx as nx

from .model import Edge, EdgeWeight, Node


_WEIGHT_MAP: dict[EdgeWeight, int] = {
    EdgeWeight.CRITICAL: 4,
    EdgeWeight.HIGH: 3,
    EdgeWeight.MEDIUM: 2,
    EdgeWeight.LOW: 1,
}


class DependencyGraph:
    """业务依赖拓扑图。

    使用 networkx.DiGraph 作为底层存储，边方向 = 依赖方向。
    """

    def __init__(self) -> None:
        self._graph = nx.DiGraph()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> None:
        self._graph.add_node(node.id, node=node)

    def add_edge(self, edge: Edge) -> None:
        self._graph.add_edge(
            edge.from_id, edge.to_id,
            edge=edge,
            weight=_WEIGHT_MAP.get(edge.weight, 2),
        )

    def build(self, nodes: list[Node], edges: list[Edge]) -> "DependencyGraph":
        """批量构建拓扑。"""
        for node in nodes:
            self.add_node(node)
        for edge in edges:
            # 确保两个端点存在
            if edge.from_id not in self._graph:
                self._graph.add_node(edge.from_id, node=None)
            if edge.to_id not in self._graph:
                self._graph.add_node(edge.to_id, node=None)
            self.add_edge(edge)
        return self

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @property
    def nodes(self) -> list[Node]:
        return [self.get_node(n) for n in self._graph.nodes if self.get_node(n) is not None]

    def get_node(self, node_id: str) -> Node | None:
        data = self._graph.nodes.get(node_id)
        return data["node"] if data else None

    def get_edge(self, from_id: str, to_id: str) -> Edge | None:
        data = self._graph.get_edge_data(from_id, to_id)
        return data["edge"] if data else None

    def has_node(self, node_id: str) -> bool:
        return self._graph.has_node(node_id)

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    # ------------------------------------------------------------------
    # 遍历 — 核心拓扑分析原语
    # ------------------------------------------------------------------

    def upstream_of(self, node_id: str) -> list[Node]:
        """返回依赖 node_id 的所有节点（node_id 故障时的爆炸半径）。"""
        result: list[Node] = []
        for pred in self._graph.predecessors(node_id):
            node = self.get_node(pred)
            if node:
                result.append(node)
        return result

    def downstream_of(self, node_id: str) -> list[Node]:
        """返回 node_id 所依赖的所有节点（潜在故障根因）。"""
        result: list[Node] = []
        for succ in self._graph.successors(node_id):
            node = self.get_node(succ)
            if node:
                result.append(node)
        return result

    def upstream_chain(self, node_id: str, max_depth: int = 10) -> list[list[Node]]:
        """BFS 查找上游影响链，按层返回。"""
        return self._bfs_layers(node_id, reverse=True, max_depth=max_depth)

    def downstream_chain(self, node_id: str, max_depth: int = 10) -> list[list[Node]]:
        """BFS 查找下游依赖链，按层返回。"""
        return self._bfs_layers(node_id, reverse=False, max_depth=max_depth)

    def all_upstream(self, node_id: str) -> set[str]:
        """返回所有上游节点 ID（包括间接依赖方）。"""
        return set(nx.ancestors(self._graph, node_id))

    def all_downstream(self, node_id: str) -> set[str]:
        """返回所有下游节点 ID（包括间接被依赖方）。"""
        return set(nx.descendants(self._graph, node_id))

    # ------------------------------------------------------------------
    # 故障影响分析
    # ------------------------------------------------------------------

    def impact_radius(self, node_id: str) -> dict[str, list[str]]:
        """给定故障节点，计算按严重度分组的受影响节点。

        返回：{'critical': [...], 'high': [...], 'medium': [...], 'low': [...]}
        """
        buckets: dict[str, list[str]] = {"critical": [], "high": [], "medium": [], "low": []}
        ancestors = self.all_upstream(node_id)

        for anc_id in ancestors:
            edge_data = self._graph.get_edge_data(anc_id, node_id)
            # 检查直接边权重；间接依赖默认 medium
            if edge_data:
                w = edge_data["edge"].weight.value
            else:
                # BFS 找到最近路径上的最大权重
                w = self._max_edge_weight_on_path(anc_id, node_id) or "medium"
            buckets.setdefault(w, []).append(anc_id)

        # 去掉空桶
        return {k: v for k, v in buckets.items() if v}

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _bfs_layers(self, start: str, reverse: bool, max_depth: int) -> list[list[Node]]:
        layers: list[list[Node]] = []
        visited: set[str] = {start}
        frontier: set[str] = {start}

        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                neighbors = self._graph.predecessors(nid) if reverse else self._graph.successors(nid)
                for neighbor in neighbors:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            if not next_frontier:
                break
            layer_nodes: list[Node] = []
            for nid in sorted(next_frontier):
                node = self.get_node(nid)
                if node:
                    layer_nodes.append(node)
            if layer_nodes:
                layers.append(layer_nodes)
            frontier = next_frontier

        return layers

    def _max_edge_weight_on_path(self, from_id: str, to_id: str) -> str | None:
        try:
            path = nx.shortest_path(self._graph, from_id, to_id)
        except nx.NetworkXNoPath:
            return None
        max_w = 0
        for u, v in zip(path, path[1:]):
            edge = self.get_edge(u, v)
            if edge:
                w = _WEIGHT_MAP.get(edge.weight, 2)
                if w > max_w:
                    max_w = w
        return {4: "critical", 3: "high", 2: "medium", 1: "low"}.get(max_w)

    def __repr__(self) -> str:
        return f"DependencyGraph(nodes={self.node_count}, edges={self.edge_count})"
