#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


def _resolve_base_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _remove_tree(path: Path) -> bool:
    if not path.exists():
        return False
    shutil.rmtree(path)
    return True


def main() -> int:
    base_dir = _resolve_base_dir()
    data_dir = base_dir / "data"

    print(f"[INFO] base_dir={base_dir}")
    print(f"[INFO] data_dir={data_dir}")
    data_deleted = _remove_tree(data_dir)

    # Ensure startup path can recreate/load required runtime dirs immediately.
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "converted_models").mkdir(parents=True, exist_ok=True)

    print(f"[OK] cleanup complete: data_deleted={data_deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
