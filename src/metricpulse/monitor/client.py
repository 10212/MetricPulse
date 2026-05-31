"""PrometheusClient — HTTP API 客户端。

封装 Prometheus HTTP API：instant query、range query、series 查询。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import MetricConfig
from .query import QueryBuilder
from .sliding_window import parse_duration


@dataclass
class QueryResult:
    """单次查询的结构化结果。"""

    config_id: str
    promql: str
    value: float | None = None           # instant query 的单值
    values: list[tuple[float, str]] = field(default_factory=list)  # range query 时序数据
    raw: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    error: str | None = None


class PrometheusClient:
    """Prometheus HTTP API 客户端。

    支持：
    - 基础认证 / Bearer Token
    - instant query / range query
    - 批量 MetricConfig 查询
    - 持续阈值所需的 range query 快捷方法
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        bearer_token: str | None = None,
        basic_auth: tuple[str, str] | None = None,
        default_step: str = "1m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        auth: httpx.BasicAuth | None = None
        if basic_auth:
            auth = httpx.BasicAuth(basic_auth[0], basic_auth[1])

        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
            headers=headers,
            auth=auth,
        )
        self.default_step = default_step

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "PrometheusClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def instant_query(
        self, config: MetricConfig, time_str: str | None = None
    ) -> QueryResult:
        """执行 instant query。"""
        promql = QueryBuilder.build(config)
        params: dict[str, str] = {"query": promql}
        if time_str:
            params["time"] = time_str
        return await self._execute(promql, config.id, "/api/v1/query", params)

    async def range_query(
        self,
        config: MetricConfig,
        start: str,
        end: str,
        step: str | None = None,
    ) -> QueryResult:
        """执行 range query。"""
        promql = QueryBuilder.build_range(config)
        params: dict[str, str] = {
            "query": promql,
            "start": start,
            "end": end,
            "step": step or self.default_step,
        }
        return await self._execute(promql, config.id, "/api/v1/query_range", params)

    async def range_query_sustained(
        self,
        config: MetricConfig,
        window: str,
        *,
        step: str | None = None,
    ) -> QueryResult:
        """为持续阈值执行 range query。

        自动计算 start = now - window, end = now。

        Args:
            config:  指标配置
            window:  窗口时长，如 '5m'、'10m'
            step:    Prometheus step，默认使用 client 的 default_step
        """
        window_secs = parse_duration(window)
        now = datetime.now(timezone.utc)
        start = (now - timedelta(seconds=window_secs)).isoformat()
        end = now.isoformat()
        return await self.range_query(config, start, end, step=step)

    async def query_many(
        self,
        configs: list[MetricConfig],
        *,
        time_str: str | None = None,
    ) -> list[QueryResult]:
        """并发执行多个 instant query。"""
        tasks = [self.instant_query(c, time_str) for c in configs]
        return await asyncio.gather(*tasks)

    async def query_many_sustained(
        self,
        configs: list[MetricConfig],
        *,
        step: str | None = None,
    ) -> list[QueryResult]:
        """并发执行多个 range query，每个取各自最长的持续窗口。"""
        async def _query_one(c: MetricConfig) -> QueryResult:
            w = c.max_sustained_window
            if not w:
                # 没有持续阈值，回退到 instant query
                return await self.instant_query(c)
            return await self.range_query_sustained(c, w, step=step)

        tasks = [_query_one(c) for c in configs]
        return await asyncio.gather(*tasks)

    async def health(self) -> bool:
        """检查 Prometheus 端点健康状态。"""
        try:
            resp = await self._client.get("/-/healthy")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    async def _execute(
        self, promql: str, config_id: str, path: str, params: dict[str, str]
    ) -> QueryResult:
        result = QueryResult(config_id=config_id, promql=promql)
        try:
            resp = await self._client.get(path, params=params)
            resp.raise_for_status()
            data = resp.json()
            result.raw = data
            result.timestamp = datetime.now().isoformat()

            # 提取第一个结果的值
            series_list = data.get("data", {}).get("result", [])
            if series_list:
                first = series_list[0]
                if "value" in first:
                    _, raw_val = first["value"]
                    result.value = float(raw_val)
                if "values" in first:
                    result.values = [(float(ts), val) for ts, val in first["values"]]
        except httpx.HTTPStatusError as exc:
            result.error = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        except httpx.RequestError as exc:
            result.error = str(exc)
        except (KeyError, ValueError, IndexError) as exc:
            result.error = f"Parse error: {exc}"
        return result