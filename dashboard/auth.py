"""Single-owner password and in-memory dashboard sessions."""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from config.storage import atomic_write_json

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
SALT_BYTES = 16
HASH_BYTES = 32


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=HASH_BYTES,
    )


class AuthStore:
    def __init__(self, root: Path) -> None:
        self._path = root / "data" / "admin_auth.json"

    def needs_setup(self) -> bool:
        return self._load() is None

    def create_password(self, password: str) -> None:
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise ValueError("Password must contain 10 to 128 characters")
        if self._load() is not None:
            raise ValueError("Authentication is already configured")
        salt = secrets.token_bytes(SALT_BYTES)
        atomic_write_json(
            self._path,
            {
                "version": 1,
                "salt": base64.b64encode(salt).decode("ascii"),
                "password_hash": base64.b64encode(_derive(password, salt)).decode("ascii"),
            },
        )

    def verify_password(self, password: str) -> bool:
        loaded = self._load()
        if loaded is None:
            return False
        salt, expected = loaded
        return hmac.compare_digest(_derive(password, salt), expected)

    def _load(self) -> tuple[bytes, bytes] | None:
        if not self._path.exists():
            return None
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "version",
                "salt",
                "password_hash",
            }:
                raise ValueError
            if payload["version"] != 1:
                raise ValueError
            salt_value = payload["salt"]
            hash_value = payload["password_hash"]
            if not isinstance(salt_value, str) or not isinstance(hash_value, str):
                raise ValueError
            salt = base64.b64decode(salt_value, validate=True)
            password_hash = base64.b64decode(hash_value, validate=True)
            if len(salt) != SALT_BYTES or len(password_hash) != HASH_BYTES:
                raise ValueError
            return salt, password_hash
        except (OSError, UnicodeError, ValueError):
            raise ValueError("Invalid authentication file") from None


@dataclass(frozen=True)
class Session:
    session_id: str
    csrf_token: str


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    def create(self) -> Session:
        session = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32))
        self._sessions.clear()
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str | None) -> Session | None:
        return self._sessions.get(session_id) if session_id is not None else None

    def verify_csrf(self, session_id: str | None, token: str | None) -> bool:
        session = self.get(session_id)
        expected = session.csrf_token if session is not None else "0" * 43
        provided = token or ""
        matches = hmac.compare_digest(expected, provided)
        return session is not None and token is not None and matches

    def delete(self, session_id: str | None) -> None:
        if session_id is not None:
            self._sessions.pop(session_id, None)


class LoginThrottle:
    def __init__(self) -> None:
        self._failures = 0

    def record_failure(self) -> int:
        self._failures += 1
        return min(self._failures, 3)

    def reset(self) -> None:
        self._failures = 0
