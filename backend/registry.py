from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .convert_pkl_to_xgb import ModelConversionError, convert_pkl_to_xgb_json
from .convert_xgb_to_tl2cgen import ModelCompileError, convert_xgb_json_to_tl2cgen_so
from .db import Database, RegisteredModel
from .parser import ModelSnapshot, SymbolRecord, load_model_json_text, scan_model_root


class ModelRegistryError(Exception):
    pass


class ModelNotFound(ModelRegistryError):
    pass


class SymbolNotFound(ModelRegistryError):
    pass


def _safe_file_token(raw: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", raw.strip())
    token = token.strip("._-")
    return token or "model"


class ModelRegistry:
    def __init__(self, db: Database, converted_model_dir: Path | str | None = None) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._cache: dict[str, ModelSnapshot] = {}
        if converted_model_dir is None:
            self._converted_model_dir = (Path(__file__).resolve().parents[1] / "data" / "converted_models")
        else:
            self._converted_model_dir = Path(converted_model_dir).expanduser().resolve()
        self._converted_model_dir.mkdir(parents=True, exist_ok=True)

    def warmup(self) -> None:
        for item in self.db.list_models():
            self._refresh_model_from_row(item, raise_on_error=False)

    def list_registered_models(self) -> list[RegisteredModel]:
        return self.db.list_models()

    def _refresh_model_from_row(self, row: RegisteredModel, raise_on_error: bool) -> None:
        try:
            snapshot = scan_model_root(row.model_name, row.root_path)
            self._assert_unique_symbols(snapshot)
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
        self._assert_unique_symbols(snapshot)
        self.db.upsert_model(name, snapshot.root_path)

        with self._lock:
            self._cache[name] = snapshot
        return snapshot

    def refresh_model(self, model_name: str) -> ModelSnapshot:
        row = self.db.get_model(model_name)
        if row is None:
            raise ModelNotFound(f"model not found: {model_name}")

        snapshot = scan_model_root(row.model_name, row.root_path)
        self._assert_unique_symbols(snapshot)
        self.db.upsert_model(row.model_name, row.root_path)
        with self._lock:
            self._cache[row.model_name] = snapshot
        return snapshot

    def delete_model(self, model_name: str) -> None:
        name = model_name.strip()
        if not name:
            raise ModelRegistryError("model_name must not be empty")

        deleted = self.db.delete_model(name)
        if not deleted:
            raise ModelNotFound(f"model not found: {name}")

        with self._lock:
            self._cache.pop(name, None)

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
        self._assert_unique_symbols(snapshot)
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

    def list_model_factors(self, model_name: str) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)

        factors: list[str] = []
        seen: set[str] = set()
        for record in snapshot.symbols:
            for raw_factor in record.factors:
                factor = str(raw_factor).strip()
                if not factor or factor in seen:
                    continue
                seen.add(factor)
                factors.append(factor)

        return {
            "model_name": snapshot.model_name,
            "scanned_at": snapshot.scanned_at,
            "symbol_count": snapshot.symbol_count,
            "group_count": snapshot.group_count,
            "factor_count": len(factors),
            "factors": factors,
        }

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

    def build_model_payload(self, model_name: str, symbol: str) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        record = self._select_unique_record(snapshot, symbol)

        if not record.feature_dim or not (
            record.artifacts.get("model_json") or record.artifacts.get("model_pkl")
        ):
            raise SymbolNotFound(
                f"symbol '{symbol}' in model '{model_name}' is not payload-ready "
                "(missing model json/model pkl or dim)"
            )

        model_json_path = self._resolve_model_json_path(snapshot, record)
        model_json_text = load_model_json_text(model_json_path)

        return {
            "model_name": snapshot.model_name,
            "root_path": snapshot.root_path,
            "scanned_at": snapshot.scanned_at,
            "symbol": record.symbol,
            "return_name": record.return_name,
            "feature_dim": record.feature_dim,
            "train_window_start_ts": record.train_window_start_ts,
            "train_window_end_ts": record.train_window_end_ts,
            "train_start_date": record.train_start_date,
            "train_end_date": record.train_end_date,
            "train_samples": record.train_samples,
            "train_time_sec": record.train_time_sec,
            "model_json": model_json_text,
            "model_json_path": model_json_path,
            "dim_factors": [asdict(item) for item in record.dim_factors],
        }

    def build_model_so_payload(self, model_name: str, symbol: str) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        record = self._select_unique_record(snapshot, symbol)

        if not record.feature_dim or not (
            record.artifacts.get("model_json") or record.artifacts.get("model_pkl")
        ):
            raise SymbolNotFound(
                f"symbol '{symbol}' in model '{model_name}' is not payload-ready "
                "(missing model json/model pkl or dim)"
            )

        model_json_path = Path(self._resolve_model_json_path(snapshot, record))
        model_so_path = self._build_converted_so_path(snapshot.model_name, record.group_key, model_json_path)
        try:
            converted = convert_xgb_json_to_tl2cgen_so(model_json_path, model_so_path)
        except ModelCompileError as exc:
            raise ModelRegistryError(
                f"failed to compile tl2cgen shared library for {record.group_key}: {exc}"
            ) from exc

        return {
            "model_name": snapshot.model_name,
            "root_path": snapshot.root_path,
            "scanned_at": snapshot.scanned_at,
            "symbol": record.symbol,
            "return_name": record.return_name,
            "feature_dim": record.feature_dim,
            "train_window_start_ts": record.train_window_start_ts,
            "train_window_end_ts": record.train_window_end_ts,
            "train_start_date": record.train_start_date,
            "train_end_date": record.train_end_date,
            "train_samples": record.train_samples,
            "train_time_sec": record.train_time_sec,
            "model_json_path": str(model_json_path),
            "model_so_path": str(converted),
            "model_so_sha256": self._sha256_file(converted),
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

        # 默认优先：payload可用 + train_end_date较新 + group_key字典序
        candidates.sort(
            key=lambda item: (
                int(item.grpc_ready),
                item.train_end_date or "",
                item.group_key,
            ),
            reverse=True,
        )
        return candidates[0]

    def _select_unique_record(self, snapshot: ModelSnapshot, symbol: str) -> SymbolRecord:
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
        if len(candidates) > 1:
            groups = ", ".join(sorted(item.group_key for item in candidates))
            raise SymbolNotFound(
                f"symbol '{normalized_symbol}' has multiple groups in model '{snapshot.model_name}' "
                f"({groups}); require unique symbol for model payload API"
            )
        return candidates[0]

    def _assert_unique_symbols(self, snapshot: ModelSnapshot) -> None:
        symbol_groups: dict[str, set[str]] = {}
        for record in snapshot.symbols:
            normalized_symbol = record.symbol.strip().upper()
            if not normalized_symbol:
                continue
            groups = symbol_groups.setdefault(normalized_symbol, set())
            groups.add(record.group_key)

        duplicates = [
            (symbol, sorted(groups))
            for symbol, groups in symbol_groups.items()
            if len(groups) > 1
        ]
        if not duplicates:
            return

        duplicates.sort(key=lambda item: item[0])
        details = "; ".join(
            f"{symbol}: {', '.join(groups)}"
            for symbol, groups in duplicates[:8]
        )
        if len(duplicates) > 8:
            details = f"{details}; ... ({len(duplicates)} duplicated symbols total)"

        raise ModelRegistryError(
            f"symbol must be unique per model root, duplicated symbols found in "
            f"model '{snapshot.model_name}': {details}"
        )

    def _resolve_model_json_path(self, snapshot: ModelSnapshot, record: SymbolRecord) -> str:
        model_json_meta = record.artifacts.get("model_json")
        if model_json_meta is not None:
            model_json_path = Path(model_json_meta.path).expanduser().resolve()
            if model_json_path.exists():
                return str(model_json_path)

        model_pkl_meta = record.artifacts.get("model_pkl")
        if model_pkl_meta is None:
            raise SymbolNotFound(f"model json/model pkl path missing for {record.group_key}")

        model_pkl_path = Path(model_pkl_meta.path).expanduser().resolve()
        if not model_pkl_path.exists():
            raise SymbolNotFound(f"model pkl path missing for {record.group_key}")

        target_path = self._build_converted_json_path(snapshot.model_name, record.group_key, model_pkl_path)
        try:
            converted = convert_pkl_to_xgb_json(model_pkl_path, target_path)
        except ModelConversionError as exc:
            raise SymbolNotFound(f"failed to convert model.pkl for {record.group_key}: {exc}") from exc

        return str(converted)

    def _build_converted_json_path(self, model_name: str, group_key: str, model_pkl_path: Path) -> Path:
        model_dir = self._converted_model_dir / _safe_file_token(model_name)
        digest = hashlib.sha1(str(model_pkl_path).encode("utf-8")).hexdigest()[:12]
        file_name = f"{_safe_file_token(group_key)}.{digest}.model.json"
        return model_dir / file_name

    def _build_converted_so_path(self, model_name: str, group_key: str, model_json_path: Path) -> Path:
        model_dir = self._converted_model_dir / _safe_file_token(model_name)
        digest = hashlib.sha1(str(model_json_path).encode("utf-8")).hexdigest()[:12]
        file_name = f"{_safe_file_token(group_key)}.{digest}.model.so"
        return model_dir / file_name

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
