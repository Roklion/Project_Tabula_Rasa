"""Profile-scoped ledger filters and selection state."""

from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
import streamlit as st
from tabula_rasa.errors import StorageError
from tabula_rasa.ledger_validation import decode_receipt_references
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.ledger_presentation import transaction_type_label as transaction_type_label
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

def _source_driven_transaction_ids(
    transactions: Sequence[Mapping[str, object]],
) -> set[str]:
    """Return protected source-driven IDs from an unfiltered snapshot."""
    return {
        str(transaction.get("id") or "")
        for transaction in transactions
        if transaction_is_source_driven(transaction)
    }

def transaction_is_source_driven(transaction: Mapping[str, object]) -> bool:
    return transaction_is_mixed_use(transaction) or (
        str(transaction.get("source_type") or "").strip().lower() == "depreciation"
    )


def transaction_is_mixed_use(transaction: Mapping[str, object]) -> bool:
    """Return whether durable provenance makes this projection read-only."""
    return bool(
        str(transaction.get("source_type") or "").strip() == MIXED_USE_SOURCE_TYPE
        and str(transaction.get("source_id") or "").strip()
    )


def _selection_ids(transaction_ids: Sequence[str], rows: Sequence[int]) -> tuple[str, ...]:
    return tuple(
        transaction_ids[row_index]
        for row_index in rows
        if 0 <= row_index < len(transaction_ids)
    )
