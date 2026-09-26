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


def test_memory_provider_follows_chat_by_default() -> None:
    value = PrivateSettings(chat=provider())

    resolved = value.memory_provider()

    assert resolved == value.chat
    assert resolved is not value.chat
    assert value.memory is None


def test_independent_memory_provider_is_preserved() -> None:
    memory = provider(
        provider="openai_compatible",
        base_url="https://memory.example/v1",
        model="memory-model",
        api_key="memory-secret",
    )
    value = PrivateSettings(chat=provider(), memory=memory)

    assert value.memory_provider() == memory
    assert value.memory_provider() is not memory


def test_vision_can_reuse_only_chat_api_key() -> None:
    value = PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="napcat-secret",
        chat=provider(api_key="chat-secret"),
        vision_enabled=True,
        vision_reuse_chat_api_key=True,
        vision=provider(
            provider="openai_compatible",
            base_url="https://vision.example/v1",
            model="vision-model",
            api_key="",
        ),
    )

    resolved = value.vision_provider()

    assert resolved.base_url == "https://vision.example/v1"
    assert resolved.model == "vision-model"
    assert resolved.api_key == "chat-secret"
    assert value.vision.api_key == ""
    value.validate_for_start()


def test_blank_resolved_keys_remain_safe_and_missing() -> None:
    value = PrivateSettings(
        napcat_ws_url="ws://127.0.0.1:3001/",
        napcat_access_token="napcat-secret",
        chat=provider(api_key=""),
        memory=provider(api_key=""),
        vision_enabled=True,
        vision_reuse_chat_api_key=True,
        vision=provider(api_key=""),
    )

    assert value.memory_provider().api_key == ""
    assert value.vision_provider().api_key == ""
    assert "provider-secret" not in repr(value.memory_provider())
    with pytest.raises(ValueError, match="chat.api_key"):
        value.validate_for_start()


def test_provider_inheritance_persists_without_duplicate_keys(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    value = PrivateSettings(
        chat=provider(api_key="chat-secret"),
        memory=None,
        vision_reuse_chat_api_key=True,
        vision=provider(api_key=""),
    )

    save_private_settings(tmp_path, value)
    saved = (tmp_path / "config/private.json").read_text(encoding="utf-8")

    assert '"memory": null' in saved
    assert '"vision_reuse_chat_api_key": true' in saved
    assert saved.count("chat-secret") == 1


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
