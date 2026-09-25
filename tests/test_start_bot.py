import os
import subprocess
from pathlib import Path


def test_start_bot_script_opens_ui_from_repository_root(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$PWD" "$*" > "$CAPTURE_FILE"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    capture = tmp_path / "capture"
    env = os.environ.copy()
    env.update(PATH=f"{fake_bin}:{env['PATH']}", CAPTURE_FILE=str(capture))

    result = subprocess.run(
        ["bash", str(root / "scripts/start_bot.sh")],
        text=True,
        capture_output=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )

    assert result.returncode == 0
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(root),
        "run python scripts/start_ui.py",
    ]
