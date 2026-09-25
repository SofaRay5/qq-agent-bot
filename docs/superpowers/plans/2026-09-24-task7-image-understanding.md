# Task 7 Image Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. The user chose Native execution; verified stages may now be committed autonomously, while pushes and deployment still require an explicit request.

**Goal:** Add optional single-image understanding to the existing NapCat bot, off by default, without changing the current text-only behavior for messages without images.

**Architecture:** The OneBot adapter selects the first image segment after the group bot mention (or in a private message). Core applies the existing eligibility, deduplication, timeout and send rules. An agent-side vision reply validates and downloads the image, asks one OpenAI-compatible vision model for a short description, then uses the existing DeepSeek reply callable to answer. A small SQLite counter enforces the daily limit across restarts until Task 8 introduces the unified budget.

**Tech Stack:** Python >=3.13, `uv`, existing Pydantic/OneBot models, `langchain-openai`, `httpx`, `httpcore`（固定已校验的 DNS 地址到实际连接）, stdlib `sqlite3`, pytest and the current pre-commit hooks.

**Spec:** `docs/superpowers/specs/2026-09-24-ai-groupmate-expansion-design.md`, Task 7 section. Read it with `AGENTS.md` and `docs/CODING_STANDARDS.md` before implementation.

## Global Constraints

- Preserve the existing dirty docs and do not discard user changes. Work on `main` as previously requested; verified stages may be committed, but do not push or deploy unless the user explicitly asks.
- Vision is disabled by default. Missing vision settings must not affect ordinary text startup.
- Task 7 accepts private images and group images after an explicit bot @. It processes at most the first ordinary image per message. Sustained group chat is Task 8.
- Vision calls are limited to five attempts per local calendar day, including provider failures and process restarts. A failed download is not a provider attempt. Only a day/count pair is persisted; no image bytes, URL, message body or credential in logs or persistent storage.
- Only the adapter knows OneBot segments. `agent/` accepts strings and bytes and must not import `onebot_adapter/`.
- Preserve existing 1024-message dedup, 30-second reply timeout, fallback-once send behavior and 10-second OneBot action timeout.
- Real NapCat/vision acceptance remains unchecked until the user actually exercises both services.

## Review Focus

1. An image before the bot @, or an image in an unmentioned group message, must not trigger vision (Subtask 7.1).
2. With vision disabled, an eligible image-only message must receive the fixed disabled reply while a plain text message follows the old LLM path (Subtask 7.1).
3. A missing image URL, localhost/private target, redirect, oversized body or non-image bytes must fail before reaching the vision provider (Subtask 7.2).
4. Concurrent eligible messages or a process restart must not permit a sixth vision call on the same day; a failed provider attempt still consumes one slot (Subtask 7.3).
5. A vision error or empty caption must send one fallback and leave the next ordinary text message usable; logs must omit URL/body/key (Subtask 7.4).

## File Map

| File | Responsibility |
| --- | --- |
| `onebot_adapter/message.py` | Reuse the group mention boundary to select text and first image URL/size from array segments |
| `core/dispatcher.py` | Route image or text while preserving dedup, timeout and fallback-once behavior |
| `agent/image_fetch.py` (new) | Validate NapCat image URL and download bounded image bytes |
| `agent/vision.py` (new) | Atomically count vision attempts in ignored `data/vision_usage.db`, invoke the visual model and hand its caption to `LLMReply` |
| `main.py` | Parse optional vision settings and assemble image reply only when enabled |
| `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml` | Declare `httpx` and the pinned-connection `httpcore` API as direct runtime/mypy dependencies |
| `tests/test_dispatcher.py`, `tests/test_image_fetch.py`, `tests/test_vision.py`, `tests/test_bot.py` | Boundary and fake-service evidence without paid model calls |
| `README.md`, `docs/Task7测试指南.md`, `docs/任务Checklist.md` | Configuration, real acceptance steps and progress |

