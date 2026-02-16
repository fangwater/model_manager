from __future__ import annotations

import json
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
    mean_values: list[float]
    variance_values: list[float]
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
                    mean_values_json TEXT NOT NULL DEFAULT '[]',
                    variance_values_json TEXT NOT NULL DEFAULT '[]',
                    mean_value REAL NOT NULL,
                    variance_value REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(model_name, symbol, factor_index)
                );

                CREATE INDEX IF NOT EXISTS idx_symbol_factor_stats_model_symbol
                ON symbol_factor_stats(model_name, symbol);
                """
            )
            self._migrate_symbol_factor_stats_schema(conn)

    def _migrate_symbol_factor_stats_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(symbol_factor_stats)").fetchall()
        }

        if "mean_values_json" not in columns:
            conn.execute(
                "ALTER TABLE symbol_factor_stats "
                "ADD COLUMN mean_values_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "variance_values_json" not in columns:
            conn.execute(
                "ALTER TABLE symbol_factor_stats "
                "ADD COLUMN variance_values_json TEXT NOT NULL DEFAULT '[]'"
            )

        # Backfill json columns for legacy rows that only had scalar values.
        conn.execute(
            """
            UPDATE symbol_factor_stats
            SET mean_values_json = '[' || CAST(mean_value AS TEXT) || ']'
            WHERE mean_values_json IS NULL OR mean_values_json = ''
            """
        )
        conn.execute(
            """
            UPDATE symbol_factor_stats
            SET variance_values_json = '[' || CAST(variance_value AS TEXT) || ']'
            WHERE variance_values_json IS NULL OR variance_values_json = ''
            """
        )
        conn.commit()

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
        default_mean: float = 0.2,
        default_variance: float = 1.0,
    ) -> None:
        now = utc_now_iso()
        normalized_model = model_name.strip()
        normalized_symbol = symbol.strip().upper()
        safe_default_mean = _safe_float64(default_mean)
        safe_default_variance = _safe_float64(default_variance)
        expected_dim = len(factor_names)

        if not normalized_model or not normalized_symbol:
            return

        with self._lock, self._connect() as conn:
            existing_rows = conn.execute(
                """
                SELECT
                    factor_index,
                    factor_name,
                    mean_values_json,
                    variance_values_json,
                    mean_value,
                    variance_value
                FROM symbol_factor_stats
                WHERE model_name = ? AND symbol = ?
                ORDER BY factor_index ASC
                """,
                (normalized_model, normalized_symbol),
            ).fetchall()
            existing_by_index = {
                int(row["factor_index"]): row
                for row in existing_rows
            }

            for idx, raw_name in enumerate(factor_names):
                factor_name = str(raw_name or "")
                existing = existing_by_index.get(idx)
                if existing is None:
                    mean_values = [safe_default_mean for _ in range(expected_dim)]
                    variance_values = [safe_default_variance for _ in range(expected_dim)]
                    conn.execute(
                        """
                        INSERT INTO symbol_factor_stats(
                            model_name, symbol, factor_index, factor_name,
                            mean_values_json, variance_values_json,
                            mean_value, variance_value, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            normalized_model,
                            normalized_symbol,
                            idx,
                            factor_name,
                            _dump_float_array(mean_values),
                            _dump_float_array(variance_values),
                            mean_values[idx],
                            variance_values[idx],
                            now,
                        ),
                    )
                    continue

                existing_name = str(existing["factor_name"])
                mean_values = _normalize_float_vector(
                    _parse_float_array(existing["mean_values_json"]),
                    expected_dim=expected_dim,
                    fill_value=safe_default_mean,
                    fallback_scalar=_safe_float64(existing["mean_value"]),
                )
                variance_values = _normalize_float_vector(
                    _parse_float_array(existing["variance_values_json"]),
                    expected_dim=expected_dim,
                    fill_value=safe_default_variance,
                    fallback_scalar=_safe_float64(existing["variance_value"]),
                )

                if (
                    existing_name != factor_name
                    or _parse_float_array(existing["mean_values_json"]) != mean_values
                    or _parse_float_array(existing["variance_values_json"]) != variance_values
                    or _safe_float64(existing["mean_value"]) != mean_values[idx]
                    or _safe_float64(existing["variance_value"]) != variance_values[idx]
                ):
                    conn.execute(
                        """
                        UPDATE symbol_factor_stats
                        SET
                            factor_name = ?,
                            mean_values_json = ?,
                            variance_values_json = ?,
                            mean_value = ?,
                            variance_value = ?,
                            updated_at = ?
                        WHERE model_name = ? AND symbol = ? AND factor_index = ?
                        """,
                        (
                            factor_name,
                            _dump_float_array(mean_values),
                            _dump_float_array(variance_values),
                            mean_values[idx],
                            variance_values[idx],
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
                SELECT
                    model_name,
                    symbol,
                    factor_index,
                    factor_name,
                    mean_values_json,
                    variance_values_json,
                    mean_value,
                    variance_value,
                    updated_at
                FROM symbol_factor_stats
                WHERE model_name = ? AND symbol = ?
                ORDER BY factor_index ASC
                """,
                (normalized_model, normalized_symbol),
            ).fetchall()

        expected_dim = len(rows)
        output: list[SymbolFactorStatsRow] = []
        for row in rows:
            mean_values = _normalize_float_vector(
                _parse_float_array(row["mean_values_json"]),
                expected_dim=expected_dim,
                fill_value=_safe_float64(row["mean_value"]),
                fallback_scalar=_safe_float64(row["mean_value"]),
            )
            variance_values = _normalize_float_vector(
                _parse_float_array(row["variance_values_json"]),
                expected_dim=expected_dim,
                fill_value=_safe_float64(row["variance_value"]),
                fallback_scalar=_safe_float64(row["variance_value"]),
            )

            output.append(
                SymbolFactorStatsRow(
                    model_name=str(row["model_name"]),
                    symbol=str(row["symbol"]),
                    factor_index=int(row["factor_index"]),
                    factor_name=str(row["factor_name"]),
                    mean_values=mean_values,
                    variance_values=variance_values,
                    updated_at=str(row["updated_at"]),
                )
            )
        return output

    def replace_symbol_factor_stats(
        self,
        model_name: str,
        symbol: str,
        factor_names: list[str],
        factor_mean_values: list[list[float]],
        factor_variance_values: list[list[float]],
    ) -> None:
        if len(factor_names) != len(factor_mean_values) or len(factor_names) != len(factor_variance_values):
            raise ValueError(
                "factor_names, factor_mean_values, and factor_variance_values must have the same length"
            )

        normalized_model = model_name.strip()
        normalized_symbol = symbol.strip().upper()
        if not normalized_model or not normalized_symbol:
            raise ValueError("model_name and symbol must not be empty")

        now = utc_now_iso()
        expected_dim = len(factor_names)
        with self._lock, self._connect() as conn:
            for idx, factor_name in enumerate(factor_names):
                mean_values = _strict_float_vector(
                    factor_mean_values[idx],
                    expected_dim=expected_dim,
                    path=f"factor_mean_values[{idx}]",
                )
                variance_values = _strict_float_vector(
                    factor_variance_values[idx],
                    expected_dim=expected_dim,
                    path=f"factor_variance_values[{idx}]",
                )

                conn.execute(
                    """
                    INSERT INTO symbol_factor_stats(
                        model_name, symbol, factor_index, factor_name,
                        mean_values_json, variance_values_json,
                        mean_value, variance_value, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(model_name, symbol, factor_index) DO UPDATE SET
                        factor_name = excluded.factor_name,
                        mean_values_json = excluded.mean_values_json,
                        variance_values_json = excluded.variance_values_json,
                        mean_value = excluded.mean_value,
                        variance_value = excluded.variance_value,
                        updated_at = excluded.updated_at
                    """,
                    (
                        normalized_model,
                        normalized_symbol,
                        idx,
                        str(factor_name or ""),
                        _dump_float_array(mean_values),
                        _dump_float_array(variance_values),
                        mean_values[idx],
                        variance_values[idx],
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


def _parse_float_array(raw: Any) -> list[float]:
    if not isinstance(raw, str) or not raw.strip():
        return []

    try:
        decoded = json.loads(raw)
    except Exception:
        return []

    if not isinstance(decoded, list):
        return []

    out: list[float] = []
    for item in decoded:
        try:
            value = _safe_float64(item)
        except Exception:
            return []
        out.append(value)
    return out


def _dump_float_array(values: list[float]) -> str:
    normalized = [_safe_float64(item) for item in values]
    return json.dumps(normalized, separators=(",", ":"))


def _normalize_float_vector(
    values: list[float],
    expected_dim: int,
    fill_value: float,
    fallback_scalar: float,
) -> list[float]:
    safe_fill = _safe_float64(fill_value)
    safe_fallback = _safe_float64(fallback_scalar)

    if expected_dim <= 0:
        return []

    if not values:
        return [safe_fallback for _ in range(expected_dim)]

    normalized = [_safe_float64(item) for item in values]
    if len(normalized) < expected_dim:
        normalized.extend([safe_fill for _ in range(expected_dim - len(normalized))])
    elif len(normalized) > expected_dim:
        normalized = normalized[:expected_dim]

    return normalized


def _strict_float_vector(values: list[float], expected_dim: int, path: str) -> list[float]:
    if not isinstance(values, list):
        raise ValueError(f"{path} must be a list")
    if len(values) != expected_dim:
        raise ValueError(f"{path} length must be {expected_dim}, got {len(values)}")

    try:
        return [_safe_float64(item) for item in values]
    except Exception as exc:
        raise ValueError(f"{path} contains non-finite values") from exc
