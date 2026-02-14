from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class RegisteredModel:
    model_name: str
    root_path: str
    created_at: str
    updated_at: str


@dataclass
class SymbolFactorStatsRow:
    model_name: str
    symbol: str
    factor_index: int
    factor_name: str
    mean_value: float
    variance_value: float
    updated_at: str


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS auth_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    password_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS model_repo (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL UNIQUE,
                    root_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS symbol_factor_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    factor_index INTEGER NOT NULL,
                    factor_name TEXT NOT NULL,
                    mean_value REAL NOT NULL,
                    variance_value REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(model_name, symbol, factor_index)
                );

                CREATE INDEX IF NOT EXISTS idx_symbol_factor_stats_model_symbol
                ON symbol_factor_stats(model_name, symbol);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_password_hash(self) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT password_hash FROM auth_state WHERE id = 1").fetchone()
            return None if row is None else str(row["password_hash"])

    def set_password_hash(self, password_hash: str) -> None:
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_state(id, password_hash, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    updated_at = excluded.updated_at
                """,
                (password_hash, now),
            )
            conn.commit()

    def insert_password_hash_once(self, password_hash: str) -> bool:
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT 1 FROM auth_state WHERE id = 1").fetchone()
            if row is not None:
                return False

            conn.execute(
                "INSERT INTO auth_state(id, password_hash, updated_at) VALUES (1, ?, ?)",
                (password_hash, now),
            )
            conn.commit()
            return True

    def upsert_model(self, model_name: str, root_path: str) -> None:
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_repo(model_name, root_path, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model_name) DO UPDATE SET
                    root_path = excluded.root_path,
                    updated_at = excluded.updated_at
                """,
                (model_name, root_path, now, now),
            )
            conn.commit()

    def get_model(self, model_name: str) -> RegisteredModel | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT model_name, root_path, created_at, updated_at
                FROM model_repo
                WHERE model_name = ?
                """,
                (model_name,),
            ).fetchone()
            if row is None:
                return None
            return RegisteredModel(
                model_name=str(row["model_name"]),
                root_path=str(row["root_path"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

    def list_models(self) -> list[RegisteredModel]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model_name, root_path, created_at, updated_at
                FROM model_repo
                ORDER BY model_name ASC
                """
            ).fetchall()
        return [
            RegisteredModel(
                model_name=str(row["model_name"]),
                root_path=str(row["root_path"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [item.__dict__.copy() for item in self.list_models()]

    def sync_symbol_factor_stats(
        self,
        model_name: str,
        symbol: str,
        factor_names: list[str],
        default_mean: float = 0.0,
        default_variance: float = 1.0,
    ) -> None:
        now = utc_now_iso()
        normalized_model = model_name.strip()
        normalized_symbol = symbol.strip().upper()
        safe_default_mean = _safe_float64(default_mean)
        safe_default_variance = _safe_float64(default_variance)

        if not normalized_model or not normalized_symbol:
            return

        with self._lock, self._connect() as conn:
            existing_rows = conn.execute(
                """
                SELECT factor_index, factor_name
                FROM symbol_factor_stats
                WHERE model_name = ? AND symbol = ?
                ORDER BY factor_index ASC
                """,
                (normalized_model, normalized_symbol),
            ).fetchall()
            existing_by_index = {int(row["factor_index"]): str(row["factor_name"]) for row in existing_rows}

            for idx, raw_name in enumerate(factor_names):
                factor_name = str(raw_name or "")
                existing_name = existing_by_index.get(idx)
                if existing_name is None:
                    conn.execute(
                        """
                        INSERT INTO symbol_factor_stats(
                            model_name, symbol, factor_index, factor_name,
                            mean_value, variance_value, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            normalized_model,
                            normalized_symbol,
                            idx,
                            factor_name,
                            safe_default_mean,
                            safe_default_variance,
                            now,
                        ),
                    )
                    continue

                if existing_name != factor_name:
                    conn.execute(
                        """
                        UPDATE symbol_factor_stats
                        SET factor_name = ?, updated_at = ?
                        WHERE model_name = ? AND symbol = ? AND factor_index = ?
                        """,
                        (
                            factor_name,
                            now,
                            normalized_model,
                            normalized_symbol,
                            idx,
                        ),
                    )

            conn.execute(
                """
                DELETE FROM symbol_factor_stats
                WHERE model_name = ? AND symbol = ? AND factor_index >= ?
                """,
                (normalized_model, normalized_symbol, len(factor_names)),
            )
            conn.commit()

    def get_symbol_factor_stats(self, model_name: str, symbol: str) -> list[SymbolFactorStatsRow]:
        normalized_model = model_name.strip()
        normalized_symbol = symbol.strip().upper()
        if not normalized_model or not normalized_symbol:
            return []

        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model_name, symbol, factor_index, factor_name, mean_value, variance_value, updated_at
                FROM symbol_factor_stats
                WHERE model_name = ? AND symbol = ?
                ORDER BY factor_index ASC
                """,
                (normalized_model, normalized_symbol),
            ).fetchall()

        return [
            SymbolFactorStatsRow(
                model_name=str(row["model_name"]),
                symbol=str(row["symbol"]),
                factor_index=int(row["factor_index"]),
                factor_name=str(row["factor_name"]),
                mean_value=float(row["mean_value"]),
                variance_value=float(row["variance_value"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def replace_symbol_factor_stats(
        self,
        model_name: str,
        symbol: str,
        factor_names: list[str],
        mean_values: list[float],
        variance_values: list[float],
    ) -> None:
        if len(factor_names) != len(mean_values) or len(factor_names) != len(variance_values):
            raise ValueError("factor_names, mean_values, and variance_values must have the same length")

        normalized_model = model_name.strip()
        normalized_symbol = symbol.strip().upper()
        if not normalized_model or not normalized_symbol:
            raise ValueError("model_name and symbol must not be empty")

        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            for idx, factor_name in enumerate(factor_names):
                conn.execute(
                    """
                    INSERT INTO symbol_factor_stats(
                        model_name, symbol, factor_index, factor_name,
                        mean_value, variance_value, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(model_name, symbol, factor_index) DO UPDATE SET
                        factor_name = excluded.factor_name,
                        mean_value = excluded.mean_value,
                        variance_value = excluded.variance_value,
                        updated_at = excluded.updated_at
                    """,
                    (
                        normalized_model,
                        normalized_symbol,
                        idx,
                        str(factor_name or ""),
                        _safe_float64(mean_values[idx]),
                        _safe_float64(variance_values[idx]),
                        now,
                    ),
                )

            conn.execute(
                """
                DELETE FROM symbol_factor_stats
                WHERE model_name = ? AND symbol = ? AND factor_index >= ?
                """,
                (normalized_model, normalized_symbol, len(factor_names)),
            )
            conn.commit()


def _safe_float64(value: float) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("all numeric values must be finite float64")
    return out
