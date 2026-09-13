"""Mileage Add controller and compatibility exports."""

from __future__ import annotations

import streamlit as st
from typing import TYPE_CHECKING

from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    tag_selector_error,
)

from .mileage_form_shared import (
    render_mileage_fields,
    validate_mileage_draft,
)
from .mileage_routing import _route_key, _save_round_trip

if TYPE_CHECKING:
    from .mileage import MileageContext


def render_add_mileage_form(context: MileageContext, tags: object) -> None:
    """Render Add mileage fields and keep creation in this controller."""
    mileage_form_keys = (
        "add_mileage_trip_date",
        "add_mileage_miles",
        "add_mileage_vehicle",
        "add_mileage_start",
        "add_mileage_destination",
        "add_mileage_round_trip",
        "add_mileage_round_trip__last",
        "add_mileage_purpose",
        "add_mileage_notes",
        "add_mileage_tag_ids",
        "add_mileage_return_miles",
        "add_mileage_start__selection",
        "add_mileage_destination__selection",
        "add_mileage_recorded_start",
        "add_mileage_recorded_destination",
        "add_mileage_recorded_start__autocomplete_version",
        "add_mileage_recorded_destination__autocomplete_version",
        "add_mileage_recorded_start__autofill_value",
        "add_mileage_recorded_destination__autofill_value",
        "add_mileage_recorded_start__manually_edited",
        "add_mileage_recorded_destination__manually_edited",
        _route_key(context, "add"),
        f"{_route_key(context, 'add')}__pending_miles",
        f"{_route_key(context, 'add')}__stale",
        "add_mileage_miles__calculated",
        "add_mileage_return_miles__calculated",
    )
    context.reset_widget_state_if_requested(
        "reset_add_mileage_form", keys=mileage_form_keys
    )
    st.subheader("Add trip")
    if not isinstance(tags, (list, tuple)):
        tags = []
    draft = render_mileage_fields(
        context, tags, mode="add", defaults={}, allow_round_trip=True
    )
    save_error = st.empty()
    submitted = st.button("Save mileage trip", type="primary", width="stretch")
    if not submitted:
        return
    if draft_error := validate_mileage_draft(draft):
        save_error.error(draft_error)
    elif tag_error := tag_selector_error("add_mileage_tag_ids"):
        save_error.error(tag_error)
    elif tag_error := inline_tag_name_error(draft["new_tag_name"]):
        save_error.error(tag_error)
    elif draft["start_selection"].place_id and not draft["start_location"].strip():
        save_error.error("Enter the starting location text to record in the ledger.")
    elif draft["destination_selection"].place_id and not draft["destination"].strip():
        save_error.error("Enter the destination text to record in the ledger.")
    else:
        payload = {
            "trip_date": draft["trip_date"],
            "miles": draft["miles"],
            "return_miles": draft["return_miles"],
            "vehicle": draft["vehicle"],
            "start_location": draft["start_location"],
            "destination": draft["destination"],
            "business_purpose": draft["business_purpose"],
            "notes": draft["notes"],
            "tag_ids": draft["tag_ids"],
            "new_tag_name": draft["new_tag_name"],
            "round_trip": draft["round_trip"],
        }
        context.confirmed_write(
            "create_mileage_round_trip"
            if draft["round_trip"]
            else "create_mileage_trip",
            payload,
            (
                lambda: _save_round_trip(
                    context.storage,
                    trip_date=draft["trip_date"],
                    miles=draft["miles"],
                    return_miles=draft["return_miles"],
                    vehicle=draft["vehicle"],
                    start_location=draft["start_location"],
                    destination=draft["destination"],
                    business_purpose=draft["business_purpose"],
                    notes=draft["notes"],
                    tag_ids=draft["tag_ids"],
                    new_tag_name=draft["new_tag_name"] or "",
                )
            )
            if draft["round_trip"]
            else lambda: context.storage.create_mileage_trip(
                trip_date=draft["trip_date"],
                miles=draft["miles"],
                vehicle=draft["vehicle"],
                start_location=draft["start_location"],
                destination=draft["destination"],
                business_purpose=draft["business_purpose"],
                notes=draft["notes"],
                tag_ids=draft["tag_ids"],
                new_tag_name=draft["new_tag_name"],
            ),
            "Round trip saved as two mileage entries."
            if draft["round_trip"]
            else "Mileage trip saved.",
            on_success=lambda: context.schedule_widget_reset("reset_add_mileage_form"),
            report_error=save_error.error,
        )
