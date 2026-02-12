from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    db_path: Path
    converted_model_dir: Path
    frontend_dir: Path
    http_host: str
    http_port: int
    token_ttl_seconds: int
    watch_enabled: bool
    watch_interval_seconds: int
    watch_debounce_seconds: int



def load_settings(base_dir: Path | None = None) -> Settings:
    root = base_dir or Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    frontend_dir = root / "frontend"
    converted_model_dir = data_dir / "converted_models"

    data_dir.mkdir(parents=True, exist_ok=True)
    converted_model_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        base_dir=root,
        data_dir=data_dir,
        db_path=data_dir / "model_manager.sqlite3",
        converted_model_dir=converted_model_dir,
        frontend_dir=frontend_dir,
        http_host=os.getenv("MODEL_MANAGER_HTTP_HOST", "0.0.0.0"),
        http_port=int(os.getenv("MODEL_MANAGER_HTTP_PORT", "6300")),
        token_ttl_seconds=int(os.getenv("MODEL_MANAGER_TOKEN_TTL", "43200")),
        watch_enabled=os.getenv("MODEL_MANAGER_WATCH_ENABLED", "1") not in {"0", "false", "False"},
        watch_interval_seconds=int(os.getenv("MODEL_MANAGER_WATCH_INTERVAL", "5")),
        watch_debounce_seconds=int(os.getenv("MODEL_MANAGER_WATCH_DEBOUNCE", "2")),
    )
