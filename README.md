# QQ Agent Bot

基于 NapCat（OneBot v11 正向 WebSocket）和 DeepSeek 的 QQ 机器人。已在真实 QQ 上验证基础私聊、群聊 @、NapCat 重启后的自动重连及 DeepSeek 生成回复。群友行为已通过自动化测试，等待真实群聊验收。

## 运行机器人

需要 Python 3.13+、`uv` 和已登录 QQ 的 NapCat。在 NapCat「网络配置」中启用 **WebSocket 服务端**，监听 `127.0.0.1:3001`，消息格式选 `array`，并设置 WebSocket Token。它与 NapCat WebUI 登录密钥不同。

```bash
uv sync
cp config/settings.example.json config/settings.json
cp config/persona.example.json config/persona.json
bash scripts/start_echo.sh
```

`settings.json` 控制持续对话窗口、次数、每日调用额度、主动参与和回复节奏；`persona.json` 是角色卡，可按需填写。两份本地文件都被 Git 忽略。主动参与默认关闭。

脚本依次提示输入 NapCat WebSocket Token 和 DeepSeek API Key，输入时不会回显。两者是不同的密钥，WebSocket Token 也不同于 NapCat WebUI 登录密钥。若端口不是 `3001`，先设置 `NAPCAT_WS_URL`（例如 `export NAPCAT_WS_URL='ws://127.0.0.1:3002/'`）。用另一个 QQ 号私聊机器人，或在群里 @ 机器人并发送文字，应收到 `deepseek-flash` 生成的回复。首次真实运行会产生少量 API 费用。按 Ctrl+C 退出。不要把密钥写入仓库或发到聊天中。

也可以使用本机窗口启动：

```bash
uv run python scripts/start_ui.py
```

在窗口中填写 WebSocket 地址、Token 和 API Key，点击“启动”；点击“停止”或关闭窗口会结束机器人进程。密钥输入框会隐藏文字，启动后清空，关闭窗口后不会保存。窗口显示的是进程状态；是否已连上 NapCat，请用 QQ 消息验证。启动错误的详情会显示在运行该命令的终端中。

私聊会保留本次进程内的近期上下文。群聊可通过 @ 机器人、回复机器人发出的消息，或用人格名称开头来触发；触发后同群消息会在受限窗口内持续对话。上下文不会跨重启保存。识图默认关闭；符合回复条件的图片会收到“识图尚未开启”。

如需测试识图，先在当前终端设置以下变量，再运行启动脚本：

```bash
export VISION_ENABLED=1
export VISION_API_BASE_URL='https://你的视觉服务地址/v1'
export VISION_MODEL='支持图片输入的模型名'
read -r -s VISION_API_KEY && export VISION_API_KEY
bash scripts/start_echo.sh
```

视觉接口须兼容 OpenAI 图片消息格式。每条消息最多处理第一张普通图片；文字、主动参与和识图共享 `settings.json` 中的每日调用额度，计数保存在 Git 忽略的 `data/model_usage.db`。服务商调用失败也计数。完整步骤见 [Task 8 测试指南](docs/Task8测试指南.md)。

## 开发进度

Task 1–6 已完成并通过真实 QQ 验收。Task 7 识图和 Task 8 群友行为的实现与自动化测试已完成，等待真实服务验收。每次只做一个任务；完成并验证合适的阶段后可自主提交，但不自动推送或部署。

- [文档索引](docs/README.md)
- [Task 6 测试指南](docs/Task6测试指南.md)
- [Task 7 测试指南](docs/Task7测试指南.md)
- [Task 8 测试指南](docs/Task8测试指南.md)
- [路线图与验收记录](docs/里程碑Checklist.md)
- [任务总打勾清单](docs/任务Checklist.md)
- [Superpowers 实施计划与 Task 勾选](docs/superpowers/plans/2026-09-23-qq-bot-mvp.md)
