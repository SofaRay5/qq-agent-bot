"""Scoped, versioned long-term memory backed by SQLite."""

import asyncio
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

MemoryKind = Literal["fact", "preference", "quote"]
MemoryOrigin = Literal["automatic", "manual", "edit"]
ScopeKind = Literal["private", "group_user", "group_shared"]


@dataclass(frozen=True)
class MemoryScope:
    kind: ScopeKind
    group_id: int | None
    user_id: int | None

    def __post_init__(self) -> None:
        valid = (
            self.kind == "private"
            and self.group_id is None
            and _valid_id(self.user_id)
            or self.kind == "group_user"
            and _valid_id(self.group_id)
            and _valid_id(self.user_id)
            or self.kind == "group_shared"
            and _valid_id(self.group_id)
            and self.user_id is None
        )
        if not valid:
            raise ValueError("Invalid memory scope")

    @property
    def key(self) -> tuple[ScopeKind, int | None, int | None]:
        return self.kind, self.group_id, self.user_id

    @classmethod
    def private(cls, user_id: int) -> "MemoryScope":
        return cls("private", None, user_id)

    @classmethod
    def group_user(cls, group_id: int, user_id: int) -> "MemoryScope":
        return cls("group_user", group_id, user_id)

    @classmethod
    def group_shared(cls, group_id: int) -> "MemoryScope":
        return cls("group_shared", group_id, None)


@dataclass(frozen=True)
class MemoryContext:
    user_id: int
    group_id: int | None = None

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.user_id)
            or self.group_id is not None
            and not _valid_id(self.group_id)
        ):
            raise ValueError("Invalid memory context")

    @classmethod
    def private(cls, user_id: int) -> "MemoryContext":
        return cls(user_id)

    @classmethod
    def group(cls, group_id: int, user_id: int) -> "MemoryContext":
        return cls(user_id, group_id)


@dataclass(frozen=True)
class MemorySource:
    message_id: str | None = None
    message_time: int | None = None
    excerpt: str = ""

    def __post_init__(self) -> None:
        if len(self.excerpt) > 300:
            raise ValueError("Memory source excerpt exceeds 300 characters")


@dataclass(frozen=True)
class MemoryVersion:
    item_id: int
    version: int
    current: bool
    content: str
    importance: int
    source: MemorySource
    created_by: MemoryOrigin
    created_at: str


@dataclass(frozen=True)
class MemoryRecord:
    id: int
    scope: MemoryScope
    kind: MemoryKind
    created_at: str
    version: MemoryVersion