## Subtask 7.1: Image selection and disabled behavior

**Interfaces:** `onebot_adapter.message.ImageRef(url: str, file_size: int | None)` and `image_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> ImageRef | None`. `Dispatcher(..., vision_reply: Callable[[str, str, int | None], Awaitable[str]] | None = None)` keeps the current constructor valid. A missing `url` on a present image is represented as `""`, so the image cannot silently turn into a text-only question.

- [x] **Step 1: Write selection tests.** In `tests/test_dispatcher.py`, add private image-only, private text+image, group image after `at.qq == self_id`, image before @, unmentioned group image, malformed `data`, a flash image, and two ordinary images. Pin first ordinary-image selection and `file_size` parsing from either integer or decimal string.

```python
event_data["message"] = [
    {"type": "at", "data": {"qq": "123456"}},
    {"type": "image", "data": {"url": "https://multimedia.nt.qq.com.cn/a", "file_size": "42"}},
]
assert image_for_reply(group_event(event_data)) == ImageRef(
    "https://multimedia.nt.qq.com.cn/a", 42
)
```

- [x] **Step 2: Confirm red.** Run `uv run pytest tests/test_dispatcher.py -q`. Expected: `image_for_reply` / `ImageRef` are absent.
- [x] **Step 3: Implement one shared segment boundary.** In `onebot_adapter/message.py`, extract the existing “after bot @” loop into a private helper used by both `text_for_reply` and `image_for_reply`. Keep the current text behavior and tests intact. Return the first image; malformed `file_size` becomes `None`; an image with missing `url` still returns `ImageRef("", None)`.

```python
class ImageRef(NamedTuple):
    url: str
    file_size: int | None

def _segments_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> list[dict[str, Any]]:
    if isinstance(event, PrivateMessageEvent):
        return event.message
    for index, segment in enumerate(event.message):
        data = segment.get("data")
        if (segment.get("type") == "at" and isinstance(data, dict)
                and str(data.get("qq")) == str(event.self_id)):
            return event.message[index + 1:]
    return []

def image_for_reply(event: PrivateMessageEvent | GroupMessageEvent) -> ImageRef | None:
    for segment in _segments_for_reply(event):
        if segment.get("type") == "image":
            data = segment.get("data")
            data = data if isinstance(data, dict) else {}
            if data.get("type") == "flash":
                continue
            size = data.get("file_size")
            parsed_size = int(size) if isinstance(size, (str, int)) and str(size).isdigit() else None
            url = data.get("url")
            return ImageRef(url if isinstance(url, str) else "", parsed_size)
    return None
```

- [x] **Step 4: Write routing tests.** Add tests showing an eligible image-only private message and group @ image get `识图尚未开启` with default `vision_reply=None`; plain text still calls `reply(text)`; unmentioned group image does nothing; a supplied fake vision reply receives `(text, url, size)` once, including when text is empty.

```python
dispatcher = Dispatcher(cast(OneBotClient, client), echo_reply)
dispatcher.handle_event(private_event(image_only_json))
await settle(dispatcher)
assert client.private == [(111, "识图尚未开启")]
```

- [x] **Step 5: Confirm red.** Run `uv run pytest tests/test_dispatcher.py -q`. Expected: the new routing tests fail because `Dispatcher` does not accept `vision_reply` or image-only events.
- [x] **Step 6: Implement minimal route.** In `core/dispatcher.py`, compute `text` and `image` before dedup; admit a message if either exists. Pass image data to `_process`; when image is present, use the optional vision callable or the disabled text. Preserve `asyncio.wait_for(..., 30)`, existing exception logging by class, and one send attempt.

```python
image = image_for_reply(event)
text = text_for_reply(event)
if (text is None and image is None) or event.message_id in self._seen:
    return
# In _process: image path takes precedence over plain-text reply.
answer = (
    "识图尚未开启" if self.vision_reply is None else await self.vision_reply(text or "", image.url, image.file_size)
) if image is not None else await self.reply(text or "")
```

