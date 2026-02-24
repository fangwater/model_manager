# model_manager

Python service for:

- registering model artifact directories (read-only parsing)
- exploring symbol/factor/IC/info via web UI
- serving XGBoost model json + metadata through HTTP
- auto-refreshing registered models when artifact files change
- per-venue order quantiles (low/high thresholds) via pkl files

## Artifact layout

Each model directory can contain files like:

- `SOLUSDT_mid_chg_1m_factors.txt`
- `SOLUSDT_mid_chg_1m_ic.csv`
- `SOLUSDT_mid_chg_1m_info.pkl`
- `SOLUSDT_mid_chg_1m_model.pkl`
- `SOLUSDT_mid_chg_1m_model.json` (optional; auto-converted from pkl if absent)

Service groups these by `group_key` (`SOLUSDT_mid_chg_1m`) and extracts:

- symbol
- return_name
- feature dimension
- factor list
- IC table
- training metadata
- dim-to-factor mapping for model payload API

## Minimal operation flow

### 1) Setup (first time / dependency update)

```bash
cd /home/fanghaizhou/project/model_manager
./setup.sh
```

### 2) Start

Default web endpoint is no longer `8788`; it is now `6300`.

```bash
cd /home/fanghaizhou/project/model_manager
./start.sh
```

Change web endpoint:

```bash
./start.sh --web-host 0.0.0.0 --web-port 18090
```

or with env vars:

```bash
MODEL_MANAGER_HTTP_HOST=0.0.0.0 MODEL_MANAGER_HTTP_PORT=18090 ./start.sh
```

### 3) Stop

```bash
cd /home/fanghaizhou/project/model_manager
./stop.sh
```

## Run (direct, optional)

`start_model_manager.sh` is pinned to `.venv/bin/python`.

```bash
cd /home/fanghaizhou/project/model_manager
./start_model_manager.sh
```

Default ports:

- HTTP: `0.0.0.0:6300`

Open UI:

- `http://127.0.0.1:6300`

## Auth

Auth is disabled. All HTTP endpoints are public.

## Model Payload API

Method:

- `GET /api/models/{model_name}/model/{symbol}`

Response includes:

- `payload.model_json` (XGBoost json text, auto-converted from `*_model.pkl` when needed)
- `payload.metadata` (time window, dim, train samples, etc.)
- `payload.dim_factors` with `factor_name` and `kendall_tau`

Selection behavior:

- `symbol` must map to exactly one group in the registered path
- if multiple groups share the same `symbol`, request returns `404`

Compression:

- server enables gzip for large responses (including model payload) when client sends `Accept-Encoding: gzip`
- with curl, use `--compressed` to enable it automatically

## HTTP API summary

- `GET /api/models`
- `POST /api/models`
- `POST /api/models/{model_name}/refresh`
- `GET /api/models/{model_name}/symbols`
- `GET /api/models/{model_name}/factors`
- `GET /api/models/{model_name}/symbols/{symbol}?group_key=...`
- `GET /api/models/{model_name}/model/{symbol}`
- `GET /api/venues`
- `PUT /api/venues/{venue}/quantiles`
- `GET /api/venues/{venue}/quantiles`
- `GET /api/venues/{venue}/quantiles/{symbol}`

`POST /api/models` and refresh require unique `symbol` per registered root path.
If one symbol maps to multiple groups, request fails with `400`.

All model endpoints are public; no bearer token is required.

`GET /api/models/{model_name}/factors` returns the union factor list across all symbols/groups:

- `model_name`
- `symbol_count`
- `group_count`
- `factor_count`
- `factors` (deduplicated list)

## Order Quantiles API

Per-venue 阈值配置，每个 venue 对应一份 pkl 文件，pkl 内按 symbol 存储 `medium_notional_threshold` 和 `large_notional_threshold`。

pkl 数据格式（list of dicts）：

```json
[
  {"symbol": "BTCUSDT", "medium_notional_threshold": 10000.0, "large_notional_threshold": 50000.0},
  {"symbol": "ETHUSDT", "medium_notional_threshold": 5000.0, "large_notional_threshold": 20000.0}
]
```

合法 venue 列表：`binance-margin`, `binance-futures`, `okex-margin`, `okex-futures`, `bybit-margin`, `bybit-futures`, `bitget-margin`, `bitget-futures`, `gate-margin`, `gate-futures`

### 注册/更新 venue 的 pkl 路径

```
PUT /api/venues/{venue}/quantiles
Body: {"pkl_path": "/path/to/order_quantiles.pkl"}
```

返回：`{"venue": "binance-futures", "symbol_count": 42}`

### 查询指定 venue 的所有阈值

```
GET /api/venues/{venue}/quantiles
```

返回：

```json
{
  "venue": "binance-futures",
  "symbols": {
    "BTCUSDT": {"medium_notional_threshold": 10000.0, "large_notional_threshold": 50000.0},
    "ETHUSDT": {"medium_notional_threshold": 5000.0, "large_notional_threshold": 20000.0}
  }
}
```

### 查询指定 venue+symbol 的阈值

```
GET /api/venues/{venue}/quantiles/{symbol}
```

返回：`{"venue": "binance-futures", "symbol": "BTCUSDT", "medium_notional_threshold": 10000.0, "large_notional_threshold": 50000.0}`

### 列出所有已注册 venue

```
GET /api/venues
```

返回：`{"items": [{"venue": "binance-futures", "pkl_path": "/path/to/file.pkl", "updated_at": "..."}]}`

## Env vars

- `MODEL_MANAGER_HTTP_HOST`
- `MODEL_MANAGER_HTTP_PORT`
- `MODEL_MANAGER_WATCH_ENABLED` (default `1`)
- `MODEL_MANAGER_WATCH_INTERVAL` (seconds, default `5`)
- `MODEL_MANAGER_WATCH_DEBOUNCE` (seconds, default `2`)

You can edit these in `ecosystem.config.js`.
