"""Validated local settings and persona files."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderSettings(StrictModel):
    provider: Literal["deepseek", "openai_compatible"] = "deepseek"
    base_url: str = ""
    model: str = ""
    api_key: str = Field(default="", repr=False)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        if not value:
            return value
        try:
            parts = urlsplit(value)
            _ = parts.port
        except ValueError:
            raise ValueError("base_url must be a valid HTTPS URL") from None
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("base_url must be a valid HTTPS URL")
        return value


class PrivateSettings(StrictModel):
    napcat_ws_url: str = ""
    napcat_access_token: str = Field(default="", repr=False)
    chat: ProviderSettings = Field(
        default_factory=lambda: ProviderSettings(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
        )
    )
    vision_enabled: bool = False
    vision: ProviderSettings = Field(default_factory=ProviderSettings)

    @field_validator("napcat_ws_url")
    @classmethod
    def validate_napcat_ws_url(cls, value: str) -> str:
        if not value:
            return value
        try:
            parts = urlsplit(value)
            _ = parts.port
        except ValueError:
            raise ValueError("napcat_ws_url must be a valid WebSocket URL") from None
        if (
            parts.scheme not in {"ws", "wss"}
            or not parts.hostname
            or parts.path not in {"", "/"}
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("napcat_ws_url must be a valid root WebSocket URL")
        return value

    def validate_for_start(self) -> None:
        missing = [
            name
            for name, value in (
                ("napcat_ws_url", self.napcat_ws_url),
                ("napcat_access_token", self.napcat_access_token),
                ("chat.base_url", self.chat.base_url),
                ("chat.model", self.chat.model),
                ("chat.api_key", self.chat.api_key),
            )
            if not value.strip()
        ]
        if self.vision_enabled:
            missing.extend(
                name
                for name, value in (
                    ("vision.base_url", self.vision.base_url),
                    ("vision.model", self.vision.model),
                    ("vision.api_key", self.vision.api_key),
                )
                if not value.strip()
            )
        if missing:
            raise ValueError(f"Missing private settings fields: {', '.join(missing)}")


class Settings(StrictModel):
    continuous_window_seconds: int = Field(ge=60, le=3600)
    window_max_attempts: int = Field(ge=1, le=20)
    window_max_replies: int = Field(ge=1, le=20)
    daily_model_calls: int = Field(ge=1, le=1000)
    daily_proactive_calls: int = Field(ge=0, le=1000)
    daily_vision_calls: int = Field(ge=0, le=1000)
    proactive_mode: Literal["off", "random", "topic", "both"]
    proactive_probability: float = Field(ge=0, le=1)
    minimum_reply_interval_seconds: float = Field(ge=0, le=300)
    send_delay_seconds: float = Field(ge=0, le=300)
    context_max_messages: int = Field(ge=1, le=100)
    context_max_characters: int = Field(ge=500, le=20_000)

    @model_validator(mode="after")
    def validate_related_limits(self) -> "Settings":
        if self.window_max_replies > self.window_max_attempts:
            raise ValueError("window_max_replies exceeds window_max_attempts")
        if self.daily_proactive_calls > self.daily_model_calls:
            raise ValueError("daily_proactive_calls exceeds daily_model_calls")
        if self.daily_vision_calls > self.daily_model_calls:
            raise ValueError("daily_vision_calls exceeds daily_model_calls")
        return self


class ExampleDialogue(StrictModel):
    user: str = Field(min_length=1, max_length=1000)
    assistant: str = Field(min_length=1, max_length=1000)


class Persona(StrictModel):
    name: str = Field(min_length=1, max_length=32)
    description: str = Field(max_length=2000)
    personality: str = Field(max_length=2000)
    scenario: str = Field(max_length=2000)
    speech_style: str = Field(max_length=1000)
    identity_response: str = Field(max_length=1000)
    example_dialogues: list[ExampleDialogue] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_total_length(self) -> "Persona":
        total = sum(
            len(value)
            for value in (
                self.name,
                self.description,
                self.personality,
                self.scenario,
                self.speech_style,
                self.identity_response,
            )
        ) + sum(len(item.user) + len(item.assistant) for item in self.example_dialogues)
        if total > 8000:
            raise ValueError("persona exceeds 8000 characters")
        return self


def _load[T: BaseModel](root: Path, name: str, model: type[T]) -> T:
    local = root / "config" / f"{name}.json"
    path = local if local.exists() else root / "config" / f"{name}.example.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read {name} configuration") from exc
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        errors = exc.errors(include_input=False)
        if errors and errors[0]["type"] == "json_invalid":
            raise ValueError(f"Invalid {name} JSON") from None
        fields = ", ".join(".".join(map(str, item["loc"])) or str(item["msg"]) for item in errors)
        raise ValueError(f"Invalid {name} fields: {fields}") from None


def load_settings(root: Path) -> Settings:
    """Load and validate local settings, falling back to the tracked example."""
    return _load(root, "settings", Settings)


def load_persona(root: Path) -> Persona:
    """Load and validate the local persona, falling back to the tracked example."""
    return _load(root, "persona", Persona)
