"""Coordinate Simple Transaction and Multi-line Journal creation."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence

import streamlit as st

from tabula_rasa.page_renderers.transactions.context import TransactionsContext
from tabula_rasa.page_renderers.transactions.creation import render_add_transaction
from tabula_rasa.page_renderers.transactions.journal_editor import (
    render_new_journal_entry,
)
from tabula_rasa.page_renderers.transactions.metadata_fields import (
    render_transaction_date,
    render_transaction_description,
)
from tabula_rasa.page_renderers.transactions.receipts import (
    creation_receipt_workflow,
    render_receipt_creation_recovery,
)


SIMPLE_MODE = "Simple Transaction"
JOURNAL_MODE = "Multi-line Journal"
ENTRY_MODES = (SIMPLE_MODE, JOURNAL_MODE)
_SHARED_WIDGET_KEYS = ("add_transaction_date", "add_transaction_description")


def _entry_state_key(profile_key: str, name: str) -> str:
    return f"entry_creation_{name}_{profile_key}"


def _dirty_key(profile_key: str, mode: str) -> str:
    suffix = "simple" if mode == SIMPLE_MODE else "journal"
    return _entry_state_key(profile_key, f"{suffix}_dirty")


def _baseline_key(profile_key: str, mode: str) -> str:
    suffix = "simple" if mode == SIMPLE_MODE else "journal"
    return _entry_state_key(profile_key, f"{suffix}_baseline")


def _raw_baseline_key(profile_key: str, mode: str) -> str:
    suffix = "simple" if mode == SIMPLE_MODE else "journal"
    return _entry_state_key(profile_key, f"{suffix}_raw_baseline")


def _snapshot_widget_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _snapshot_widget_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot_widget_value(item) for item in value)
    if hasattr(value, "name") and (
        hasattr(value, "file_id") or hasattr(value, "size")
    ):
        return (
            str(getattr(value, "file_id", "") or ""),
            str(getattr(value, "name", "") or ""),
            int(getattr(value, "size", 0) or 0),
        )
    return value


def _mode_widget_snapshot(
    state: Mapping[str, object], profile_key: str, mode: str
) -> tuple[tuple[str, object], ...]:
    """Capture current mode widgets for callback-time dirty detection."""
    if mode == SIMPLE_MODE:
        items = (
            (key, value)
            for key, value in state.items()
            if key.startswith("add_transaction_")
            and key not in {*_SHARED_WIDGET_KEYS, "add_transaction_save"}
        )
    else:
        items = (
            (key, value)
            for key, value in state.items()
            if (
                key.startswith(f"journal_create_{profile_key}_")
                or (
                    key.startswith("journal_create_")
                    and key.endswith(f"_{profile_key}")
                )
            )
            and not key.endswith(("_save", "_add_line", "_remove"))
        )
    return tuple(
        sorted((key, _snapshot_widget_value(value)) for key, value in items)
    )


def _clear_mode_specific_state(
    state: MutableMapping[str, object],
    profile_key: str,
    mode: str,
) -> None:
    """Discard only the outgoing editor body, retaining shared Date and Memo."""
    state.pop(_baseline_key(profile_key, mode), None)
    state.pop(_raw_baseline_key(profile_key, mode), None)
    state.pop(_dirty_key(profile_key, mode), None)
    if mode == SIMPLE_MODE:
        for key in list(state):
            if key.startswith("add_transaction_") and key not in _SHARED_WIDGET_KEYS:
                state.pop(key, None)
        state.pop(_entry_state_key(profile_key, "simple_switch_blocked"), None)
        return
    for key in list(state):
        if key.startswith(f"journal_create_{profile_key}_") or (
            key.startswith("journal_create_")
            and key.endswith(f"_{profile_key}")
        ):
            state.pop(key, None)


def _request_entry_mode(profile_key: str) -> None:
    state = st.session_state
    active_key = _entry_state_key(profile_key, "active_mode")
    requested_key = _entry_state_key(profile_key, "requested_mode")
    pending_key = _entry_state_key(profile_key, "pending_mode")
    notice_key = _entry_state_key(profile_key, "switch_notice")
    active = str(state.get(active_key) or SIMPLE_MODE)
    requested = str(state.get(requested_key) or active)
    if requested == active:
        state.pop(pending_key, None)
        return
    if bool(state.get(_entry_state_key(profile_key, "simple_switch_blocked"))) and (
        active == SIMPLE_MODE
    ):
        state[requested_key] = active
        state[notice_key] = (
            "Finish or resolve the pending recurring transaction save before "
            "switching entry editors."
        )
        return
    raw_baseline = state.get(_raw_baseline_key(profile_key, active))
    dirty = bool(state.get(_dirty_key(profile_key, active))) or (
        raw_baseline is not None
        and raw_baseline != _mode_widget_snapshot(state, profile_key, active)
    )
    if dirty:
        state[pending_key] = requested
        state[requested_key] = active
        state.pop(notice_key, None)
        return
    _clear_mode_specific_state(state, profile_key, active)
    state[active_key] = requested
    state.pop(pending_key, None)
    state.pop(notice_key, None)


def _confirm_entry_mode_switch(profile_key: str) -> None:
    state = st.session_state
    active_key = _entry_state_key(profile_key, "active_mode")
    requested_key = _entry_state_key(profile_key, "requested_mode")
    pending_key = _entry_state_key(profile_key, "pending_mode")
    active = str(state.get(active_key) or SIMPLE_MODE)
    pending = str(state.get(pending_key) or "")
    if pending not in ENTRY_MODES or pending == active:
        state.pop(pending_key, None)
        return
    _clear_mode_specific_state(state, profile_key, active)
    state[active_key] = pending
    state[requested_key] = pending
    state.pop(pending_key, None)


def _cancel_entry_mode_switch(profile_key: str) -> None:
    state = st.session_state
    active = str(
        state.get(_entry_state_key(profile_key, "active_mode")) or SIMPLE_MODE
    )
    state[_entry_state_key(profile_key, "requested_mode")] = active
    state.pop(_entry_state_key(profile_key, "pending_mode"), None)


def _record_draft_state(
    state: MutableMapping[str, object],
    profile_key: str,
    mode: str,
    draft: Mapping[str, object],
) -> None:
    baseline_key = _baseline_key(profile_key, mode)
    if baseline_key not in state:
        state[baseline_key] = dict(draft)
    raw_baseline_key = _raw_baseline_key(profile_key, mode)
    current_raw = _mode_widget_snapshot(state, profile_key, mode)
    if raw_baseline_key not in state:
        state[raw_baseline_key] = current_raw
    state[_dirty_key(profile_key, mode)] = (
        state[baseline_key] != dict(draft)
        or state[raw_baseline_key] != current_raw
    )


def _reset_creation_widgets_if_requested(context: TransactionsContext) -> None:
    reset_requested = bool(st.session_state.get("reset_add_transaction_form"))
    context.reset_widget_state_if_requested(
        "reset_add_transaction_form",
        keys=(
            *_SHARED_WIDGET_KEYS,
            "add_transaction_kind",
            "add_transaction_amount",
            "add_transaction_category_income",
            "add_transaction_category_expense",
            "add_transaction_category_transfer",
            "add_transaction_account_income",
            "add_transaction_account_expense",
            "add_transaction_account_transfer",
            "add_transaction_to_account",
            "add_transaction_payee",
            "add_transaction_tags",
            "add_transaction_reference",
            "add_transaction_receipts",
            "add_transaction_recurring",
            "add_transaction_recurrence_unit",
            "add_transaction_recurrence_interval",
            "add_transaction_recurrence_name",
            "add_transaction_recurrence_end",
        ),
    )
    if reset_requested:
        # A confirmed save starts a fresh baseline without changing the selected
        # editor mode or affecting retry state owned by receipts/recurrence.
        for mode in ENTRY_MODES:
            st.session_state.pop(_baseline_key(context.profile_key, mode), None)
            st.session_state.pop(_raw_baseline_key(context.profile_key, mode), None)
            st.session_state.pop(_dirty_key(context.profile_key, mode), None)


def _render_switch_confirmation(profile_key: str) -> None:
    pending = str(
        st.session_state.get(_entry_state_key(profile_key, "pending_mode")) or ""
    )
    notice = str(
        st.session_state.pop(_entry_state_key(profile_key, "switch_notice"), "")
    )
    if notice:
        st.warning(notice)
    if pending not in ENTRY_MODES:
        return
    st.warning(
        f"Switching to {pending} will discard the unsaved fields in the current "
        "editor. The shared Date and Description / memo will be kept."
    )
    discard_column, keep_column = st.columns(2)
    discard_column.button(
        f"Discard and switch to {pending}",
        type="primary",
        width="stretch",
        key=_entry_state_key(profile_key, "confirm_switch"),
        on_click=_confirm_entry_mode_switch,
        args=(profile_key,),
    )
    keep_column.button(
        "Keep editing",
        width="stretch",
        key=_entry_state_key(profile_key, "cancel_switch"),
        on_click=_cancel_entry_mode_switch,
        args=(profile_key,),
    )


def _render_entry_creation(
    context: TransactionsContext,
    *,
    accounts: Sequence[Mapping[str, object]],
    account_map: Mapping[str, str],
    categories: Sequence[Mapping[str, object]],
    category_paths: Mapping[str, str],
    payees: Sequence[Mapping[str, object]],
    tags: Sequence[Mapping[str, object]],
) -> None:
    """Render the shared creation surface and one committed editor mode."""
    recovery = creation_receipt_workflow(context)
    if isinstance(recovery, Mapping) and recovery.get("mixed_use_source_id"):
        return
    if render_receipt_creation_recovery(context):
        return

    _reset_creation_widgets_if_requested(context)
    profile_key = context.profile_key
    active_key = _entry_state_key(profile_key, "active_mode")
    requested_key = _entry_state_key(profile_key, "requested_mode")
    active_mode = str(st.session_state.setdefault(active_key, SIMPLE_MODE))
    st.session_state.setdefault(requested_key, active_mode)

    st.subheader("New entry")
    st.caption(
        "Use Simple Transaction for ordinary activity or Multi-line Journal "
        "for an advanced balanced entry."
    )
    st.segmented_control(
        "Entry Type",
        list(ENTRY_MODES),
        key=requested_key,
        on_change=_request_entry_mode,
        args=(profile_key,),
    )
    _render_switch_confirmation(profile_key)

    # Shared fields remain mounted when the mode-specific editor changes.
    shared_date = render_transaction_date(None, key="add_transaction_date")
    shared_description = render_transaction_description(
        "", key="add_transaction_description"
    )
    active_mode = str(st.session_state.get(active_key) or SIMPLE_MODE)
    if active_mode == SIMPLE_MODE:
        state = render_add_transaction(
            context,
            account_map=account_map,
            categories=categories,
            category_paths=category_paths,
            payees=payees,
            tags=tags,
            shared_date=shared_date,
            shared_description=shared_description,
            show_heading=False,
            check_recovery=False,
        )
        if state is not None:
            _record_draft_state(
                st.session_state,
                profile_key,
                SIMPLE_MODE,
                state.draft,
            )
            st.session_state[
                _entry_state_key(profile_key, "simple_switch_blocked")
            ] = state.switch_blocked
        return

    account_paths = {
        str(account_id): str(account_path)
        for account_path, account_id in account_map.items()
    }
    journal_state = render_new_journal_entry(
        context,
        shared_date=shared_date,
        shared_description=shared_description,
        accounts=accounts,
        categories=categories,
        account_paths=account_paths,
        category_paths=category_paths,
        payees=payees,
    )
    _record_draft_state(
        st.session_state,
        profile_key,
        JOURNAL_MODE,
        journal_state.draft,
    )


def render_entry_creation(context: TransactionsContext, **kwargs) -> None:
    """Replace the whole creation surface after a confirmed save."""
    slot = st.empty()
    if creation_receipt_workflow(context) is not None:
        # Keep the old editor slot empty while recovery renders beside it.
        # Reusing its block for fewer children can retain stale browser controls
        # across an interrupted save/rerun.
        slot.empty()
        _render_entry_creation(context, **kwargs)
    else:
        with slot.container():
            _render_entry_creation(context, **kwargs)


__all__ = [
    "ENTRY_MODES",
    "JOURNAL_MODE",
    "SIMPLE_MODE",
    "render_entry_creation",
]
