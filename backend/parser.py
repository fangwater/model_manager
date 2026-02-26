from __future__ import annotations

import csv
import json
import pickle
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_SUFFIXES: dict[str, str] = {
    "factors_txt": "_factors.txt",
    "ic_csv": "_ic.csv",
    "info_pkl": "_info.pkl",
    "model_pkl": "_model.pkl",
    "model_json": "_model.json",
    "model_onnx": "_model.onnx",
}


@dataclass
class ArtifactFileMeta:
    path: str
    size_bytes: int
    modified_at: str


@dataclass
class DimFactor:
    dim: int
    factor_name: str
    kendall_tau: float | None


@dataclass
class SymbolRecord:
    symbol: str
    group_key: str
    return_name: str
    feature_dim: int
    factor_count: int
    grpc_ready: bool
    train_window_start_ts: int | None
    train_window_end_ts: int | None
    train_start_date: str | None
    train_end_date: str | None
    train_samples: int | None
    train_time_sec: float | None
    factors: list[str]
    dim_factors: list[DimFactor]
    ic_rows: list[dict[str, Any]]
    info_summary: dict[str, Any]
    model_meta: dict[str, Any]
    artifacts: dict[str, ArtifactFileMeta]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["dim_factors"] = [asdict(item) for item in self.dim_factors]
        return raw


@dataclass
class ModelSnapshot:
    model_name: str
    root_path: str
    scanned_at: str
    symbol_count: int
    group_count: int
    warnings: list[str]
    symbols: list[SymbolRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "root_path": self.root_path,
            "scanned_at": self.scanned_at,
            "symbol_count": self.symbol_count,
            "group_count": self.group_count,
            "warnings": list(self.warnings),
            "symbols": [item.to_dict() for item in self.symbols],
        }



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()



def _safe_float(raw: Any) -> float | None:
    try:
        if raw is None or raw == "":
            return None
        return float(raw)
    except Exception:
        return None



def _safe_int(raw: Any) -> int | None:
    try:
        if raw is None or raw == "":
            return None
        return int(raw)
    except Exception:
        return None



def _as_iso(raw: Any) -> str | None:
    if raw is None:
        return None
    if hasattr(raw, "isoformat"):
        try:
            return str(raw.isoformat())
        except Exception:
            pass
    return str(raw)



def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            return str(value)
    if hasattr(value, "isoformat"):
        return _as_iso(value)
    return str(value)



def _file_meta(path: Path | None) -> ArtifactFileMeta | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc).replace(microsecond=0)
    return ArtifactFileMeta(
        path=str(path),
        size_bytes=int(stat.st_size),
        modified_at=modified.isoformat(),
    )



def _parse_factors_txt(path: Path | None) -> tuple[list[str], list[str]]:
    if path is None or not path.exists():
        return [], []

    warnings: list[str] = []
    factors: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.strip()
        if not name:
            continue
        factors.append(name)

    if not factors:
        warnings.append(f"{path.name} exists but has no non-empty factor rows")
    return factors, warnings



