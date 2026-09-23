# Repository Guidelines

## Goal and Working Style

Build a usable QQ bot with OneBot v11 (NapCat) and an LLM. This is now an AI-assisted development project: agents may design, implement, test, and refactor requested features. Do not require the user to handwrite core logic. Ask for user decisions only when product behavior, external accounts, credentials, cost, or deployment choices cannot be inferred. Keep changes small, explain key tradeoffs, and verify the result.

## Current State and Roadmap

`onebot_adapter/event.py` parses private/group messages and heartbeats with an `UnknownEvent` fallback. The WebSocket client, text routing, and `main.py` echo entry point pass local fake NapCat tests; real QQ/NapCat acceptance is pending. LLM integration is not implemented. Follow [docs/里程碑Checklist.md](docs/里程碑Checklist.md): environment, NapCat echo loop, LLM reply MVP, then optional enhancements. The old hand-coding checklist is archived at [docs/archive/里程碑Checklist-学习版.md](docs/archive/里程碑Checklist-学习版.md) for historical reference only.

## Architecture

- `onebot_adapter/`: OneBot protocol and WebSocket I/O; no LLM logic.
- `core/`: message routing and coordination between adapter and agent.
- `agent/`: LLM orchestration; no OneBot imports.
- `memory/` and `config/`: add concrete behavior when required by the roadmap.
- `tests/`: pytest tests and JSON fixtures; `docs/`: design, references, and decisions.

Use forward WebSocket connections to NapCat. Treat [docs/QQ机器人工程化设计文档.md](docs/QQ机器人工程化设计文档.md) as background and target options, not a mandate to build every component before the MVP. Avoid speculative services, adapters, and storage layers.

## Development

Python >=3.13; use `uv` and the committed `uv.lock`.

```bash
uv sync
uv run pytest
uv run pre-commit run --all-files
uv run python main.py  # requires NAPCAT_WS_URL and NAPCAT_ACCESS_TOKEN
```

Follow [docs/CODING_STANDARDS.md](docs/CODING_STANDARDS.md). Test behavior at protocol boundaries and failure paths; keep credentials out of Git and logs. Update the roadmap and entry-point instructions when functionality changes. Do not mark real NapCat or LLM acceptance checks complete without exercising those services.
