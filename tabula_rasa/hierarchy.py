"""Shared validation for the ledger's two-level item hierarchies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class HierarchyValidationError(ValueError):
    """Raised when a complete account or category hierarchy is invalid."""


def _parent_id(item: Mapping[str, Any]) -> str:
    value = item.get("parent_id")
    return str(value).strip() if value else ""


def hierarchy_paths(items: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Return stable display paths while keeping stored names unchanged."""
    records = [dict(item) for item in items]
    by_id = {str(item.get("id", "")): item for item in records}
    paths: dict[str, str] = {}
    for item_id, item in by_id.items():
        name = str(item.get("name", ""))
        parent = by_id.get(_parent_id(item))
        paths[item_id] = (
            f'{parent.get("name", "")} › {name}' if parent is not None else name
        )
    return paths


def ordered_hierarchy(
    items: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Order Layer 1 items with their Layer 2 children."""
    records = [dict(item) for item in items]
    children: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for item in records:
        parent_id = _parent_id(item)
        if parent_id:
            children.setdefault(parent_id, []).append(item)
        else:
            roots.append(item)
    ordered: list[dict[str, Any]] = []
    for root in sorted(roots, key=lambda item: str(item.get("name", "")).casefold()):
        ordered.append(root)
        ordered.extend(
            sorted(
                children.get(str(root.get("id", "")), []),
                key=lambda item: str(item.get("name", "")).casefold(),
            )
        )
    return ordered


def eligible_parent_ids(
    items: Iterable[Mapping[str, Any]],
    *,
    compatibility_field: str,
    compatibility_value: str,
    item_id: str = "",
) -> list[str]:
    """Return eligible Layer 1 parents for a create or edit form."""
    return [
        str(item["id"])
        for item in ordered_hierarchy(items)
        if not _parent_id(item)
        and str(item.get("id", "")) != item_id
        and item.get(compatibility_field) == compatibility_value
    ]


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
        parent_id = _parent_id(item)
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
        if _parent_id(parent):
            raise HierarchyValidationError(
                f"{item_label} hierarchy may contain only two levels"
            )
        if item.get(compatibility_field) != parent.get(compatibility_field):
            raise HierarchyValidationError(
                f"{item_label} parent must have the same "
                f"{compatibility_field.replace('_', ' ')}"
            )
