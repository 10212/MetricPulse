# Config

MetricPulse 的 YAML 配置文件目录。

## 文件

| 文件 | 说明 |
|---|---|
| metrics.yaml | 语义化指标配置 -- 定义要查询的 Prometheus 指标、标签过滤、告警阈值 |
| topology.yaml | 业务拓扑配置 -- 定义服务节点及有向依赖边 |

## metrics.yaml 结构

每个指标包含：
- id -- 唯一标识，如 gateway_latency_p99
- category -- 指标大类：latency / error_rate / throughput / saturation / custom
- metric_name -- Prometheus 原始指标名
- service -- 关联的拓扑节点 ID
- labels -- Prometheus 标签过滤
- thresholds -- 告警阈值（operator + value + severity）

## topology.yaml 结构

- **Node** -- id（关联 metrics 的 service）、node_type（service/database/queue/cache/external）
- **Edge** -- from_id -> to_id = from 依赖 to，weight（critical/high/medium/low）
