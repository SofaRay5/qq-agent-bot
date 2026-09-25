# QQ Agent Bot

基于 NapCat（OneBot v11 正向 WebSocket）和 DeepSeek 的 QQ 机器人。已在真实 QQ 上验证基础私聊、群聊 @、NapCat 重启后的自动重连及 DeepSeek 生成回复。群友行为已通过自动化测试，等待真实群聊验收。

## 运行机器人

需要 Python 3.13+、`uv` 和已登录 QQ 的 NapCat。在 NapCat「网络配置」中启用 **WebSocket 服务端**，监听 `127.0.0.1:3001`，消息格式选 `array`，并设置 WebSocket Token。它与 NapCat WebUI 登录密钥不同。

推荐使用本地浏览器后台启动：

```bash
uv sync
bash scripts/start_dashboard.sh
```

首次打开 `http://127.0.0.1:8765/` 时创建管理密码。登录后在“模型与连接”填写 NapCat 地址、Token、DeepSeek 聊天模型和 API Key，再到“行为设置”和“人格”检查配置，最后在状态页点击“启动机器人”。后台只监听本机回环地址；浏览器关闭不会停止机器人，状态页的“停止机器人”或终端 `Ctrl+C` 会停止它。

完整步骤和真实 Mac 验收见 [Task 9 测试指南](docs/Task9测试指南.md)。

备用的文件和环境变量启动方式仍可用：

```bash
uv sync
cp config/settings.example.json config/settings.json
cp config/persona.example.json config/persona.json
bash scripts/start_bot.sh
```

`settings.json` 控制持续对话窗口、次数、每日调用额度、主动参与和回复节奏；`persona.json` 是角色卡，可按需填写。两份本地文件都被 Git 忽略。主动参与默认关闭。

Tkinter 启动窗口仍可通过 `uv run python scripts/start_ui.py` 使用。它只把密钥放入子进程环境，不写入配置文件；窗口关闭会结束机器人进程。WebSocket Token 与 NapCat WebUI 登录密钥不同。

命令行备用启动方式为 `bash scripts/start_echo.sh`。

私聊会保留本次进程内的近期上下文。群聊可通过 @ 机器人、回复机器人发出的消息，或用人格名称开头来触发；触发后同群消息会在受限窗口内持续对话。上下文不会跨重启保存。识图默认关闭；符合回复条件的图片会收到“识图尚未开启”。

如需测试识图，在启动窗口勾选“启用识图”，再填写视觉 API 地址、支持图片输入的模型名和视觉 API Key。未勾选时，窗口会明确关闭识图，不会继承终端中残留的视觉配置。

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
