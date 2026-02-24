# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目简介

Python 服务（FastAPI + uvicorn），用于管理 XGBoost 模型产物。注册模型目录、解析产物文件、通过 HTTP 提供模型 JSON 和元数据，文件变更时自动刷新。前端为原生 JS（无构建步骤）。

## 常用命令

```bash
# 初始化环境
./setup.sh                    # 创建 .venv 并安装依赖

# 直接运行
./start_model_manager.sh      # 使用 .venv/bin/python -m model_manager

# 通过 PM2 运行
./start.sh                    # 以 PM2 启动（配置见 ecosystem.config.js）
./stop.sh                     # 停止 PM2 进程

# 覆盖 host/port
./start.sh --web-host 0.0.0.0 --web-port 18090
MODEL_MANAGER_HTTP_PORT=18090 ./start.sh
```

默认 HTTP 端口：`6300`。UI 在 `/`。

目前没有测试套件。

## 架构

入口：`__main__.py` → `backend/main.py:main()` → `async_main()`，依次初始化：
- `Settings`（读取环境变量，`backend/config.py`）
- `Database`（SQLite WAL 模式，`backend/db.py`）— 存储已注册模型
- `ModelRegistry`（`backend/registry.py`）— 线程安全（RLock）的模型缓存，扫描产物目录，构建 payload
- `ModelWatcher`（`backend/watcher.py`）— 异步文件监听，使用 SHA256 指纹检测变更
- `create_app()`（`backend/web.py`）— FastAPI 应用，定义所有 HTTP 端点

### 数据流

1. 用户通过 `POST /api/models` 注册模型目录
2. Registry 调用 `parser.py:scan_model_root()` 扫描目录，按 `group_key`（如 `SOLUSDT_mid_chg_1m`）分组产物文件
3. 每个分组生成一个 `SymbolRecord`，包含 symbol、factors、IC 表、训练信息
4. Pickle 模型通过 `convert_pkl_to_xgb.py` 自动转换为 XGBoost JSON（缓存在 `data/converted_models/`）
5. Watcher 轮询已注册路径，检测到文件变更后触发重新扫描

### 关键设计

- 线程安全：`Database` 和 `ModelRegistry` 均使用 `threading.RLock`
- 扫描容错：扫描失败时 registry 保留带警告的 snapshot，不会丢失可见性
- PYTHONPATH 设置为项目根目录的父目录（`start_model_manager.sh` 中 `PYTHONPATH="${ROOT_DIR}/.."`)

## 项目结构

```
backend/          Python 服务（FastAPI 端点、registry、DB、parser、watcher）
frontend/         原生 HTML/JS/CSS（index.html、app.js、styles.css）
data/             运行时数据（SQLite 数据库、转换后的模型）— gitignore
proto/            空目录（已移除的 gRPC 遗留）
```

## 依赖

Python 3，依赖：fastapi、uvicorn、pandas、xgboost（版本锁定在 `requirements.txt`）。生产部署使用 PM2 进程管理。
