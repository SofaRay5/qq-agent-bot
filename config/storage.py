"""Atomic storage for Git-ignored local configuration."""

import json
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from config.models import Persona, PrivateSettings, Settings


def atomic_write_json(path: Path, payload: object) -> None:
    """Replace one owner-readable JSON file without exposing a partial write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def load_private_settings(root: Path) -> PrivateSettings:
    """Load dashboard secrets, or an empty first-run draft when absent."""
    path = root / "config" / "private.json"
    if not path.exists():
        return PrivateSettings()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError("Cannot read private settings") from exc
    try:
        return PrivateSettings.model_validate_json(raw)
    except ValidationError as exc:
        errors = exc.errors(include_input=False)
        if errors and errors[0]["type"] == "json_invalid":
            raise ValueError("Invalid private settings JSON") from None
        fields = ", ".join(".".join(map(str, item["loc"])) for item in errors)
        raise ValueError(f"Invalid private settings fields: {fields}") from None


def save_private_settings(root: Path, value: PrivateSettings) -> None:
    atomic_write_json(root / "config" / "private.json", value.model_dump(mode="json"))


def save_settings(root: Path, value: Settings) -> None:
    atomic_write_json(root / "config" / "settings.json", value.model_dump(mode="json"))


def save_persona(root: Path, value: Persona) -> None:
    atomic_write_json(root / "config" / "persona.json", value.model_dump(mode="json"))
