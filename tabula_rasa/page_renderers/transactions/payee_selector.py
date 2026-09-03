"""Shared Payee selector value handling for transaction forms."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def resolve_payee_selection(
    value: object,
    payees: Sequence[Mapping[str, Any]],
    allowed_ids: Sequence[str],
) -> tuple[str, str]:
    """Return the selected managed ID and any new inline Payee name."""
    typed_name = str(value or "").strip()
    allowed = set(allowed_ids)
    payee_id = typed_name if typed_name in allowed else ""
    by_name = {
        str(payee.get("name") or "").strip().casefold(): str(payee["id"])
        for payee in payees
        if str(payee.get("name") or "").strip()
        and str(payee.get("id") or "") in allowed
    }
    if not payee_id and typed_name:
        payee_id = by_name.get(typed_name.casefold(), "")
    return payee_id, "" if payee_id or not typed_name else typed_name
