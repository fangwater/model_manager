from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from .auth import AuthManager
from .config import load_settings
from .db import Database
from .grpc_service import start_grpc_server
from .proto_loader import ProtoGenerationError, ensure_proto_modules
from .registry import ModelRegistry
from .watcher import ModelWatcher
from .web import create_app


LOG = logging.getLogger("model_manager")



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Model Manager server")
    parser.add_argument("--http-host", default="", help="HTTP listen host")
    parser.add_argument("--http-port", type=int, default=0, help="HTTP listen port")
    parser.add_argument("--grpc-host", default="", help="gRPC listen host")
    parser.add_argument("--grpc-port", type=int, default=0, help="gRPC listen port")
    parser.add_argument("--disable-grpc", action="store_true", help="Disable gRPC service")
    parser.add_argument(
        "--init-password",
        default="",
        help="Initialize password once and exit (fails if already initialized)",
    )
    parser.add_argument(
        "--set-password",
        default="",
        help="Force reset password and exit",
    )
    return parser.parse_args()


async def async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings()
    http_host = args.http_host or settings.http_host
    http_port = args.http_port or settings.http_port
    grpc_host = args.grpc_host or settings.grpc_host
    grpc_port = args.grpc_port or settings.grpc_port

    db = Database(settings.db_path)
    db.initialize()

    auth_manager = AuthManager(db=db, token_ttl_seconds=settings.token_ttl_seconds)

    if args.init_password:
        created = auth_manager.bootstrap_password(args.init_password)
        if not created:
            LOG.error("password is already initialized")
            return 2
        LOG.info("password initialized")
        return 0

    if args.set_password:
        auth_manager.set_password(args.set_password)
        LOG.info("password updated")
        return 0

    registry = ModelRegistry(db)
    registry.warmup()
    watcher = None
    if settings.watch_enabled:
        watcher = ModelWatcher(
            registry=registry,
            interval_seconds=settings.watch_interval_seconds,
            debounce_seconds=settings.watch_debounce_seconds,
        )
        await watcher.start()

    app = create_app(settings=settings, registry=registry, auth_manager=auth_manager)

    grpc_server = None
    if not args.disable_grpc:
        try:
            pb2, pb2_grpc = ensure_proto_modules(
                proto_dir=settings.proto_dir,
                generated_dir=settings.generated_proto_dir,
            )
            grpc_server = await start_grpc_server(
                registry=registry,
                pb2=pb2,
                pb2_grpc=pb2_grpc,
                host=grpc_host,
                port=grpc_port,
            )
            LOG.info("gRPC started at %s:%s", grpc_host, grpc_port)
        except ProtoGenerationError as exc:
            LOG.error("gRPC startup failed: %s", exc)
            return 3

    config = uvicorn.Config(app=app, host=http_host, port=http_port, log_level="info")
    server = uvicorn.Server(config)

    LOG.info("HTTP started at %s:%s", http_host, http_port)
    try:
        await server.serve()
    finally:
        if watcher is not None:
            await watcher.stop()
        if grpc_server is not None:
            await grpc_server.stop(grace=1)
            LOG.info("gRPC stopped")

    return 0



def main() -> None:
    args = parse_args()
    code = asyncio.run(async_main(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
