from __future__ import annotations

import os
import tempfile
from pathlib import Path


class ModelOnnxConversionError(Exception):
    pass


def _load_xgboost_booster(model_json_path: Path):
    try:
        import xgboost as xgb  # type: ignore
    except Exception as exc:
        raise ModelOnnxConversionError(
            f"xgboost import failed, please install xgboost: {exc}"
        ) from exc

    booster = xgb.Booster()
    try:
        booster.load_model(str(model_json_path))
    except Exception as exc:
        raise ModelOnnxConversionError(
            f"failed to load xgboost model json '{model_json_path}': {exc}"
        ) from exc
    return booster


def _resolve_feature_dim(booster, expected_feature_dim: int | None) -> int:
    if expected_feature_dim is not None:
        if expected_feature_dim <= 0:
            raise ModelOnnxConversionError(
                f"invalid expected feature dim: {expected_feature_dim}"
            )
        return expected_feature_dim

    getter = getattr(booster, "num_features", None)
    if callable(getter):
        try:
            value = int(getter())
        except Exception as exc:
            raise ModelOnnxConversionError(f"booster.num_features() failed: {exc}") from exc
        if value > 0:
            return value

    raise ModelOnnxConversionError("cannot resolve feature dim from booster")


def convert_xgb_json_to_onnx(
    model_json_path: str | Path,
    model_onnx_path: str | Path,
    *,
    feature_dim: int | None = None,
    force: bool = False,
) -> Path:
    source = Path(model_json_path).expanduser().resolve()
    target = Path(model_onnx_path).expanduser().resolve()

    if not source.exists() or not source.is_file():
        raise ModelOnnxConversionError(f"xgboost model json not found: {source}")

    if not force and target.exists() and target.is_file():
        if target.stat().st_size > 0 and target.stat().st_mtime >= source.stat().st_mtime:
            return target

    booster = _load_xgboost_booster(source)
    resolved_dim = _resolve_feature_dim(booster, feature_dim)

    try:
        from onnxmltools.convert import convert_xgboost  # type: ignore
        from onnxconverter_common.data_types import FloatTensorType  # type: ignore
        import onnxmltools  # type: ignore
    except Exception as exc:
        raise ModelOnnxConversionError(
            "onnxmltools conversion dependencies missing; install onnxmltools onnx onnxconverter-common"
        ) from exc

    target.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp.onnx",
        dir=str(target.parent),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        onnx_model = convert_xgboost(
            booster,
            initial_types=[("input", FloatTensorType([1, resolved_dim]))],
        )
        onnxmltools.utils.save_model(onnx_model, str(tmp_path))

        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise ModelOnnxConversionError(f"onnxmltools produced empty ONNX file: {tmp_path}")

        tmp_path.replace(target)
    except Exception as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        if isinstance(exc, ModelOnnxConversionError):
            raise
        raise ModelOnnxConversionError(
            f"failed to convert xgboost json to onnx from '{source}' -> '{target}': {exc}"
        ) from exc

    return target
