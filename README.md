# model_manager

Python service for:

- registering model artifact directories (read-only parsing)
- exploring symbol/factor/IC/info via web UI
- serving XGBoost model json + metadata through HTTP
- auto-refreshing registered models when artifact files change

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

## Password management (sqlite)

No user concept, only one password.

- first time: initialize from UI (Access Control card)
- optional CLI init once:

```bash
./start_model_manager.sh --init-password 'your-passwd'
```

- optional CLI reset:

```bash
./start_model_manager.sh --set-password 'new-passwd'
```

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

- `GET /api/auth/status`
- `POST /api/auth/bootstrap`
- `POST /api/auth/login`
- `GET /api/models`
- `POST /api/models`
- `POST /api/models/{model_name}/refresh`
- `GET /api/models/{model_name}/symbols`
- `GET /api/models/{model_name}/factors`
- `GET /api/models/{model_name}/symbols/{symbol}?group_key=...`
- `GET /api/models/{model_name}/model/{symbol}`

`POST /api/models` and refresh require unique `symbol` per registered root path.
If one symbol maps to multiple groups, request fails with `400`.

All model endpoints require Bearer token from login.

`GET /api/models/{model_name}/factors` returns the union factor list across all symbols/groups:

- `model_name`
- `symbol_count`
- `group_count`
- `factor_count`
- `factors` (deduplicated list)

## Env vars

- `MODEL_MANAGER_HTTP_HOST`
- `MODEL_MANAGER_HTTP_PORT`
- `MODEL_MANAGER_TOKEN_TTL`
- `MODEL_MANAGER_WATCH_ENABLED` (default `1`)
- `MODEL_MANAGER_WATCH_INTERVAL` (seconds, default `5`)
- `MODEL_MANAGER_WATCH_DEBOUNCE` (seconds, default `2`)

You can edit these in `ecosystem.config.js`.
