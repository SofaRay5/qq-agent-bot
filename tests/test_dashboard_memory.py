import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import pytest
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer

from dashboard.app import create_app
from dashboard.auth import AuthStore
from dashboard.runtime import BotManager
from memory.store import MemoryScope, MemorySource, MemoryStore

SOURCE = MemorySource(message_id="12", message_time=34, excerpt="<b>原始用户内容</b>")


class FakeManager:
    state = "stopped"
    errors: tuple[object, ...] = ()

    async def start(self, *_args: object) -> None:
        self.state = "starting"

    async def stop(self) -> None:
        self.state = "stopped"

    def update_runtime(self, *_args: object) -> None:
        pass


def csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


@pytest.fixture
async def memory_client(
    tmp_path: Path,
) -> AsyncIterator[tuple[TestClient, MemoryStore, Path]]:
    AuthStore(tmp_path).create_password("correct horse battery staple")
    store = MemoryStore(tmp_path / "data" / "memory.db")
    await store.initialize()
    app = create_app(tmp_path, cast(BotManager, FakeManager()))
    async with TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True)) as client:
        login = await client.get("/login")
        await client.post(
            "/login",
            data={
                "password": "correct horse battery staple",
                "csrf_token": csrf(await login.text()),
            },
        )
        yield client, store, tmp_path


async def test_memory_requires_login_and_lists_filtered_escaped_history(
    memory_client: tuple[TestClient, MemoryStore, Path],
) -> None:
    client, store, _ = memory_client
    first = await store.create(
        MemoryScope.private(1), "fact", "<script>芝加哥</script>", 3, SOURCE, "manual"
    )
    await store.update(first.id, "住在纽约", 4, SOURCE, "edit")
    await store.create(
        MemoryScope.private(2), "preference", "不应显示的秘密偏好", 2, SOURCE, "manual"
    )

    response = await client.get(
        "/memory?scope_kind=private&user_id=1&kind=fact&q=%E7%BA%BD%E7%BA%A6"
    )
    text = await response.text()

    assert response.status == 200
    assert "住在纽约" in text
    assert "不应显示的秘密偏好" not in text
    assert "&lt;script&gt;芝加哥&lt;/script&gt;" in text
    assert "&lt;b&gt;原始用户内容&lt;/b&gt;" in text
    assert "<details" in text
    assert 'aria-current="page">记忆</a>' in text
    assert str(store._path) not in text

    await client.post("/logout", data={"csrf_token": csrf(text)})
    denied = await client.get("/memory", allow_redirects=False)
    assert denied.status == 302
    assert denied.headers["Location"] == "/login"


async def test_memory_paginates_at_fifty(
    memory_client: tuple[TestClient, MemoryStore, Path],
) -> None:
    client, store, _ = memory_client
    for index in range(51):
        await store.create(MemoryScope.private(1), "fact", f"分页记忆 {index}", 3, SOURCE, "manual")

    first = await (await client.get("/memory?scope_kind=private&user_id=1")).text()
    second = await (await client.get("/memory?scope_kind=private&user_id=1&page=2")).text()

    assert first.count('data-memory-id="') == 50
    assert "下一页" in first
    assert second.count('data-memory-id="') == 1
    assert "分页记忆 0" in second


async def test_owner_can_add_edit_copy_delete_and_clear_exact_scope(
    memory_client: tuple[TestClient, MemoryStore, Path],
) -> None:
    client, store, _ = memory_client
    token = csrf(await (await client.get("/memory")).text())
    add = {
        "csrf_token": token,
        "scope_kind": "private",
        "user_id": "1",
        "group_id": "",
        "kind": "preference",
        "content": "喜欢咖啡",
        "importance": "4",
    }
    response = await client.post("/memory/add", data=add)
    assert response.status == 200
    original = (await store.list_current(MemoryScope.private(1)))[0]

    response = await client.post(
        "/memory/edit",
        data={
            "csrf_token": token,
            "item_id": str(original.id),
            "content": "喜欢茶",
            "importance": "5",
        },
    )
    assert response.status == 200
    assert len(await store.history(original.id)) == 2

    response = await client.post(
        "/memory/copy",
        data={
            "csrf_token": token,
            "item_id": str(original.id),
            "copy_scope_kind": "group_shared",
            "copy_group_id": "9",
            "copy_user_id": "",
        },
    )
    assert response.status == 200
    copied = (await store.list_current(MemoryScope.group_shared(9)))[0]

    response = await client.post(
        "/memory/delete", data={"csrf_token": token, "item_id": str(copied.id)}
    )
    assert response.status == 200
    assert await store.list_current(MemoryScope.group_shared(9)) == ()
    assert await store.history(copied.id) == ()

    await store.create(MemoryScope.private(2), "fact", "保留", 3, SOURCE, "manual")
    rejected = await client.post(
        "/memory/clear",
        data={
            "csrf_token": token,
            "clear_scope_kind": "private",
            "clear_user_id": "1",
            "clear_group_id": "",
            "confirmation": "清空",
        },
    )
    assert rejected.status == 400
    assert await store.list_current(MemoryScope.private(1))

    cleared = await client.post(
        "/memory/clear",
        data={
            "csrf_token": token,
            "clear_scope_kind": "private",
            "clear_user_id": "1",
            "clear_group_id": "",
            "confirmation": "确认清空",
        },
    )
    assert cleared.status == 200
    assert await store.list_current(MemoryScope.private(1)) == ()
    assert await store.list_current(MemoryScope.private(2))


@pytest.mark.parametrize("route", ["add", "edit", "copy", "delete", "clear"])
async def test_memory_mutations_require_csrf(
    memory_client: tuple[TestClient, MemoryStore, Path], route: str
) -> None:
    client, _, _ = memory_client
    assert (await client.post(f"/memory/{route}", data={})).status == 403


async def test_invalid_or_failed_memory_mutation_is_safe_and_atomic(
    memory_client: tuple[TestClient, MemoryStore, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, store, _ = memory_client
    existing = await store.create(MemoryScope.private(1), "fact", "原内容", 3, SOURCE, "manual")
    token = csrf(await (await client.get("/memory")).text())

    invalid = await client.post(
        "/memory/edit",
        data={
            "csrf_token": token,
            "item_id": "-1",
            "content": "无效编号",
            "importance": "3",
        },
    )
    assert invalid.status == 400
    assert (await store.history(existing.id))[0].content == "原内容"

    oversized = await client.post(
        "/memory/edit",
        data={
            "csrf_token": token,
            "item_id": str(existing.id),
            "content": "x" * 501,
            "importance": "3",
        },
    )
    assert oversized.status == 400
    assert (await store.history(existing.id))[0].content == "原内容"

    cross_scope = await client.post(
        "/memory/copy",
        data={
            "csrf_token": token,
            "item_id": str(existing.id),
            "copy_scope_kind": "private",
            "copy_group_id": "9",
            "copy_user_id": "1",
        },
    )
    assert cross_scope.status == 400
    assert len(await store.list_current(MemoryScope.private(1))) == 1

    async def fail_create(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.DatabaseError("private database path and raw model output")

    monkeypatch.setattr(MemoryStore, "create", fail_create)
    failed = await client.post(
        "/memory/add",
        data={
            "csrf_token": token,
            "scope_kind": "private",
            "user_id": "1",
            "group_id": "",
            "kind": "fact",
            "content": "不会保存",
            "importance": "3",
        },
    )
    text = await failed.text()
    assert failed.status == 500
    assert "private database path" not in text
    assert "raw model output" not in text
    assert len(await store.list_current(MemoryScope.private(1))) == 1
