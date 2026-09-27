# Task 10 SQLite Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user wants one numbered task completed per “下一个任务”; stop after each numbered task. Commits are allowed after verified tasks, but never push or deploy without an explicit request.

**Goal:** Add scoped, versioned SQLite long-term memory with automatic extraction, bounded recall, owner management and a simpler local dashboard.

**Architecture:** Keep Task 8 short-term context in memory and add a standard-library SQLite store beside it. The coordinator retrieves low-privilege memory before a reply and submits bounded extraction candidates after a successful send; one background worker serializes extraction. The existing aiohttp dashboard manages memory and uses one primary model configuration with optional memory and vision overrides.

**Tech Stack:** Python 3.13+, stdlib `sqlite3`/`asyncio`, Pydantic, LangChain `ChatOpenAI`, aiohttp, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-task10-sqlite-memory-design.md`

## Global Constraints

- Preserve OneBot, agent and core boundaries; `memory/` must not import OneBot types.
- Keep Task 8 short-term history in memory; do not add LangGraph, embeddings, vector databases or a managed memory service.
- Store only atomic memory and a source excerpt of at most 300 characters; never persist full conversations, bot replies or images.
- Private memories must never be candidates in groups; group memories must never cross groups.
- Recall at most 5 current versions and at most 1500 total characters.
- Old versions remain reviewable but never enter reply prompts; deleting an item permanently deletes its whole version chain.
- Default memory provider follows the primary chat provider; independent memory settings are optional.
- Default `daily_memory_calls` is 10 and memory reservations also consume `daily_model_calls`.
- Dashboard remains localhost-only, owner-authenticated and CSRF-protected; secrets are never echoed.
- Keep the Tkinter and environment-variable startup paths working.
- Preserve the user's unstaged `config/persona.example.json` and `config/settings.example.json` edits.
- Run focused tests per numbered task; run one full `uv run pre-commit run --all-files` only in Task 8.

## Review Focus

- Existing or partially migrated SQLite files: initialize or migrate atomically without clearing valid rows; malformed schemas disable memory without breaking chat.
- Invalid and adversarial scope identifiers: reject zero/negative IDs and every private-to-group or cross-group update before SQL mutation.
- Chinese queries with little exact overlap and explicit “你记得什么”: return bounded useful results without injecting unrelated scopes.
- Blank, cleared and inherited model secrets: following the primary provider must not copy secrets into HTML or accidentally erase persisted keys.
- Shutdown and queue saturation during extraction: bound pending work, finish the active write and never persist queued raw conversations.

---

### Task 1: 10.1 Versioned SQLite Memory Store

**Files:**
- Create: `memory/store.py`
- Create: `tests/test_memory_store.py`

**Interfaces:**
- Produces: `MemoryScope`, `MemoryContext`, `MemorySource`, `MemoryRecord`, `MemoryVersion`, `MemoryStore`.
- `MemoryStore(path: Path)` exposes async `initialize() -> None`, `create(scope, kind, content, importance, source, created_by) -> MemoryRecord`, `update(item_id, content, importance, source, created_by) -> MemoryRecord`, `recall(context, query, limit=5, max_characters=1500) -> tuple[MemoryRecord, ...]`, `list_current(scope=None, kind=None, query="", limit=50, offset=0) -> tuple[MemoryRecord, ...]`, `history(item_id) -> tuple[MemoryVersion, ...]`, `copy(item_id, target_scope) -> MemoryRecord`, `delete(item_id) -> None` and `clear(scope) -> int`.
- `MemoryScope` constructors validate `private(user_id)`, `group_user(group_id, user_id)` and `group_shared(group_id)`.

- [x] **Step 1: Write failing schema and scope tests.**

Assert initialization creates only `memory_items` and `memory_versions`, enables foreign keys and WAL, accepts all three valid scopes, rejects zero/negative or malformed ID combinations, and ignores no existing valid rows on repeated initialization.

Run: `uv run pytest tests/test_memory_store.py -q`

Expected: FAIL because `memory.store` does not exist.

- [x] **Step 2: Implement the minimal store schema and validated value types.**

Use short-lived `sqlite3` connections through `asyncio.to_thread`, `PRAGMA user_version`, a finite busy timeout, scope `CHECK` constraints, one-current-version uniqueness and foreign-key cascade. The existing `.gitignore` already covers both `*.db` and `data/`.

- [x] **Step 3: Write failing version, isolation and deletion tests.**

Assert create returns version 1; update makes version 2 current and version 1 historical; private/group-user/group-shared recall is isolated; copy creates a new item in the target scope; delete removes every version; clear affects only the exact scope. Include concurrent updates and a malformed/partial schema that must fail without deleting the file.

- [x] **Step 4: Implement transactions, bounded recall and administration methods.**

`recall(context: MemoryContext, query: str, limit: int = 5, max_characters: int = 1500)` must combine group-user plus group-shared candidates only for the same group, rank locally by phrase overlap, importance and update time, and return current versions only. Explicit memory questions may relax overlap but keep limits.

- [x] **Step 5: Verify and commit Task 10.1.**

Run: `uv run pytest tests/test_memory_store.py -q`

Expected: PASS.

```bash
git add memory/store.py tests/test_memory_store.py
git commit -m "feat: add versioned sqlite memory store"
```

### Task 2: 10.2 Memory Provider and Daily Budget Configuration

**Files:**
- Modify: `config/models.py`
- Modify: `config/storage.py`
- Modify: `core/budget.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_private_config.py`
- Modify: `tests/test_budget.py`

**Interfaces:**
- Extends `Settings` with `daily_memory_calls: int` in `0..1000`, default 10. The total daily limit remains the effective upper bound, so existing low-total configurations remain valid.
- Extends `PrivateSettings` with optional `memory: ProviderSettings | None` and `vision_reuse_chat_api_key: bool`.
- Produces `PrivateSettings.memory_provider() -> ProviderSettings` and `vision_provider() -> ProviderSettings` resolved copies.
- Extends `BudgetKind`, `BudgetResult` and `BudgetUsage` with `memory`.

- [x] **Step 1: Write failing provider-resolution tests.**

Assert a missing memory override follows the full primary provider; an override is independent; vision can reuse only the primary API key while retaining its own URL/model; blank or cleared keys validate correctly; no resolved secret appears in `repr`.

- [x] **Step 2: Implement strict private configuration resolution.**

Keep persisted overrides explicit: following the primary model stores `memory=null`; vision key reuse stores the boolean and does not duplicate the primary key into the vision object.

- [x] **Step 3: Write failing memory-budget migration tests.**

Assert memory reservations increment total and memory counters atomically, obey both limits, expose usage, and migrate an existing Task 8 `model_usage` table by adding a zero-filled memory column without losing counters.

- [x] **Step 4: Implement `daily_memory_calls` and the SQLite counter migration.**

Keep one `model_usage.db`; do not create a second budget database.

- [x] **Step 5: Verify and commit Task 10.2.**

Run: `uv run pytest tests/test_config.py tests/test_private_config.py tests/test_budget.py -q`

Expected: PASS.

```bash
git add config/models.py config/storage.py core/budget.py tests/test_config.py tests/test_private_config.py tests/test_budget.py
git commit -m "feat: configure memory models and budgets"
```

### Task 3: 10.3 Safe Memory Extraction

**Files:**
- Create: `memory/extractor.py`
- Create: `tests/test_memory_extractor.py`

**Interfaces:**
- Consumes: Task 1 memory value types and Task 2 `DailyBudget`/resolved provider.
- Produces: `MemoryCandidate`, `MemoryOperation`, `MemoryExtractor` and `should_extract(text: str) -> bool`.
- `MemoryExtractor(provider, budget)` exposes async `extract(candidate, existing) -> tuple[MemoryOperation, ...]`.

- [x] **Step 1: Write failing local-filter and protocol tests.**

Assert empty, image-only, fixed-error, very short and credential-like messages are rejected locally; stable facts, preferences, corrections and explicit group agreements remain candidates. Pin password, Token, verification-code, ID-card, bank-card and precise-address examples.

- [x] **Step 2: Implement the local candidate filter.**

Use bounded deterministic rules only; false negatives are safer than persisting sensitive data. Do not add a classifier dependency.

- [x] **Step 3: Write failing model extraction tests.**

Patch the chat model and assert strict JSON accepts only `ignore`, `create` and in-scope `update`; rejects unknown fields, more than 3 operations, content over 500 characters, excerpts over 300 characters, duplicate creates, missing targets, cross-scope IDs and sensitive output. Assert one memory reservation and safe failures for empty/malformed model content.

- [x] **Step 4: Implement `MemoryExtractor`.**

Follow the existing DeepSeek/OpenAI-compatible construction pattern from `agent/groupmate.py`, disable retries, reserve `memory` before the call, and return an empty operation tuple without calling the model when the memory quota is exhausted.

- [x] **Step 5: Verify and commit Task 10.3.**

Run: `uv run pytest tests/test_memory_extractor.py -q`

Expected: PASS.

```bash
git add memory/extractor.py tests/test_memory_extractor.py
git commit -m "feat: extract safe atomic memories"
```

### Task 4: 10.4 Recall and Background Extraction Coordination

**Files:**
- Modify: `agent/groupmate.py`
- Modify: `core/groupmate.py`
- Modify: `tests/test_groupmate_reply.py`
- Modify: `tests/test_groupmate.py`

**Interfaces:**
- Extends `GroupmateReply.__call__(..., memories: Sequence[str] = ())`.
- Defines `RecallMemory = Callable[[MemoryContext, str], Awaitable[tuple[str, ...]]]` and `ExtractMemory = Callable[[tuple[MemoryCandidate, ...]], Awaitable[None]]`.
- Extends `GroupmateRuntime` with optional `recall: RecallMemory` and `extract: ExtractMemory` callables.
- `GroupmateCoordinator(..., extraction_delay: Callable[[float], Awaitable[None]] = asyncio.sleep)` uses the injected delay for deterministic batching tests.
- Produces `GroupmateCoordinator.close() -> Awaitable[None]` to finish the active extraction write and drop queued candidates.

- [x] **Step 1: Write failing prompt and recall tests.**

Assert up to 5 memory strings are placed in a separate low-privilege `HumanMessage` labeled untrusted; source excerpts and metadata are absent; no memory message is added for an empty result. Assert private recall uses only the private context and group recall passes the current group plus sender.

- [x] **Step 2: Implement per-message recall and prompt injection.**

Recall after trigger selection and before the chat model call. A recall exception logs only its class/category and continues with an empty memory list.

- [x] **Step 3: Write failing post-send extraction and queue tests.**

Assert only successful generated replies submit candidates; silence, fixed errors and failed sends do not. With a fake `extraction_delay`, assert the same scope batches at most 3 candidates within 30 seconds without waiting in real time. Assert the queue is bounded, saturation skips new work, extraction failures do not affect later messages, and close drops queued raw text after finishing the active write.

- [x] **Step 4: Implement one bounded extraction worker in the coordinator.**

Keep raw candidates only in memory. Start lazily on first candidate, serialize extraction, and preserve existing per-session message ordering and short-term history.

- [x] **Step 5: Verify and commit Task 10.4.**

Run: `uv run pytest tests/test_groupmate_reply.py tests/test_groupmate.py -q`

Expected: PASS.

```bash
git add agent/groupmate.py core/groupmate.py tests/test_groupmate_reply.py tests/test_groupmate.py
git commit -m "feat: recall and queue long-term memory"
```

### Task 5: 10.5 Runtime Assembly and Restart Persistence

**Files:**
- Modify: `bot_runtime.py`
- Modify: `core/dispatcher.py`
- Modify: `dashboard/runtime.py`
- Modify: `tests/test_bot_runtime.py`
- Modify: `tests/test_dispatcher.py`
- Modify: `tests/test_bot.py`

**Interfaces:**
- Consumes: Tasks 1–4 store, extractor and coordinator hooks.
- `BotService` owns one `MemoryStore` and memory worker for its lifetime; hot updates replace providers/settings without clearing short-term history or the database.
- Extends `BotService(..., on_error: Callable[[str | BaseException], None] | None = None)`; memory wrappers report only `memory_failed` to this callback.
- `Dispatcher.close()` closes the coordinator before the OneBot client.

- [ ] **Step 1: Write failing assembly and lifecycle tests.**

Assert startup initializes the store before connecting, chat and memory default to the same provider, independent memory override is used when set, runtime updates change later extraction without replacing the store, and close drains only the active write. A malformed memory schema must add a safe error and leave ordinary chat usable.

- [ ] **Step 2: Implement store/extractor assembly and safe degradation.**

Use `data/memory.db`; pass callable hooks through `GroupmateRuntime`. Catch store/extractor failures in the runtime wrappers, call `on_error("memory_failed")`, and do not expose them through OneBot messages.

- [ ] **Step 3: Write a fake NapCat restart-persistence test.**

Create a memory through a fake extraction result, stop the service, create a new service on the same root, and assert a later reply receives the current memory while another user/group does not.

- [ ] **Step 4: Implement lifecycle cleanup and safe error mapping.**

Add `memory_failed` to dashboard-safe categories; never store exception text, prompts or source excerpts in the error buffer.

- [ ] **Step 5: Verify and commit Task 10.5.**

Run: `uv run pytest tests/test_bot_runtime.py tests/test_dispatcher.py tests/test_bot.py tests/test_dashboard_runtime.py -q`

Expected: PASS.

```bash
git add bot_runtime.py core/dispatcher.py dashboard/runtime.py tests/test_bot_runtime.py tests/test_dispatcher.py tests/test_bot.py tests/test_dashboard_runtime.py
git commit -m "feat: assemble persistent bot memory"
```

### Task 6: 10.6 Simpler Model Configuration and Shared Dashboard Styling

**Files:**
- Modify: `dashboard/app.py`
- Modify: `dashboard/views.py`
- Modify: `tests/test_dashboard_app.py`

**Interfaces:**
- Consumes: Task 2 resolved provider semantics.
- Produces: primary model form, optional independent memory form, collapsed optional vision form, vision-key reuse, and shared accessible page styles.

- [ ] **Step 1: Write failing simplified-form tests.**

Assert the primary API config appears once; memory override fields are collapsed, disabled and not required while following the primary model; vision fields are collapsed/disabled until enabled; DeepSeek fills server-side defaults; following/reusing providers preserves existing keys; blank inputs do not erase secrets; explicit clear remains available.

- [ ] **Step 2: Implement form parsing and persistence before runtime update.**

Keep no-JavaScript submission functional. Use a few lines of native JavaScript only to toggle optional fieldsets; do not add a frontend dependency or build step.

- [ ] **Step 3: Write failing layout and accessibility tests.**

Assert one responsive stylesheet, visible current navigation, labels for every control, field-level errors, success notices, keyboard-usable `details` sections, escaped persona/config text and no secret values in HTML.

- [ ] **Step 4: Implement the shared visual refresh.**

Use CSS variables, cards, responsive grids and native `details`; keep all pages server-rendered and under the existing 65,536-byte request limit.

- [ ] **Step 5: Verify and commit Task 10.6.**

Run: `uv run pytest tests/test_dashboard_app.py tests/test_private_config.py -q`

Expected: PASS.

```bash
git add dashboard/app.py dashboard/views.py tests/test_dashboard_app.py
git commit -m "feat: simplify dashboard model settings"
```

### Task 7: 10.7 Owner Memory Administration

**Files:**
- Modify: `dashboard/app.py`
- Modify: `dashboard/views.py`
- Create: `tests/test_dashboard_memory.py`

**Interfaces:**
- Consumes: Task 1 administration methods and existing dashboard auth/CSRF state.
- Produces authenticated `/memory` list/filter, add, edit, copy, delete and clear flows.

- [ ] **Step 1: Write failing memory-page read tests.**

Assert authenticated owners can filter by exact scope/type and search current content, expand escaped history/source excerpts, and paginate deterministically at 50 items per page. Unauthenticated access redirects; no page contains other scopes when an exact filter is selected, secrets, full paths or model raw output.

- [ ] **Step 2: Implement the read-only memory page.**

Add “记忆” to shared navigation. Use normal forms and `details`; do not add client-side data fetching.

- [ ] **Step 3: Write failing mutation and security tests.**

Assert CSRF is required for add/edit/copy/delete/clear; edit creates a version; copy creates a new target-scope item; delete removes the chain; clear requires the exact phrase `确认清空` and affects only the selected scope. Invalid IDs, negative IDs, cross-scope targets, oversized content and failed SQLite transactions preserve prior data and return safe field errors.

- [ ] **Step 4: Implement owner mutations.**

Persist first, then render the result. Never expose SQL errors or deleted content in response messages.

- [ ] **Step 5: Verify and commit Task 10.7.**

Run: `uv run pytest tests/test_dashboard_memory.py tests/test_dashboard_app.py tests/test_memory_store.py -q`

Expected: PASS.

```bash
git add dashboard/app.py dashboard/views.py tests/test_dashboard_memory.py
git commit -m "feat: manage long-term memory in dashboard"
```

### Task 8: 10.8 Documentation and Acceptance Gate

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/任务Checklist.md`
- Create: `docs/Task10测试指南.md`
- Modify: `docs/superpowers/plans/2026-09-26-task10-sqlite-memory.md`

