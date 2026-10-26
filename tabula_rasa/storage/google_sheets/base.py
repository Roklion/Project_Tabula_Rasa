"""Small shared storage primitives used by the client and facade."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, RLock
from typing import Any
import weakref

@dataclass(frozen=True)
class _WorkbookLockBundle:
    """Process-local mutation locks for one configured workbook."""

    ledger: RLock


_WORKBOOK_LOCK_REGISTRY_LOCK = Lock()
_WORKBOOK_LOCK_REGISTRY: weakref.WeakValueDictionary[
    str, _WorkbookLockBundle
] = weakref.WeakValueDictionary()


def _workbook_lock_bundle(
    workbook: Any,
    spreadsheet_id: str | None,
) -> _WorkbookLockBundle:
    """Return the shared process-local lock bundle for one workbook identity.

    Production storage passes the configured spreadsheet ID. Direct callers
    that wrap an in-memory or otherwise unconfigured workbook use object
    identity as a safe, documented fallback; workbook titles are mutable and
    are deliberately not used as lock identities.
    """
    if spreadsheet_id is None:
        spreadsheet_id = getattr(workbook, "id", None) or getattr(
            workbook, "key", None
        )

    if spreadsheet_id is None:
        identity = f"workbook-object:{id(workbook)}"
    else:
        normalized_id = str(spreadsheet_id).strip()
        if not normalized_id or normalized_id.casefold() == "none":
            raise ValueError("spreadsheet_id is empty")
        identity = f"spreadsheet:{normalized_id}"

    with _WORKBOOK_LOCK_REGISTRY_LOCK:
        bundle = _WORKBOOK_LOCK_REGISTRY.get(identity)
        if bundle is None:
            bundle = _WorkbookLockBundle(
                ledger=RLock()
            )
            _WORKBOOK_LOCK_REGISTRY[identity] = bundle
        return bundle


@dataclass(frozen=True)
class _StoredRow:
    row_number: int
    values: dict[str, str]


__all__ = ["_StoredRow"]
