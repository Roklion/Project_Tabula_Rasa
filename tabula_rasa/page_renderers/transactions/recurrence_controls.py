"""Shared controls and payload helpers for recurring Expense creation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import streamlit as st


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
    return f"recurring_edit_pending_schedule_id_{record_id}_profile_{profile_key}"


def mixed_use_edit_pending_schedule_key(profile_key: str, source_id: str) -> str:
    """Build a mixed-use-edit retry key with an unambiguous profile suffix."""
    return f"mixed_use_edit_pending_schedule_id_{source_id}_profile_{profile_key}"


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
    "recurring_edit_pending_schedule_key",
    "render_recurrence_controls",
]
