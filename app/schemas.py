"""API 请求 / 响应模型。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class Point(BaseModel):
    """单个时间序列数据点，timestamp 支持 ISO 8601 字符串或 Unix 时间戳。"""

    timestamp: datetime
    value: float

    @field_validator("timestamp")
    @classmethod
    def _assume_utc(cls, ts: datetime) -> datetime:
        # 未带时区的时间按 UTC 处理，避免与带时区时间混排时报错
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts


class DetectRequest(BaseModel):
    """检测请求：数值序列 + 算法参数。"""

    points: list[Point] = Field(min_length=3, description="时间序列数据点")
    window_size: int = Field(default=24, ge=3, le=1000, description="滑动窗口大小")
    threshold: float = Field(default=3.5, gt=0, le=1000, description="稳健 z 分数阈值")
    merge_gap: int = Field(
        default=0, ge=0, le=100, description="合并区间允许的最大正常点间隔"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "points": [
                    {"timestamp": "2026-09-01T00:00:00Z", "value": 10.1},
                    {"timestamp": "2026-09-01T00:01:00Z", "value": 9.8},
                    {"timestamp": "2026-09-01T00:02:00Z", "value": 10.0},
                ],
                "window_size": 24,
                "threshold": 3.5,
                "merge_gap": 0,
            }
        }
    }


class TriggerPoint(BaseModel):
    timestamp: datetime
    value: float
    baseline: float
    score: float
    reason: str


class AnomalyInterval(BaseModel):
    start_time: datetime
    end_time: datetime
    point_count: int
    direction: str
    baseline: float
    score: float
    peak_value: float
    peak_time: datetime
    trigger_points: list[TriggerPoint]


class DetectSummary(BaseModel):
    point_count: int
    anomalous_point_count: int
    interval_count: int
    start_time: datetime | None
    end_time: datetime | None
    warmup_points: int


class DetectResponse(BaseModel):
    """检测响应：检测 ID + 参数回显 + 合并后的异常区间。"""

    id: str
    created_at: datetime
    params: dict
    summary: DetectSummary
    intervals: list[AnomalyInterval]


class DetectionSummaryItem(BaseModel):
    """列表接口中的摘要项。"""

    id: str
    created_at: datetime
    point_count: int
    interval_count: int
