# 时间序列异常检测 API

基于 **FastAPI + SQLite** 的时间序列异常检测服务。接收带时间戳的数值序列，按滑动窗口计算稳健基线（中位数 + MAD）并识别突变，返回**合并后的异常区间**及每段的基线、分数和触发点解释；检测结果自动保存，支持按 ID 查询。

## 功能特性

- 🚀 **稳健基线**：滑动窗口中位数 + MAD（绝对中位差），抗离群值污染，只使用历史数据、无前视偏差
- 📉 **突变识别**：稳健 z 分数 `|x − median| / (1.4826 × MAD)` 超过阈值即判定异常，支持向上 / 向下两个方向
- 🔗 **区间合并**：相邻异常点自动合并为区间，可用 `merge_gap` 容忍短暂回落
- 💾 **结果持久化**：每次检测写入 SQLite，支持按 ID 查询完整结果、按时间倒序列出摘要
- 🐳 **开箱即用**：提供 Dockerfile 与 Compose，启动即可调用

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
docker compose up --build
```

### 方式二：Docker

```bash
docker build -t ts-anomaly-api .
docker run -p 8000:8000 -v $(pwd)/data:/app/data ts-anomaly-api
```

### 方式三：本地运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后访问交互式文档：<http://localhost:8000/docs>

## 使用示例

### 1. 提交检测

仓库内置了示例数据 `examples/sample_request.json`（基线 10，含两处突变）：

```bash
curl -X POST http://localhost:8000/api/v1/detect \
  -H 'Content-Type: application/json' \
  -d @examples/sample_request.json
```

请求体：

```json
{
  "points": [
    {"timestamp": "2026-09-01T00:00:00Z", "value": 10.1},
    {"timestamp": "2026-09-01T00:01:00Z", "value": 9.8}
  ],
  "window_size": 12,
  "threshold": 3.5,
  "merge_gap": 1
}
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `points` | 必填 | 数据点列表（≥3 个），`timestamp` 支持 ISO 8601 或 Unix 时间戳，允许乱序提交 |
| `window_size` | 24 | 滑动窗口大小（只用历史点），前 `window_size` 个点为预热期不参与判定 |
| `threshold` | 3.5 | 稳健 z 分数阈值，越大越不敏感 |
| `merge_gap` | 0 | 合并区间时允许的最大正常点间隔 |

响应（节选）：

```json
{
  "id": "b1445d3d66074529a7dad87e27f91523",
  "created_at": "2026-09-20T22:41:30.057316Z",
  "params": {"window_size": 12, "threshold": 3.5, "merge_gap": 1},
  "summary": {
    "point_count": 48,
    "anomalous_point_count": 3,
    "interval_count": 2,
    "warmup_points": 12
  },
  "intervals": [
    {
      "start_time": "2026-09-01T00:30:00Z",
      "end_time": "2026-09-01T00:31:00Z",
      "point_count": 2,
      "direction": "up",
      "baseline": 10.0,
      "score": 101.1736,
      "peak_value": 25.0,
      "peak_time": "2026-09-01T00:30:00Z",
      "trigger_points": [
        {
          "timestamp": "2026-09-01T00:30:00Z",
          "value": 25.0,
          "baseline": 10.0,
          "score": 101.1736,
          "reason": "数值 25.0 偏离稳健基线 10，稳健 z 分数 101.17 >= 阈值 3.5（向上突变）"
        }
      ]
    }
  ]
}
```

### 2. 按 ID 查询检测结果

```bash
curl http://localhost:8000/api/v1/detections/<id>
```

### 3. 列出历史检测

```bash
curl "http://localhost:8000/api/v1/detections?limit=20&offset=0"
```

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/v1/detect` | 执行检测、保存并返回结果（含 ID） |
| `GET` | `/api/v1/detections/{id}` | 按 ID 查询完整检测结果 |
| `GET` | `/api/v1/detections` | 按时间倒序列出检测摘要 |

## 算法说明

1. **排序**：输入点按时间升序排列（容忍乱序提交；无时区时间按 UTC 处理）。
2. **稳健基线**：对每个点取前 `window_size` 个历史点，基线 = 窗口中位数，尺度 = `1.4826 × MAD`。
3. **打分**：稳健 z 分数 = `|x − 基线| / 尺度`，≥ `threshold` 判为异常。窗口完全平坦时任何非零偏离都会触发。
4. **合并**：连续异常点合并为区间；间隔 ≤ `merge_gap` 个正常点的相邻区间进一步合并。
5. **解释**：每个区间报告触发点处的基线、区间内峰值分数、方向，以及最多 5 个触发点（首个触发点必选，其余按分数排序）的中文解释。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DB_PATH` | `data/detections.db`（容器内 `/app/data/detections.db`） | SQLite 数据库文件路径 |

Compose 默认将 `./data` 挂载到容器 `/app/data`，检测结果在容器重启后保留。

## 测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

## 项目结构

```
├── app/
│   ├── main.py       # FastAPI 应用与路由
│   ├── detector.py   # 滑动窗口稳健基线检测核心
│   ├── storage.py    # SQLite 持久化
│   └── schemas.py    # Pydantic 请求/响应模型
├── tests/test_api.py # API 集成测试
├── examples/sample_request.json
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
