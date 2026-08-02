"""Shared validation for the ledger's two-level item hierarchies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class HierarchyValidationError(ValueError):
    """Raised when a complete account or category hierarchy is invalid."""


def validate_two_level_hierarchy(
    items: Iterable[Mapping[str, Any]],
    *,
    compatibility_field: str,
    item_label: str,
) -> None:
    """Validate stable parent IDs, compatibility, and the two-level limit."""
    records = [dict(item) for item in items]
    ids = [str(item.get("id", "")).strip() for item in records]
    if any(not item_id for item_id in ids) or len(ids) != len(set(ids)):
        raise HierarchyValidationError(
            f"{item_label} IDs must be present and unique"
        )

    by_id = dict(zip(ids, records))
    for item_id, item in by_id.items():
        parent_id = str(item.get("parent_id", "")).strip()
        if not parent_id:
            continue
        if parent_id == item_id:
            raise HierarchyValidationError(
                f"A {item_label.lower()} cannot be its own parent"
            )
        parent = by_id.get(parent_id)
        if parent is None:
            raise HierarchyValidationError(
                f"{item_label} parent does not exist"
            )
        if str(parent.get("parent_id", "")).strip():
            raise HierarchyValidationError(
                f"{item_label} hierarchy may contain only two levels"
            )
        if item.get(compatibility_field) != parent.get(compatibility_field):
            raise HierarchyValidationError(
                f"{item_label} parent must have the same "
                f"{compatibility_field.replace('_', ' ')}"
            )
