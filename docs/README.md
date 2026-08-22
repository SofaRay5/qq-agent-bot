# 文档目录

当前进度：**里程碑 0（项目初始化）✅ 完成**，**里程碑 1（OneBot 协议数据模型）✅ 完成**。
下一步是里程碑 2（OneBot WebSocket 客户端）。

## 规划与架构

- [QQ机器人工程化设计文档.md](QQ机器人工程化设计文档.md) — 完整目标架构设计（技术选型、
  各层职责、代码结构、Docker 部署方案）。动手设计任何一层之前先看这个。
- [里程碑Checklist.md](里程碑Checklist.md) — 逐里程碑执行清单，标注了哪些必须自己做（🧠）、
  哪些可以让 AI 协助（🤖），以及每个里程碑的验收标准。

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
