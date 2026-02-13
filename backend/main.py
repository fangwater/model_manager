from __future__ import annotations

import argparse
import asyncio
import logging

import uvicorn

from .config import load_settings
from .db import Database
from .registry import ModelRegistry
from .watcher import ModelWatcher
from .web import create_app


LOG = logging.getLogger("model_manager")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Model Manager server")
    parser.add_argument("--http-host", default="", help="HTTP listen host")
    parser.add_argument("--http-port", type=int, default=0, help="HTTP listen port")
    return parser.parse_args()


async def _stop_watcher(watcher: ModelWatcher | None) -> None:
    if watcher is None:
        return
    try:
        await watcher.stop()
    except asyncio.CancelledError:
        # shutdown path should be quiet on Ctrl+C
        LOG.info("watcher stop cancelled during shutdown")
    except Exception as exc:
        LOG.warning("watcher stop failed: %s", exc)


async def async_main(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = load_settings()
    http_host = args.http_host or settings.http_host
    http_port = args.http_port or settings.http_port

    db = Database(settings.db_path)
    db.initialize()

    registry = ModelRegistry(db, converted_model_dir=settings.converted_model_dir)
    registry.warmup()

    watcher = None
    if settings.watch_enabled:
        watcher = ModelWatcher(
            registry=registry,
            interval_seconds=settings.watch_interval_seconds,
            debounce_seconds=settings.watch_debounce_seconds,
        )
        await watcher.start()

    app = create_app(settings=settings, registry=registry)

    config = uvicorn.Config(app=app, host=http_host, port=http_port, log_level="info")
    server = uvicorn.Server(config)

    LOG.info("HTTP started at %s:%s", http_host, http_port)
    cancelled = False
    try:
        await server.serve()
    except asyncio.CancelledError:
        cancelled = True
        LOG.info("Shutdown requested")
    finally:
        await _stop_watcher(watcher)

    if cancelled:
        return 130
    return 0


def main() -> None:
    args = parse_args()
    try:
        code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        # Avoid noisy traceback on manual Ctrl+C.
        raise SystemExit(130)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
