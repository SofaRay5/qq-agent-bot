"""Check that the optional UI launches and stops the bot safely."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from scripts import start_ui


def test_launch_passes_secrets_only_to_child_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = tmp_path / "capture"
    (tmp_path / "main.py").write_text(
        "import os, pathlib, time\n"
        "pathlib.Path(os.environ['CAPTURE_FILE']).write_text("
        "os.environ['NAPCAT_WS_URL'] + '\\n' + "
        "os.environ['NAPCAT_ACCESS_TOKEN'] + '\\n' + "
        "os.environ['DEEPSEEK_API_KEY'])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(start_ui, "ROOT", tmp_path)
    monkeypatch.setenv("CAPTURE_FILE", str(capture))
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("NAPCAT_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    process = start_ui.launch_bot("ws://127.0.0.1:3001/", "ws-secret", "api-secret")
    try:
        for _ in range(100):
            if capture.exists():
                break
            time.sleep(0.01)
        assert capture.read_text(encoding="utf-8") == (
            "ws://127.0.0.1:3001/\nws-secret\napi-secret"
        )
        assert os.environ.get("NAPCAT_ACCESS_TOKEN") is None
        assert os.environ.get("DEEPSEEK_API_KEY") is None
    finally:
        start_ui.stop_bot(process)
    assert process.poll() is not None


@pytest.mark.parametrize(
    ("url", "token", "api_key"),
    [
        ("", "token", "key"),
        ("ws://127.0.0.1:3001/", "", "key"),
        ("ws://127.0.0.1:3001/", "token", ""),
    ],
)
def test_launch_rejects_missing_fields(url: str, token: str, api_key: str) -> None:
    with pytest.raises(ValueError, match="请填写"):
        start_ui.launch_bot(url, token, api_key)


def test_disabled_vision_overrides_inherited_vision_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = tmp_path / "capture"
    (tmp_path / "main.py").write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['CAPTURE_FILE']).write_text('|'.join(("
        "os.environ['VISION_ENABLED'], "
        "os.environ.get('VISION_API_BASE_URL', ''), "
        "os.environ.get('VISION_MODEL', ''), "
        "os.environ.get('VISION_API_KEY', ''))))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(start_ui, "ROOT", tmp_path)
    monkeypatch.setenv("CAPTURE_FILE", str(capture))
    monkeypatch.setenv("VISION_ENABLED", "1")
    monkeypatch.setenv("VISION_API_BASE_URL", "https://stale.example/v1")
    monkeypatch.setenv("VISION_MODEL", "stale-model")
    monkeypatch.setenv("VISION_API_KEY", "stale-key")

    process = start_ui.launch_bot("ws://127.0.0.1:3001/", "token", "key")
    process.wait(timeout=3)

    assert capture.read_text(encoding="utf-8") == "0|||"


def test_enabled_vision_passes_settings_only_to_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = tmp_path / "capture"
    (tmp_path / "main.py").write_text(
        "import os, pathlib\n"
        "pathlib.Path(os.environ['CAPTURE_FILE']).write_text('|'.join(("
        "os.environ['VISION_ENABLED'], os.environ['VISION_API_BASE_URL'], "
        "os.environ['VISION_MODEL'], os.environ['VISION_API_KEY'])))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(start_ui, "ROOT", tmp_path)
    monkeypatch.setenv("CAPTURE_FILE", str(capture))
    monkeypatch.setenv("VISION_API_KEY", "parent-vision-key")

    process = start_ui.launch_bot(
        "ws://127.0.0.1:3001/",
        "token",
        "key",
        vision_enabled=True,
        vision_base_url="https://vision.example/v1",
        vision_model="vision-model",
        vision_api_key="vision-key",
    )
    process.wait(timeout=3)

    assert capture.read_text(encoding="utf-8") == (
        "1|https://vision.example/v1|vision-model|vision-key"
    )
    assert os.environ.get("VISION_API_KEY") == "parent-vision-key"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://",
        "http://vision.example/v1",
        "https://user:pass@vision.example/v1",
        "https://vision.example/v1?key=secret",
    ],
)
def test_invalid_vision_url_does_not_start_child(
    monkeypatch: pytest.MonkeyPatch, base_url: str
) -> None:
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("child started"),
    )

    with pytest.raises(ValueError, match="HTTPS"):
        start_ui.launch_bot(
            "ws://127.0.0.1:3001/",
            "token",
            "key",
            vision_enabled=True,
            vision_base_url=base_url,
            vision_model="vision-model",
            vision_api_key="vision-key",
        )


@pytest.mark.parametrize(
    ("base_url", "model", "api_key"),
    [
        ("", "vision-model", "vision-key"),
        ("https://vision.example/v1", "", "vision-key"),
        ("https://vision.example/v1", "vision-model", ""),
    ],
)
def test_enabled_vision_rejects_missing_fields(base_url: str, model: str, api_key: str) -> None:
    with pytest.raises(ValueError, match="识图"):
        start_ui.launch_bot(
            "ws://127.0.0.1:3001/",
            "token",
            "key",
            vision_enabled=True,
            vision_base_url=base_url,
            vision_model=model,
            vision_api_key=api_key,
        )
