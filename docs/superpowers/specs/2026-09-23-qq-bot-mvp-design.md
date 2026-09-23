# QQ 机器人最小可运行闭环设计

日期：2026-09-23

## 目标与范围

在现有 Python 项目中完成 OneBot v11（NapCat）正向 WebSocket 到 QQ 回复的闭环，先以 echo 验收，再接入一个 LLM。项目应让 AI 能按清晰的模块边界持续开发，但只增加这条链路需要的代码、配置、日志、测试和运行说明。

第一阶段交付可运行的 echo 机器人；第二阶段使用 OpenAI GPT-6 Luna 生成单轮文本回复。两阶段分别验收，真实 NapCat 和真实 LLM 检查只有实际执行后才能标记完成。记忆、工具、数据库、Web 服务、部署及 CI 留待出现具体需求。

现状：`onebot_adapter/event.py` 已解析私聊、群聊和心跳事件，并对未知事件返回 `UnknownEvent`；`main.py` 仍是占位。现有工作区有未提交文档修改，实施时必须保留。

## 技术选择

- 沿用 Python >=3.13、`uv` 和现有 Pydantic 事件模型。
- 使用 NapCat 的 OneBot v11 正向 WebSocket 服务端；机器人主动连接其 `/` 路径，在同一连接上接收事件和发送 action。NapCat 将 `messagePostFormat` 配为 `array`，启用 token。
- 使用 `websockets` 的 asyncio 客户端及其内置重连退避，避免自写重连状态机。
- LLM 阶段使用 LangChain `create_agent` 和 OpenAI 集成包；`create_agent` 使用 LangGraph 运行时，但本 MVP 不配置工具或 checkpointer。模型为 `gpt-6-luna`。

这些选择以 [OneBot v11 正向 WebSocket 规范](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)、[NapCat 配置定义](https://github.com/NapNeko/NapCatQQ/blob/main/packages/napcat-onebot/config/config.ts)、[websockets asyncio 客户端文档](https://websockets.readthedocs.io/en/latest/reference/asyncio/client.html)、[LangChain agent 文档](https://docs.langchain.com/oss/python/langchain/agents) 和 [OpenAI 聊天模型集成文档](https://docs.langchain.com/oss/python/integrations/chat/openai) 为准。具体依赖版本由实施计划结合 `uv.lock` 决定。

## 组件与边界

| 位置 | 职责 | 依赖边界 |
| --- | --- | --- |
| `onebot_adapter/event.py` | 保留现有事件模型和 `parse_event()` | 不引入 LLM 逻辑 |
| `onebot_adapter/client.py` | 建立连接、接收 JSON、区分事件与 action 结果、匹配 `echo`、发送私聊或群聊消息、处理超时和断线 | 只理解 OneBot 协议 |
| `core/dispatcher.py` | 过滤消息、提取文本、去重、调度回复任务并选择发送目标 | 使用 adapter，调用一个接收文本并返回文本的回复函数 |
| `agent/` | 在第二阶段封装一次异步 `create_agent` 调用，把用户文本转为回复文本 | 不导入 OneBot 类型 |
| `main.py` | 读取环境变量、验证启动配置、组装并运行上述组件 | 唯一的程序入口 |

不为单一实现新增工厂、通用 provider 接口或中间件管线。Echo 阶段的回复函数直接返回输入文本；LLM 阶段将同一调用点接到 `agent/`。

## 消息流程与行为

1. 启动时读取 `NAPCAT_WS_URL`（指向 `/` 路径）、`NAPCAT_ACCESS_TOKEN`；缺项或空值直接报出配置项名称并退出。token 通过 `Authorization: Bearer` 连接鉴权头传递，日志不输出 token 或完整鉴权头。第二阶段启动还要求 `OPENAI_API_KEY`。凭据仅从环境变量读取，不提交 `.env`。
2. 客户端连接 NapCat 的 `/` WebSocket 路径。接收循环先解码 JSON：带 `echo` 的 action 结果交给对应等待者；其他对象交给现有 `parse_event()`。心跳仅用于连接可见性，未知事件忽略，格式错误的帧或已知事件只记录无正文的错误并继续读取。
3. `core` 跳过 `user_id == self_id` 的消息。私聊只处理含文本的消息；群聊只处理包含 `at` 段且其 `qq` 指向 `self_id` 的消息。群聊从该 @ 段之后提取文本，去掉 @ 段；纯空白文本不回复。图片、表情和其他非文本段不进入回复函数。
4. Echo 阶段回显提取出的文本。LLM 阶段以该文本作为一次独立输入，返回纯文本；没有跨消息记忆、工具调用或用户画像。私聊调用 `send_private_msg`，群聊调用 `send_group_msg`。
5. 同一进程内用最多 1024 个近期 `message_id` 去重，符合条件的消息在启动回复任务前记入，同一 ID 只处理一次；重启后不保留去重记录。接收循环不等待回复生成：每条符合条件的消息由独立任务处理，程序退出时取消并收尾任务。

## action 与故障处理

- 每个 action 使用唯一的 `echo`，等待结果最多 10 秒。结果必须检查 `status`/`retcode`；失败向调用方报告，而不是把收到响应当作发送成功。
- 连接断开时，所有等待中的 action 立即失败并从待处理表移除；新连接建立后继续接收事件。断线期间的发送立即失败，已发出的 action 不自动重发，以免重复回复。
- LLM 调用最多等待 30 秒。超时、限流或提供方错误时，给用户发送固定提示“暂时无法回复，请稍后再试”；只在日志记录错误类别。若发送提示本身失败，仅记录错误，不再次发送。
- 日志记录启动、连接、重连、action 失败及 LLM 失败；不记录密钥、完整消息正文或原始 action 帧。

## 阶段与验收

### 阶段 A：NapCat echo

- 增加 WebSocket 客户端、最薄路由、环境配置和入口；复用已有事件模型。
- 用本地假 WebSocket 服务验证：私聊和群聊 @ 触发回复，其他群聊不触发；action `echo` 与响应匹配；超时和断线解除等待；重连后继续接收。
- 更新启动说明和路线图。运行 `uv sync`、`uv run pytest`、`uv run pre-commit run --all-files`。在真实 NapCat 上收发消息并重启 NapCat 验证恢复；若缺少服务或账号，将真实验收保持未完成，暂不进入阶段 B。

### 阶段 B：LLM 回复

- 加入 LangChain/OpenAI 所需依赖和最小 `agent/` 调用，替换 echo 回复函数；启动时检查 API key。
- 用假的回复函数或模型调用验证正常回复、超时与失败提示，不让测试调用付费 API；保留假 WebSocket 的全链路自动化检查。
- 更新运行说明和路线图，再执行相关检查。用真实 API 在 QQ 中验证回复，并确认一次失败后后续消息仍能处理；若缺少凭据，将真实验收保持未完成。

## 已知限制

MVP 仅处理文本；不提供长消息分段、持久去重、多轮记忆或消息重试。若实际 NapCat 或 OpenAI 行为与假服务不同，先依据真实服务反馈修正协议边界，再扩展功能。
