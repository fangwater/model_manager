from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass

from .db import Database

ROLE_READONLY = "readonly"


class AuthError(Exception):
    pass


class PasswordNotInitialized(AuthError):
    pass


class InvalidPassword(AuthError):
    pass


class InvalidToken(AuthError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")



def _b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data.encode("ascii"))


# Format: scrypt$N$r$p$salt_b64$hash_b64

def hash_password(password: str, *, n: int = 2**14, r: int = 8, p: int = 1) -> str:
    if not password:
        raise ValueError("password must not be empty")

    salt = os.urandom(16)
    pwd_hash = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(pwd_hash)}"



def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = encoded.split("$", maxsplit=5)
    except ValueError:
        return False

    if algo != "scrypt":
        return False

    try:
        n_int = int(n)
        r_int = int(r)
        p_int = int(p)
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
    except Exception:
        return False

    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n_int,
        r=r_int,
        p=p_int,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


@dataclass
class SessionInfo:
    token: str
    expires_at: int
    permission: str = ROLE_READONLY


class AuthManager:
    def __init__(self, db: Database, token_ttl_seconds: int = 12 * 60 * 60) -> None:
        self.db = db
        self.token_ttl_seconds = token_ttl_seconds
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionInfo] = {}

    def is_password_initialized(self) -> bool:
        return self.db.get_password_hash() is not None

    def bootstrap_password(self, password: str) -> bool:
        encoded = hash_password(password)
        return self.db.insert_password_hash_once(encoded)

    def set_password(self, password: str) -> None:
        encoded = hash_password(password)
        self.db.set_password_hash(encoded)
        self._clear_sessions()

    def login(self, password: str) -> SessionInfo:
        encoded = self.db.get_password_hash()
        if encoded is None:
            raise PasswordNotInitialized("password is not initialized")

        if not verify_password(password, encoded):
            raise InvalidPassword("password mismatch")

        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + self.token_ttl_seconds
        session = SessionInfo(token=token, expires_at=expires_at)

        with self._lock:
            self._gc_expired_locked()
            self._sessions[token] = session
        return session

    def verify_token(self, token: str) -> SessionInfo:
        now = int(time.time())
        with self._lock:
            self._gc_expired_locked(now=now)
            session = self._sessions.get(token)
            if session is None:
                raise InvalidToken("invalid token")
            if session.expires_at <= now:
                self._sessions.pop(token, None)
                raise InvalidToken("token expired")
            return session

    def _gc_expired_locked(self, now: int | None = None) -> None:
        current = now if now is not None else int(time.time())
        expired = [tok for tok, sess in self._sessions.items() if sess.expires_at <= current]
        for token in expired:
            self._sessions.pop(token, None)

    def _clear_sessions(self) -> None:
        with self._lock:
            self._sessions.clear()
