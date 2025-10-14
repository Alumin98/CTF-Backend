from pathlib import Path

import sqlite3
from sqlalchemy import create_engine, text as sql_text

from app.models.hint import (
    DEFAULT_PENALTY_COLUMN,
    DEFAULT_TEXT_COLUMN,
    _detect_hint_columns,
)


def _make_sqlite_engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path}")


def test_detect_hint_columns_defaults_when_table_missing(tmp_path):
    engine = _make_sqlite_engine(tmp_path / "missing.sqlite")
    try:
        text_col, penalty_col = _detect_hint_columns(engine)
    finally:
        engine.dispose()

    assert (text_col, penalty_col) == (
        DEFAULT_TEXT_COLUMN,
        DEFAULT_PENALTY_COLUMN,
    )


def test_detect_hint_columns_prefers_legacy_names(tmp_path):
    engine = _make_sqlite_engine(tmp_path / "legacy.sqlite")
    try:
        with engine.begin() as conn:
            conn.execute(
                sql_text(
                    """
                    CREATE TABLE hints (
                        id INTEGER PRIMARY KEY,
                        challenge_id INTEGER NOT NULL,
                        hint_text TEXT NOT NULL,
                        point_penalty INTEGER NOT NULL,
                        order_index INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            )

        text_col, penalty_col = _detect_hint_columns(engine)
    finally:
        engine.dispose()

    assert text_col == "hint_text"
    assert penalty_col == "point_penalty"


def test_detect_hint_columns_handles_database_errors(monkeypatch, tmp_path):
    engine = _make_sqlite_engine(tmp_path / "broken.sqlite")

    class _FailingConnection:
        def __enter__(self):
            raise sqlite3.OperationalError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    def _broken_connect():
        return _FailingConnection()

    monkeypatch.setattr(engine, "connect", _broken_connect)

    try:
        text_col, penalty_col = _detect_hint_columns(engine)
    finally:
        engine.dispose()

    assert (text_col, penalty_col) == (
        DEFAULT_TEXT_COLUMN,
        DEFAULT_PENALTY_COLUMN,
    )
