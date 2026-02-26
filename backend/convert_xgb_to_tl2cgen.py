from __future__ import annotations

import logging
import os
import tempfile
import traceback
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelCompileError(Exception):
    pass


def _find_xgb_loader() -> callable:
    """Find a working load_xgboost_model function across treelite/tl2cgen versions."""
    candidates: list[tuple[str, callable]] = []

    # treelite.frontend.load_xgboost_model (treelite >= 4.x)
    try:
        import treelite  # type: ignore
        ver = getattr(treelite, "__version__", "unknown")
        logger.info("treelite version: %s", ver)
        frontend = getattr(treelite, "frontend", None)
        if frontend:
            fn = getattr(frontend, "load_xgboost_model", None)
            if callable(fn):
                candidates.append(("treelite.frontend.load_xgboost_model", fn))
        # older treelite: Model.load
        fn2 = getattr(getattr(treelite, "Model", None), "load", None)
        if callable(fn2):
            candidates.append(("treelite.Model.load", fn2))
    except ImportError:
        logger.info("treelite not installed")

    # tl2cgen.frontend.load_xgboost_model (older tl2cgen)
    try:
        import tl2cgen  # type: ignore
        frontend = getattr(tl2cgen, "frontend", None)
        if frontend:
            fn = getattr(frontend, "load_xgboost_model", None)
            if callable(fn):
                candidates.append(("tl2cgen.frontend.load_xgboost_model", fn))
    except ImportError:
        logger.info("tl2cgen not installed")

    if not candidates:
        raise ModelCompileError(
            "no xgboost model loader found; run 'pip install treelite tl2cgen'"
        )
    logger.info("loader candidates: %s", [c[0] for c in candidates])
    return candidates[0]


def _load_tl2cgen_model(model_json_path: Path) -> object:
    name, loader = _find_xgb_loader()
    logger.info("using loader: %s", name)

    kwargs = {}
    if "Model.load" in name:
        kwargs["model_format"] = "xgboost_json"

    try:
        return loader(str(model_json_path), **kwargs)
    except Exception as exc:
        logger.error(
            "%s raised %s for %s:\n%s",
            name, type(exc).__name__, model_json_path, traceback.format_exc(),
        )
        raise ModelCompileError(
            f"{name} failed for {model_json_path}: {exc}"
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
        import tl2cgen as _tl2cgen  # type: ignore
        _has_tl2cgen = True
    except ImportError:
        _has_tl2cgen = False

    try:
        import treelite as _treelite  # type: ignore
        _has_treelite_export = callable(getattr(_treelite, "export_lib", None))
    except ImportError:
        _has_treelite_export = False

    if not _has_tl2cgen and not _has_treelite_export:
        raise ModelCompileError(
            "no export_lib found; run 'pip install treelite tl2cgen'"
        )

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}.",
        suffix=".tmp.so",
        dir=str(target.parent),
    )
    os.close(tmp_fd)
    tmp_path = Path(tmp_name)

    try:
        # Prefer treelite.export_lib when available — its C++ compiler version
        # matches the Python package version, avoiding segfaults from version
        # mismatches between the model checkpoint and the tl2cgen bundled runtime.
        if _has_treelite_export:
            logger.info("compiling .so via treelite.export_lib (version %s)",
                        getattr(_treelite, "__version__", "?"))
            _treelite.export_lib(model, toolchain="gcc", libpath=str(tmp_path))
        else:
            logger.info("compiling .so via tl2cgen.export_lib")
            _tl2cgen.export_lib(model, toolchain="gcc", libpath=str(tmp_path))
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