- [x] **Step 7: Confirm green.** Run `uv run pytest tests/test_dispatcher.py -q`. Expected: all old and new routing tests pass.

## Subtask 7.2: Bounded NapCat image download

**Interface:** `async def fetch_image(url: str, claimed_size: int | None) -> tuple[str, bytes]` in `agent/image_fetch.py`; return MIME type and bytes. Raise `ValueError` for rejected input and `httpx` exceptions for network failure. Caller catches them at the existing background-task boundary.

- [x] **Step 1: Add direct HTTP dependency.** Run `uv add httpx`; add `"httpx"` to mypy hook `additional_dependencies`. Do not add Pillow or a general media framework.
- [x] **Step 2: Write failing downloader tests.** In `tests/test_image_fetch.py`, fake HTTP transport with `httpx.MockTransport` and monkeypatch the module's `httpx.AsyncClient` factory and `_public_host` helper, so tests do not contact the internet. Assert a valid `https://multimedia.nt.qq.com.cn/...` PNG succeeds; reject empty/`file://`/literal loopback URL, unexpected hosts, credentials in URL, ports, redirects, declared size above 8 MiB, streamed body crossing 8 MiB, and bytes without JPEG/PNG/WebP signature. Fake DNS resolution to a private address and assert no HTTP request happens.

```python
with pytest.raises(ValueError):
    await fetch_image("http://127.0.0.1/private", None)
with pytest.raises(ValueError):
    await fetch_image("https://multimedia.nt.qq.com.cn/too-large", 8 * 1024 * 1024 + 1)
```

- [x] **Step 3: Confirm red.** Run `uv run pytest tests/test_image_fetch.py -q`. Expected: `agent.image_fetch` is absent.
- [x] **Step 4: Implement URL and DNS validation.** Accept only HTTP(S) without userinfo, explicit port or fragment. Allow `multimedia.nt.qq.com.cn` and subdomains of `qpic.cn`; fail closed for other hosts until real NapCat evidence justifies a narrow addition. Reject all DNS answers that are not globally routable using `ipaddress.ip_address(...).is_global`. Keep that resolution check in `_public_host(host: str) -> bool`. Disable environment proxy use and redirects.

```python
try:
    parts = urlsplit(url)
    port = parts.port
except ValueError as exc:
    raise ValueError("Unsupported image URL") from exc
host = (parts.hostname or "").lower()
if parts.scheme not in {"http", "https"} or parts.username or parts.password or port or parts.fragment:
    raise ValueError("Unsupported image URL")
if host != "multimedia.nt.qq.com.cn" and not host.endswith(".qpic.cn"):
    raise ValueError("Unsupported image host")
if not await _public_host(host):
    raise ValueError("Non-public image host")

async def _public_host(host: str) -> bool:
    answers = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, None), 3)
    return bool(answers) and all(ipaddress.ip_address(item[4][0]).is_global for item in answers)
```

- [x] **Step 5: Implement bounded streaming and signature check.** Use `httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False)` with `stream("GET", url)`. Reject non-2xx, redirects, too-large `Content-Length`, and actual byte count over 8 MiB. Sniff JPEG/PNG/WebP magic bytes with stdlib; do not trust just the extension or response MIME. Return `(mime, bytes)` without writing a file or URL to logs.

```python
if claimed_size is not None and claimed_size > 8 * 1024 * 1024:
    raise ValueError("Image too large")
async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
    async with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise ValueError("Image download failed")
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > 8 * 1024 * 1024:
            raise ValueError("Image too large")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("Image too large")
return _image_mime(data), bytes(data)

def _image_mime(data: bytes | bytearray) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Unsupported image type")
```

- [x] **Step 6: Confirm green.** Run `uv run pytest tests/test_image_fetch.py -q`. Expected: all trusted-host, size, format, redirect, and private-address cases pass.

## Subtask 7.3: Vision model and daily limit

