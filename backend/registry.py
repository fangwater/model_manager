from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .convert_pkl_to_xgb import ModelConversionError, convert_pkl_to_xgb_json
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
            self._sync_snapshot_factor_stats(snapshot)
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
        self._sync_snapshot_factor_stats(snapshot)

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
        self._sync_snapshot_factor_stats(snapshot)
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
        self._assert_unique_symbols(snapshot)
        self._sync_snapshot_factor_stats(snapshot)
        with self._lock:
            self._cache[row.model_name] = snapshot
        return snapshot

    def get_symbol_factor_stats(
        self,
        model_name: str,
        symbol: str,
        group_key: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        chosen = self._select_record(snapshot, symbol, group_key)
        factor_stats = self._get_or_init_factor_stats_for_record(snapshot, chosen)

        return {
            chosen.symbol: {
                "factor_names": factor_stats["factor_names"],
                "mean_values": factor_stats["mean_values"],
                "variance_values": factor_stats["variance_values"],
            }
        }

    def set_symbol_factor_stats(
        self,
        model_name: str,
        symbol: str,
        mean_values: list[float],
        variance_values: list[float],
        factor_names: list[str] | None = None,
        group_key: str | None = None,
    ) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        chosen = self._select_record(snapshot, symbol, group_key)
        expected_factor_names = [str(item.factor_name or "") for item in chosen.dim_factors]
        self._validate_symbol_stats_dim(chosen.feature_dim, len(expected_factor_names))
        factor_count = len(expected_factor_names)

        if factor_names is not None:
            provided_factor_names = [str(item) for item in factor_names]
            if len(provided_factor_names) != factor_count:
                raise ModelRegistryError(
                    f"factor_names length must match factor count={factor_count}, got {len(provided_factor_names)}"
                )
            for idx, expected_name in enumerate(expected_factor_names):
                if provided_factor_names[idx] != expected_name:
                    raise ModelRegistryError(
                        f"factor_names[{idx}] mismatch: expected '{expected_name}', got '{provided_factor_names[idx]}'"
                    )

        if len(mean_values) != factor_count or len(variance_values) != factor_count:
            raise ModelRegistryError(
                f"mean_values and variance_values must match factor count={factor_count}"
            )

        try:
            normalized_mean_values = [float(item) for item in mean_values]
            normalized_variance_values = [float(item) for item in variance_values]
        except (TypeError, ValueError) as exc:
            raise ModelRegistryError("mean_values/variance_values must be numeric arrays") from exc

        factor_mean_values = [list(normalized_mean_values) for _ in expected_factor_names]
        factor_variance_values = [list(normalized_variance_values) for _ in expected_factor_names]

        try:
            self.db.replace_symbol_factor_stats(
                model_name=snapshot.model_name,
                symbol=chosen.symbol,
                factor_names=expected_factor_names,
                factor_mean_values=factor_mean_values,
                factor_variance_values=factor_variance_values,
            )
        except ValueError as exc:
            raise ModelRegistryError(str(exc)) from exc

        return self.get_symbol_factor_stats(
            model_name=snapshot.model_name,
            symbol=chosen.symbol,
            group_key=chosen.group_key,
        )

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

    def build_model_payload(
        self,
        model_name: str,
        symbol: str,
    ) -> dict[str, Any]:
        snapshot = self.get_model_snapshot(model_name)
        record = self._select_unique_record(snapshot, symbol)
        if not record.grpc_ready:
            raise SymbolNotFound(
                f"symbol '{symbol}' in model '{model_name}' is not payload-ready "
                "(missing model json/model pkl or dim)"
            )

        model_json_path = self._resolve_model_json_path(snapshot, record)
        model_json_text = load_model_json_text(model_json_path)
        factor_stats = self._get_or_init_factor_stats_for_record(snapshot, record)

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
            "symbol_stats": {
                record.symbol: {
                    "factor_names": factor_stats["factor_names"],
                    "mean_values": factor_stats["mean_values"],
                    "variance_values": factor_stats["variance_values"],
                }
            },
            "factor_stats_updated_at": factor_stats["updated_at"],
        }

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

    def _sync_snapshot_factor_stats(self, snapshot: ModelSnapshot) -> None:
        for record in snapshot.symbols:
            factor_names = [str(item.factor_name or "") for item in record.dim_factors]
            self._validate_symbol_stats_dim(record.feature_dim, len(factor_names))
            self.db.sync_symbol_factor_stats(
                model_name=snapshot.model_name,
                symbol=record.symbol,
                factor_names=factor_names,
            )

    def _validate_symbol_stats_dim(self, feature_dim: int, factor_count: int) -> None:
        if int(feature_dim) != int(factor_count):
            raise ModelRegistryError(
                f"dimension mismatch: feature_dim={feature_dim}, factor_count={factor_count}"
            )

    def _get_or_init_factor_stats_for_record(
        self,
        snapshot: ModelSnapshot,
        record: SymbolRecord,
    ) -> dict[str, Any]:
        factor_names = [str(item.factor_name or "") for item in record.dim_factors]
        self._validate_symbol_stats_dim(record.feature_dim, len(factor_names))

        self.db.sync_symbol_factor_stats(
            model_name=snapshot.model_name,
            symbol=record.symbol,
            factor_names=factor_names,
        )
        rows = self.db.get_symbol_factor_stats(snapshot.model_name, record.symbol)
        if len(rows) != record.feature_dim:
            raise ModelRegistryError(
                f"factor stats row count mismatch: expected dim={record.feature_dim}, got {len(rows)}"
            )

        means: list[float] = []
        variances: list[float] = []
        latest_updated_at = snapshot.scanned_at
        expected_dim = record.feature_dim
        rows_by_index = sorted(rows, key=lambda item: int(item.factor_index))
        for row in rows:
            if len(row.mean_values) != expected_dim or len(row.variance_values) != expected_dim:
                raise ModelRegistryError(
                    f"factor '{row.factor_name}' vector length mismatch: "
                    f"mean_values={len(row.mean_values)}, variance_values={len(row.variance_values)}, "
                    f"expected={expected_dim}"
                )

            dim = int(row.factor_index)
            if dim < 0 or dim >= expected_dim:
                raise ModelRegistryError(
                    f"factor index out of range for '{row.factor_name}': index={dim}, expected 0..{expected_dim - 1}"
                )

            if row.updated_at > latest_updated_at:
                latest_updated_at = row.updated_at

        for expected_index, row in enumerate(rows_by_index):
            if int(row.factor_index) != expected_index:
                raise ModelRegistryError(
                    f"factor index mismatch: expected index={expected_index}, got {row.factor_index}"
                )
            means.append(float(row.mean_values[expected_index]))
            variances.append(float(row.variance_values[expected_index]))

        return {
            "factor_count": len(factor_names),
            "factor_names": list(factor_names),
            "mean_values": means,
            "variance_values": variances,
            "updated_at": latest_updated_at,
        }
