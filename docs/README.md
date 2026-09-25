# 文档索引

安装和运行方式见仓库根目录的 [README](../README.md)。这里按用途列出其余文档。

## 规划与架构

- [任务Checklist.md](任务Checklist.md) — Task 1–11 的总打勾进度；完成一个子项就更新一个勾。
- [里程碑Checklist.md](里程碑Checklist.md) — 当前阶段和真实 QQ 验收记录。
- [superpowers/specs/2026-09-23-qq-bot-mvp-design.md](superpowers/specs/2026-09-23-qq-bot-mvp-design.md) — 已批准的 echo 与单轮 LLM MVP 设计。
- [superpowers/specs/2026-09-24-ai-groupmate-expansion-design.md](superpowers/specs/2026-09-24-ai-groupmate-expansion-design.md) — 已批准的 AI 群友扩展总设计与 Task 7–11 顺序。
- [superpowers/specs/2026-09-24-task8-groupmate-behavior-design.md](superpowers/specs/2026-09-24-task8-groupmate-behavior-design.md) — 已批准的 Task 8 群友行为、人格与费用专项设计。
- [superpowers/specs/2026-09-25-task9-local-dashboard-design.md](superpowers/specs/2026-09-25-task9-local-dashboard-design.md) — 已批准的 Task 9 本地浏览器后台设计。
- [superpowers/plans/2026-09-23-qq-bot-mvp.md](superpowers/plans/2026-09-23-qq-bot-mvp.md) — 逐任务实施计划和 Task/Step 勾选。
- [superpowers/plans/2026-09-24-task7-image-understanding.md](superpowers/plans/2026-09-24-task7-image-understanding.md) — 已批准并执行的 Task 7 识图实施计划。
- [superpowers/plans/2026-09-24-task8-groupmate-behavior.md](superpowers/plans/2026-09-24-task8-groupmate-behavior.md) — 已批准并执行的 Task 8 群友行为实施计划。
- [superpowers/plans/2026-09-25-task9-local-dashboard.md](superpowers/plans/2026-09-25-task9-local-dashboard.md) — Task 9 本地后台逐任务实施计划。
- [QQ机器人工程化设计文档.md](QQ机器人工程化设计文档.md) — 长期目标架构的参考选项；MVP 不要求一次实现全部内容。

## 工程规范与流程

- [Task6测试指南.md](Task6测试指南.md) — 使用启动窗口完成自动化、私聊、群聊和停止验收。
- [Task7测试指南.md](Task7测试指南.md) — 验证默认关闭、真实识图、失败隔离和每日额度。
- [Task8测试指南.md](Task8测试指南.md) — 验证人格、上下文、群聊触发、费用边界及组合识图。
- [Task9测试指南.md](Task9测试指南.md) — 浏览器后台登录、配置、启动停止和真实 Mac 验收。
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
