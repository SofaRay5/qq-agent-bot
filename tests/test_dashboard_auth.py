import json
import stat
from pathlib import Path

import pytest

from dashboard.auth import AuthStore, LoginThrottle, SessionStore


def test_creates_owner_only_scrypt_hash_and_verifies_password(tmp_path: Path) -> None:
    store = AuthStore(tmp_path)

    store.create_password("correct horse battery staple")

    path = tmp_path / "data" / "admin_auth.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert set(payload) == {"version", "salt", "password_hash"}
    assert "correct horse battery staple" not in path.read_text(encoding="utf-8")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.verify_password("correct horse battery staple")
    assert not store.verify_password("wrong password")


def test_each_password_file_uses_a_distinct_salt(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    AuthStore(first).create_password("same-password")
    AuthStore(second).create_password("same-password")

    first_payload = json.loads((first / "data" / "admin_auth.json").read_text())
    second_payload = json.loads((second / "data" / "admin_auth.json").read_text())

    assert first_payload["salt"] != second_payload["salt"]
    assert first_payload["password_hash"] != second_payload["password_hash"]


@pytest.mark.parametrize("password", ["short", "字" * 129])
def test_rejects_password_outside_length_bounds(tmp_path: Path, password: str) -> None:
    store = AuthStore(tmp_path)

    with pytest.raises(ValueError, match="10.*128"):
        store.create_password(password)

    assert not (tmp_path / "data" / "admin_auth.json").exists()


def test_missing_auth_file_allows_setup(tmp_path: Path) -> None:
    store = AuthStore(tmp_path)

    assert store.needs_setup()
    assert not store.verify_password("any-password")


@pytest.mark.parametrize(
    "content",
    ["{", "{}", '{"version":2,"salt":"AA==","password_hash":"AA=="}'],
)
def test_corrupt_or_invalid_existing_auth_file_fails_closed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "data" / "admin_auth.json"
    path.parent.mkdir()
    path.write_text(content, encoding="utf-8")
    store = AuthStore(tmp_path)

    with pytest.raises(ValueError, match="Invalid authentication file"):
        store.needs_setup()
    with pytest.raises(ValueError, match="Invalid authentication file"):
        store.verify_password("correct horse battery staple")


def test_login_rotates_session_and_csrf_tokens() -> None:
    sessions = SessionStore()

    first = sessions.create()
    second = sessions.create()

    assert first.session_id != second.session_id
    assert first.csrf_token != second.csrf_token
    assert sessions.get(first.session_id) is None
    assert sessions.get(second.session_id) == second


def test_csrf_check_and_logout_invalidate_session() -> None:
    sessions = SessionStore()
    session = sessions.create()

    assert sessions.verify_csrf(session.session_id, session.csrf_token)
    assert not sessions.verify_csrf(session.session_id, "wrong-token")
    assert not sessions.verify_csrf(session.session_id, None)
    assert not sessions.verify_csrf(None, session.csrf_token)

    sessions.delete(session.session_id)
    assert sessions.get(session.session_id) is None
    assert not sessions.verify_csrf(session.session_id, session.csrf_token)


def test_sessions_are_process_local_and_never_write_files(tmp_path: Path) -> None:
    before = set(tmp_path.rglob("*"))

    sessions = SessionStore()
    sessions.create()

    assert set(tmp_path.rglob("*")) == before


def test_login_failure_delay_caps_and_success_resets() -> None:
    throttle = LoginThrottle()

    assert [throttle.record_failure() for _ in range(5)] == [1, 2, 3, 3, 3]
    throttle.reset()
    assert throttle.record_failure() == 1
