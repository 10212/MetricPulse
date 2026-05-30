# Monitor

语义化监控查询模块。将 Prometheus 指标封装为携带业务语义的配置对象。

## 文件

| 文件 | 职责 |
|---|---|
| config.py | MetricConfig / Threshold / Severity / MetricCategory 数据模型 |
| query.py | QueryBuilder — 根据 category + labels 编译 PromQL |
| client.py | PrometheusClient — HTTP API 客户端，支持 instant/range query、并发批量查询 |

## 设计思路

不手写 PromQL，通过 MetricConfig 声明式描述目标和判定规则：

```
config = MetricConfig(
    id="gateway_latency_p99",
    category=MetricCategory.LATENCY,
    metric_name="http_request_duration_seconds",
    labels={"job": "api-gateway"},
    thresholds=[Threshold(operator="gt", value=0.5, severity=Severity.WARNING)],
)
print(config.to_promql())
```

| category | 默认 PromQL 模板 |
|---|---|
| latency | histogram_quantile(0.99, rate({name}[5m])) |
| error_rate | rate({name}[5m]) > 0 |
| throughput | rate({name}[5m]) |
| saturation | avg({name}) |
| custom | {name} |
