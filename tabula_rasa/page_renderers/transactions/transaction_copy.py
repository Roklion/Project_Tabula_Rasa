"""Transaction copy and provenance state helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import re
import streamlit as st
from .metadata_fields import (  # noqa: F401 - compatibility exports
    editable_account_ids as _editable_account_ids,
    copyable_tag_ids as _copyable_tag_ids,
)
from tabula_rasa.page_renderers.tag_selector import schedule_tag_selector_reset

def copied_transaction_description(transaction: Mapping[str, object]) -> str:
    """Build copy provenance while retaining the user's current memo."""
    source_id = str(transaction.get("id") or "").strip()
    description = str(transaction.get("description", "") or "").strip()

    # Copies created by earlier versions put provenance before the memo, while
    # the current format puts it after the memo. Remove either form repeatedly
    # so copying an already-copied transaction does not accumulate stale notes.
    provenance_prefix = re.compile(
        r"^Copy From\s+(?:[^\s]+|"
        rf"{re.escape(source_id)})"
        r"(?:\s*:\s+|\.\s+)"
        r"|^Copied from transaction\s+(?:[^\s]+|"
        rf"{re.escape(source_id)})"
        r"(?:\s*:\s+|\.\s+)"
    )
    provenance_prefix_only = re.compile(
        r"^(?:Copy From|Copied from transaction)\s+(?:[^\s]+|"
        rf"{re.escape(source_id)})$"
    )
    provenance_suffix = re.compile(
        r"\.\s+(?:Copy From|Copied from transaction)\s+"
        r"(?:[^\s]+|"
        rf"{re.escape(source_id)})$"
    )
    while description:
        stripped = provenance_prefix.sub("", description, count=1).strip()
        if stripped != description:
            description = stripped
            continue
        stripped = provenance_prefix_only.sub("", description, count=1).strip()
        if stripped != description:
            description = stripped
            continue
        match = provenance_suffix.search(description)
        if match is None:
            break
        description = description[: match.start()].rstrip(" .:")

    provenance = f"Copy From {source_id}" if source_id else "Copy From"
    if not description:
        return provenance
    if not description.endswith("."):
        description += "."
    return f"{description} {provenance}"

def _finish_copy_save(profile_key: str, tag_selector_key: str) -> None:
    _clear_copy_state(profile_key)
    schedule_tag_selector_reset(tag_selector_key)

def _pending_edit_transaction_key(profile_key: str) -> str:
    return f"transaction_pending_edit_{profile_key}"

def _clear_copy_state(profile_key: str) -> None:
    """Leave the source row in normal edit mode without writing anything."""
    st.session_state.pop(_copy_source_key(profile_key), None)

def _copy_source_key(profile_key: str) -> str:
    """Return the profile-scoped source ID for the active copy form."""
    return f"transaction_copy_source_{profile_key}"

def _make_created_copy_visible(
    profile_key: str,
    transaction: Mapping[str, object],
) -> None:
    """Adjust ledger filters so the newly created copy stays selectable."""
    transaction_id = str(transaction.get("id") or "").strip()
    transaction_date = transaction.get("txn_date")
    if not transaction_id or not transaction_date:
        return
    try:
        created_date = date.fromisoformat(str(transaction_date))
    except ValueError:
        return
    start = st.session_state.get("ledger_start")
    end = st.session_state.get("ledger_end")
    if isinstance(start, date):
        st.session_state["ledger_start"] = min(start, created_date)
    else:
        st.session_state["ledger_start"] = created_date
    if isinstance(end, date):
        st.session_state["ledger_end"] = max(end, created_date)
    else:
        st.session_state["ledger_end"] = created_date
    st.session_state[f"ledger_filter_type_{profile_key}"] = "All"
    st.session_state[f"ledger_filter_accounts_{profile_key}"] = []
    st.session_state[f"ledger_filter_tags_{profile_key}"] = []
    for key in tuple(st.session_state):
        if key.startswith(f"ledger_search_{profile_key}_"):
            st.session_state[key] = ""
    st.session_state["edit_transaction_id"] = transaction_id

def _copy_generation_key(profile_key: str) -> str:
    """Return the profile-scoped generation used to isolate copy widgets."""
    return f"transaction_copy_generation_{profile_key}"
