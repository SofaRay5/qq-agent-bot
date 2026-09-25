# QQ Agent Bot

基于 NapCat（OneBot v11 正向 WebSocket）和 DeepSeek 的 QQ 机器人。已在真实 QQ 上验证私聊、群聊 @、NapCat 重启后的自动重连及 DeepSeek 生成回复。

## 运行机器人

需要 Python 3.13+、`uv` 和已登录 QQ 的 NapCat。在 NapCat「网络配置」中启用 **WebSocket 服务端**，监听 `127.0.0.1:3001`，消息格式选 `array`，并设置 WebSocket Token。它与 NapCat WebUI 登录密钥不同。

```bash
uv sync
bash scripts/start_echo.sh
```

脚本依次提示输入 NapCat WebSocket Token 和 DeepSeek API Key，输入时不会回显。两者是不同的密钥，WebSocket Token 也不同于 NapCat WebUI 登录密钥。若端口不是 `3001`，先设置 `NAPCAT_WS_URL`（例如 `export NAPCAT_WS_URL='ws://127.0.0.1:3002/'`）。用另一个 QQ 号私聊机器人，或在群里 @ 机器人并发送文字，应收到 `deepseek-flash` 生成的回复。首次真实运行会产生少量 API 费用。按 Ctrl+C 退出。不要把密钥写入仓库或发到聊天中。

也可以使用本机窗口启动：

```bash
uv run python scripts/start_ui.py
```

在窗口中填写 WebSocket 地址、Token 和 API Key，点击“启动”；点击“停止”或关闭窗口会结束机器人进程。密钥输入框会隐藏文字，启动后清空，关闭窗口后不会保存。窗口显示的是进程状态；是否已连上 NapCat，请用 QQ 消息验证。启动错误的详情会显示在运行该命令的终端中。

当前是单轮回复，不会记住前文或调用工具。识图默认关闭；私聊图片或群内 @ 后的图片会收到“识图尚未开启”，普通文字仍按原方式回复。

如需测试识图，先在当前终端设置以下变量，再运行启动脚本：

```bash
export VISION_ENABLED=1
export VISION_API_BASE_URL='https://你的视觉服务地址/v1'
export VISION_MODEL='支持图片输入的模型名'
read -r -s VISION_API_KEY && export VISION_API_KEY
bash scripts/start_echo.sh
```

视觉接口须兼容 OpenAI 图片消息格式。每条消息最多处理第一张普通图片，每个本地日最多尝试视觉 API 5 次；计数保存在 Git 忽略的 `data/vision_usage.db`，服务商调用失败也计数。图片下载或模型调用失败时只发送一次“暂时无法回复，请稍后再试”，后续文字消息仍可继续使用。完整步骤见 [Task 7 测试指南](docs/Task7测试指南.md)。

## 开发进度

Task 1–6 已完成，NapCat echo 与 DeepSeek 回复均通过本地自动化和真实 QQ 验收。Task 7 代码与假服务测试已完成，等待真实 NapCat + 视觉模型验收。每次只做一个任务；完成并验证合适的阶段后可自主提交，但不自动推送或部署。

- [文档索引](docs/README.md)
- [Task 6 测试指南](docs/Task6测试指南.md)
- [Task 7 测试指南](docs/Task7测试指南.md)
- [路线图与验收记录](docs/里程碑Checklist.md)
- [任务总打勾清单](docs/任务Checklist.md)
- [Superpowers 实施计划与 Task 勾选](docs/superpowers/plans/2026-09-23-qq-bot-mvp.md)
