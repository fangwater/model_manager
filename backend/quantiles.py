from __future__ import annotations

import json
import logging
import pickle
import threading
from pathlib import Path
from typing import Any

import redis

from .db import Database

LOG = logging.getLogger("model_manager.quantiles")

VALID_VENUES: set[str] = {
    "binance-margin",
    "binance-futures",
    "okex-margin",
    "okex-futures",
    "bybit-margin",
    "bybit-futures",
    "bitget-margin",
    "bitget-futures",
    "gate-margin",
    "gate-futures",
}


class VenueNotFound(Exception):
    pass


class SymbolNotFound(Exception):
    pass


class InvalidVenue(Exception):
    pass


def _load_pkl(pkl_path: Path) -> dict[str, dict[str, float]]:
    with open(pkl_path, "rb") as f:
        raw: Any = pickle.load(f)

    result: dict[str, dict[str, float]] = {}

    if isinstance(raw, list):
        # list of dicts: [{"symbol": "BTCUSDT", "medium_notional_threshold": ..., "large_notional_threshold": ...}, ...]
        for item in raw:
            symbol = str(item["symbol"])
            result[symbol] = {
                "medium_notional_threshold": float(item["medium_notional_threshold"]),
                "large_notional_threshold": float(item["large_notional_threshold"]),
            }
    elif isinstance(raw, dict):
        # dict keyed by symbol: {"BTCUSDT": {"medium_notional_threshold": ..., "large_notional_threshold": ...}, ...}
        for symbol, values in raw.items():
            result[str(symbol)] = {
                "medium_notional_threshold": float(values["medium_notional_threshold"]),
                "large_notional_threshold": float(values["large_notional_threshold"]),
            }
    else:
        raise ValueError(f"unexpected pkl format: {type(raw)}")

    return result


class QuantilesStore:
    def __init__(self, db: Database, redis_host: str = "localhost", redis_port: int = 6379) -> None:
        self.db = db
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, dict[str, float]]] = {}
        self._pkl_paths: dict[str, str] = {}
        self._redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)

    def _sync_to_redis(self, venue: str, data: dict[str, dict[str, float]]) -> None:
        for symbol, values in data.items():
            key = f"{venue}:{symbol}:amount-threshold"
            value = json.dumps({"symbol": symbol, **values})
            try:
                self._redis.set(key, value)
            except Exception as exc:
                LOG.warning("failed to write Redis key %s: %s", key, exc)
        LOG.info("synced %d symbols to Redis for venue %s", len(data), venue)

    def warmup(self) -> None:
        for row in self.db.list_venue_quantiles():
            try:
                data = _load_pkl(Path(row.pkl_path))
                with self._lock:
                    self._cache[row.venue] = data
                    self._pkl_paths[row.venue] = row.pkl_path
                self._sync_to_redis(row.venue, data)
                LOG.info("loaded quantiles for venue %s: %d symbols", row.venue, len(data))
            except Exception as exc:
                LOG.warning("failed to load quantiles for venue %s: %s", row.venue, exc)

    def load_venue(self, venue: str, pkl_path: str) -> int:
        if venue not in VALID_VENUES:
            raise InvalidVenue(f"unknown venue: {venue}")

        path = Path(pkl_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"pkl file not found: {path}")

        data = _load_pkl(path)
        self.db.upsert_venue_quantiles(venue, str(path))

        with self._lock:
            self._cache[venue] = data
            self._pkl_paths[venue] = str(path)

        self._sync_to_redis(venue, data)
        LOG.info("loaded quantiles for venue %s: %d symbols", venue, len(data))
        return len(data)

    def get(self, venue: str, symbol: str) -> dict[str, float]:
        with self._lock:
            venue_data = self._cache.get(venue)
        if venue_data is None:
            raise VenueNotFound(f"venue not registered: {venue}")
        values = venue_data.get(symbol)
        if values is None:
            raise SymbolNotFound(f"symbol {symbol} not found in venue {venue}")
        return values

    def get_all(self, venue: str) -> dict[str, dict[str, float]]:
        with self._lock:
            venue_data = self._cache.get(venue)
        if venue_data is None:
            raise VenueNotFound(f"venue not registered: {venue}")
        return venue_data

    def list_venues(self) -> list[dict[str, str]]:
        rows = self.db.list_venue_quantiles()
        return [
            {"venue": row.venue, "pkl_path": row.pkl_path, "updated_at": row.updated_at}
            for row in rows
        ]
