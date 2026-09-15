"""Profile-scoped ledger filters and selection state."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import streamlit as st
from tabula_rasa.storage import StorageError
from tabula_rasa.storage import decode_receipt_references
from tabula_rasa.storage import MIXED_USE_SOURCE_TYPE
from .transaction_copy import _copy_source_key

def _bulk_selection_key(profile_key: str) -> str:
    return f"transaction_bulk_selected_ids_{profile_key}"

def _clear_bulk_selection(profile_key: str) -> None:
    st.session_state[_bulk_selection_key(profile_key)] = ()
    st.session_state["transaction_bulk_selection_generation"] = int(
        st.session_state.get("transaction_bulk_selection_generation", 0)
    ) + 1

def transaction_has_receipts(transaction: Mapping[str, object]) -> bool:
    references = transaction.get("receipt_references", "")
    if not references or (
        isinstance(references, str) and references.strip() in {"", "[]"}
    ):
        return False
    try:
        return bool(decode_receipt_references(references))
    except StorageError:
        return False

def _change_ledger_mode(profile_key: str) -> None:
    _clear_bulk_selection(profile_key)
    st.session_state["transaction_ledger_mode_generation"] = int(
        st.session_state.get("transaction_ledger_mode_generation", 0)
    ) + 1
    if not st.session_state.get(_copy_source_key(profile_key)):
        st.session_state.pop("edit_transaction_id", None)

def _mixed_use_transaction_ids(
    transactions: Sequence[Mapping[str, object]],
) -> set[str]:
    """Return protected source-driven IDs from an unfiltered snapshot."""
    return {
        str(transaction.get("id") or "")
        for transaction in transactions
        if transaction_is_source_driven(transaction)
    }

def transaction_is_source_driven(transaction: Mapping[str, object]) -> bool:
    return transaction_is_mixed_use(transaction) or transaction.get("source_type") == "depreciation"


def transaction_is_mixed_use(transaction: Mapping[str, object]) -> bool:
    """Return whether durable provenance makes this projection read-only."""
    return bool(
        str(transaction.get("source_type") or "").strip() == MIXED_USE_SOURCE_TYPE
        and str(transaction.get("source_id") or "").strip()
    )


def transaction_type_label(value: object, transaction: Mapping[str, object]) -> str:
    """Add durable mixed-use and recurring indicators to a ledger type."""
    mixed_use = transaction_is_mixed_use(transaction)
    recurring = bool(str(transaction.get("recurring_schedule_id") or "").strip())
    suffix = " · ".join(
        label
        for label, enabled in (("Mixed-use", mixed_use), ("Recurring", recurring),
                               ("Depreciation", transaction.get("source_type") == "depreciation"))
        if enabled
    )
    return f"{value} · {suffix}" if suffix else str(value)

def _selection_ids(transaction_ids: Sequence[str], rows: Sequence[int]) -> tuple[str, ...]:
    return tuple(
        transaction_ids[row_index]
        for row_index in rows
        if 0 <= row_index < len(transaction_ids)
    )
