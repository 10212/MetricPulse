# Topology

业务拓扑图谱引擎。基于 networkx 的有向依赖图。

## 文件

| 文件 | 职责 |
|---|---|
| model.py | Node / Edge / NodeType / EdgeWeight 数据模型 |
| graph.py | DependencyGraph — networkx.DiGraph 封装，上下游遍历、BFS 分层 |
| discovery.py | FaultDiscovery — 故障传播分析、根因定位、多节点联合分析 |

## 边方向约定

from -> to 表示 from 依赖 to

- **Predecessors（上游）** = 依赖我的人 — 我故障时他们受影响（爆炸半径）
- **Successors（下游）** = 我依赖的人 — 我的候选根因

## 核心算法

```python
discovery = FaultDiscovery(graph)

# 单节点分析 — 爆炸半径 + 根因候选
report = discovery.analyze("postgres-primary")
# impacted_services: [api-gateway, order-service, payment-service, ...]
# possible_root_causes: 下游最深层节点

# 多节点联合分析 — 下游交集 = 最可疑共同根因
joint = discovery.joint_analyze(["order-service", "payment-service"])
# possible_root_causes: [postgres-primary]
```
