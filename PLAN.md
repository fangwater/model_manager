# Trade Flow 阈值管理功能方案

## 概述

在 model_manager 中为每个 model 的每个 symbol 管理 `medium_notional_threshold` 和 `large_notional_threshold`，保存到 SQLite 并自动同步到 Redis。

## 数据模型

### model_repo 表增加 venue 字段

```sql
ALTER TABLE model_repo ADD COLUMN venue TEXT NOT NULL DEFAULT '';
```

注册 model 时 venue 必填（如 `binance-futures`）。

### 新增 symbol_thresholds 表

```sql
CREATE TABLE IF NOT EXISTS symbol_thresholds (
    model_name TEXT NOT NULL,
    symbol TEXT NOT NULL,
    medium_notional_threshold REAL NOT NULL DEFAULT 2000.0,
    large_notional_threshold REAL NOT NULL DEFAULT 10000.0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (model_name, symbol)
);
```

## 修改文件清单

### 1. requirements.txt
- 添加 `redis` 依赖

### 2. backend/db.py
- `initialize()` 中创建 `symbol_thresholds` 表，并 ALTER model_repo 加 venue 列（兼容已有数据库）
- `RegisteredModel` 增加 `venue: str` 字段
- `upsert_model()` 接受 venue 参数
- 新增方法：
  - `get_symbol_threshold(model_name, symbol)` → 单条
  - `list_symbol_thresholds(model_name)` → 该 model 下所有
  - `upsert_symbol_threshold(model_name, symbol, medium, large)` → 插入或更新
  - `upsert_symbol_thresholds_batch(model_name, items)` → 批量 upsert（用于自动初始化）

### 3. backend/redis_sync.py（新文件）
- `RedisSync` 类，连接 127.0.0.1:6379/0
- `sync_threshold(venue, symbol, medium, large)` — 写单个 key `{venue}:{symbol}:amount-threshold`，值为 JSON
- `sync_all_thresholds(venue, thresholds_list)` — 批量写入（pipeline）
- 连接失败时 log warning 不阻塞主流程

### 4. backend/registry.py
- `add_or_refresh_model()` 和 `refresh_model()` 扫描后自动为新 symbol 初始化默认阈值（已有的不覆盖）
- 初始化后调用 redis_sync 同步
- 新增方法：
  - `get_symbol_thresholds(model_name)` — 返回该 model 所有 symbol 的阈值
  - `set_symbol_threshold(model_name, symbol, medium, large)` — 更新单个 symbol 阈值并同步 Redis

### 5. backend/main.py
- 创建 `RedisSync` 实例，传给 `ModelRegistry`

### 6. backend/web.py
- `AddModelRequest` 增加 `venue` 字段（必填）
- 新增端点：
  - `GET /api/models/{model_name}/thresholds` — 列出该 model 所有 symbol 阈值
  - `PUT /api/models/{model_name}/thresholds/{symbol}` — 更新单个 symbol 阈值
- `POST /api/models` 响应中包含 venue

### 7. frontend/index.html
- 注册表单增加 venue 输入框
- 新增 Thresholds 面板：选择 model 后展示所有 symbol 的阈值表格，支持编辑和保存

### 8. frontend/app.js
- 注册 model 时发送 venue
- 加载阈值列表、编辑保存逻辑

## 默认值
- `medium_notional_threshold`: 2000.0
- `large_notional_threshold`: 10000.0

## Redis key 格式
- `{venue}:{symbol}:amount-threshold`
- 值：`{"medium_notional_threshold": 2000.0, "large_notional_threshold": 10000.0}`
