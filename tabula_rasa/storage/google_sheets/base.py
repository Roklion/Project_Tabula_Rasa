"""Small shared storage primitives used by the client and facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from typing import Any, TypeVar

_PAYEE_WRITE_LOCK = RLock()
_MIXED_USE_CREATE_LOCK = RLock()
_TAG_WRITE_LOCK = RLock()


@dataclass(frozen=True)
class _StoredRow:
    row_number: int
    values: dict[str, str]


T = TypeVar("T")


def _active_ledger_mutation_lock(operation: Callable[..., T]) -> Callable[..., T]:
    """Serialize writes that can create or change Payee/Tag references."""

    @wraps(operation)
    def locked(*args: Any, **kwargs: Any) -> T:
        with _MIXED_USE_CREATE_LOCK:
            return operation(*args, **kwargs)

    return locked


__all__ = [
    "_StoredRow",
    "_active_ledger_mutation_lock",
    "_PAYEE_WRITE_LOCK",
    "_MIXED_USE_CREATE_LOCK",
    "_TAG_WRITE_LOCK",
]
