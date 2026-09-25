"""Optional local window for starting the QQ bot."""

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Literal
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def launch_bot(
    url: str,
    token: str,
    api_key: str,
    *,
    vision_enabled: bool = False,
    vision_base_url: str = "",
    vision_model: str = "",
    vision_api_key: str = "",
) -> subprocess.Popen[bytes]:
    """Start main.py with credentials only in the child process environment."""
    if not url.strip() or not token.strip() or not api_key.strip():
        raise ValueError("请填写 WebSocket 地址、Token 和 API Key")
    env = os.environ.copy()
    env.update(
        NAPCAT_WS_URL=url.strip(),
        NAPCAT_ACCESS_TOKEN=token.strip(),
        DEEPSEEK_API_KEY=api_key.strip(),
    )
    if vision_enabled:
        if not vision_base_url.strip() or not vision_model.strip() or not vision_api_key.strip():
            raise ValueError("启用识图后请填写视觉 API 地址、模型名和 API Key")
        try:
            parts = urlsplit(vision_base_url.strip())
            _ = parts.port
        except ValueError:
            raise ValueError("视觉 API 地址必须是有效的 HTTPS 地址") from None
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
        ):
            raise ValueError("视觉 API 地址必须是有效的 HTTPS 地址")
        env.update(
            VISION_ENABLED="1",
            VISION_API_BASE_URL=vision_base_url.strip(),
            VISION_MODEL=vision_model.strip(),
            VISION_API_KEY=vision_api_key.strip(),
        )
    else:
        env["VISION_ENABLED"] = "0"
        for name in ("VISION_API_BASE_URL", "VISION_MODEL", "VISION_API_KEY"):
            env.pop(name, None)
    return subprocess.Popen([sys.executable, str(ROOT / "main.py")], cwd=ROOT, env=env)


def stop_bot(process: subprocess.Popen[bytes]) -> None:
    """Stop the child before closing the window."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> None:
    """Show a small local start/stop window."""
    window = tk.Tk()
    window.title("QQ 机器人")
    window.resizable(False, False)
    form = tk.Frame(window, padx=16, pady=16)
    form.pack()
    url = tk.StringVar(value="ws://127.0.0.1:3001/")
    token = tk.StringVar()
    api_key = tk.StringVar()
    vision_enabled = tk.BooleanVar(value=False)
    vision_url = tk.StringVar(value="https://")
    vision_model = tk.StringVar()
    vision_api_key = tk.StringVar()
    status = tk.StringVar(value="未启动")
    for row, (label, value, secret) in enumerate(
        (
            ("WebSocket 地址", url, False),
            ("NapCat Token", token, True),
            ("DeepSeek API Key", api_key, True),
        )
    ):
        tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
        tk.Entry(form, textvariable=value, show="*" if secret else "", width=36).grid(
            row=row, column=1, pady=4
        )

    vision_entries: list[tk.Entry] = []
    for row, (label, value, secret) in enumerate(
        (
            ("视觉 API 地址", vision_url, False),
            ("视觉模型", vision_model, False),
            ("视觉 API Key", vision_api_key, True),
        ),
        start=4,
    ):
        tk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = tk.Entry(
            form,
            textvariable=value,
            show="*" if secret else "",
            width=36,
            state="disabled",
        )
        entry.grid(row=row, column=1, pady=4)
        vision_entries.append(entry)

    def toggle_vision() -> None:
        state: Literal["normal", "disabled"] = "normal" if vision_enabled.get() else "disabled"
        for entry in vision_entries:
            entry.config(state=state)

    tk.Checkbutton(
        form,
        text="启用识图",
        variable=vision_enabled,
        command=toggle_vision,
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

    process: subprocess.Popen[bytes] | None = None

    def start() -> None:
        nonlocal process
        try:
            process = launch_bot(
                url.get(),
                token.get(),
                api_key.get(),
                vision_enabled=vision_enabled.get(),
                vision_base_url=vision_url.get(),
                vision_model=vision_model.get(),
                vision_api_key=vision_api_key.get(),
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("无法启动", str(exc))
            return
        token.set("")
        api_key.set("")
        vision_api_key.set("")
        status.set("进程运行中；请在 QQ 中验证连接")
        start_button.config(state="disabled")
        stop_button.config(state="normal")

    def stop() -> None:
        nonlocal process
        if process is not None:
            stop_bot(process)
            process = None
        status.set("已停止")
        start_button.config(state="normal")
        stop_button.config(state="disabled")

    def poll() -> None:
        nonlocal process
        if process is not None and (code := process.poll()) is not None:
            process = None
            status.set(f"进程已退出（代码 {code}）；错误详情见终端")
            start_button.config(state="normal")
            stop_button.config(state="disabled")
        window.after(500, poll)

    buttons = tk.Frame(form)
    buttons.grid(row=7, column=0, columnspan=2, pady=8)
    start_button = tk.Button(buttons, text="启动", command=start)
    start_button.pack(side="left", padx=8)
    stop_button = tk.Button(buttons, text="停止", command=stop, state="disabled")
    stop_button.pack(side="left", padx=8)
    tk.Label(form, textvariable=status).grid(row=8, column=0, columnspan=2)

    def close() -> None:
        stop()
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close)
    window.after(500, poll)
    window.mainloop()


if __name__ == "__main__":
    main()
