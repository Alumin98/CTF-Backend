"""Application package initializer that restores real modules when test stubs were installed."""

from importlib import import_module
import sys
from typing import Iterable

# Stubs in tests may register lightweight modules in ``sys.modules`` without
# ``__file__`` metadata. When other tests later need the real database helpers
# or ORM models, the stub prevents imports from succeeding. To keep those
# integration-style tests working, replace any such stub with the genuine
# module when the package is imported.


def _restore_module(full_name: str) -> None:
    module = sys.modules.get(full_name)
    if module is None:
        return
    if getattr(module, "__file__", None):
        return
    # Remove the stub and import the real module.
    sys.modules.pop(full_name, None)
    import_module(full_name)


_MODULES_TO_RESTORE: Iterable[str] = (
    "app.database",
    "app.models.challenge",
    "app.models.hint",
    "app.models.challenge_tag",
    "app.models.submission",
    "app.models.user",
)

for _name in _MODULES_TO_RESTORE:
    _restore_module(_name)

# Re-export the common database helpers for convenience.
from .database import Base, SessionLocal, engine, get_db  # noqa: E402,F401

__all__ = ["Base", "SessionLocal", "engine", "get_db"]
