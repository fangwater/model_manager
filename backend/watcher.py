from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from .db import RegisteredModel
from .parser import ARTIFACT_SUFFIXES
from .registry import ModelRegistry

LOG = logging.getLogger("model_manager.watcher")

WATCH_SUFFIXES = tuple(ARTIFACT_SUFFIXES.values())


@dataclass
class _PendingRefresh:
    fingerprint: str
    first_seen_at: float


@dataclass
class _WatchState:
    stable_fingerprint: str | None = None
    pending: _PendingRefresh | None = None



def _fingerprint_model_root(root_path: str) -> str:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return "missing"

    hasher = hashlib.sha256()
    count = 0
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        if not file_path.name.endswith(WATCH_SUFFIXES):
            continue
        try:
            stat = file_path.stat()
        except FileNotFoundError:
            continue
        rel = file_path.relative_to(root)
        hasher.update(str(rel).encode("utf-8"))
        hasher.update(b"|")
        hasher.update(str(stat.st_size).encode("ascii"))
        hasher.update(b"|")
        hasher.update(str(stat.st_mtime_ns).encode("ascii"))
        hasher.update(b"\n")
        count += 1

    hasher.update(f"count={count}".encode("ascii"))
    return hasher.hexdigest()


class ModelWatcher:
    def __init__(
        self,
        registry: ModelRegistry,
        interval_seconds: int = 5,
        debounce_seconds: int = 2,
    ) -> None:
        self.registry = registry
        self.interval_seconds = max(1, int(interval_seconds))
        self.debounce_seconds = max(1, int(debounce_seconds))
        self._states: dict[str, _WatchState] = {}
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop(), name="model-manager-watcher")
        LOG.info(
            "watcher started: interval=%ss debounce=%ss",
            self.interval_seconds,
            self.debounce_seconds,
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                # watcher task might already be cancelled by outer loop shutdown
                pass
            finally:
                self._task = None
        LOG.info("watcher stopped")

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            start = time.time()
            try:
                self._tick()
            except Exception as exc:
                LOG.warning("watch tick failed: %s", exc)

            elapsed = time.time() - start
            sleep_for = max(0.1, self.interval_seconds - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass

    def _tick(self) -> None:
        rows = self.registry.list_registered_models()
        active_names = {row.model_name for row in rows}

        for model_name in list(self._states.keys()):
            if model_name not in active_names:
                self._states.pop(model_name, None)

        now = time.time()
        for row in rows:
            self._tick_model(row=row, now=now)

    def _tick_model(self, row: RegisteredModel, now: float) -> None:
        model_name = row.model_name
        state = self._states.setdefault(model_name, _WatchState())

        current = _fingerprint_model_root(row.root_path)

        if state.stable_fingerprint is None:
            state.stable_fingerprint = current
            state.pending = None
            return

        if current == state.stable_fingerprint:
            state.pending = None
            return

        pending = state.pending
        if pending is None or pending.fingerprint != current:
            state.pending = _PendingRefresh(fingerprint=current, first_seen_at=now)
            return

        if now - pending.first_seen_at < self.debounce_seconds:
            return

        try:
            snapshot = self.registry.refresh_model(model_name)
        except Exception as exc:
            LOG.warning("watch refresh failed: model=%s err=%s", model_name, exc)
            return

        state.stable_fingerprint = current
        state.pending = None
        LOG.info(
            "watch refresh ok: model=%s symbols=%s groups=%s scanned_at=%s",
            model_name,
            snapshot.symbol_count,
            snapshot.group_count,
            snapshot.scanned_at,
        )
