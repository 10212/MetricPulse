"""滑动窗口持续阈值评估器。

当 Threshold 配置了 window_duration + min_samples 时，
通过 Prometheus range query 获取时间序列数据，在滑动窗口内
统计违反次数，达到 min_samples 才视为异常。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 时长解析
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"^(\d+)([smh])$")
_UNITS: dict[str, int] = {"s": 1, "m": 60, "h": 3600}


def parse_duration(s: str) -> int:
    """将 '5m'、'30s'、'1h' 解析为秒数。

    Raises:
        ValueError: 格式无效。
    """
    m = _DURATION_RE.match(s)
    if not m:
        raise ValueError(f"无效的时长格式: {s!r}，期望如 '5m'、'30s'、'1h'")
    return int(m.group(1)) * _UNITS[m.group(2)]


# ---------------------------------------------------------------------------
# 滑动窗口结果
# ---------------------------------------------------------------------------

@dataclass
class SustainedResult:
    """持续阈值评估结果。"""

    triggered: bool
    """是否有任一滑动窗口满足条件。"""

    window_max_count: int
    """所有窗口中违反次数最大值。"""

    window_required: int
    """触发所需的最小违反次数（min_samples）。"""

    window_duration: str
    """窗口时长（如 '5m'）。"""

    first_violation_time: str = ""
    """首个满足条件的窗口起始时间（ISO 8601）。"""


# ---------------------------------------------------------------------------
# 滑动窗口核心算法
# ---------------------------------------------------------------------------

def _check_single(value: float, operator: str, threshold_val: float) -> bool:
    ops: dict[str, Any] = {
        "gt":  lambda v, tv: v >  tv,     # type: ignore[dict-item]
        "lt":  lambda v, tv: v <  tv,
        "gte": lambda v, tv: v >= tv,
        "lte": lambda v, tv: v <= tv,
        "eq":  lambda v, tv: v == tv,
    }
    fn = ops.get(operator)
    return fn(value, threshold_val) if fn else False


def evaluate_sustained(
    samples: list[tuple[float, str]],
    operator: str,
    threshold_value: float,
    window_duration: str,
    min_samples: int,
) -> SustainedResult:
    """在时间序列数据上执行滑动窗口评估。

    算法：以每个采样点作为窗口起点 [ts, ts + window_duration)，
    统计该区间内违反阈值的采样点数，取各窗口中的最大值。
    任意窗口达到 min_samples 即视为异常。

    Args:
        samples:   [(unix_timestamp, value_string), ...]
        operator:  比较操作符
        threshold_value:  阈值
        window_duration:  窗口时长字符串，如 '5m'
        min_samples:  最少违反次数

    Returns:
        SustainedResult
    """
    if not samples or min_samples <= 0:
        return SustainedResult(
            triggered=False,
            window_max_count=0,
            window_required=min_samples,
            window_duration=window_duration,
        )

    # 将 value_string 转为 float
    try:
        points = [(ts, float(val)) for ts, val in samples]
    except ValueError:
        return SustainedResult(
            triggered=False,
            window_max_count=0,
            window_required=min_samples,
            window_duration=window_duration,
        )

    window_secs = parse_duration(window_duration)

    # 按时序排序
    points.sort(key=lambda p: p[0])

    max_count = 0
    first_trigger_time = ""

    for i, (start_ts, _) in enumerate(points):
        end_ts = start_ts + window_secs
        count = 0
        for j in range(i, len(points)):
            ts_j, val_j = points[j]
            if ts_j >= end_ts:
                break
            if _check_single(val_j, operator, threshold_value):
                count += 1

        if count > max_count:
            max_count = count

        if count >= min_samples and not first_trigger_time:
            first_trigger_time = (
                datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
            )

    return SustainedResult(
        triggered=max_count >= min_samples,
        window_max_count=max_count,
        window_required=min_samples,
        window_duration=window_duration,
        first_violation_time=first_trigger_time,
    )