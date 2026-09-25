import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from config.models import (
    Persona,
    PrivateSettings,
    ProviderSettings,
    Settings,
    load_persona,
    load_settings,
)
from config.storage import (
    load_private_settings,
    save_persona,
    save_private_settings,
    save_settings,
)


def provider(**changes: object) -> ProviderSettings:
    values: dict[str, object] = {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "api_key": "provider-secret",
    }
    return ProviderSettings.model_validate({**values, **changes})


def test_accepts_deepseek_provider() -> None:
    value = provider()

    assert value.base_url == "https://api.deepseek.com"
    assert value.model == "deepseek-flash"


@pytest.mark.parametrize(
    "url",
    [
        "http://models.example/v1",
        "https://user:pass@models.example/v1",
        "https://models.example/v1?key=value",
        "https://models.example/v1#fragment",
        "https://models.example:bad/v1",
    ],
)
def test_rejects_unsafe_provider_urls_without_leaking_key(url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        provider(provider="openai_compatible", base_url=url)

    assert "provider-secret" not in str(exc_info.value)


@pytest.mark.parametrize(
    "url",
    ["ws://127.0.0.1:3001/", "wss://napcat.example/"],
)
def test_accepts_root_napcat_websocket_urls(url: str) -> None:
    value = PrivateSettings(napcat_ws_url=url)

    assert value.napcat_ws_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:3001/",
        "ws://127.0.0.1:3001/onebot",
        "ws://user:pass@127.0.0.1:3001/",
        "ws://127.0.0.1:bad/",
        "ws://127.0.0.1:3001/?token=secret",
    ],
)
def test_rejects_invalid_napcat_urls_without_leaking_token(url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        PrivateSettings(napcat_ws_url=url, napcat_access_token="napcat-secret")

    assert "napcat-secret" not in str(exc_info.value)


def test_first_run_draft_is_allowed_but_cannot_start() -> None:
    value = PrivateSettings()

    with pytest.raises(ValueError) as exc_info:
        value.validate_for_start()

    message = str(exc_info.value)
    assert "napcat_ws_url" in message
    assert "napcat_access_token" in message
    assert "chat.api_key" in message


def test_enabled_vision_requires_complete_provider() -> None:
    value = PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="napcat-secret",
        chat=provider(),
        vision_enabled=True,
    )

    with pytest.raises(ValueError) as exc_info:
        value.validate_for_start()

    assert "vision.base_url" in str(exc_info.value)
    assert "vision.model" in str(exc_info.value)
    assert "vision.api_key" in str(exc_info.value)


def test_whitespace_credentials_are_missing_at_start() -> None:
    value = PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token=" ",
        chat=provider(api_key="\t"),
    )

    with pytest.raises(ValueError) as exc_info:
        value.validate_for_start()

    assert "napcat_access_token" in str(exc_info.value)
    assert "chat.api_key" in str(exc_info.value)


def test_secrets_are_excluded_from_repr() -> None:
    value = PrivateSettings(
        napcat_access_token="napcat-secret",
        chat=provider(),
    )

    representation = repr(value)
    assert "napcat-secret" not in representation
    assert "provider-secret" not in representation


def settings() -> Settings:
    return Settings.model_validate(
        {
            "continuous_window_seconds": 600,
            "window_max_attempts": 5,
            "window_max_replies": 5,
            "daily_model_calls": 50,
            "daily_proactive_calls": 5,
            "daily_vision_calls": 5,
            "proactive_mode": "off",
            "proactive_probability": 0.05,
            "minimum_reply_interval_seconds": 8.0,
            "send_delay_seconds": 1.5,
            "context_max_messages": 20,
            "context_max_characters": 6000,
        }
    )


def persona() -> Persona:
    return Persona.model_validate(
        {
            "name": "小薯",
            "description": "",
            "personality": "",
            "scenario": "",
            "speech_style": "",
            "identity_response": "",
            "example_dialogues": [],
        }
    )


def private_settings() -> PrivateSettings:
    return PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="napcat-secret",
        chat=provider(),
    )


def test_saves_and_reloads_private_settings_with_owner_only_mode(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    value = private_settings()

    save_private_settings(tmp_path, value)

    path = tmp_path / "config" / "private.json"
    assert load_private_settings(tmp_path) == value
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_saves_settings_and_persona_without_touching_examples(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    settings_example = config / "settings.example.json"
    persona_example = config / "persona.example.json"
    settings_example.write_text("settings-example", encoding="utf-8")
    persona_example.write_text("persona-example", encoding="utf-8")

    save_settings(tmp_path, settings())
    save_persona(tmp_path, persona())

    assert load_settings(tmp_path) == settings()
    assert load_persona(tmp_path) == persona()
    assert stat.S_IMODE((config / "settings.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((config / "persona.json").stat().st_mode) == 0o600
    assert settings_example.read_text(encoding="utf-8") == "settings-example"
    assert persona_example.read_text(encoding="utf-8") == "persona-example"


def test_failed_replace_preserves_previous_private_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config").mkdir()
    original = private_settings()
    save_private_settings(tmp_path, original)
    replacement = original.model_copy(update={"napcat_access_token": "replacement-secret"})

    def fail_replace(_source: os.PathLike[str], _target: os.PathLike[str]) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("config.storage.os.replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        save_private_settings(tmp_path, replacement)

    assert load_private_settings(tmp_path) == original


def test_missing_private_file_returns_first_run_draft(tmp_path: Path) -> None:
    assert load_private_settings(tmp_path) == PrivateSettings()


def test_malformed_private_file_raises_safe_error(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "private.json").write_text('{"api_key":"file-secret"', encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        load_private_settings(tmp_path)

    assert str(exc_info.value) == "Invalid private settings JSON"
    assert "file-secret" not in str(exc_info.value)


def test_private_config_path_is_git_ignored() -> None:
    ignore = Path(".gitignore").read_text(encoding="utf-8")

    assert "/config/private.json" in ignore.splitlines()