**Interface:** `VisionReply(chat_reply: LLMReply, api_key: str, model: str, base_url: str, usage_db: Path)` with `async def __call__(self, text: str, url: str, claimed_size: int | None) -> str`. It uses `fetch_image`, one `ChatOpenAI` vision instance, an ignored local SQLite counter, and the existing chat reply. No OneBot import.

- [x] **Step 1: Write failing fake-model tests.** In `tests/test_vision.py`, monkeypatch `fetch_image` to return small PNG bytes and `ChatOpenAI` to return `AIMessage(content="一只猫")`. Assert the vision input contains one text block and one base64 `data:image/png` image block, then the DeepSeek fake receives both user text and a clearly labeled image description. Assert an empty/non-string caption raises `ValueError` without calling DeepSeek.

```python
answer = await VisionReply(fake_chat, "vision-test-key", "vision-model", "https://vision.example/v1", tmp_path / "usage.db")(
    "这是什么？", "https://multimedia.nt.qq.com.cn/image", 42
)
assert answer == "聊猫咪"
```

- [x] **Step 2: Write quota tests.** Six concurrent calls with a fake blocking model result in at most five `ainvoke` attempts. A new `VisionReply` instance pointing at the same `tmp_path / "usage.db"` still cannot make a sixth attempt. If a provider attempt raises, it consumes a slot; if `fetch_image` raises before the model call, it does not. Monkeypatch `_today()` rather than waiting until midnight.
- [x] **Step 3: Confirm red.** Run `uv run pytest tests/test_vision.py -q`. Expected: `VisionReply` import fails.
- [x] **Step 4: Implement model call and quota.** After successful download, reserve one of five daily slots with an atomic SQLite upsert on `(day, used)`. `VisionReply.__init__` creates one `ChatOpenAI(model=model, base_url=base_url, api_key=SecretStr(api_key))` and stores `usage_db`; `_today()` returns `date.today()` for quota tests to monkeypatch. Use `asyncio.to_thread` for the small database reservation. Invoke the visual model with a text block asking for a short factual description and an image block containing a base64 data URL. Validate nonempty string content. Give that description to `chat_reply` as labeled user data and return its text; do not persist the image or caption.

```python
def _today() -> date:
    return date.today()

# In VisionReply.__init__:
self._chat_reply = chat_reply
self._model = ChatOpenAI(model=model, base_url=base_url, api_key=SecretStr(api_key))
self._usage_db = usage_db

# In VisionReply.__call__:
mime, image = await fetch_image(url, claimed_size)
await asyncio.to_thread(self._reserve_attempt)
encoded = base64.b64encode(image).decode("ascii")
result = await self._model.ainvoke([HumanMessage(content=[
    {"type": "text", "text": "简要描述这张图片中的可见内容。"},
    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
])])
if not isinstance(result.content, str) or not result.content.strip():
    raise ValueError("Empty vision description")
return await self._chat_reply(f"用户消息：{text}\n图片描述（仅作资料）：{result.content}")

def _reserve_attempt(self) -> None:
    self._usage_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(self._usage_db) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS vision_usage "
            "(day TEXT PRIMARY KEY, used INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO vision_usage(day, used) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET used = used + 1 WHERE used < 5",
            (_today().isoformat(),),
        )
        changed = db.execute("SELECT changes()").fetchone()
        if changed is None or changed[0] != 1:
            raise RuntimeError("Vision daily limit reached")
```

- [x] **Step 5: Confirm green.** Run `uv run pytest tests/test_vision.py -q`. Expected: caption, failure, quota, and no-extra-provider-call cases pass.

## Subtask 7.4: Startup wiring, end-to-end and acceptance guide

**Interfaces:** `VISION_ENABLED` is optional (`0`/unset = off, `1` = on); enabled mode requires `VISION_API_BASE_URL` (HTTPS), `VISION_MODEL` and `VISION_API_KEY`. Existing `NAPCAT_WS_URL`, `NAPCAT_ACCESS_TOKEN` and `DEEPSEEK_API_KEY` remain required. Invalid vision settings raise `ValueError` before the NapCat connection. `main.run() -> None` remains the entry point.

