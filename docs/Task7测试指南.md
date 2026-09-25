# Task 7 识图测试指南

Task 7 默认关闭识图，不影响现有 DeepSeek 文字回复。真实视觉服务可能收费；视觉调用受 `config/settings.json` 的 `daily_vision_calls` 和 `daily_model_calls` 共同限制，服务商调用失败也会占用一次。

## 1. 自动化检查

在仓库根目录运行：

```bash
uv sync
uv run pytest -q
uv run pre-commit run --all-files
```

三条命令都成功后再测试 QQ。自动化测试使用假 NapCat 和假模型，不产生 API 费用。

## 2. 确认 NapCat

1. 登录 NapCat WebUI。
2. 在“网络配置”启用 WebSocket 服务端，地址使用 `127.0.0.1:3001`。
3. 消息格式选择 `array`。
4. 确认 WebSocket Token 已设置。它不是 WebUI 登录密钥。

## 3. 验证默认关闭

不要设置 `VISION_ENABLED`，按原方式启动：

```bash
bash scripts/start_echo.sh
```

依次验证：

1. 用另一个 QQ 私聊机器人发送一张普通图片，应回复“识图尚未开启”。
2. 在群里不 @ 机器人发送图片，应不回复。
3. 在群里 @ 机器人并发送图片，应回复“识图尚未开启”。
4. 再发送普通文字，应继续得到 DeepSeek 回复。
5. 按 `Ctrl+C` 停止机器人。

这些步骤不会调用视觉 API，也不会占用每日次数。

## 4. 配置视觉模型

准备一个兼容 OpenAI 图片消息格式的视觉接口，并确认模型本身支持图片输入。不要把密钥写进文件或提交到 Git。

```bash
export VISION_ENABLED=1
export VISION_API_BASE_URL='https://你的视觉服务地址/v1'
export VISION_MODEL='支持图片输入的模型名'
read -r -s VISION_API_KEY
printf '\n'
export VISION_API_KEY
bash scripts/start_echo.sh
```

启动脚本还会依次询问 NapCat WebSocket Token 和 DeepSeek API Key。三个密钥都不会回显。

## 5. 验证真实识图

1. 私聊发送一张 JPEG、PNG 或 WebP 图片，并附一句“图里有什么？”。
2. 确认回复同时参考了文字和图片内容。
3. 在群里 @ 机器人后发送一张图片，确认得到识图回复。
4. 一条消息放两张图片时，只应使用第一张普通图片。
5. 按 `Ctrl+C` 停止机器人。

程序只从受限的 QQ 图片域名下载，拒绝跳转、私网地址、非图片内容和超过 8 MiB 的响应。真实 NapCat 若提供了未在允许列表中的图片域名，机器人会回复固定失败提示；记录该域名形态后再收窄地补充允许列表，不要直接放开任意网址。

## 6. 验证失败后仍能聊天

为了少花费用，可临时把 `VISION_MODEL` 改成一个不存在的名称后启动：

1. 发送一张图片，应只收到一次“暂时无法回复，请稍后再试”。这次服务商尝试会计入每日额度。
2. 紧接着发送普通文字，应仍能得到 DeepSeek 回复。
3. 按 `Ctrl+C` 停止，然后恢复正确的模型名。

## 7. 验收记录

确认第 3、5、6 节结果后，告诉开发代理实际结果。只有真实 NapCat 和真实视觉模型都测试成功，才在 `docs/任务Checklist.md` 勾选 Task 7 的最终验收。

每日用量只保存日期和次数，文件位于 `data/model_usage.db`；图片、图片 URL、聊天正文、人格和密钥不会写入该数据库。需要重新测试新的一天额度时等待本地日期变化，不要在机器人运行时修改数据库。