def _parse_ic_csv(path: Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    if path is None or not path.exists():
        return [], []

    warnings: list[str] = []
    rows: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            factor_name = (raw.get("factor_name") or "").strip()
            symbol = (raw.get("symbol") or "").strip()
            return_name = (raw.get("return_name") or "").strip()
            kendall_tau = _safe_float(raw.get("Kendall_tau"))
            rows.append(
                {
                    "symbol": symbol,
                    "factor_name": factor_name,
                    "return_name": return_name,
                    "Kendall_tau": kendall_tau,
                }
            )

    if not rows:
        warnings.append(f"{path.name} exists but has no IC rows")
    return rows, warnings



def _parse_info_pkl(path: Path | None) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], list[str]]:
    if path is None or not path.exists():
        return {}, [], [], []

    warnings: list[str] = []
    selected_factors: list[str] = []
    ic_rows: list[dict[str, Any]] = []

    try:
        with path.open("rb") as fh:
            obj = pickle.load(fh)
    except Exception as exc:
        warnings.append(f"failed to parse {path.name}: {exc}")
        return {}, [], [], warnings

    if not isinstance(obj, dict):
        warnings.append(f"{path.name} payload is not dict: {type(obj).__name__}")
        return {"raw_type": str(type(obj).__name__)}, [], [], warnings

    selected_raw = obj.get("selected_factors") or []
    for item in selected_raw:
        if item is None:
            continue
        selected_factors.append(str(item))

    ic_df = obj.get("ic_df")
    if ic_df is not None and hasattr(ic_df, "to_dict"):
        try:
            records = ic_df.to_dict(orient="records")
            for record in records:
                ic_rows.append(
                    {
                        "symbol": str(record.get("symbol", "")),
                        "factor_name": str(record.get("factor_name", "")),
                        "return_name": str(record.get("return_name", "")),
                        "Kendall_tau": _safe_float(record.get("Kendall_tau")),
                    }
                )
        except Exception as exc:
            warnings.append(f"failed to decode ic_df from {path.name}: {exc}")

    train_window = obj.get("train_window")
    train_start_ts = None
    train_end_ts = None
    if isinstance(train_window, (tuple, list)) and len(train_window) >= 2:
        train_start_ts = _safe_int(train_window[0])
        train_end_ts = _safe_int(train_window[1])

    info_summary = {
        "symbol": _jsonable(obj.get("symbol")),
        "return_name": _jsonable(obj.get("return_name")),
        "train_window_start_ts": train_start_ts,
        "train_window_end_ts": train_end_ts,
        "train_start_date": _as_iso(obj.get("train_start_date")),
        "train_end_date": _as_iso(obj.get("train_end_date")),
        "train_samples": _safe_int(obj.get("train_samples")),
        "original_factors_count": _safe_int(obj.get("original_factors_count")),
        "ic_filtered_count": _safe_int(obj.get("ic_filtered_count")),
        "final_factors_count": _safe_int(obj.get("final_factors_count")),
        "selected_factors_count": len(selected_factors),
        "train_time_sec": _safe_float(obj.get("train_time")),
        "config": _jsonable(obj.get("config")),
        "feature_importance": _jsonable(obj.get("feature_importance")),
    }

    return info_summary, selected_factors, ic_rows, warnings



def _parse_model_json(path: Path | None) -> tuple[dict[str, Any], list[str]]:
    if path is None or not path.exists():
        return {}, []

    warnings: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"failed to parse {path.name}: {exc}")
        return {}, warnings

    learner = payload.get("learner") or {}
    model_param = learner.get("learner_model_param") or {}
    objective = (learner.get("objective") or {}).get("name")
    booster_meta = ((learner.get("gradient_booster") or {}).get("model") or {}).get(
        "gbtree_model_param"
    ) or {}

    feature_dim = _safe_int(model_param.get("num_feature"))
    model_meta = {
        "feature_dim": feature_dim or 0,
        "objective": objective,
        "num_trees": _safe_int(booster_meta.get("num_trees")),
        "num_parallel_tree": _safe_int(booster_meta.get("num_parallel_tree")),
        "version": _jsonable(payload.get("version")),
    }
    return model_meta, warnings



def _derive_symbol(group_key: str) -> str:
    head, *_ = group_key.split("_", maxsplit=1)
    return head



def _derive_return_name(group_key: str) -> str:
    parts = group_key.split("_", maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1]



