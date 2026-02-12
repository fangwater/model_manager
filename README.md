# model_manager

Python service for:

- registering model artifact directories (read-only parsing)
- exploring symbol/factor/IC/info via web UI
- serving converted XGBoost `*_model.json` + metadata through gRPC
- auto-refreshing registered models when artifact files change

## Artifact layout

Each model directory can contain files like:

- `SOLUSDT_mid_chg_1m_factors.txt`
- `SOLUSDT_mid_chg_1m_ic.csv`
- `SOLUSDT_mid_chg_1m_info.pkl`
- `SOLUSDT_mid_chg_1m_model.pkl`
- `SOLUSDT_mid_chg_1m_model.json`

Service groups these by `group_key` (`SOLUSDT_mid_chg_1m`) and extracts:

- symbol
- return_name
- feature dimension
- factor list
- IC table
- training metadata
- dim-to-factor mapping for gRPC

## Install

```bash
cd /home/fanghaizhou/project/model_manager
./setup_venv.sh
```

## Run (direct)

`start_model_manager.sh` is pinned to `.venv/bin/python`.

```bash
cd /home/fanghaizhou/project/model_manager
./start_model_manager.sh
```

Default ports:

- HTTP: `0.0.0.0:8788`
- gRPC: `0.0.0.0:50061`

Open UI:

- `http://127.0.0.1:8788`

## PM2 management

Start or restart:

```bash
cd /home/fanghaizhou/project/model_manager
./pm2_start.sh
```

Restart:

```bash
./pm2_restart.sh
```

Stop and delete process:

```bash
./pm2_stop.sh
```

Tail logs:

```bash
./pm2_logs.sh 200
```

## PM2 auto-start on boot

```bash
cd /home/fanghaizhou/project/model_manager
./pm2_enable_startup.sh
```

Then run the `sudo ...` command printed by `pm2 startup`, and finally:

```bash
pm2 save
```

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

## gRPC

Proto file:

- `proto/model_manager.proto`

Primary method:

- `GetModel(GetModelRequest)`

Request fields:

- `model_name`
- `symbol`
- `group_key` (optional disambiguation)

Response includes:

- `model_json` (converted XGBoost json text)
- model metadata (time window, dim, train samples, etc.)
- per-dim mapping (`DimFactor`) with `factor_name` and `kendall_tau`

Secondary method:

- `ListSymbols(ListSymbolsRequest)`

## HTTP API summary

- `GET /api/auth/status`
- `POST /api/auth/bootstrap`
- `POST /api/auth/login`
- `GET /api/models`
- `POST /api/models`
- `POST /api/models/{model_name}/refresh`
- `GET /api/models/{model_name}/symbols`
- `GET /api/models/{model_name}/symbols/{symbol}?group_key=...`

All model endpoints require Bearer token from login.

## Env vars

- `MODEL_MANAGER_HTTP_HOST`
- `MODEL_MANAGER_HTTP_PORT`
- `MODEL_MANAGER_GRPC_HOST`
- `MODEL_MANAGER_GRPC_PORT`
- `MODEL_MANAGER_TOKEN_TTL`
- `MODEL_MANAGER_WATCH_ENABLED` (default `1`)
- `MODEL_MANAGER_WATCH_INTERVAL` (seconds, default `5`)
- `MODEL_MANAGER_WATCH_DEBOUNCE` (seconds, default `2`)

You can edit these in `ecosystem.config.js` for PM2-managed runs.
