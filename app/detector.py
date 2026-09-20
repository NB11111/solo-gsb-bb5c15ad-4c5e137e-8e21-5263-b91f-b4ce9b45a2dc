"""滑动窗口稳健基线异常检测核心算法。

算法说明：
1. 对每个点取其后置（历史）滑动窗口，用中位数作为稳健基线，
   用 MAD（绝对中位差）* 1.4826 估计稳健标准差，抗离群值污染。
2. 计算稳健 z 分数：|x - median| / (1.4826 * MAD)，超过阈值即判为异常。
3. 将相邻（或间隔不超过 merge_gap 个正常点）的异常点合并为异常区间，
   并给出每个区间的基线、峰值分数与触发点解释。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Sequence

# MAD 到标准差的一致性系数（正态分布下 1.4826 * MAD ≈ σ）
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class SeriesPoint:
    """排序后的内部数据点。"""

    timestamp: datetime
    value: float


def _robust_sigma(window: Sequence[float], med: float) -> float:
    """基于 MAD 的稳健标准差估计。"""
    mad = median(abs(v - med) for v in window)
    return MAD_TO_SIGMA * mad


def _robust_score(value: float, med: float, sigma: float) -> float:
    """稳健 z 分数。

    当窗口完全平坦（sigma 为 0）时，用一个与基线量级相关的极小量
    兜底，保证任何非零偏离都会产生很大的分数而不会被除零。
    """
    eps = 1e-9 * max(1.0, abs(med))
    return abs(value - med) / max(sigma, eps)


def detect_anomalies(
    points: list[SeriesPoint],
    window_size: int,
    threshold: float,
    merge_gap: int,
    max_triggers: int = 5,
) -> dict:
    """执行异常检测，返回可 JSON 序列化的结果字典。

    :param points: 已按时间升序排列的数据点。
    :param window_size: 滑动窗口大小（只用历史点，无前视偏差）。
    :param threshold: 稳健 z 分数阈值。
    :param merge_gap: 合并区间时允许的最大正常点间隔。
    :param max_triggers: 每个区间最多返回的触发点数量。
    """
    n = len(points)
    values = [p.value for p in points]

    baselines: list[float | None] = [None] * n
    scores: list[float] = [0.0] * n
    flags: list[bool] = [False] * n

    # 前 window_size 个点为预热期，历史不足，不参与判定
    for i in range(window_size, n):
        window = values[i - window_size : i]
        med = median(window)
        sigma = _robust_sigma(window, med)
        score = _robust_score(values[i], med, sigma)
        baselines[i] = med
        scores[i] = score
        flags[i] = score >= threshold

    intervals = _build_intervals(
        points, values, baselines, scores, flags, merge_gap, threshold, max_triggers
    )

    return {
        "summary": {
            "point_count": n,
            "anomalous_point_count": sum(flags),
            "interval_count": len(intervals),
            "start_time": points[0].timestamp.isoformat() if n else None,
            "end_time": points[-1].timestamp.isoformat() if n else None,
            "warmup_points": min(window_size, n),
        },
        "intervals": intervals,
    }


def _build_intervals(
    points: list[SeriesPoint],
    values: list[float],
    baselines: list[float | None],
    scores: list[float],
    flags: list[bool],
    merge_gap: int,
    threshold: float,
    max_triggers: int,
) -> list[dict]:
    """把异常点标记合并为异常区间并生成解释。"""
    n = len(points)

    # 1) 找出所有连续异常段 [start, end]（闭区间）
    runs: list[list[int]] = []
    i = 0
    while i < n:
        if flags[i]:
            start = i
            while i < n and flags[i]:
                i += 1
            runs.append([start, i - 1])
        else:
            i += 1

    # 2) 间隔不超过 merge_gap 个正常点的相邻段合并为一个区间
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] - 1 <= merge_gap:
            merged[-1][1] = run[1]
        else:
            merged.append(run)

    # 3) 逐区间生成基线、分数与触发点解释
    intervals: list[dict] = []
    for start, end in merged:
        peak_idx = max(range(start, end + 1), key=lambda k: scores[k])
        trigger_idx = start  # 第一个越过阈值的点
        trigger_baseline = baselines[trigger_idx]
        assert trigger_baseline is not None  # 预热期不会产生标记
        direction = "up" if values[trigger_idx] > trigger_baseline else "down"

        # 触发点：首个触发点必选，其余按分数从高到低补足，最后按时间排序
        chosen = {trigger_idx}
        by_score = sorted(range(start, end + 1), key=lambda k: scores[k], reverse=True)
        for k in by_score:
            if len(chosen) >= max_triggers:
                break
            chosen.add(k)
        trigger_points = [
            {
                "timestamp": points[k].timestamp.isoformat(),
                "value": values[k],
                "baseline": round(baselines[k], 6),  # type: ignore[arg-type]
                "score": round(scores[k], 4),
                "reason": (
                    f"数值 {values[k]} 偏离稳健基线 "
                    f"{baselines[k]:.6g}，稳健 z 分数 {scores[k]:.2f} "
                    f">= 阈值 {threshold}（{'向上' if values[k] > baselines[k] else '向下'}突变）"
                ),
            }
            for k in sorted(chosen)
        ]

        intervals.append(
            {
                "start_time": points[start].timestamp.isoformat(),
                "end_time": points[end].timestamp.isoformat(),
                "point_count": end - start + 1,
                "direction": direction,
                "baseline": round(trigger_baseline, 6),
                "score": round(scores[peak_idx], 4),
                "peak_value": values[peak_idx],
                "peak_time": points[peak_idx].timestamp.isoformat(),
                "trigger_points": trigger_points,
            }
        )

    return intervals