**Interfaces:**
- Consumes: all implemented Task 10 behavior.
- Produces exact operating, inspection, backup and real-service acceptance instructions.

- [ ] **Step 1: Run focused Task 10 compatibility tests.**

Run: `uv run pytest tests/test_memory_store.py tests/test_memory_extractor.py tests/test_groupmate_reply.py tests/test_groupmate.py tests/test_bot_runtime.py tests/test_bot.py tests/test_dashboard_app.py tests/test_dashboard_memory.py -q`

Expected: PASS.

- [ ] **Step 2: Write the Task 10 operating guide.**

Document automatic extraction, scope isolation, version history, deletion, daily limits, primary/override providers, browser administration, safe `sqlite3` read-only queries, database backup while stopped, and the eight real acceptance steps from the spec.

- [ ] **Step 3: Update progress only with current evidence.**

Add the guide and plan to `docs/README.md`; mark implemented Task 10 subtasks complete. Leave real NapCat/QQ/model memory acceptance unchecked until the user performs it. Do not change Task 7/8 real acceptance.

- [ ] **Step 4: Run the one full verification pass.**

Run: `uv run pre-commit run --all-files`

Expected: ruff, ruff-format, mypy and pytest all PASS.

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 5: Commit Task 10.8 and stop before Task 11.**

```bash
git add README.md docs/README.md docs/任务Checklist.md docs/Task10测试指南.md docs/superpowers/plans/2026-09-26-task10-sqlite-memory.md
git commit -m "docs: add task 10 memory testing guide"
```

Report exact automated evidence and give the user `docs/Task10测试指南.md`. Do not mark real service acceptance complete and do not begin Task 11.
