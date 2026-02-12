from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Any

from .db import Database, RegisteredModel
from .parser import ModelSnapshot, SymbolRecord, load_model_json_text, scan_model_root


class ModelRegistryError(Exception):
    pass


class ModelNotFound(ModelRegistryError):
    pass


class SymbolNotFound(ModelRegistryError):
    pass


class ModelRegistry:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._cache: dict[str, ModelSnapshot] = {}

    def warmup(self) -> None:
        for item in self.db.list_models():
            self._refresh_model_from_row(item, raise_on_error=False)

    def list_registered_models(self) -> list[RegisteredModel]:
        return self.db.list_models()

    def _refresh_model_from_row(self, row: RegisteredModel, raise_on_error: bool) -> None:
        try:
            snapshot = scan_model_root(row.model_name, row.root_path)
        except Exception as exc:
            if raise_on_error:
                raise ModelRegistryError(str(exc)) from exc
            # Keep soft-fail warning snapshot for visibility.
            snapshot = ModelSnapshot(
                model_name=row.model_name,
                root_path=row.root_path,
                scanned_at=row.updated_at,
                symbol_count=0,
                group_count=0,
                warnings=[f"scan failed: {exc}"],
                symbols=[],
            )

        with self._lock:
            self._cache[row.model_name] = snapshot

    def add_or_refresh_model(self, model_name: str, root_path: str) -> ModelSnapshot:
        name = model_name.strip()
        if not name:
            raise ModelRegistryError("model_name must not be empty")

        path = root_path.strip()
        if not path:
            raise ModelRegistryError("root_path must not be empty")

        snapshot = scan_model_root(name, path)
        self.db.upsert_model(name, snapshot.root_path)

        with self._lock:
            self._cache[name] = snapshot
        return snapshot

    def refresh_model(self, model_name: str) -> ModelSnapshot:
        row = self.db.get_model(model_name)
        if row is None:
            raise ModelNotFound(f"model not found: {model_name}")

        snapshot = scan_model_root(row.model_name, row.root_path)
        self.db.upsert_model(row.model_name, row.root_path)
        with self._lock:
            self._cache[row.model_name] = snapshot
        return snapshot

    def list_models(self) -> list[dict[str, Any]]:
        rows = self.db.list_models()
        output: list[dict[str, Any]] = []
        with self._lock:
            for row in rows:
                snapshot = self._cache.get(row.model_name)
                output.append(
                    {
                        "model_name": row.model_name,
                        "root_path": row.root_path,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                        "symbol_count": snapshot.symbol_count if snapshot else 0,
                        "group_count": snapshot.group_count if snapshot else 0,
                        "scanned_at": snapshot.scanned_at if snapshot else None,
                        "warnings": list(snapshot.warnings) if snapshot else [],
                    }
                )
        return output

    def get_model_snapshot(self, model_name: str) -> ModelSnapshot:
        with self._lock:
            snapshot = self._cache.get(model_name)
        if snapshot is not None:
            return snapshot

        row = self.db.get_model(model_name)
        if row is None:
            raise ModelNotFound(f"model not found: {model_name}")

        snapshot = scan_model_root(row.model_name, row.root_path)
        with self._lock:
            self._cache[row.model_name] = snapshot
        return snapshot

    def list_symbols(self, model_name: str) -> list[dict[str, Any]]:
        snapshot = self.get_model_snapshot(model_name)
        out: list[dict[str, Any]] = []
        for record in snapshot.symbols:
            out.append(
                {
                    "symbol": record.symbol,
                    "group_key": record.group_key,
                    "return_name": record.return_name,
                    "feature_dim": record.feature_dim,
                    "factor_count": record.factor_count,
                    "grpc_ready": record.grpc_ready,
                    "train_start_date": record.train_start_date,
                    "train_end_date": record.train_end_date,
                    "warnings": list(record.warnings),
                }
            )
        return out

    def get_symbol_detail(
        self,
        model_name: str,
        symbol: str,
        group_key: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        chosen = self._select_record(snapshot, symbol, group_key)
        return {
            "model_name": snapshot.model_name,
            "root_path": snapshot.root_path,
            "scanned_at": snapshot.scanned_at,
            "symbol": chosen.symbol,
            "group_key": chosen.group_key,
            "return_name": chosen.return_name,
            "feature_dim": chosen.feature_dim,
            "factor_count": chosen.factor_count,
            "grpc_ready": chosen.grpc_ready,
            "train_window_start_ts": chosen.train_window_start_ts,
            "train_window_end_ts": chosen.train_window_end_ts,
            "train_start_date": chosen.train_start_date,
            "train_end_date": chosen.train_end_date,
            "train_samples": chosen.train_samples,
            "train_time_sec": chosen.train_time_sec,
            "factors": list(chosen.factors),
            "dim_factors": [asdict(item) for item in chosen.dim_factors],
            "ic_rows": list(chosen.ic_rows),
            "info_summary": dict(chosen.info_summary),
            "model_meta": dict(chosen.model_meta),
            "artifacts": {k: asdict(v) for k, v in chosen.artifacts.items()},
            "warnings": list(chosen.warnings),
        }

    def build_grpc_payload(
        self,
        model_name: str,
        symbol: str,
        group_key: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        record = self._select_record(snapshot, symbol, group_key)
        if not record.grpc_ready:
            raise SymbolNotFound(
                f"symbol '{symbol}' in model '{model_name}' is not gRPC ready (missing model json or dim)"
            )

        model_json_meta = record.artifacts.get("model_json")
        if model_json_meta is None:
            raise SymbolNotFound(f"model json path missing for {record.group_key}")

        model_json_text = load_model_json_text(model_json_meta.path)

        return {
            "model_name": snapshot.model_name,
            "root_path": snapshot.root_path,
            "scanned_at": snapshot.scanned_at,
            "symbol": record.symbol,
            "group_key": record.group_key,
            "return_name": record.return_name,
            "feature_dim": record.feature_dim,
            "train_window_start_ts": record.train_window_start_ts,
            "train_window_end_ts": record.train_window_end_ts,
            "train_start_date": record.train_start_date,
            "train_end_date": record.train_end_date,
            "train_samples": record.train_samples,
            "train_time_sec": record.train_time_sec,
            "model_json": model_json_text,
            "model_json_path": model_json_meta.path,
            "dim_factors": [asdict(item) for item in record.dim_factors],
        }

    def _select_record(
        self,
        snapshot: ModelSnapshot,
        symbol: str,
        group_key: str | None,
    ) -> SymbolRecord:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise SymbolNotFound("symbol must not be empty")

        candidates = [
            record
            for record in snapshot.symbols
            if record.symbol.strip().upper() == normalized_symbol
        ]
        if not candidates:
            raise SymbolNotFound(
                f"symbol '{normalized_symbol}' not found in model '{snapshot.model_name}'"
            )

        if group_key:
            wanted = group_key.strip()
            for record in candidates:
                if record.group_key == wanted:
                    return record
            raise SymbolNotFound(
                f"group_key '{group_key}' not found for symbol '{normalized_symbol}'"
            )

        # 默认优先：gRPC可用 + train_end_date较新 + group_key字典序
        candidates.sort(
            key=lambda item: (
                int(item.grpc_ready),
                item.train_end_date or "",
                item.group_key,
            ),
            reverse=True,
        )
        return candidates[0]
