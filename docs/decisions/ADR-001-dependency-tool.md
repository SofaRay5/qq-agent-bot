# ADR-001: 依赖管理工具选型

## 状态
已接受 / 2026-08-15

## Context
个人练手的小型项目，Python >= 3.13，只有本人一个开发者，不需要打包发布成 PyPI 包。
项目最终形态是一个部署在服务器上长期运行的机器人进程，需要能在 Windows（本地开发）和
Linux（部署）之间简单迁移，我本人挺偏好也加上 macOS 生产部署，因为和Linux很接近。跨平台只是"本地开发方便"的加分项，
不是硬性生产需求。 项目重度依赖 LangChain / LangGraph 这类版本迭代非常快的 AI 生态包
（LangChain 1.0 刚 GA，API 还在变动），依赖解析的准确性和 lockfile 的可靠性。

## Decision
使用 uv 作为依赖管理与虚拟环境工具，通过官方安装脚本安装，只锁定项目依赖版本
（`uv.lock`），不锁定 uv 自身版本。

## Alternatives Considered

**pip + venv**：最基础、零额外工具依赖，但没有 lockfile 机制，依赖版本靠
`requirements.txt` 手工维护，容易出现"本地能跑、换台机器装不出同样环境"的问题。
在依赖变动频繁的 AI 生态场景下，这个风险被放大，所以放弃。

**poetry**：生态成熟、文档丰富，lockfile 和依赖解析能力都不错，是三个选项里最接近
uv 的替代品。放弃的理由主要是速度和维护现状：poetry 的依赖解析在包数量上来后明显变慢，
而本项目要装的 LangChain 系列包体量不小；另外 uv 目前迭代速度和社区在 AI/LLM 项目里
的采用率都更高，长期维护成本预期更低。项目不需要用到 poetry 的打包发布能力，这部分
优势对本项目没有价值。

**uv（选定）**：依赖解析和安装速度显著快于前两者，原生支持 lockfile
（`uv.lock`），命令行体验（`uv add` / `uv sync` / `uv run`）比 poetry 更简洁，
跨平台支持完善，能满足 Windows 开发 + Linux 部署的场景。

## Consequences

（待补充——由你决定：统一用哪个命令装依赖、lockfile 是否提交进 git、
`.venv/` 如何处理、CI 引入时机等）
.venv要被.gitignore，lockfile提交进main branch，我把master branch名改成main，然后CI在后面几个里程碑再引入，用uv sync装依赖