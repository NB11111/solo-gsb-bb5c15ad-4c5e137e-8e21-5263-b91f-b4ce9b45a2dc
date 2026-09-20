"""API 集成测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client():
    # 每个测试用例使用独立的内存数据库
    app = create_app(db_path=":memory:")
    with TestClient(app) as c:
        yield c


def make_points(n: int = 60, spikes: dict[int, float] | None = None) -> list[dict]:
    """生成基线为 10 的平稳序列，并在指定位置注入突变。"""
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    points = []
    for i in range(n):
        value = 10.0 + (0.1 if i % 2 == 0 else -0.1)  # 微小波动
        if spikes and i in spikes:
            value = spikes[i]
        points.append(
            {"timestamp": (base + timedelta(minutes=i)).isoformat(), "value": value}
        )
    return points


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_detect_spike_and_fetch_by_id(client):
    payload = {
        "points": make_points(60, {40: 50.0, 41: 48.0}),
        "window_size": 12,
        "threshold": 3.5,
    }
    resp = client.post("/api/v1/detect", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    assert body["summary"]["point_count"] == 60
    assert body["summary"]["interval_count"] == 1

    interval = body["intervals"][0]
    assert interval["direction"] == "up"
    assert interval["baseline"] == pytest.approx(10.0, abs=0.2)
    assert interval["score"] > 3.5
    assert interval["peak_value"] == 50.0
    assert interval["start_time"].startswith("2026-09-01T00:40")
    assert interval["end_time"].startswith("2026-09-01T00:41")
    assert len(interval["trigger_points"]) >= 1
    assert "稳健基线" in interval["trigger_points"][0]["reason"]

    # 结果已保存，可按 ID 查询到相同内容
    det_id = body["id"]
    fetched = client.get(f"/api/v1/detections/{det_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_detect_downward_spike(client):
    payload = {
        "points": make_points(50, {30: -20.0}),
        "window_size": 10,
        "threshold": 3.5,
    }
    body = client.post("/api/v1/detect", json=payload).json()
    assert body["intervals"][0]["direction"] == "down"


def test_merge_gap_combines_intervals(client):
    # 两个尖峰间隔 3 个正常点：merge_gap=0 时为两个区间，merge_gap=3 时合并为一个
    spikes = {30: 50.0, 34: 50.0}
    payload = {"points": make_points(50, spikes), "window_size": 10, "threshold": 3.5}

    body = client.post("/api/v1/detect", json=payload).json()
    assert body["summary"]["interval_count"] == 2

    payload["merge_gap"] = 3
    body = client.post("/api/v1/detect", json=payload).json()
    assert body["summary"]["interval_count"] == 1
    assert body["intervals"][0]["point_count"] == 5


def test_stable_series_has_no_anomalies(client):
    payload = {"points": make_points(40, None), "window_size": 8}
    body = client.post("/api/v1/detect", json=payload).json()
    assert body["summary"]["interval_count"] == 0
    assert body["intervals"] == []


def test_get_unknown_detection_returns_404(client):
    resp = client.get("/api/v1/detections/does-not-exist")
    assert resp.status_code == 404


def test_too_few_points_rejected(client):
    payload = {"points": make_points(2, None)}
    resp = client.post("/api/v1/detect", json=payload)
    assert resp.status_code == 422


def test_unsorted_input_is_sorted(client):
    points = make_points(40, {25: 60.0})
    points.reverse()  # 乱序提交
    payload = {"points": points, "window_size": 8}
    body = client.post("/api/v1/detect", json=payload).json()
    assert body["summary"]["interval_count"] == 1
    assert body["intervals"][0]["start_time"].startswith("2026-09-01T00:25")


def test_list_detections(client):
    payload = {"points": make_points(30, {20: 99.0}), "window_size": 6}
    client.post("/api/v1/detect", json=payload)
    client.post("/api/v1/detect", json=payload)

    resp = client.get("/api/v1/detections")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    assert items[0]["interval_count"] == 1
