"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from .errors import StorageValidationError
from .validation import _as_bool
from .validation import _clean_text
from .validation import normalize_payee_name

class PayeesMixin:
    """PayeesMixin boundary for the Google Sheets facade."""

    def list_payees(
        self, *, active_only: bool = False, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        payees: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for row in self._rows("Payees", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Payee ID", required=True)
            item["name"] = _clean_text(item.get("name"), "Payee name", required=True)
            item["active"] = "TRUE" if _as_bool(item.get("active"), "Payee active") else "FALSE"
            item["created_at"] = _clean_text(item.get("created_at"), "Payee created at")
            key = normalize_payee_name(item["name"])
            if item["id"] in seen_ids or key in seen_names:
                raise StorageValidationError("Payee IDs and names must be unique")
            seen_ids.add(item["id"])
            seen_names.add(key)
            if not active_only or item["active"] == "TRUE":
                payees.append(item)
        return sorted(payees, key=lambda item: item["name"].casefold())


    def _payee_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_payees(_force_refresh=force_refresh)}

__all__ = ['PayeesMixin']
