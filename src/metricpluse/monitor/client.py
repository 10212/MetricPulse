"""PrometheusClient — HTTP API 客户端。

封装 Prometheus HTTP API：instant query、range query、series 查询。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from .config import MetricConfig
from .query import QueryBuilder


@dataclass
class QueryResult:
    """单次查询的结构化结果。"""

    config_id: str
    promql: str
    value: float | None           # instant query 的单值
    values: list[tuple[float, str]] = field(default_factory=list)  # range query
    raw: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    error: str | None = None


class PrometheusClient:
    """Prometheus HTTP API 客户端。

    支持：
    - 基础认证 / Bearer Token
    - instant query / range query
    - 批量 MetricConfig 查询
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

    async def instant_query(self, config: MetricConfig, time_str: str | None = None) -> QueryResult:
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

    async def query_many(
        self,
        configs: list[MetricConfig],
        *,
        time_str: str | None = None,
    ) -> list[QueryResult]:
        """并发执行多个 instant query。"""
        tasks = [self.instant_query(c, time_str) for c in configs]
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

    async def _execute(self, promql: str, config_id: str, path: str, params: dict[str, str]) -> QueryResult:
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
