# Task 9 Local Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user selected Native execution and wants one numbered task completed per “下一个小任务”; stop after each numbered task. Commits are allowed after verified tasks, but never push or deploy without an explicit request.

**Goal:** Add a localhost-only, single-owner browser dashboard that safely configures, starts, stops and observes the existing QQ bot.

**Architecture:** An `aiohttp` server and the bot share one Python process and event loop. Strict local files hold authentication, credentials, behavior and persona; a small runtime manager serializes lifecycle changes and atomically swaps immutable per-message configuration without clearing conversation state.

**Tech Stack:** Python 3.13+, asyncio, aiohttp, Pydantic, hashlib.scrypt, existing SQLite budget, pytest

**Spec:** `docs/superpowers/specs/2026-09-25-task9-local-dashboard-design.md`

## Global Constraints

- Bind the dashboard only to `127.0.0.1:8765`; do not add a LAN/public binding option.
- Add only `aiohttp` as a direct dependency; use server-rendered HTML/CSS and no frontend framework or build tool.
- The dashboard starts first and the bot stays stopped until its authenticated Start action succeeds.
- One owner account only; hash the password with `hashlib.scrypt`, require CSRF on every state-changing request, and keep sessions in memory.
- Keep credentials in Git-ignored, owner-readable local files and never return full secrets, chat text, image URLs, provider bodies or private paths.
- Reuse the existing `Settings` and `Persona` validation; do not duplicate their numeric or length limits.
- A message uses one immutable runtime snapshot from start to finish; later messages use an updated snapshot and existing conversation state survives the swap.
- NapCat URL/token changes take effect only after restart. Behavior, persona and provider changes affect later messages.
- Preserve `main.py`, `scripts/start_bot.sh` and the Tkinter UI as supported fallback paths.
- Before Task 9.1, preserve and separately commit the already verified Task 7/8 debugging changes that overlap Task 9 files; never overwrite the user's current example persona/settings edits.
- Run focused tests while developing. Run `uv run pre-commit run --all-files` and `git diff --check` once after Task 9.6.

## Review Focus

- Stored persona containing HTML or script syntax must render as escaped text, never executable markup; Task 9.5 pins this with a response-body assertion.
- A corrupt authentication file must fail closed instead of reopening first-run password setup; Task 9.4 pins this with a load failure test.
- A corrupt private configuration must leave the dashboard usable but keep Start disabled without exposing file content; Task 9.5 pins this with a status-page test.
- Concurrent or repeated Start/Stop requests must create at most one bot task and leave a truthful final state; Task 9.3 pins this with concurrent lifecycle tests.
- Failed validation or file replacement must preserve the prior secret and runtime snapshot; Tasks 9.1 and 9.5 pin this with failure-injection tests.

---

### Task 1: 9.1 Strict Private Configuration and Atomic Storage

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.gitignore`
- Modify: `config/models.py`
- Create: `config/storage.py`
- Create: `tests/test_private_config.py`

**Interfaces:**
- Consumes: existing `StrictModel`, `Settings`, `Persona`, `load_settings(root)`, `load_persona(root)`.
- Produces: `ProviderSettings`, `PrivateSettings`, `atomic_write_json(path: Path, payload: object) -> None`, `load_private_settings(root: Path) -> PrivateSettings`, `save_private_settings(root: Path, value: PrivateSettings) -> None`, `save_settings(root: Path, value: Settings) -> None`, and `save_persona(root: Path, value: Persona) -> None`.

- [x] **Step 1: Add `aiohttp` with uv.**

Run: `uv add aiohttp`

Expected: `pyproject.toml` and `uv.lock` contain aiohttp; no other direct product dependency is added.

- [x] **Step 2: Write failing private-model tests.**

Add tests proving:

- `ProviderSettings(provider="deepseek", base_url="https://api.deepseek.com", model="deepseek-flash", api_key="secret")` is valid;
- generic provider URLs reject HTTP, embedded credentials, query strings, fragments and invalid ports;
- NapCat accepts root `ws://127.0.0.1:3001/` and valid `wss://`, but rejects non-root paths and malformed URLs;
- `PrivateSettings` allows an unconfigured first-run draft but `validate_for_start()` names missing fields without their values;
- model repr and validation errors do not contain API keys or tokens.

Run: `uv run pytest tests/test_private_config.py -q`

Expected: FAIL because the models do not exist.

