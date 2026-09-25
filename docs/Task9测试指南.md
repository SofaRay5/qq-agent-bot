# Task 9 本地浏览器后台测试指南

这份指南适用于 macOS 本地测试。后台固定监听 `127.0.0.1:8765`，不会开放到局域网。

## 1. 启动后台

在仓库根目录执行：

```bash
uv sync
bash scripts/start_dashboard.sh
```

命令会启动后台并打开浏览器。若浏览器没有自动打开，手动访问 <http://127.0.0.1:8765/>。

首次使用：

1. 创建至少 10 个字符的管理密码。
2. 登录后台。
3. 以后每次启动后台都使用这个密码登录。

密码哈希保存在 `data/admin_auth.json`，不会保存明文。忘记密码时，先停止后台，再删除这个文件并重新启动；这会重新进入首次设置流程。

## 2. 填写配置

在“模型与连接”页面填写：

1. NapCat WebSocket 地址，例如 `ws://127.0.0.1:3001/`。
2. NapCat WebSocket Token。
3. 聊天模型选择 DeepSeek，填写 API Key；也可以选择 OpenAI 兼容服务并填写 HTTPS 地址、模型名和 Key。
4. 识图默认关闭。只有在视觉服务支持图片输入时才打开，并单独填写视觉服务配置。

保存后页面不会显示完整 Token 或 API Key。密钥输入框留空表示保持旧值，勾选清除才会删除。修改 NapCat 地址或 Token 后，先停止再重新启动机器人。

在“行为设置”检查主动模式、回复速度、上下文限制和每日额度；在“人格”页面检查角色卡。保存成功后，后续新消息使用新配置，已开始的请求继续使用原配置。

## 3. 启动和停止机器人

1. 确认 NapCat 已登录，并启用正向 WebSocket 服务端。
2. 在后台状态页点击“启动机器人”。
3. 状态应经历启动中，随后显示已连接或重连中。
4. 用 QQ 发一条明确的私聊消息验证回复。
5. 点击“停止机器人”，状态应回到已停止。

后台启动的是同一个 `BotManager`，重复点击不会创建多个机器人任务。状态页只显示连接状态、当日调用计数、剩余额度和安全错误类别，不显示聊天正文、图片地址或完整模型响应。

## 4. 自动化检查

只检查后台相关功能：

```bash
env UV_CACHE_DIR=/tmp/qq-agent-uv-cache uv run pytest \
  tests/test_dashboard_app.py tests/test_dashboard_auth.py \
  tests/test_dashboard_runtime.py tests/test_dashboard_entrypoint.py -q
```

Task 9.6 结束时执行完整工程检查：

```bash
uv run pre-commit run --all-files
git diff --check
```

## 5. 真实 Mac 验收

按下面顺序逐项验证，并把结果反馈给开发代理：

1. 一条命令启动后台并打开浏览器。
2. 首次创建密码，退出后重新登录。
3. 保存 NapCat、聊天模型和可选识图模型配置。
4. 启动机器人，在真实 QQ 中完成私聊文字回复。
5. 在后台修改回复速度或人格，确认下一条消息使用新配置。
6. 修改 NapCat 地址或 Token，确认页面提示重启机器人。
7. 停止并重新启动机器人，确认不会出现重复回复任务。
8. 核对连接状态、调用量、剩余额度和错误类别。
9. 核对页面不显示完整密钥、聊天正文、图片 URL 或本机私有路径。
10. 如果启用识图，再按 [Task 7 测试指南](Task7测试指南.md)完成真实图片验收。

真实 NapCat、QQ、DeepSeek 和视觉服务通过前，`docs/任务Checklist.md` 中的真实验收项目保持未勾选。

## 6. 备用启动方式

- `bash scripts/start_bot.sh`：命令行环境变量入口，适合排错。
- `uv run python scripts/start_ui.py`：Tkinter 启动窗口，适合不使用浏览器后台时启动。
- 后台或命令行运行时按 `Ctrl+C`，会先停止机器人再退出服务。
