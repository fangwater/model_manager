from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    frontend_dir: Path
    proto_dir: Path
    generated_proto_dir: Path
    http_host: str
    http_port: int
    grpc_host: str
    grpc_port: int
    token_ttl_seconds: int
    watch_enabled: bool
    watch_interval_seconds: int
    watch_debounce_seconds: int



def load_settings(base_dir: Path | None = None) -> Settings:
    root = base_dir or Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    frontend_dir = root / "frontend"
    proto_dir = root / "proto"
    generated_dir = root / "backend" / "generated"

    data_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        base_dir=root,
        data_dir=data_dir,
        db_path=data_dir / "model_manager.sqlite3",
        frontend_dir=frontend_dir,
        proto_dir=proto_dir,
        generated_proto_dir=generated_dir,
        http_host=os.getenv("MODEL_MANAGER_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("MODEL_MANAGER_HTTP_PORT", "18088")),
        grpc_host=os.getenv("MODEL_MANAGER_GRPC_HOST", "0.0.0.0"),
        grpc_port=int(os.getenv("MODEL_MANAGER_GRPC_PORT", "50061")),
        token_ttl_seconds=int(os.getenv("MODEL_MANAGER_TOKEN_TTL", "43200")),
        watch_enabled=os.getenv("MODEL_MANAGER_WATCH_ENABLED", "1") not in {"0", "false", "False"},
        watch_interval_seconds=int(os.getenv("MODEL_MANAGER_WATCH_INTERVAL", "5")),
        watch_debounce_seconds=int(os.getenv("MODEL_MANAGER_WATCH_DEBOUNCE", "2")),
    )