def _valid_id(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


class MemoryStore:
    """Store atomic memories with strict scope isolation and version history."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        return db

    async def initialize(self) -> None:
        """Create or validate the memory database without replacing existing data."""
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            tables = {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name IN ('memory_items', 'memory_versions')"
                )
            }
            if version == 0 and tables:
                raise sqlite3.DatabaseError("Partial memory schema")
            if version not in (0, 1):
                raise sqlite3.DatabaseError("Unsupported memory schema version")
            if version == 1:
                if tables != {"memory_items", "memory_versions"} or not _schema_valid(db):
                    raise sqlite3.DatabaseError("Incomplete memory schema")
                return
            db.executescript(
                """
                BEGIN;
                CREATE TABLE memory_items (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'quote')),
                    scope TEXT NOT NULL CHECK (scope IN ('private', 'group_user', 'group_shared')),
                    group_id INTEGER,
                    user_id INTEGER,
                    created_at TEXT NOT NULL,
                    CHECK (
                        (scope='private' AND group_id IS NULL AND user_id > 0) OR
                        (scope='group_user' AND group_id > 0 AND user_id > 0) OR
                        (scope='group_shared' AND group_id > 0 AND user_id IS NULL)
                    )
                );
                CREATE TABLE memory_versions (
                    item_id INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL CHECK (version > 0),
                    is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
                    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 500),
                    importance INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
                    source_message_id TEXT,
                    source_message_time INTEGER,
                    source_excerpt TEXT NOT NULL CHECK (length(source_excerpt) <= 300),
                    created_by TEXT NOT NULL CHECK (created_by IN ('automatic', 'manual', 'edit')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (item_id, version)
                );
                CREATE UNIQUE INDEX one_current_memory_version
                    ON memory_versions(item_id) WHERE is_current=1;
                PRAGMA user_version=1;
                COMMIT;
                """
            )

    async def create(
        self,
        scope: MemoryScope,
        kind: MemoryKind,
        content: str,
        importance: int,
        source: MemorySource,
        created_by: MemoryOrigin,
    ) -> MemoryRecord:
        """Create one memory at version 1."""
        return await asyncio.to_thread(
            self._create_sync, scope, kind, content, importance, source, created_by
        )

    def _create_sync(
        self,
        scope: MemoryScope,
        kind: MemoryKind,
        content: str,
        importance: int,
        source: MemorySource,
        created_by: MemoryOrigin,
    ) -> MemoryRecord:
        _validate_version_input(kind, content, importance, created_by)
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as db, db:
            cursor = db.execute(
                "INSERT INTO memory_items(kind, scope, group_id, user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (kind, scope.kind, scope.group_id, scope.user_id, now),
            )
            item_id = cursor.lastrowid
            if item_id is None:
                raise sqlite3.DatabaseError("Memory insert did not return an ID")
            db.execute(
                "INSERT INTO memory_versions VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    content,
                    importance,
                    source.message_id,
                    source.message_time,
                    source.excerpt,
                    created_by,
                    now,
                ),
            )
        return MemoryRecord(
            item_id,
            scope,
            kind,
            now,
            MemoryVersion(item_id, 1, True, content, importance, source, created_by, now),
        )

    async def update(
        self,
        item_id: int,
        content: str,
        importance: int,
        source: MemorySource,
        created_by: MemoryOrigin,
    ) -> MemoryRecord:
        """Create a new current version for an existing memory."""
        return await asyncio.to_thread(
            self._update_sync, item_id, content, importance, source, created_by
        )

    def _update_sync(
        self,
        item_id: int,
        content: str,
        importance: int,
        source: MemorySource,
        created_by: MemoryOrigin,
    ) -> MemoryRecord:
        _validate_item_id(item_id)
        _validate_version_input(None, content, importance, created_by)
        now = datetime.now(UTC).isoformat()
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT i.*, v.version FROM memory_items i "
                "JOIN memory_versions v ON v.item_id=i.id AND v.is_current=1 "
                "WHERE i.id=?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise KeyError(item_id)
            version = int(row["version"]) + 1
            db.execute("UPDATE memory_versions SET is_current=0 WHERE item_id=?", (item_id,))
            db.execute(
                "INSERT INTO memory_versions VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_id,
                    version,
                    content,
                    importance,
                    source.message_id,
                    source.message_time,
                    source.excerpt,
                    created_by,
                    now,
                ),
            )
        scope = _scope_from_row(row)
        memory_version = MemoryVersion(
            item_id, version, True, content, importance, source, created_by, now
        )
        return MemoryRecord(item_id, scope, row["kind"], row["created_at"], memory_version)

    async def recall(
        self,
        context: MemoryContext,
        query: str,
        limit: int = 5,
        max_characters: int = 1500,
    ) -> tuple[MemoryRecord, ...]:
        """Recall bounded current memories visible to one conversation."""
        if limit < 1 or max_characters < 1:
            return ()
        records = await asyncio.to_thread(self._visible_sync, context)
        explicit = "记得" in query or "记忆" in query
        query_terms = _terms(query)
        ranked: list[tuple[int, int, str, MemoryRecord]] = []
        for record in records:
            overlap = len(query_terms & _terms(record.version.content))
            if overlap or explicit:
                ranked.append(
                    (overlap, record.version.importance, record.version.created_at, record)
                )
        ranked.sort(key=lambda item: item[:3], reverse=True)
        result: list[MemoryRecord] = []
        used = 0
        for _, _, _, record in ranked:
            size = len(record.version.content)
            if size > max_characters - used:
                continue
            result.append(record)
            used += size
            if len(result) == limit:
                break
        return tuple(result)

    def _visible_sync(self, context: MemoryContext) -> tuple[MemoryRecord, ...]:
        if context.group_id is None:
            where = "i.scope='private' AND i.user_id=?"
            params: tuple[object, ...] = (context.user_id,)
        else:
            where = (
                "i.group_id=? AND ((i.scope='group_user' AND i.user_id=?) "
                "OR i.scope='group_shared')"
            )
            params = (context.group_id, context.user_id)
        return self._select_current(where, params)

    async def list_current(
        self,
        scope: MemoryScope | None = None,
        kind: MemoryKind | None = None,
        query: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[MemoryRecord, ...]:
        """List current memories for owner administration."""
        if limit < 1 or offset < 0:
            raise ValueError("Invalid memory page")
        return await asyncio.to_thread(self._list_current_sync, scope, kind, query, limit, offset)

    def _list_current_sync(
        self,
        scope: MemoryScope | None,
        kind: MemoryKind | None,
        query: str,
        limit: int,
        offset: int,
    ) -> tuple[MemoryRecord, ...]:
        clauses: list[str] = []
        params: list[object] = []
        if scope is not None:
            clauses.extend(("i.scope=?", "i.group_id IS ?", "i.user_id IS ?"))
            params.extend(scope.key)
        if kind is not None:
            _validate_kind(kind)
            clauses.append("i.kind=?")
            params.append(kind)
        if query:
            clauses.append("v.content LIKE ? ESCAPE '\\'")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        where = " AND ".join(clauses) if clauses else "1"
        return self._select_current(where, tuple(params), limit, offset)

    def _select_current(
        self,
        where: str,
        params: tuple[object, ...],
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[MemoryRecord, ...]:
        sql = (
            "SELECT i.*, v.version AS v_version, v.is_current, v.content, v.importance, "
            "v.source_message_id, v.source_message_time, v.source_excerpt, "
            "v.created_by, v.created_at AS version_created_at "
            "FROM memory_items i JOIN memory_versions v ON v.item_id=i.id AND v.is_current=1 "
            f"WHERE {where} ORDER BY v.created_at DESC, i.id DESC"
        )
        query_params = list(params)
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            query_params.extend((limit, offset))
        with closing(self._connect()) as db:
            rows = db.execute(sql, query_params).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    async def copy(self, item_id: int, target_scope: MemoryScope) -> MemoryRecord:
        """Copy the current version into a new memory identity and scope."""
        record = await asyncio.to_thread(self._current_sync, item_id)
        return await self.create(
            target_scope,
            record.kind,
            record.version.content,
            record.version.importance,
            record.version.source,
            "manual",
        )

    def _current_sync(self, item_id: int) -> MemoryRecord:
        _validate_item_id(item_id)
        records = self._select_current("i.id=?", (item_id,))
        if not records:
            raise KeyError(item_id)
        return records[0]

    async def delete(self, item_id: int) -> None:
        """Permanently delete a memory and its complete version chain."""
        await asyncio.to_thread(self._delete_sync, item_id)

    def _delete_sync(self, item_id: int) -> None:
        _validate_item_id(item_id)
        with closing(self._connect()) as db, db:
            deleted = db.execute("DELETE FROM memory_items WHERE id=?", (item_id,))
            if deleted.rowcount == 0:
                raise KeyError(item_id)

    async def clear(self, scope: MemoryScope) -> int:
        """Permanently delete all memories in one exact scope."""
        return await asyncio.to_thread(self._clear_sync, scope)

    def _clear_sync(self, scope: MemoryScope) -> int:
        with closing(self._connect()) as db, db:
            deleted = db.execute(
                "DELETE FROM memory_items WHERE scope=? AND group_id IS ? AND user_id IS ?",
                scope.key,
            )
        return deleted.rowcount

    async def history(self, item_id: int) -> tuple[MemoryVersion, ...]:
        """Return every version of one memory, newest first."""
        return await asyncio.to_thread(self._history_sync, item_id)

    def _history_sync(self, item_id: int) -> tuple[MemoryVersion, ...]:
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT * FROM memory_versions WHERE item_id=? ORDER BY version DESC", (item_id,)
            ).fetchall()
        return tuple(_version_from_row(row) for row in rows)


def _version_from_row(row: sqlite3.Row) -> MemoryVersion:
    return MemoryVersion(
        item_id=row["item_id"],
        version=row["version"],
        current=bool(row["is_current"]),
        content=row["content"],
        importance=row["importance"],
        source=MemorySource(
            row["source_message_id"], row["source_message_time"], row["source_excerpt"]
        ),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _schema_valid(db: sqlite3.Connection) -> bool:
    expected = {
        "memory_items": {"id", "kind", "scope", "group_id", "user_id", "created_at"},
        "memory_versions": {
            "item_id",
            "version",
            "is_current",
            "content",
            "importance",
            "source_message_id",
            "source_message_time",
            "source_excerpt",
            "created_by",
            "created_at",
        },
    }
    for table, columns in expected.items():
        actual = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        if actual != columns:
            return False
    indexes = {row["name"] for row in db.execute("PRAGMA index_list(memory_versions)")}
    return "one_current_memory_version" in indexes


def _scope_from_row(row: sqlite3.Row) -> MemoryScope:
    return MemoryScope(row["scope"], row["group_id"], row["user_id"])


def _record_from_row(row: sqlite3.Row) -> MemoryRecord:
    version = MemoryVersion(
        item_id=row["id"],
        version=row["v_version"],
        current=bool(row["is_current"]),
        content=row["content"],
        importance=row["importance"],
        source=MemorySource(
            row["source_message_id"], row["source_message_time"], row["source_excerpt"]
        ),
        created_by=row["created_by"],
        created_at=row["version_created_at"],
    )
    return MemoryRecord(row["id"], _scope_from_row(row), row["kind"], row["created_at"], version)


def _validate_item_id(item_id: int) -> None:
    if not _valid_id(item_id):
        raise ValueError("Invalid memory ID")


def _validate_kind(kind: object) -> None:
    if kind not in ("fact", "preference", "quote"):
        raise ValueError("Invalid memory kind")


def _validate_version_input(
    kind: object | None,
    content: str,
    importance: int,
    created_by: object,
) -> None:
    if kind is not None:
        _validate_kind(kind)
    if not content or len(content) > 500:
        raise ValueError("Memory content must contain 1 to 500 characters")
    if not isinstance(importance, int) or isinstance(importance, bool) or not 1 <= importance <= 5:
        raise ValueError("Memory importance must be between 1 and 5")
    if created_by not in ("automatic", "manual", "edit"):
        raise ValueError("Invalid memory origin")


def _terms(text: str) -> set[str]:
    normalized = "".join(character.lower() for character in text if character.isalnum())
    terms = set(normalized)
    terms.update(normalized[index : index + 2] for index in range(len(normalized) - 1))
    return terms
