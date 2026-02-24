from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
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
class VenueQuantilesRow:
    venue: str
    pkl_path: str
    created_at: str
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

                CREATE TABLE IF NOT EXISTS venue_quantiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue TEXT NOT NULL UNIQUE,
                    pkl_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

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

    def upsert_venue_quantiles(self, venue: str, pkl_path: str) -> None:
        now = utc_now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO venue_quantiles(venue, pkl_path, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(venue) DO UPDATE SET
                    pkl_path = excluded.pkl_path,
                    updated_at = excluded.updated_at
                """,
                (venue, pkl_path, now, now),
            )
            conn.commit()

    def get_venue_quantiles(self, venue: str) -> VenueQuantilesRow | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT venue, pkl_path, created_at, updated_at FROM venue_quantiles WHERE venue = ?",
                (venue,),
            ).fetchone()
            if row is None:
                return None
            return VenueQuantilesRow(
                venue=str(row["venue"]),
                pkl_path=str(row["pkl_path"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

    def list_venue_quantiles(self) -> list[VenueQuantilesRow]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT venue, pkl_path, created_at, updated_at FROM venue_quantiles ORDER BY venue ASC"
            ).fetchall()
        return [
            VenueQuantilesRow(
                venue=str(row["venue"]),
                pkl_path=str(row["pkl_path"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def delete_venue_quantiles(self, venue: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM venue_quantiles WHERE venue = ?", (venue,))
            conn.commit()
            return cursor.rowcount > 0
