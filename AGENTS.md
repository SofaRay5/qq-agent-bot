# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project status

This is a **learning/practice project** for the user (a hands-on exercise in building a production-style
system, not just getting something to run). The user writes the code and design decisions themselves;
Codex's role here is primarily **review, targeted help, and boilerplate** — not driving core design.
See `docs/里程碑Checklist.md` for exactly which parts are meant to be user-driven (🧠) vs. AI-assistable (🤖)
at each milestone. Respect that split: don't preemptively design or implement the 🧠 items even if asked to
"just build it" — point back to the checklist and offer review/questions instead, unless the user explicitly
overrides this.

Current progress: **milestone 0 (project init) and milestone 1 (OneBot protocol data models) are done**
(see `docs/里程碑Checklist.md` for the full milestone list). `onebot_adapter/event.py` implements
`PrivateMessageEvent` / `GroupMessageEvent` / `HeartbeatEvent` with discriminated-union parsing and an
`UnknownEvent` fallback for unsupported event types — see `docs/README.md` for a full index of what's been
written so far (design docs, ADRs, protocol reference, dev workflow notes). Everything below `onebot_adapter/`
in the target architecture (core/, agent/, memory/, config/) is still unimplemented.

## Planning docs

- [`docs/QQ机器人工程化设计文档.md`](docs/QQ机器人工程化设计文档.md) — full architecture/design spec (target
  state). Read this before helping design or review any layer.
- [`docs/里程碑Checklist.md`](docs/里程碑Checklist.md) — milestone-by-milestone checklist with 🧠/🤖 split and
  acceptance criteria. Use this to gauge what stage the project is at and what's appropriate to help with.

## Target architecture (per the design doc)

Stack: **OneBot v11** (via NapCat, a headless QQNT-based implementation) for QQ connectivity +
**LangChain 1.0 / LangGraph** (`create_agent()`) for agent orchestration. Layers are intentionally decoupled
so any one of them (QQ implementation, LLM provider, storage backend) can be swapped without touching the
others:

```
onebot_adapter/   OneBot v11 protocol only: WS client, heartbeat/reconnect, event models (Pydantic),
                   message-segment <-> UnifiedMessage conversion. No business logic, no LLM awareness.
                   Event models done (event.py); WS client, action calls, and message.py conversion
                   are still unimplemented (milestone 2+).
core/              dispatcher.py wires adapter -> agent; session.py builds thread_id
                   (group: "group:{group_id}:user:{user_id}", private: "private:{user_id}");
                   sender.py handles chunked/rate-limited sending; middleware_pipeline.py for
                   permissions/blacklists (distinct from agent-level LLM middleware).
agent/             LangChain/LangGraph layer: builder.py assembles create_agent() with model/tools/
                   middleware/checkpointer; tools/ (Pydantic-schema'd, must catch their own exceptions
                   and return friendly errors rather than raising); middleware/ (rate limiting, content
                   filtering, logging); prompts.py (system prompt built dynamically per-call from user
                   context, not a static string).
memory/            Short-term = LangGraph checkpointer (SQLite dev / Redis prod), not hand-rolled.
                   Mid-term = user_profiles / user_styles SQL tables (nickname, personality, interests,
                   intimacy_score). Long-term = key_events table, optionally indexed into a vector store
                   (Chroma) once per-user event volume makes linear prompt-stuffing impractical — not
                   needed at MVP stage.
config/            Pydantic Settings (no scattered os.getenv); fail-fast validation on startup.
```

Key cross-cutting decisions worth knowing before touching any layer:
- Reply first, then update memory in a background `asyncio.create_task` — never block the user-facing
  reply on memory extraction (an extra LLM call).
- `agent/` must stay entirely unaware of OneBot; all protocol translation happens in
  `onebot_adapter/message.py` via `UnifiedMessage`.
- Forward WebSocket (bot connects to NapCat), not reverse — bot owns reconnection logic.
- go-cqhttp is dead; NapCat is the supported OneBot v11 implementation to target.

## Environment

- Python >= 3.13 (see `pyproject.toml`)
- Dependency management: **uv** (see `docs/decisions/ADR-001-dependency-tool.md` for why), lockfile
  `uv.lock` is committed. Install/sync deps with `uv sync`.

## Commands

```bash
uv sync                                    # install/sync dependencies
uv run pytest                              # run tests
uv run pre-commit run --all-files          # run all checks (ruff, ruff-format, mypy, pytest)
uv run pre-commit install                  # one-time: install the git commit hook
uv run python main.py                      # run the current (placeholder) entry point
```

See `docs/DEV_WORKFLOW.md` for the full commit/push cheat sheet, including how to handle a failing
pre-commit hook.

## Notes for future updates

As this project grows, update this file with:
- New commands as tooling is added (e.g. running the bot for real once `core/dispatcher.py` exists).
- Deviations from the design doc, once real implementation choices are made (the design doc is the plan,
  not necessarily the final word — keep this section in sync with what's actually true in the code).