- [x] **Step 3: Add strict private models.**

In `config/models.py`, add:

```python
class ProviderSettings(StrictModel): ...
class PrivateSettings(StrictModel):
    def validate_for_start(self) -> None: ...
```

Use `provider: Literal["deepseek", "openai_compatible"]`; keep secrets as `str` fields excluded from repr. Keep missing first-run fields as empty strings, while `validate_for_start()` requires NapCat URL/token, chat URL/model/key, and all vision fields when vision is enabled.

- [x] **Step 4: Run model tests.**

Run: `uv run pytest tests/test_private_config.py -q`

Expected: model tests PASS; storage tests are not added yet.

- [x] **Step 5: Write failing atomic-storage tests.**

Test that saves create `config/private.json`, `config/settings.json` and `config/persona.json` with mode `0o600`; reload returns the same validated values; the tracked examples remain untouched; and a monkeypatched `os.replace` failure leaves the previous file unchanged.

Also assert `.gitignore` ignores `/config/private.json`.

Run: `uv run pytest tests/test_private_config.py -q`

Expected: FAIL because storage functions do not exist.

- [x] **Step 6: Implement one atomic JSON writer and the four storage functions.**

In `config/storage.py`, implement `atomic_write_json` with a same-directory temporary file, UTF-8 JSON, `os.chmod(path, 0o600)` and `os.replace`. Reuse it for all saves and later authentication storage. `load_private_settings` returns an empty first-run `PrivateSettings` only when the file is absent; malformed existing JSON raises a safe `ValueError`.

- [x] **Step 7: Verify and commit Task 9.1.**

Run: `uv run pytest tests/test_private_config.py tests/test_config.py -q`

Expected: PASS.

```bash
git add pyproject.toml uv.lock .gitignore config/models.py config/storage.py tests/test_private_config.py
git commit -m "feat: add private dashboard configuration"
```

### Task 2: 9.2 Provider Selection and Per-Message Runtime Swaps

**Files:**
- Modify: `agent/groupmate.py`
- Modify: `agent/vision.py`
- Modify: `core/groupmate.py`
- Modify: `tests/test_groupmate_reply.py`
- Modify: `tests/test_groupmate.py`
- Modify: `tests/test_vision.py`

**Interfaces:**
- Consumes: Task 9.1 `ProviderSettings`; existing `DailyBudget`, `SessionState`, `GroupmateReply`, `VisionDescriber`.
- Produces: `GroupmateRuntime` and `GroupmateCoordinator.replace_runtime(runtime: GroupmateRuntime) -> None`; constructors `GroupmateReply(persona, provider, budget)` and `VisionDescriber(provider, budget)`.

- [ ] **Step 1: Write failing provider-construction tests.**

Patch `ChatOpenAI` and assert both reply classes pass the configured base URL, model and secret. Assert only the DeepSeek chat preset adds its current thinking setting; both chat providers retain JSON response format and zero retries.

Run: `uv run pytest tests/test_groupmate_reply.py tests/test_vision.py -q`

Expected: FAIL because constructors still take separate fixed values.

- [ ] **Step 2: Make provider settings drive both model clients.**

Change the two constructors to consume `ProviderSettings`. Keep prompt construction, JSON protocol, image message format and budget behavior unchanged.

- [ ] **Step 3: Run provider tests.**

Run: `uv run pytest tests/test_groupmate_reply.py tests/test_vision.py -q`

Expected: PASS.

- [ ] **Step 4: Write failing runtime-swap tests.**

Add a blocking old reply and a new reply. Start one message, call `replace_runtime`, release the old message, then send another message. Assert the first uses the old reply, the second uses the new reply, and the second receives the first message's retained history. Add the same boundary assertion for new settings/persona name.

Run: `uv run pytest tests/test_groupmate.py -q`

Expected: FAIL because runtime replacement does not exist.

- [ ] **Step 5: Introduce one immutable runtime bundle.**

Add:

```python
@dataclass(frozen=True)
class GroupmateRuntime:
    settings: Settings
    persona_name: str
    reply: GroupmateReply
    vision: VisionDescriber | None

def replace_runtime(self, runtime: GroupmateRuntime) -> None: ...
```

`handle()` captures `self._runtime` once before processing and passes that snapshot through helpers. Keep `_states` on the coordinator so swaps do not clear context. The authenticated NapCat image resolver remains connection-scoped and unchanged.

