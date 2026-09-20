"""FastAPI 应用入口：时间序列异常检测 API。"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query

from app import __version__
from app.detector import SeriesPoint, detect_anomalies
from app.schemas import (
    DetectRequest,
    DetectResponse,
    DetectionSummaryItem,
)
from app.storage import DetectionStore, default_db_path


def create_app(db_path: str | None = None) -> FastAPI:
    """应用工厂，便于测试时注入独立数据库。"""
    store = DetectionStore(db_path or default_db_path())

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        yield
        store.close()

    app = FastAPI(
        title="时间序列异常检测 API",
        version=__version__,
        description=(
            "接收带时间戳的数值序列，基于滑动窗口稳健基线（中位数 + MAD）"
            "识别突变，返回合并后的异常区间及基线、分数与触发点解释。"
        ),
        lifespan=_lifespan,
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.post("/api/v1/detect", response_model=DetectResponse, tags=["detection"])
    def detect(req: DetectRequest) -> dict:
        """执行异常检测，保存结果并返回（含检测 ID）。"""
        # 按时间升序排序，容忍客户端乱序提交
        series = sorted(
            (SeriesPoint(timestamp=p.timestamp, value=p.value) for p in req.points),
            key=lambda p: p.timestamp,
        )

        result = detect_anomalies(
            points=series,
            window_size=req.window_size,
            threshold=req.threshold,
            merge_gap=req.merge_gap,
        )

        detection_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        response = {
            "id": detection_id,
            "created_at": created_at,
            "params": {
                "window_size": req.window_size,
                "threshold": req.threshold,
                "merge_gap": req.merge_gap,
            },
            **result,
        }
        store.save(detection_id, created_at, response)
        return response

    @app.get(
        "/api/v1/detections/{detection_id}",
        response_model=DetectResponse,
        tags=["detection"],
    )
    def get_detection(detection_id: str) -> dict:
        """按 ID 查询已保存的检测结果。"""
        result = store.get(detection_id)
        if result is None:
            raise HTTPException(status_code=404, detail="检测结果不存在")
        return result

    @app.get(
        "/api/v1/detections",
        response_model=list[DetectionSummaryItem],
        tags=["detection"],
    )
    def list_detections(
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict]:
        """列出历史检测摘要（按时间倒序）。"""
        return store.list(limit=limit, offset=offset)

    return app


app = create_app()
