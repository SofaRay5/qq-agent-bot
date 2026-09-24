import os
import subprocess
from pathlib import Path


def test_start_script_passes_hidden_token_to_bot(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$PWD" "$NAPCAT_WS_URL" '
        '"$NAPCAT_ACCESS_TOKEN" "$DEEPSEEK_API_KEY" "$*" > "$CAPTURE_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    capture = tmp_path / "capture"
    env = os.environ.copy()
    env.update(PATH=f"{fake_bin}:{env['PATH']}", CAPTURE_FILE=str(capture))
    env.pop("NAPCAT_ACCESS_TOKEN", None)
    env.pop("NAPCAT_WS_URL", None)
    env.pop("DEEPSEEK_API_KEY", None)

    result = subprocess.run(
        ["bash", str(root / "scripts/start_echo.sh")],
        input="replacement-token\nreplacement-api-key\n",
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(root),
        "ws://127.0.0.1:3001/",
        "replacement-token",
        "replacement-api-key",
        "run python main.py",
    ]
    assert "replacement-token" not in result.stdout + result.stderr
    assert "replacement-api-key" not in result.stdout + result.stderr


def test_start_script_rejects_empty_token(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", str(root / "scripts/start_echo.sh")],
        input="\n",
        text=True,
        capture_output=True,
        env={**os.environ, "NAPCAT_ACCESS_TOKEN": ""},
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0
    assert "Token 不能为空" in result.stderr


def test_start_script_rejects_empty_deepseek_api_key(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", str(root / "scripts/start_echo.sh")],
        input="replacement-token\n\n",
        text=True,
        capture_output=True,
        env={**os.environ, "DEEPSEEK_API_KEY": ""},
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0
    assert "API Key 不能为空" in result.stderr