- [ ] **Step 6: Verify and commit Task 9.2.**

Run: `uv run pytest tests/test_groupmate.py tests/test_groupmate_reply.py tests/test_vision.py -q`

Expected: PASS.

```bash
git add agent/groupmate.py agent/vision.py core/groupmate.py tests/test_groupmate.py tests/test_groupmate_reply.py tests/test_vision.py
git commit -m "feat: support live groupmate configuration"
```

### Task 3: 9.3 Bot Lifecycle, Connection State and Usage

**Files:**
- Create: `bot_runtime.py`
- Create: `dashboard/__init__.py`
- Create: `dashboard/runtime.py`
- Modify: `main.py`
- Modify: `onebot_adapter/client.py`
- Modify: `core/budget.py`
- Create: `tests/test_bot_runtime.py`
- Create: `tests/test_dashboard_runtime.py`
- Modify: `tests/test_onebot_client.py`
- Modify: `tests/test_budget.py`

**Interfaces:**
- Consumes: Task 9.1 configuration and Task 9.2 `GroupmateRuntime` replacement.
- Produces: `BotService`, `BotManager.start(private, settings, persona)`, `BotManager.stop()`, `BotManager.update_runtime(private, settings, persona)`, `BotManager.state`, `SafeErrorBuffer`, `BudgetUsage`, `DailyBudget.usage() -> BudgetUsage`, and optional OneBot connection-state callback.

- [ ] **Step 1: Write failing usage and connection-state tests.**

Assert `DailyBudget.usage()` returns zero before the first reservation and current total/proactive/vision counts afterward. Assert `OneBotClient` reports `"connected"`, `"reconnecting"` and `"stopped"` without exposing frames or credentials.

Run: `uv run pytest tests/test_budget.py tests/test_onebot_client.py -q`

Expected: FAIL because these read/status interfaces do not exist.

- [ ] **Step 2: Add read-only usage and connection callbacks.**

Use the existing SQLite table and local date for `BudgetUsage`. Add an optional synchronous state callback to `OneBotClient`; do not add a generic event bus.

- [ ] **Step 3: Write failing bot-service tests.**

Test that `BotService` builds the existing client, budget, reply, optional vision, coordinator and dispatcher from validated objects; `update()` swaps only the message runtime; and shutdown always closes dispatcher work. Update current `main.py` tests to prove the environment-based CLI still uses the same service.

Run: `uv run pytest tests/test_bot_runtime.py tests/test_bot.py -q`

Expected: FAIL because `BotService` does not exist.

- [ ] **Step 4: Extract the reusable bot service.**

Provide:

```python
class BotService:
    async def run(self) -> None: ...
    def update(self, settings: Settings, persona: Persona, private: PrivateSettings) -> None: ...
    async def close(self) -> None: ...
```

`main.py` remains a thin environment/config adapter and `asyncio.run` entry point. Connection fields are fixed for the service lifetime; `update()` only replaces the Task 9.2 runtime bundle.

- [ ] **Step 5: Write failing manager concurrency tests.**

Using a fake `BotService`, call `start()` concurrently and assert one service/task. Call `stop()` repeatedly and concurrently with start; assert the manager serializes transitions, waits for cleanup, and ends in a truthful state. Assert invalid start configuration never constructs the service.

Run: `uv run pytest tests/test_dashboard_runtime.py -q`

Expected: FAIL because `BotManager` does not exist.

- [ ] **Step 6: Implement the minimal lifecycle manager and safe error buffer.**

`BotManager` owns one lock, one service and one task. `start(private, settings, persona)` validates before construction, `stop()` awaits cleanup, and `update_runtime(private, settings, persona)` updates only a running service's message snapshot. States are `"stopped"`, `"starting"`, `"connected"`, `"reconnecting"` and `"stopping"`. `SafeErrorBuffer` keeps 20 `(time, category)` entries, accepts predefined safe categories only and maps unknown exceptions to their class name without message text.

- [ ] **Step 7: Verify and commit Task 9.3.**

Run: `uv run pytest tests/test_budget.py tests/test_onebot_client.py tests/test_bot_runtime.py tests/test_bot.py tests/test_dashboard_runtime.py -q`

Expected: PASS.

