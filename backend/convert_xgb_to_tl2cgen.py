from __future__ import annotations

import os
import tempfile
from pathlib import Path


class ModelCompileError(Exception):
    pass


def _load_tl2cgen_model(model_json_path: Path) -> object:
    try:
        import tl2cgen  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ModelCompileError(
            "failed to import tl2cgen; run 'pip install tl2cgen' first"
        ) from exc

    frontend = getattr(tl2cgen, "frontend", None)
    if frontend is None:
        raise ModelCompileError("tl2cgen frontend module not found")

    loader = getattr(frontend, "load_xgboost_model", None)
    if not callable(loader):
        raise ModelCompileError("tl2cgen.frontend.load_xgboost_model is unavailable")

    try:
        return loader(str(model_json_path))
    except Exception as exc:
        raise ModelCompileError(
            f"load xgboost json for tl2cgen failed: {model_json_path}"
        ) from exc


def convert_xgb_json_to_tl2cgen_so(
    model_json_path: str | Path,
    model_so_path: str | Path,
    *,
    force: bool = False,
) -> Path:
    source = Path(model_json_path).expanduser().resolve()
    target = Path(model_so_path).expanduser().resolve()

    if not source.exists() or not source.is_file():
        raise ModelCompileError(f"xgboost model json not found: {source}")

    if not force and target.exists() and target.is_file():
        if target.stat().st_size > 0 and target.stat().st_mtime >= source.stat().st_mtime:
            return target

    target.parent.mkdir(parents=True, exist_ok=True)
    model = _load_tl2cgen_model(source)

    try:
        import tl2cgen  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise ModelCompileError(
            "failed to import tl2cgen; run 'pip install tl2cgen' first"
        ) from exc

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp.so",
        dir=str(target.parent),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        tl2cgen.export_lib(model, toolchain="gcc", libpath=str(tmp_path))
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise ModelCompileError(f"tl2cgen produced empty shared library: {tmp_path}")
        tmp_path.replace(target)
    except Exception as exc:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        if isinstance(exc, ModelCompileError):
            raise
        raise ModelCompileError(
            f"failed to compile tl2cgen .so from '{source}' -> '{target}': {exc}"
        ) from exc

    return target

