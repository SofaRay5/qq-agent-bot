"""Check that the optional UI launches and stops the bot safely."""

import os
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
