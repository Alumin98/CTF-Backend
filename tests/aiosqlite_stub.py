"""Minimal aiosqlite stub for unit tests.

This provides enough of the aiosqlite API for SQLAlchemy's async
SQLite dialect to run basic queries without the external dependency.
It is *not* a full implementation.
"""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any, Iterable, Optional, Tuple

__all__ = [
    "connect",
    "Connection",
    "Cursor",
    "Error",
    "DatabaseError",
    "IntegrityError",
    "NotSupportedError",
    "OperationalError",
    "ProgrammingError",
    "PARSE_COLNAMES",
    "PARSE_DECLTYPES",
    "sqlite_version",
    "sqlite_version_info",
]


Error = sqlite3.Error
DatabaseError = sqlite3.DatabaseError
IntegrityError = sqlite3.IntegrityError
NotSupportedError = sqlite3.NotSupportedError
OperationalError = sqlite3.OperationalError
ProgrammingError = sqlite3.ProgrammingError

sqlite_version = sqlite3.sqlite_version
sqlite_version_info = sqlite3.sqlite_version_info

PARSE_COLNAMES = sqlite3.PARSE_COLNAMES
PARSE_DECLTYPES = sqlite3.PARSE_DECLTYPES


class Cursor:
    def __init__(self, inner: sqlite3.Cursor) -> None:
        self._cursor = inner

    async def execute(self, operation: str, parameters: Optional[Iterable[Any]] = None) -> "Cursor":
        if parameters is None:
            await asyncio.to_thread(self._cursor.execute, operation)
        else:
            await asyncio.to_thread(self._cursor.execute, operation, parameters)
        return self

    async def executemany(
        self, operation: str, seq_of_parameters: Iterable[Iterable[Any]]
    ) -> "Cursor":
        await asyncio.to_thread(self._cursor.executemany, operation, seq_of_parameters)
        return self

    async def fetchall(self) -> list[Any]:
        return await asyncio.to_thread(self._cursor.fetchall)

    async def fetchone(self) -> Optional[Any]:
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchmany(self, size: Optional[int] = None) -> list[Any]:
        if size is None:
            return await asyncio.to_thread(self._cursor.fetchmany)
        return await asyncio.to_thread(self._cursor.fetchmany, size)

    async def close(self) -> None:
        await asyncio.to_thread(self._cursor.close)

    @property
    def description(self) -> Optional[Tuple]:
        return self._cursor.description

    @property
    def lastrowid(self) -> int:
        return self._cursor.lastrowid

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


class Connection:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kw = dict(kwargs)
        kw.setdefault("check_same_thread", False)
        self._conn = sqlite3.connect(*args, **kw)
        self._tx: asyncio.Queue[Tuple[asyncio.Future[Any], Any]] = asyncio.Queue()
        self._tx_worker: Optional[asyncio.Task[None]] = None
        self._closed = False

    async def _ensure_worker(self) -> None:
        if self._tx_worker is None:
            self._tx_worker = asyncio.create_task(self._process_queue())

    async def _process_queue(self) -> None:
        while True:
            future, function = await self._tx.get()
            if future is None:
                break
            try:
                result = await asyncio.to_thread(function)
            except Exception as exc:  # pragma: no cover - defensive
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)

    async def cursor(self) -> Cursor:
        inner = await asyncio.to_thread(self._conn.cursor)
        return Cursor(inner)

    async def execute(self, operation: str, parameters: Optional[Iterable[Any]] = None) -> Cursor:
        cursor = await self.cursor()
        await cursor.execute(operation, parameters)
        return cursor

    async def executemany(
        self, operation: str, seq_of_parameters: Iterable[Iterable[Any]]
    ) -> Cursor:
        cursor = await self.cursor()
        await cursor.executemany(operation, seq_of_parameters)
        return cursor

    async def executescript(self, script: str) -> None:
        await asyncio.to_thread(self._conn.executescript, script)

    async def commit(self) -> None:
        await asyncio.to_thread(self._conn.commit)

    async def rollback(self) -> None:
        await asyncio.to_thread(self._conn.rollback)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._tx_worker is not None:
            await self._tx.put((None, None))
            await self._tx_worker
        await asyncio.to_thread(self._conn.close)

    async def create_function(self, *args: Any, **kwargs: Any) -> None:
        await asyncio.to_thread(self._conn.create_function, *args, **kwargs)

    async def __aenter__(self) -> "Connection":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @property
    def isolation_level(self) -> Optional[str]:
        return self._conn.isolation_level

    @isolation_level.setter
    def isolation_level(self, value: Optional[str]) -> None:
        self._conn.isolation_level = value


class _ConnectionFactory:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs
        self.daemon = False

    def __await__(self):  # type: ignore[override]
        async def _make() -> Connection:
            conn = Connection(*self._args, **self._kwargs)
            await conn._ensure_worker()
            return conn

        return _make().__await__()


def connect(*args: Any, **kwargs: Any) -> _ConnectionFactory:
    return _ConnectionFactory(*args, **kwargs)
