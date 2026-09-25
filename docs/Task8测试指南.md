# Task 8 群友行为测试指南

Task 8 加入进程内上下文、人格、群聊持续对话和统一每日额度。主动参与与识图默认关闭。

## 1. 准备本地配置

在仓库根目录执行：

```bash
cp config/settings.example.json config/settings.json
cp config/persona.example.json config/persona.json
```

编辑 `config/persona.json`，至少填写 `name`、人物描述、性格和说话风格。群里用 `name` 开头可直接触发机器人。编辑 `config/settings.json` 可调整持续窗口、窗口内尝试/回复次数、回复间隔、发送延迟和每日额度。本地配置已被 Git 忽略。

先保持 `proactive_mode` 为 `off`。这样机器人不会主动插入未触发的群聊，也最省 API 费用。

## 2. 自动化检查

```bash
uv sync
uv run pytest -q
uv run pre-commit run --all-files
```

这些测试使用假 NapCat 和假模型，不产生 API 费用。

## 3. 启动

确认 NapCat 已启用 `127.0.0.1:3001` 的 WebSocket 服务端，消息格式为 `array`，然后执行：

```bash
bash scripts/start_echo.sh
```

依次输入 NapCat WebSocket Token 和 DeepSeek API Key。输入不会回显。按 `Ctrl+C` 停止。

## 4. 私聊与人格

1. 用另一个 QQ 私聊机器人发送“我叫阿明”，确认得到符合角色卡的回复。
2. 接着问“我刚才说我叫什么？”，确认回复能参考前文。
3. 重新启动机器人后再问一次，确认它不保证记得；持久记忆属于后续 Task 10。

## 5. 群聊触发与持续对话

在同一个群依次验证：

1. 普通发送一句话，机器人不应回复。
2. @ 机器人并提问，应回复并开启持续对话窗口。
3. 不 @ 再发一句相关消息，应继续回复。
4. 回复机器人刚发出的消息，应回复。
5. 用人格名称开头，例如“小薯，你怎么看？”，应回复并重置持续窗口。
6. 等待 `continuous_window_seconds` 后普通发言，机器人不应回复。

模型可以选择沉默，所以某一条没有回复不一定是故障；用明确的问题重复一次即可。达到 `window_max_attempts` 或 `window_max_replies` 后，本轮持续对话也会结束。

## 6. 回复节奏与额度

- `minimum_reply_interval_seconds`：明确触发会等待剩余冷却时间；普通持续消息在冷却期内会跳过。
- `send_delay_seconds`：模型决定回复后，模拟真人等待一小段时间再发送。
- `daily_model_calls`：聊天与识图合计的每日上限。
- `daily_proactive_calls`、`daily_vision_calls`：主动参与和识图的额外子上限。

额度保存在 `data/model_usage.db`，只含日期和计数。达到总额度时，明确触发会回复“今天的聊天额度用完了，明天再聊吧”；其他候选消息保持沉默。服务商失败也会消耗已预留的次数，下一条消息仍应能处理。

低额度验收步骤：

1. 停止机器人，将 `daily_model_calls` 临时改为 `2`，并确保两个子额度不大于 `2`。
2. 等到新的本地日期，或在机器人停止时删除 `data/model_usage.db`，再启动机器人。
3. 明确触发三次文字回复；第三次应收到“今天的聊天额度用完了，明天再聊吧”。
4. 如测试识图，将 `daily_vision_calls` 临时改为 `1`；第一次识图后再次明确触发图片，应收到“今天暂时不能识图了”。
5. 测完恢复原额度并停止机器人。不要在机器人运行时修改数据库。

## 7. 主动参与（可选）

默认无需测试。要测试时，将 `proactive_mode` 改为 `random`、`topic` 或 `both`，并临时提高 `proactive_probability`。重启后在未触发的群聊发言，观察机器人是否偶尔参与。完成后改回 `off`，避免额外费用。

## 8. Task 7 + Task 8 组合验收

视觉服务可能收费。按 [Task 7 测试指南](Task7测试指南.md)设置 `VISION_ENABLED=1`、视觉地址、模型和密钥后启动：

1. 私聊发送图片并提问，回复应参考图片。
2. 群内 @ 机器人并发送图片，应回复并开启持续窗口。
3. 窗口内不 @ 再发送一张图片，应继续处理。
4. 关闭识图后重启，符合触发条件的图片应回复“识图尚未开启”，文字仍可聊天。
5. 停止机器人，确认终端日志没有密钥、人格正文、聊天正文或图片 URL。

完成真实 NapCat、DeepSeek 和视觉模型检查后，把结果告诉开发代理。此前 `docs/任务Checklist.md` 中 Task 7 与 Task 8 的真实验收保持未勾选。
