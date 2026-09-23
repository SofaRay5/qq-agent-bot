# QQ Agent Bot

基于 NapCat（OneBot v11 正向 WebSocket）的 QQ 机器人。当前 echo 版本已在真实 QQ 上验证私聊、群聊 @ 和 NapCat 重启后的自动重连；LLM 回复尚未接入。

## 运行 echo 机器人

需要 Python 3.13+、`uv` 和已登录 QQ 的 NapCat。在 NapCat「网络配置」中启用 **WebSocket 服务端**，监听 `127.0.0.1:3001`，消息格式选 `array`，并设置 WebSocket Token。它与 NapCat WebUI 登录密钥不同。

```bash
uv sync
bash scripts/start_echo.sh
```

脚本会单独提示输入 WebSocket Token，输入时不会回显。若端口不是 `3001`，先设置 `NAPCAT_WS_URL`（例如 `export NAPCAT_WS_URL='ws://127.0.0.1:3002/'`）。用另一个 QQ 号私聊机器人，或在群里 @ 机器人并发送文字，应收到原文回复。按 Ctrl+C 退出。不要把 Token 写入仓库或发到聊天中。

## 开发进度

已完成 NapCat echo 闭环；下一步按任务推进单轮 LLM 回复。每次只做一个任务，未获明确要求时不提交、推送或部署。

- [文档索引](docs/README.md)
- [路线图与验收记录](docs/里程碑Checklist.md)
- [Superpowers 实施计划与 Task 勾选](docs/superpowers/plans/2026-09-23-qq-bot-mvp.md)
