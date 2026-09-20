"""SQLite 持久化层：保存检测结果并支持按 ID 查询。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    result_json TEXT NOT NULL
);
"""


class DetectionStore:
    """线程安全的检测结果存储。"""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        with self._lock, self._conn:
            self._conn.execute(_SCHEMA)

    def save(self, detection_id: str, created_at: str, result: dict) -> None:
        """保存一次检测的完整结果。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO detections (id, created_at, result_json) VALUES (?, ?, ?)",
                (detection_id, created_at, json.dumps(result, ensure_ascii=False)),
            )

    def get(self, detection_id: str) -> dict | None:
        """按 ID 查询检测结果，不存在返回 None。"""
        with self._lock:
            row = self._conn.execute(
                "SELECT result_json FROM detections WHERE id = ?", (detection_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """按时间倒序列出检测摘要。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, result_json FROM detections "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        items = []
        for det_id, created_at, result_json in rows:
            result = json.loads(result_json)
            summary = result.get("summary", {})
            items.append(
                {
                    "id": det_id,
                    "created_at": created_at,
                    "point_count": summary.get("point_count", 0),
                    "interval_count": summary.get("interval_count", 0),
                }
            )
        return items

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def default_db_path() -> str:
    """数据库路径，可用环境变量 DB_PATH 覆盖。"""
    return os.environ.get("DB_PATH", "data/detections.db")
