"""Mileage page orchestration and compatibility facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from tabula_rasa.storage import GoogleSheetsStorage, StorageError

from .mileage_form import render_add_mileage_form
from .mileage_ledger import (
    _render_tag_selector,
    _tag_names_for_trip,
    _tag_records_by_id,
    _tag_name,
    _trip_tag_ids,
    mileage_frame,
    render_mileage_ledger,
)
from .mileage_locations import (
    _acknowledge_recorded_location_text,
    _edit_address_initial_value,
    _ledger_location_text,
    _recorded_address_changed,
)
from .mileage_routing import (
    PartialRouteError,
    RouteValidationError,
    _address_text_changed,
    _apply_pending_route_mileage,
    _autocomplete_available,
    _calculate_routes,
    _clear_unchanged_calculated_mileage,
    _discard_modified_calculated_mileage_markers,
    _edit_route_warning_visible,
    _needs_google_maps_attribution,
    _route_disabled_reason,
    _route_key,
    _route_ready,
    _route_state_has_current_endpoints,
    _route_state_is_current,
    _same_selected_place,
    _safe_route_error,
    _save_round_trip,
    _selection_fingerprint,
    _set_widget_default,
)


@dataclass(frozen=True)
class MileageContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    reset_widget_state_if_requested: Callable[..., None]
    schedule_widget_reset: Callable[[str], None]
    maps_api_key: str | None = None
    route_mileage: Callable[[str, str], float] | None = None
    autocomplete_region_code: str | None = None


def render_mileage(context: MileageContext) -> None:
    """Render the add-trip and mileage-log workflows."""
    from tabula_rasa.presentation import render_page_header
    import streamlit as st

    render_page_header(
        "Mileage",
        "Keep a dated business-mileage log with the route, purpose, and vehicle.",
    )
    try:
        tags = context.storage.list_tags()
    except StorageError as error:
        context.report_storage_error(error)
        st.stop()
    tag_by_id = _tag_records_by_id(tags)
    tab_add, tab_log = st.tabs(["Add trip", "View & edit mileage log"])
    page_footer = st.empty()
    with tab_add:
        render_add_mileage_form(context, tags)
    with tab_log:
        render_mileage_ledger(context, tags, tag_by_id, page_footer)


__all__ = [
    "MileageContext",
    "PartialRouteError",
    "RouteValidationError",
    "_acknowledge_recorded_location_text",
    "_address_text_changed",
    "_apply_pending_route_mileage",
    "_autocomplete_available",
    "_calculate_routes",
    "_clear_unchanged_calculated_mileage",
    "_discard_modified_calculated_mileage_markers",
    "_edit_address_initial_value",
    "_edit_route_warning_visible",
    "_ledger_location_text",
    "_needs_google_maps_attribution",
    "_recorded_address_changed",
    "_render_tag_selector",
    "_route_disabled_reason",
    "_route_key",
    "_route_ready",
    "_route_state_has_current_endpoints",
    "_route_state_is_current",
    "_safe_route_error",
    "_same_selected_place",
    "_save_round_trip",
    "_selection_fingerprint",
    "_set_widget_default",
    "_tag_name",
    "_tag_names_for_trip",
    "_tag_records_by_id",
    "_trip_tag_ids",
    "mileage_frame",
    "render_mileage",
]
