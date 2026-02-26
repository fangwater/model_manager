from __future__ import annotations

import argparse
import os
import pickle
import tempfile
from pathlib import Path
from typing import Any


class ModelConversionError(Exception):
    pass


def _load_pickle(path: Path) -> Any:
    try:
        with path.open("rb") as fh:
            return pickle.load(fh)
    except Exception as exc:
        raise ModelConversionError(f"failed to load pickle '{path}': {exc}") from exc


def _resolve_savable_model(obj: Any) -> Any:
    # 优先提取原生 Booster，避免 sklearn wrapper 的兼容性问题
    getter = getattr(obj, "get_booster", None)
    if callable(getter):
        try:
            booster = getter()
        except Exception as exc:
            raise ModelConversionError(f"get_booster failed: {exc}") from exc
        if booster is not None:
            saver = getattr(booster, "save_model", None)
            if callable(saver):
                return booster

    for attr in ("_Booster", "booster"):
        booster = getattr(obj, attr, None)
        if booster is not None:
            saver = getattr(booster, "save_model", None)
            if callable(saver):
                return booster

    # fallback: 对象本身
    saver = getattr(obj, "save_model", None)
    if callable(saver):
        return obj

    raise ModelConversionError(
        f"unsupported pickle payload type: {type(obj).__name__}; expected xgboost model/booster"
    )


def convert_pkl_to_xgb_json(
    model_pkl_path: str | Path,
    model_json_path: str | Path,
    *,
    force: bool = False,
) -> Path:
    source = Path(model_pkl_path).expanduser().resolve()
    target = Path(model_json_path).expanduser().resolve()

    if not source.exists() or not source.is_file():
        raise ModelConversionError(f"model.pkl not found: {source}")

    if not force and target.exists() and target.is_file():
        if target.stat().st_size > 0 and target.stat().st_mtime >= source.stat().st_mtime:
            return target

    target.parent.mkdir(parents=True, exist_ok=True)

    payload = _load_pickle(source)
    savable = _resolve_savable_model(payload)

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp.json",
        dir=str(target.parent),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        savable.save_model(str(tmp_path))
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise ModelConversionError(f"xgboost save_model produced empty file: {tmp_path}")
        tmp_path.replace(target)
    except Exception as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        if isinstance(exc, ModelConversionError):
            raise
        raise ModelConversionError(f"failed to convert '{source}' -> '{target}': {exc}") from exc

    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert xgboost model.pkl to model.json")
    parser.add_argument("--input", required=True, help="path to *_model.pkl")
    parser.add_argument(
        "--output",
        default="",
        help="path to output json (default: same dir/same stem with .json)",
    )
    parser.add_argument("--force", action="store_true", help="force reconvert even when output is newer")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source = Path(args.input).expanduser().resolve()
    target = Path(args.output).expanduser().resolve() if args.output else source.with_suffix(".json")
    try:
        output = convert_pkl_to_xgb_json(source, target, force=args.force)
    except ModelConversionError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
