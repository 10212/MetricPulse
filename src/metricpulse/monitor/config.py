"""MetricConfig — 语义化监控配置模型。

MetricConfig 是 Monitor 模块的核心抽象，将 Prometheus 指标查询
包装为携带业务语义的可扩展配置对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MetricCategory(str, Enum):
    """指标大类，驱动默认的 PromQL 模板与告警逻辑。"""

    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    SATURATION = "saturation"
    CUSTOM = "custom"


class Severity(str, Enum):
    """告警严重级别。"""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Threshold:
    """阈值判定规则。

    支持两种模式：
    - 即时判定：window_duration 为空，单次采样值越过阈值即触发。
    - 持续判定：window_duration 非空，在滑动窗口内累积 min_samples
      次违反才触发。
    """

    operator: str           # "gt" | "lt" | "gte" | "lte" | "eq"
    value: float
    severity: Severity = Severity.WARNING
    description: str = ""

    # -- 持续判定字段（可选） --
    window_duration: str = ""
    """滑动窗口时长，如 '5m'、'30s'、'1h'。为空则即时判定。"""

    min_samples: int = 0
    """窗口内最少违反次数。0 表示任何一次即触发（等同于即时判定）。"""

    @property
    def is_sustained(self) -> bool:
        return bool(self.window_duration) and self.min_samples > 0


@dataclass
class MetricConfig:
    """语义化指标配置。

    每一个 MetricConfig 实例描述"我要查什么、怎么判定、它意味着什么"，
    不直接写死 PromQL，而是由 QueryBuilder 根据 category + metric_name + labels 生成。
    """

    # ---- 标识 ----
    id: str
    """配置唯一标识，如 'payment_svc_latency_p99'。"""

    # ---- 语义 ----
    category: MetricCategory
    """指标大类，决定默认 PromQL 模板。"""

    metric_name: str
    """Prometheus 指标名，如 'http_request_duration_seconds'。"""

    description: str = ""
    """人类可读的业务含义，如 '支付服务 P99 延迟'。"""

    service: str = ""
    """关联的业务服务名，用于与 Topology 模块联动。"""

    # ---- 查询参数 ----
    labels: dict[str, str] = field(default_factory=dict)
    """Prometheus 标签过滤器，如 {'job': 'payment', 'path': '/api/checkout'}。"""

    # ---- 聚合 ----
    aggregation: str = ""
    """PromQL 聚合函数，如 'histogram_quantile(0.99, rate(...))'。
    留空则使用 category 的默认聚合。"""

    # ---- 阈值 ----
    thresholds: list[Threshold] = field(default_factory=list)
    """告警阈值列表。"""

    # ---- 扩展 ----
    extra: dict[str, Any] = field(default_factory=dict)
    """扩展字段，用于自定义 PromQL 片段、附加元数据等。"""

    @property
    def max_sustained_window(self) -> str:
        """该配置所有持续阈值中最长的窗口时长，用于 range query。"""
        windows = [t.window_duration for t in self.thresholds if t.is_sustained]
        if not windows:
            return ""
        from .sliding_window import parse_duration
        return max(windows, key=lambda d: parse_duration(d))

    def to_promql(self) -> str:
        """委托给 QueryBuilder 生成 PromQL（避免循环导入，延迟调用）。"""
        from .query import QueryBuilder
        return QueryBuilder.build(self)

    def __hash__(self) -> int:
        return hash(self.id)

    def __post_init__(self) -> None:
        if not self.aggregation:
            self.aggregation = _default_aggregation(self.category)


def _default_aggregation(category: MetricCategory) -> str:
    _defaults = {
        MetricCategory.LATENCY: "histogram_quantile(0.99, rate({name}[5m]))",
        MetricCategory.ERROR_RATE: "rate({name}[5m]) > 0",
        MetricCategory.THROUGHPUT: "rate({name}[5m])",
        MetricCategory.SATURATION: "avg({name})",
        MetricCategory.CUSTOM: "{name}",
    }
    return _defaults[category]