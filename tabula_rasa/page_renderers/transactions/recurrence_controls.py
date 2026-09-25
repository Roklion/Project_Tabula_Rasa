"""Shared controls and payload helpers for recurring Expense creation."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date

import streamlit as st

from tabula_rasa.recurrence_state import (
    mixed_use_edit_pending_state,
    transaction_edit_pending_state,
)


@dataclass(frozen=True)
class RecurrenceSelection:
    """Values collected by the shared recurring Expense controls."""

    enabled: bool = False
    unit: str | None = None
    interval: int | None = None
    name: str | None = None
    end_date: date | None = None

    def schedule_fields(
        self, *, description: str, fallback_name: str
    ) -> dict[str, object]:
        """Return storage fields shared by add and existing-expense flows."""
        return {
            "name": self.name or description or fallback_name,
            "recurrence_unit": self.unit,
            "recurrence_interval": self.interval,
            "end_date": self.end_date,
        }


def recurring_edit_pending_schedule_key(profile_key: str, record_id: str) -> str:
    """Build an ordinary-edit retry key with an unambiguous profile suffix."""
    return transaction_edit_pending_state(profile_key, record_id).schedule_id_key


def mixed_use_edit_pending_schedule_key(profile_key: str, source_id: str) -> str:
    """Build a mixed-use-edit retry key with an unambiguous profile suffix."""
    return mixed_use_edit_pending_state(profile_key, source_id).schedule_id_key


def recurring_edit_pending_payload_key(profile_key: str, record_id: str) -> str:
    """Build an ordinary-edit retry payload key with an exact profile suffix."""
    return transaction_edit_pending_state(profile_key, record_id).payload_key


def mixed_use_edit_pending_payload_key(profile_key: str, source_id: str) -> str:
    """Build a mixed-use-edit retry payload key with an exact profile suffix."""
    return mixed_use_edit_pending_state(profile_key, source_id).payload_key


def edit_defaults_with_pending_payload(
    defaults: Mapping[str, object], pending_payload: object
) -> dict[str, object]:
    """Restore all submitted edit fields before rebuilding a retry form."""
    restored = dict(defaults)
    if isinstance(pending_payload, Mapping):
        restored.update(pending_payload)
    return restored


def restore_recurrence_controls(
    state: MutableMapping[str, object],
    selection: Mapping[str, object] | None,
    *,
    key_prefix: str,
    key_suffix: str = "",
) -> None:
    """Restore recurrence widgets from a pending edit payload after a rerun."""
    if not isinstance(selection, Mapping):
        return

    def key(name: str) -> str:
        return "_".join(part for part in (key_prefix, name, key_suffix) if part)

    state.setdefault(key("recurring"), True)
    for name, field in (
        ("recurrence_unit", "recurrence_unit"),
        ("recurrence_interval", "recurrence_interval"),
        ("recurrence_name", "name"),
        ("recurrence_end", "end_date"),
    ):
        if field in selection:
            state.setdefault(key(name), selection[field])


def render_recurrence_controls(
    *,
    label: str,
    key_prefix: str,
    help_text: str,
    key_suffix: str = "",
) -> RecurrenceSelection:
    """Render the common opt-in cadence editor for an Expense."""
    def key(name: str) -> str:
        return "_".join(part for part in (key_prefix, name, key_suffix) if part)

    enabled = st.checkbox(
        label,
        key=key("recurring"),
        help=help_text,
    )
    if not enabled:
        return RecurrenceSelection()
    first, second = st.columns(2)
    unit = first.selectbox(
        "Repeat every",
        ["day", "week", "month", "year"],
        index=2,
        key=key("recurrence_unit"),
    )
    interval = second.number_input(
        "Interval",
        min_value=1,
        value=1,
        step=1,
        key=key("recurrence_interval"),
    )
    name = st.text_input(
        "Schedule name",
        key=key("recurrence_name"),
    )
    end_date = st.date_input(
        "End date (optional)",
        value=None,
        key=key("recurrence_end"),
    )
    return RecurrenceSelection(True, unit, int(interval), name, end_date)


__all__ = [
    "RecurrenceSelection",
    "mixed_use_edit_pending_schedule_key",
    "mixed_use_edit_pending_payload_key",
    "edit_defaults_with_pending_payload",
    "recurring_edit_pending_schedule_key",
    "recurring_edit_pending_payload_key",
    "render_recurrence_controls",
    "restore_recurrence_controls",
]