def scan_model_root(model_name: str, root_path: str) -> ModelSnapshot:
    root = Path(root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"model root path not found or not directory: {root}")

    grouped: dict[str, dict[str, Path]] = defaultdict(dict)
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        file_name = file_path.name
        for kind, suffix in ARTIFACT_SUFFIXES.items():
            if file_name.endswith(suffix):
                grouped[file_name[: -len(suffix)]][kind] = file_path
                break

    records: list[SymbolRecord] = []
    scan_warnings: list[str] = []

    for group_key in sorted(grouped.keys()):
        file_map = grouped[group_key]

        factors, factor_warn = _parse_factors_txt(file_map.get("factors_txt"))
        ic_rows_csv, ic_warn = _parse_ic_csv(file_map.get("ic_csv"))
        info_summary, factors_info, ic_rows_info, info_warn = _parse_info_pkl(file_map.get("info_pkl"))
        model_meta, model_warn = _parse_model_json(file_map.get("model_json"))

        warnings = [*factor_warn, *ic_warn, *info_warn, *model_warn]

        if not factors and factors_info:
            factors = list(factors_info)
        ic_rows = ic_rows_csv if ic_rows_csv else ic_rows_info

        symbol = str(info_summary.get("symbol") or "").strip()
        if not symbol and ic_rows:
            symbol = str(ic_rows[0].get("symbol") or "").strip()
        if not symbol:
            symbol = _derive_symbol(group_key)

        return_name = str(info_summary.get("return_name") or "").strip()
        if not return_name and ic_rows:
            return_name = str(ic_rows[0].get("return_name") or "").strip()
        if not return_name:
            return_name = _derive_return_name(group_key)

        feature_dim = int(model_meta.get("feature_dim") or 0)
        if feature_dim <= 0:
            feature_dim = len(factors)

        if feature_dim <= 0:
            warnings.append(f"{group_key}: feature dimension unresolved")

        if factors and feature_dim and len(factors) != feature_dim:
            warnings.append(
                f"{group_key}: factors count {len(factors)} differs from feature_dim {feature_dim}"
            )

        ic_by_factor: dict[str, float | None] = {
            str(row.get("factor_name") or ""): _safe_float(row.get("Kendall_tau"))
            for row in ic_rows
            if str(row.get("factor_name") or "")
        }

        dim_factors: list[DimFactor] = []
        for dim in range(feature_dim):
            factor_name = factors[dim] if dim < len(factors) else ""
            dim_factors.append(
                DimFactor(
                    dim=dim,
                    factor_name=factor_name,
                    kendall_tau=ic_by_factor.get(factor_name),
                )
            )

        artifacts: dict[str, ArtifactFileMeta] = {}
        for key, file_path in file_map.items():
            file_meta = _file_meta(file_path)
            if file_meta is not None:
                artifacts[key] = file_meta

        has_model_onnx = file_map.get("model_onnx") is not None and file_map["model_onnx"].exists()
        has_model_json = file_map.get("model_json") is not None and file_map["model_json"].exists()
        has_model_pkl = file_map.get("model_pkl") is not None and file_map["model_pkl"].exists()
        grpc_ready = (
            (has_model_onnx or has_model_json or has_model_pkl)
            and feature_dim > 0
            and bool(symbol)
        )

        record = SymbolRecord(
            symbol=symbol,
            group_key=group_key,
            return_name=return_name,
            feature_dim=feature_dim,
            factor_count=len(factors),
            grpc_ready=grpc_ready,
            train_window_start_ts=_safe_int(info_summary.get("train_window_start_ts")),
            train_window_end_ts=_safe_int(info_summary.get("train_window_end_ts")),
            train_start_date=_as_iso(info_summary.get("train_start_date")),
            train_end_date=_as_iso(info_summary.get("train_end_date")),
            train_samples=_safe_int(info_summary.get("train_samples")),
            train_time_sec=_safe_float(info_summary.get("train_time_sec")),
            factors=factors,
            dim_factors=dim_factors,
            ic_rows=ic_rows,
            info_summary=info_summary,
            model_meta=model_meta,
            artifacts=artifacts,
            warnings=warnings,
        )
        records.append(record)

        for warning in warnings:
            scan_warnings.append(f"{group_key}: {warning}")

    unique_symbols = sorted({record.symbol for record in records if record.symbol})

    return ModelSnapshot(
        model_name=model_name,
        root_path=str(root),
        scanned_at=utc_now_iso(),
        symbol_count=len(unique_symbols),
        group_count=len(records),
        warnings=scan_warnings,
        symbols=records,
    )



def load_model_json_text(model_json_path: str) -> str:
    path = Path(model_json_path)
    return path.read_text(encoding="utf-8")
