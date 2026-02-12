from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from types import ModuleType


class ProtoGenerationError(RuntimeError):
    pass


PROTO_FILE_NAME = "model_manager.proto"
PB2_FILE_NAME = "model_manager_pb2.py"
PB2_GRPC_FILE_NAME = "model_manager_pb2_grpc.py"



def ensure_proto_modules(proto_dir: Path, generated_dir: Path) -> tuple[ModuleType, ModuleType]:
    proto_path = proto_dir / PROTO_FILE_NAME
    if not proto_path.exists():
        raise ProtoGenerationError(f"proto file missing: {proto_path}")

    generated_dir.mkdir(parents=True, exist_ok=True)

    pb2_path = generated_dir / PB2_FILE_NAME
    pb2_grpc_path = generated_dir / PB2_GRPC_FILE_NAME

    regenerate = False
    if not pb2_path.exists() or not pb2_grpc_path.exists():
        regenerate = True
    else:
        proto_mtime = proto_path.stat().st_mtime
        regenerate = pb2_path.stat().st_mtime < proto_mtime or pb2_grpc_path.stat().st_mtime < proto_mtime

    if regenerate:
        _generate(proto_path=proto_path, proto_dir=proto_dir, output_dir=generated_dir)

    generated_dir_str = str(generated_dir)
    if generated_dir_str not in sys.path:
        sys.path.insert(0, generated_dir_str)

    try:
        pb2 = importlib.import_module("model_manager_pb2")
        pb2_grpc = importlib.import_module("model_manager_pb2_grpc")
    except Exception as exc:
        raise ProtoGenerationError(f"failed to import generated proto modules: {exc}") from exc

    return pb2, pb2_grpc



def _generate(proto_path: Path, proto_dir: Path, output_dir: Path) -> None:
    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={output_dir}",
        f"--grpc_python_out={output_dir}",
        str(proto_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        stdout = proc.stdout.strip()
        combined = "\n".join(part for part in [stdout, stderr] if part)
        raise ProtoGenerationError(
            "protobuf generation failed. "
            "Please install dependencies: pip install grpcio grpcio-tools. "
            f"Details: {combined}"
        )
