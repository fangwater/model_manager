# Order Quantiles（阈值配置）功能计划

## 概述

新增独立于 model 的 order quantiles 配置功能。每个 venue（如 `binance-futures`）有自己的一份 pkl 文件，pkl 内按 symbol 存储 `{low, high}` 阈值。通过 REST API 注册 venue 的 pkl 路径、查询指定 venue+symbol 的阈值。

## pkl 数据结构

```python
{
    "BTCUSDT": {"low": np.float64(264.97), "high": np.float64(6489.86)},
    "ETHUSDT": {"low": np.float64(40.52), "high": np.float64(3200.0)},
    ...
}
```

## Venue 列表（来自 TradingVenue 枚举）

`binance-margin`, `binance-futures`, `okex-margin`, `okex-futures`, `bybit-margin`, `bybit-futures`, `bitget-margin`, `bitget-futures`, `gate-margin`, `gate-futures`

## API 设计

### 1. 注册/更新 venue 的 quantiles pkl 路径
```
PUT /api/venues/{venue}/quantiles
Body: {"pkl_path": "/path/to/order_quantiles.pkl"}
```
- 验证 venue 名称合法（在已知列表中）
- 验证 pkl 文件存在且可加载
- 加载 pkl 数据存入内存 + 持久化 pkl_path 到 DB
- 返回加载到的 symbol 数量

### 2. 查询指定 venue+symbol 的阈值
```
GET /api/venues/{venue}/quantiles/{symbol}
```
- 返回 `{"venue": "binance-futures", "symbol": "BTCUSDT", "low": 264.97, "high": 6489.86}`
- venue 未注册或 symbol 不存在返回 404

### 3. 查询指定 venue 的所有阈值
```
GET /api/venues/{venue}/quantiles
```
- 返回该 venue 下所有 symbol 的 low/high
- venue 未注册返回 404

### 4. 列出所有已注册 venue
```
GET /api/venues
```
- 返回已注册 venue 列表及其 pkl_path

## 修改清单

### 1. `backend/db.py`
- `initialize()` 中新增 `venue_quantiles` 表：
  ```sql
  CREATE TABLE IF NOT EXISTS venue_quantiles (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      venue TEXT NOT NULL UNIQUE,
      pkl_path TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
  );
  ```
- 新增方法：
  - `upsert_venue_quantiles(venue, pkl_path)` — 插入或更新
  - `get_venue_quantiles(venue)` — 查询单个 venue 的 pkl_path
  - `list_venue_quantiles()` — 列出所有已注册 venue
  - `delete_venue_quantiles(venue)` — 删除

### 2. 新增 `backend/quantiles.py`
- `VALID_VENUES` 常量集合
- `QuantilesStore` 类：
  - 内存缓存：`dict[str, dict[str, dict[str, float]]]`（venue → symbol → {low, high}）
  - `load_venue(venue, pkl_path)` — 加载 pkl 到内存，持久化到 DB
  - `get(venue, symbol)` — 查询单个
  - `get_all(venue)` — 查询 venue 下所有
  - `list_venues()` — 已加载的 venue 列表及 pkl_path
  - `warmup()` — 启动时从 DB 读取所有已注册 venue 的 pkl_path 并加载到内存

### 3. `backend/main.py`
- 创建 `QuantilesStore(db)` 实例，调用 `warmup()`
- 传入 `create_app()`

### 4. `backend/web.py`
- `create_app()` 签名增加 `quantiles_store` 参数
- 新增 4 个端点（见上方 API 设计）

### 5. 前端 — 不做改动（纯 API 功能）