```bash
git add bot_runtime.py dashboard/__init__.py dashboard/runtime.py main.py onebot_adapter/client.py core/budget.py tests/test_bot_runtime.py tests/test_dashboard_runtime.py tests/test_onebot_client.py tests/test_budget.py
git commit -m "feat: manage bot runtime lifecycle"
```

### Task 4: 9.4 Single-Owner Authentication and CSRF

**Files:**
- Create: `dashboard/auth.py`
- Create: `tests/test_dashboard_auth.py`

**Interfaces:**
- Consumes: Task 9.1 `atomic_write_json`.
- Produces: `AuthStore`, `SessionStore`, `Session`, constant-time password/CSRF checks, and in-memory failed-login tracking consumed by Task 9.5.

- [ ] **Step 1: Write failing password-store tests.**

Assert a 10–128 character password creates `data/admin_auth.json` with mode `0o600`, random salt and scrypt hash but no plaintext. Assert correct verification, incorrect verification, distinct salts, and safe rejection of short/long passwords. A missing file means setup is allowed; malformed or structurally invalid existing files raise `ValueError` and never act as missing.

Run: `uv run pytest tests/test_dashboard_auth.py -q`

Expected: FAIL because `AuthStore` does not exist.

- [ ] **Step 2: Implement the owner password store.**

Use `secrets.token_bytes`, `hashlib.scrypt`, `hmac.compare_digest` and Task 9.1 `atomic_write_json`. Store only version, salt and derived hash.

- [ ] **Step 3: Write failing session and CSRF tests.**

Assert login creates a new random session ID and separate CSRF token, session IDs rotate on every login, logout invalidates the session, and wrong/missing CSRF fails in constant-time comparison. Assert the store never serializes sessions to disk.

Run: `uv run pytest tests/test_dashboard_auth.py -q`

Expected: FAIL because session support does not exist.

- [ ] **Step 4: Implement in-memory sessions and bounded failure delay.**

Expose only creation, lookup, CSRF verification and deletion. Track one process-local consecutive-failure count capped at a three-second delay; successful login resets it. Do not add users, roles, refresh tokens or a session database.

- [ ] **Step 5: Verify and commit Task 9.4.**

Run: `uv run pytest tests/test_dashboard_auth.py -q`

Expected: PASS.

```bash
git add dashboard/auth.py tests/test_dashboard_auth.py
git commit -m "feat: secure local dashboard login"
```

### Task 5: 9.5 Server-Rendered Dashboard Pages

**Files:**
- Create: `dashboard/app.py`
- Create: `dashboard/views.py`
- Create: `tests/test_dashboard_app.py`

**Interfaces:**
- Consumes: Task 9.1 storage, Task 9.3 `BotManager`, Task 9.4 auth/session APIs.
- Produces: `create_app(root: Path, manager: BotManager) -> aiohttp.web.Application` and the four authenticated page flows.

- [ ] **Step 1: Write failing setup/login/security route tests.**

Using `aiohttp.test_utils.TestClient`, assert first run redirects to password setup; setup accepts a valid password; login rotates the session cookie with `HttpOnly` and `SameSite=Strict`; unauthenticated reads redirect; and every POST without the matching CSRF token returns 403. Set `client_max_size=65536` and assert oversized requests return 413.

Run: `uv run pytest tests/test_dashboard_app.py -q`

Expected: FAIL because the app does not exist.

- [ ] **Step 2: Implement app creation, auth guards and shared escaped layout.**

Use aiohttp routes and `html.escape`; do not add a template dependency. Catch unexpected route failures with a generic page while logging only the exception class. Keep cookies non-Secure for the fixed local HTTP origin as required by the spec.

- [ ] **Step 3: Write failing page and secret-handling tests.**

Assert four pages exist for status, behavior, models/connection and persona. Assert saved `<script>` persona text appears escaped, chat text never appears, full secrets never appear, and secret fields show only configured state plus at most the final four characters. Assert blank secret input preserves the prior value and an explicit clear action removes it.

Run: `uv run pytest tests/test_dashboard_app.py -q`

Expected: FAIL because page routes and forms are incomplete.

- [ ] **Step 4: Implement the four minimal pages and validated POST handlers.**

Render all Task 8 settings and Persona fields, NapCat fields, separate chat/vision providers and the vision toggle. DeepSeek selection fills its preset URL/default model server-side. On successful behavior/persona/provider save, persist first and then call `manager.update_runtime`; on NapCat changes show a restart-required notice. No JavaScript framework or live log view.

