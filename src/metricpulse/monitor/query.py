"""QueryBuilder — 将 MetricConfig 编译为 PromQL 查询。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import MetricConfig


class QueryBuilder:
    """PromQL 编译器。

    从 MetricConfig 的 category + metric_name + aggregation + labels
    生成标准 PromQL，支持自定义标签片段注入（extra['promql_fragment']）。
    """

    @staticmethod
    def build(config: MetricConfig) -> str:
        metric_expr = config.metric_name
        if config.labels:
            label_parts = [f'{k}="{v}"' for k, v in config.labels.items()]
            metric_expr = f'{metric_expr}{{{", ".join(label_parts)}}}'

        # 用 metric_name 填充聚合模板中的 {name} 占位符
        agg_template = config.aggregation
        promql = agg_template.replace("{name}", metric_expr)

        # 允许通过 extra 注入额外 PromQL 后缀（如 * 100, offset 1h 等）
        fragment = config.extra.get("promql_fragment", "")
        if fragment:
            promql = f"({promql}) {fragment}"

        return promql.strip()

    @staticmethod
    def build_range(
        config: MetricConfig,
        step: str = "1m",
    ) -> str:
        """构建 range query 所用的 PromQL（与 instant 一致，step 由客户端管理）。"""
        return QueryBuilder.build(config)
