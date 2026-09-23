# 文档目录

当前进度：echo 机器人入口已可运行，本地假 NapCat 测试覆盖私聊和群聊 @ 收发；真实 NapCat 尚未验收，LLM 回复尚未接入。
按实施计划一次推进一个任务，每个任务结束后等待用户明确启动下一任务；不自动提交 Git。

## 运行 echo 机器人

在 NapCat 启用 OneBot v11 **正向 WebSocket** 服务，将 `messagePostFormat` 设为 `array`，设置访问令牌，并使用服务根路径 `/`（例如 `ws://127.0.0.1:3001/`）。令牌与下面的环境变量值保持一致；不要把令牌写入仓库或命令日志。

```bash
uv sync
export NAPCAT_WS_URL='ws://127.0.0.1:3001/'
export NAPCAT_ACCESS_TOKEN='你的 NapCat 访问令牌'
uv run python main.py
```

在 QQ 私聊机器人发送文本，或在群里 @ 机器人后发送文本，应收到原文回复。重启 NapCat 后再发送一条消息，用于确认自动重连。退出时按 Ctrl+C。当前仅处理数组格式的文本消息；其他消息段暂不作为回复内容。

## 规划与架构

- [QQ机器人工程化设计文档.md](QQ机器人工程化设计文档.md) — 完整目标架构设计（技术选型、
  各层职责、代码结构、Docker 部署方案）。动手设计任何一层之前先看这个。
- [里程碑Checklist.md](里程碑Checklist.md) — 按可运行成果推进的路线图和验收标准；
  AI 可以实现核心代码，用户决定目标并验收。
- [superpowers/specs/2026-09-23-qq-bot-mvp-design.md](superpowers/specs/2026-09-23-qq-bot-mvp-design.md) — 已批准的 echo 与单轮 LLM MVP 设计。
- [superpowers/plans/2026-09-23-qq-bot-mvp.md](superpowers/plans/2026-09-23-qq-bot-mvp.md) — 已批准的逐任务实施计划与当前进度。

## 工程规范与流程

- [CODING_STANDARDS.md](CODING_STANDARDS.md) — 编码规范：类型标注/docstring、异常处理、
  日志 vs print、模块跨层调用边界。
- [DEV_WORKFLOW.md](DEV_WORKFLOW.md) — 日常开发流程速查：commit/push 步骤、commit
  message 前缀、pre-commit 卡住了怎么处理。

## 决策记录（decisions/）

- [decisions/ADR-001-dependency-tool.md](decisions/ADR-001-dependency-tool.md) — 依赖
  管理工具选型（uv vs poetry vs pip+venv），含权衡过程。

## 协议参考资料（reference/）

- [reference/onebot-v11-events.md](reference/onebot-v11-events.md) — OneBot v11 官方
  文档四大类事件（message/notice/request/meta_event）的字段整理。
- [reference/onebot-v11-event-hierarchy.md](reference/onebot-v11-event-hierarchy.md) —
  事件类型层级图（`post_type → sub_type`，Mermaid 格式），附看图重点说明。

## 学习笔记（journal/）

- [journal/pre-commit检查项笔记.md](journal/pre-commit检查项笔记.md) — pre-commit 四项
  检查（ruff/ruff-format/mypy/pytest）分别查什么。

## 临时/存档（tmp/）

- [tmp/milestone1-plan.md](tmp/milestone1-plan.md) — 里程碑 1 的分步执行计划存档。
- [archive/里程碑Checklist-学习版.md](archive/里程碑Checklist-学习版.md) — 原手写练习清单，
  仅作历史记录，不再约束后续开发。