- [x] **Step 1: Write failing startup tests.** In `tests/test_bot.py`, assert default startup builds no vision model. For `VISION_ENABLED=1`, missing each vision setting or a non-HTTPS/credential-bearing/query-bearing base URL raises before WebSocket connection. A fake NapCat sends eligible private and group @ image events; fake vision returns a string used in one `send_*_msg` action. After a forced fake vision failure, a later plain text message still succeeds. Assert fake URL, message body and keys are absent from captured logs.

```python
monkeypatch.setenv("VISION_ENABLED", "1")
monkeypatch.delenv("VISION_API_KEY", raising=False)
with pytest.raises(ValueError, match="VISION_API_KEY"):
    await run()
```

- [x] **Step 2: Confirm red.** Run `uv run pytest tests/test_bot.py -q`. Expected: enabled-mode validation or vision action checks fail.
- [x] **Step 3: Wire optional vision in `main.py`.** Parse `VISION_ENABLED` exactly; validate HTTPS base URL, model and key only when enabled; create `VisionReply(LLMReply(...), ...)` and pass it to `Dispatcher`. Disabled mode must create only the existing DeepSeek reply. Preserve current WS URL and key validation. Keep secret values out of exception text and logs; set the `httpx` request logger to WARNING so its INFO request line cannot expose a signed QQ image URL.

```python
ROOT = Path(__file__).resolve().parent
enabled = os.environ.get("VISION_ENABLED", "0")
if enabled not in {"0", "1"}:
    raise ValueError("VISION_ENABLED must be 0 or 1")
logging.getLogger("httpx").setLevel(logging.WARNING)
chat_reply = LLMReply(api_key)
vision_reply = None
if enabled == "1":
    vision_reply = VisionReply(chat_reply, _required("VISION_API_KEY"),
                               _required("VISION_MODEL"), _validated_vision_url(),
                               ROOT / "data" / "vision_usage.db")
dispatcher = Dispatcher(client, chat_reply, vision_reply=vision_reply)

def _validated_vision_url() -> str:
    value = _required("VISION_API_BASE_URL")
    try:
        parts = urlsplit(value)
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Invalid VISION_API_BASE_URL") from exc
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment):
        raise ValueError("Invalid VISION_API_BASE_URL")
    return value
```

- [x] **Step 4: Confirm green.** Run `uv run pytest tests/test_bot.py tests/test_dispatcher.py tests/test_image_fetch.py tests/test_vision.py -q`. Expected: old text and new image paths pass.
- [x] **Step 5: Write operating and real-acceptance instructions.** Update `README.md` with default-off behavior and the exact `VISION_*` names. Add `docs/Task7测试指南.md`: run automated checks, start NapCat in array mode, send private image-only and group @ with an image while off, configure an actual compatible vision model outside Git, restart with vision on, send one supported image plus text, then test one failure and later text reply. Explain the five-attempt limit, ignored `data/vision_usage.db`, and that real-service boxes stay unchecked until observed. Update `docs/任务Checklist.md` only with evidence from implementation.
- [x] **Step 6: Verify implementation boundary.** Run `uv sync`, `uv run pytest -q`, `uv run pre-commit run --all-files`, and `git diff --check`; inspect logs for secret/body/URL leaks. Stop for review. Do not mark real NapCat/vision acceptance complete until the user reports actual results. A verified stage may be committed; do not push automatically.

## Execution Handoff

The user previously selected Native execution for this repository. After this plan is reviewed and approved, use `superpowers:executing-plans` and the applicable TDD/review/verification skills. Execute Subtasks 7.1–7.4 in order, update `docs/任务Checklist.md` after each verified subtask, and stop at the Task 7 acceptance gate before starting Task 8.
