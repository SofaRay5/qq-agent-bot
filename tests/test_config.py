import json
import traceback
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from config.models import Persona, Settings, load_persona, load_settings

DEFAULT_SETTINGS: dict[str, Any] = {
    "continuous_window_seconds": 600,
    "window_max_attempts": 5,
    "window_max_replies": 5,
    "daily_model_calls": 50,
    "daily_proactive_calls": 5,
    "daily_vision_calls": 5,
    "proactive_mode": "off",
    "proactive_probability": 0.05,
    "minimum_reply_interval_seconds": 8,
    "send_delay_seconds": 1.5,
    "context_max_messages": 20,
    "context_max_characters": 6000,
}

EMPTY_PERSONA: dict[str, Any] = {
    "name": "小薯",
    "description": "",
    "personality": "",
    "scenario": "",
    "speech_style": "",
    "identity_response": "",
    "example_dialogues": [],
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_loads_example_files_when_local_files_are_absent(tmp_path: Path) -> None:
    write_json(tmp_path / "config/settings.example.json", DEFAULT_SETTINGS)
    write_json(tmp_path / "config/persona.example.json", EMPTY_PERSONA)

    assert load_settings(tmp_path).proactive_mode == "off"
    assert load_persona(tmp_path).name == "小薯"


def test_local_files_override_examples(tmp_path: Path) -> None:
    write_json(tmp_path / "config/settings.example.json", DEFAULT_SETTINGS)
    write_json(tmp_path / "config/persona.example.json", EMPTY_PERSONA)
    write_json(
        tmp_path / "config/settings.json",
        {**DEFAULT_SETTINGS, "proactive_mode": "both"},
    )
    write_json(tmp_path / "config/persona.json", {**EMPTY_PERSONA, "name": "本地小薯"})

    assert load_settings(tmp_path).proactive_mode == "both"
    assert load_persona(tmp_path).name == "本地小薯"


@pytest.mark.parametrize(
    ("field", "low", "high", "related"),
    [
        ("continuous_window_seconds", 60, 3600, {}),
        ("window_max_attempts", 1, 20, {"window_max_replies": 1}),
        ("window_max_replies", 1, 20, {"window_max_attempts": 20}),
        (
            "daily_model_calls",
            1,
            1000,
            {"daily_proactive_calls": 1, "daily_vision_calls": 1},
        ),
        ("daily_proactive_calls", 0, 1000, {"daily_model_calls": 1000}),
        ("daily_vision_calls", 0, 1000, {"daily_model_calls": 1000}),
        ("proactive_probability", 0.0, 1.0, {}),
        ("minimum_reply_interval_seconds", 0.0, 300.0, {}),
        ("send_delay_seconds", 0.0, 300.0, {}),
        ("context_max_messages", 1, 100, {}),
        ("context_max_characters", 500, 20_000, {}),
    ],
)
def test_settings_accept_numeric_boundaries(
    field: str,
    low: int | float,
    high: int | float,
    related: dict[str, int],
) -> None:
    for value in (low, high):
        settings = Settings.model_validate({**DEFAULT_SETTINGS, **related, field: value})
        assert getattr(settings, field) == value


@pytest.mark.parametrize(
    ("field", "below", "above", "related"),
    [
        ("continuous_window_seconds", 59, 3601, {}),
        ("window_max_attempts", 0, 21, {"window_max_replies": 1}),
        ("window_max_replies", 0, 21, {"window_max_attempts": 20}),
        (
            "daily_model_calls",
            0,
            1001,
            {"daily_proactive_calls": 0, "daily_vision_calls": 0},
        ),
        ("daily_proactive_calls", -1, 1001, {"daily_model_calls": 1000}),
        ("daily_vision_calls", -1, 1001, {"daily_model_calls": 1000}),
        ("proactive_probability", -0.01, 1.01, {}),
        ("minimum_reply_interval_seconds", -0.1, 300.1, {}),
        ("send_delay_seconds", -0.1, 300.1, {}),
        ("context_max_messages", 0, 101, {}),
        ("context_max_characters", 499, 20_001, {}),
    ],
)
def test_settings_reject_values_outside_numeric_boundaries(
    field: str,
    below: int | float,
    above: int | float,
    related: dict[str, int],
) -> None:
    for value in (below, above):
        with pytest.raises(ValidationError):
            Settings.model_validate({**DEFAULT_SETTINGS, **related, field: value})


@pytest.mark.parametrize(
    "field",
    [
        "continuous_window_seconds",
        "window_max_attempts",
        "window_max_replies",
        "daily_model_calls",
        "daily_proactive_calls",
        "daily_vision_calls",
        "proactive_probability",
        "minimum_reply_interval_seconds",
        "send_delay_seconds",
        "context_max_messages",
        "context_max_characters",
    ],
)
def test_settings_reject_booleans_as_numbers(tmp_path: Path, field: str) -> None:
    write_json(
        tmp_path / "config/settings.example.json",
        {**DEFAULT_SETTINGS, field: True},
    )

    with pytest.raises(ValueError, match=field):
        load_settings(tmp_path)


@pytest.mark.parametrize(
    "changes",
    [
        {"window_max_attempts": 4, "window_max_replies": 5},
        {"daily_model_calls": 4, "daily_proactive_calls": 5},
        {"daily_model_calls": 4, "daily_vision_calls": 5},
    ],
)
def test_settings_reject_inconsistent_limits(tmp_path: Path, changes: dict[str, int]) -> None:
    write_json(
        tmp_path / "config/settings.example.json",
        {**DEFAULT_SETTINGS, **changes},
    )

    with pytest.raises(ValueError, match="exceeds"):
        load_settings(tmp_path)


@pytest.mark.parametrize("name", ["settings", "persona"])
def test_configuration_rejects_unknown_fields(tmp_path: Path, name: str) -> None:
    value = DEFAULT_SETTINGS if name == "settings" else EMPTY_PERSONA
    write_json(
        tmp_path / f"config/{name}.example.json",
        {**value, "unexpected": "do-not-accept"},
    )

    loader = load_settings if name == "settings" else load_persona
    with pytest.raises(ValueError, match="unexpected"):
        loader(tmp_path)


@pytest.mark.parametrize(
    ("field", "valid_length", "invalid_length"),
    [
        ("name", 32, 33),
        ("description", 2000, 2001),
        ("personality", 2000, 2001),
        ("scenario", 2000, 2001),
        ("speech_style", 1000, 1001),
        ("identity_response", 1000, 1001),
    ],
)
def test_persona_enforces_field_lengths(
    field: str,
    valid_length: int,
    invalid_length: int,
) -> None:
    assert Persona.model_validate({**EMPTY_PERSONA, field: "字" * valid_length})
    with pytest.raises(ValidationError):
        Persona.model_validate({**EMPTY_PERSONA, field: "字" * invalid_length})


def test_persona_rejects_empty_name() -> None:
    with pytest.raises(ValidationError):
        Persona.model_validate({**EMPTY_PERSONA, "name": ""})


def test_persona_accepts_three_complete_examples() -> None:
    examples = [{"user": "问" * 1000, "assistant": "答" * 1000}] * 3
    persona = Persona.model_validate({**EMPTY_PERSONA, "example_dialogues": examples})

    assert len(persona.example_dialogues) == 3


@pytest.mark.parametrize(
    "examples",
    [
        [{"user": "问", "assistant": "答"}] * 4,
        [{"user": "", "assistant": "答"}],
        [{"user": "问", "assistant": ""}],
        [{"user": "问"}],
        [{"assistant": "答"}],
        [{"user": "问" * 1001, "assistant": "答"}],
        [{"user": "问", "assistant": "答" * 1001}],
    ],
)
def test_persona_rejects_invalid_examples(examples: list[dict[str, str]]) -> None:
    with pytest.raises(ValidationError):
        Persona.model_validate({**EMPTY_PERSONA, "example_dialogues": examples})


def test_persona_enforces_total_character_limit() -> None:
    exactly_8000 = {
        **EMPTY_PERSONA,
        "name": "薯",
        "description": "字" * 1999,
        "personality": "字" * 2000,
        "scenario": "字" * 2000,
        "speech_style": "字" * 1000,
        "identity_response": "字" * 1000,
    }
    assert Persona.model_validate(exactly_8000)

    with pytest.raises(ValidationError, match="8000"):
        Persona.model_validate({**exactly_8000, "description": "字" * 2000})


def test_loader_errors_name_fields_without_leaking_values(tmp_path: Path) -> None:
    secret = "secret-value-that-must-not-leak"
    persona_body = "distinctive-private-persona-body"
    write_json(
        tmp_path / "config/persona.example.json",
        {
            **EMPTY_PERSONA,
            "description": persona_body * 100,
            "unexpected": secret,
        },
    )

    with pytest.raises(ValueError) as caught:
        load_persona(tmp_path)

    message = str(caught.value)
    assert "description" in message
    assert "unexpected" in message
    assert persona_body not in message
    assert secret not in message
    rendered = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert persona_body not in rendered
    assert secret not in rendered


def test_loader_reports_invalid_json_without_echoing_it(tmp_path: Path) -> None:
    secret = "secret-invalid-json"
    path = tmp_path / "config/settings.example.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"broken": "' + secret, encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid settings JSON") as caught:
        load_settings(tmp_path)

    assert secret not in str(caught.value)
