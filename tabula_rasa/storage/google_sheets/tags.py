"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from .errors import StorageValidationError
from .validation import _as_bool
from .validation import _clean_text
from .validation import normalize_tag_name

class TagsMixin:
    """TagsMixin boundary for the Google Sheets facade."""

    def list_tags(
        self, *, active_only: bool = False, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        tags: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for row in self._rows("Tags", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Tag ID", required=True)
            item["name"] = _clean_text(item.get("name"), "Tag name", required=True)
            item["active"] = (
                "TRUE" if _as_bool(item.get("active"), "Tag active") else "FALSE"
            )
            item["created_at"] = _clean_text(item.get("created_at"), "Tag created at")
            name_key = normalize_tag_name(item["name"])
            if item["id"] in seen_ids or name_key in seen_names:
                raise StorageValidationError("Tag IDs and names must be unique")
            seen_ids.add(item["id"])
            seen_names.add(name_key)
            if not active_only or item["active"] == "TRUE":
                tags.append(item)
        return sorted(tags, key=lambda item: item["name"].casefold())


    def _tag_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_tags(_force_refresh=force_refresh)}

__all__ = ['TagsMixin']