- [ ] **Step 5: Write failing invalid/corrupt/save-failure tests.**

Assert field errors preserve entered non-secret values; corrupt `private.json` keeps the dashboard accessible but disables Start with a safe configuration error; failed `os.replace` keeps the old secret and does not call runtime update; and Start/Stop routes report the manager's resulting state. Assert no response contains corrupt file content, secret values or private paths.

Run: `uv run pytest tests/test_dashboard_app.py -q`

Expected: FAIL until failure paths are implemented.

- [ ] **Step 6: Complete safe failure handling and status data.**

Status renders manager state, `DailyBudget.usage()` counts and remaining limits, plus the last 20 safe error entries. Disable Start when `PrivateSettings.validate_for_start()` or existing behavior/persona loading fails.

- [ ] **Step 7: Verify and commit Task 9.5.**

Run: `uv run pytest tests/test_dashboard_app.py tests/test_dashboard_auth.py tests/test_dashboard_runtime.py -q`

Expected: PASS.

```bash
git add dashboard/app.py dashboard/views.py tests/test_dashboard_app.py
git commit -m "feat: add local management dashboard"
```

### Task 6: 9.6 One-Command Startup, Documentation and Acceptance Gate

**Files:**
- Create: `dashboard/__main__.py`
- Create: `scripts/start_dashboard.sh`
- Create: `tests/test_dashboard_entrypoint.py`
- Modify: `README.md`
- Modify: `docs/README.md`
- Modify: `docs/任务Checklist.md`
- Create: `docs/Task9测试指南.md`

**Interfaces:**
- Consumes: Task 9.5 `create_app` and Task 9.3 `BotManager`.
- Produces: `python -m dashboard`, `bash scripts/start_dashboard.sh`, operating guide and evidence-based Checklist updates.

- [ ] **Step 1: Write failing entry-point tests.**

Patch aiohttp runner and `webbrowser.open`. Assert the entry point binds exactly `127.0.0.1:8765`, opens `http://127.0.0.1:8765/` only after binding succeeds, does not start the bot, reports an occupied port without opening a browser, and stops the manager on shutdown.

Run: `uv run pytest tests/test_dashboard_entrypoint.py -q`

Expected: FAIL because the entry point does not exist.

- [ ] **Step 2: Implement the entry point and shell script.**

`scripts/start_dashboard.sh` changes to the repository root and executes `uv run python -m dashboard`. Configure existing safe logging once. `Ctrl+C` invokes manager shutdown before aiohttp cleanup.

- [ ] **Step 3: Run focused dashboard and compatibility tests.**

Run: `uv run pytest tests/test_private_config.py tests/test_groupmate.py tests/test_bot_runtime.py tests/test_dashboard_auth.py tests/test_dashboard_runtime.py tests/test_dashboard_app.py tests/test_dashboard_entrypoint.py tests/test_start_ui.py tests/test_bot.py -q`

Expected: PASS.

- [ ] **Step 4: Write operating documentation.**

Document first-run password creation, credential setup, Start/Stop, live settings/persona/provider updates, NapCat restart-required fields, status/error privacy, password reset, terminal fallback and stopping with `Ctrl+C`. Include exact real-Mac acceptance steps from the spec.

- [ ] **Step 5: Update progress only with current evidence.**

Add the spec, plan and Task 9 guide to `docs/README.md`. Mark Task 9 spec/plan and implemented subtasks complete after their evidence exists. Leave real local dashboard/QQ acceptance unchecked until the user performs it. Do not change Task 7 real-image acceptance merely because its settings appear in the dashboard.

- [ ] **Step 6: Run the one full verification pass.**

Run: `uv run pre-commit run --all-files`

Expected: ruff, ruff-format, mypy and pytest all PASS.

Run: `git diff --check`

Expected: no output and exit 0.

- [ ] **Step 7: Commit Task 9.6 and stop at real-service acceptance.**

```bash
git add dashboard/__main__.py scripts/start_dashboard.sh tests/test_dashboard_entrypoint.py README.md docs/README.md docs/任务Checklist.md docs/Task9测试指南.md
git commit -m "docs: add dashboard startup and testing guide"
```

Report the exact verification results and give the user `docs/Task9测试指南.md`. Do not mark real NapCat, QQ or provider acceptance complete and do not begin Task 10.
