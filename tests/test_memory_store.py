import asyncio
import sqlite3
from pathlib import Path

import pytest

from memory.store import MemoryContext, MemoryScope, MemorySource, MemoryStore


SOURCE = MemorySource(message_id="10", message_time=20, excerpt="用户原话")


def test_scope_constructors_validate_ids() -> None:
    assert MemoryScope.private(1).key == ("private", None, 1)
    assert MemoryScope.group_user(2, 1).key == ("group_user", 2, 1)
    assert MemoryScope.group_shared(2).key == ("group_shared", 2, None)

    invalid = (
        lambda: MemoryScope.private(0),
        lambda: MemoryScope.group_user(-1, 1),
        lambda: MemoryScope.group_user(1, 0),
        lambda: MemoryScope.group_shared(0),
        lambda: MemoryScope("private", 2, 1),
        lambda: MemoryScope("group_shared", 2, 1),
    )
    for build in invalid:
        with pytest.raises(ValueError):
            build()


def test_source_rejects_long_excerpt() -> None:
    with pytest.raises(ValueError):
        MemorySource(message_id="1", message_time=1, excerpt="字" * 301)


async def test_initialize_creates_schema_and_preserves_rows(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    store = MemoryStore(path)

    await store.initialize()
    created = await store.create(
        MemoryScope.private(1),
        "fact",
        "住在芝加哥",
        3,
        MemorySource(message_id="10", message_time=20, excerpt="我住在芝加哥"),
        "manual",
    )
    await store.initialize()

    with sqlite3.connect(path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        version = db.execute("PRAGMA user_version").fetchone()[0]

    db = store._connect()
    try:
        foreign_keys = db.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        db.close()

    assert tables == {"memory_items", "memory_versions"}
    assert journal_mode == "wal"
    assert foreign_keys == 1
    assert version == 1
    assert (await store.history(created.id))[0].content == "住在芝加哥"


async def test_versions_copy_delete_and_exact_scope_clear(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.initialize()
    private = MemoryScope.private(1)
    original = await store.create(private, "fact", "住在芝加哥", 3, SOURCE, "manual")

    updated = await store.update(original.id, "住在纽约", 4, SOURCE, "edit")
    history = await store.history(original.id)
    listed = await store.list_current(private)

    assert updated.version.version == 2
    assert [(version.version, version.current) for version in history] == [(2, True), (1, False)]
    assert [record.version.content for record in listed] == ["住在纽约"]

    copied = await store.copy(original.id, MemoryScope.group_user(9, 1))
    assert copied.id != original.id
    assert copied.version.version == 1
    assert copied.version.content == "住在纽约"

    other = await store.create(MemoryScope.private(2), "fact", "喜欢咖啡", 2, SOURCE, "manual")
    assert await store.clear(private) == 1
    assert await store.history(original.id) == ()
    assert (await store.history(other.id))[0].current

    await store.delete(copied.id)
    assert await store.history(copied.id) == ()


async def test_recall_isolated_ranked_and_bounded(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.initialize()
    await store.create(MemoryScope.private(1), "preference", "喜欢草莓蛋糕", 3, SOURCE, "manual")
    await store.create(MemoryScope.private(2), "preference", "喜欢巧克力", 5, SOURCE, "manual")
    await store.create(MemoryScope.group_user(9, 1), "fact", "常用角色是牧师", 4, SOURCE, "manual")
    await store.create(MemoryScope.group_shared(9), "fact", "每周六晚上打游戏", 5, SOURCE, "manual")
    await store.create(MemoryScope.group_user(10, 1), "fact", "另一个群的信息", 5, SOURCE, "manual")

    private = await store.recall(MemoryContext.private(1), "草莓", limit=5)
    group = await store.recall(MemoryContext.group(9, 1), "你记得什么", limit=5)

    assert [record.version.content for record in private] == ["喜欢草莓蛋糕"]
    assert {record.version.content for record in group} == {"常用角色是牧师", "每周六晚上打游戏"}
    assert sum(len(record.version.content) for record in group) <= 1500

    bounded = await store.recall(MemoryContext.group(9, 1), "你记得什么", limit=1, max_characters=7)
    assert len(bounded) == 1
    assert len(bounded[0].version.content) <= 7


async def test_concurrent_updates_are_serialized(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    await store.initialize()
    record = await store.create(MemoryScope.private(1), "fact", "初始", 1, SOURCE, "manual")

    await asyncio.gather(
        store.update(record.id, "更新甲", 2, SOURCE, "edit"),
        store.update(record.id, "更新乙", 3, SOURCE, "edit"),
    )

    history = await store.history(record.id)
    assert [version.version for version in history] == [3, 2, 1]
    assert sum(version.current for version in history) == 1


async def test_partial_schema_fails_without_deleting_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memory_items (sentinel TEXT)")
        db.execute("INSERT INTO memory_items VALUES ('keep me')")

    with pytest.raises(sqlite3.DatabaseError):
        await MemoryStore(path).initialize()

    with sqlite3.connect(path) as db:
        assert db.execute("SELECT sentinel FROM memory_items").fetchone()[0] == "keep me"


async def test_malformed_versioned_schema_is_not_accepted(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memory_items (sentinel TEXT)")
        db.execute("CREATE TABLE memory_versions (sentinel TEXT)")
        db.execute("PRAGMA user_version=1")

    with pytest.raises(sqlite3.DatabaseError):
        await MemoryStore(path).initialize()

    assert path.exists()
