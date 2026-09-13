"""Shared mileage fields and route state for Add and Edit workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import TYPE_CHECKING, Literal

import streamlit as st

from tabula_rasa.address_autocomplete import (
    address_autocomplete,
    render_google_maps_attribution,
)
from tabula_rasa.page_renderers.tag_selector import render_tag_selector

from .mileage_locations import (
    _acknowledge_recorded_location_text,
    _edit_address_initial_value,
    _ledger_location_text,
    _recorded_address_changed,
)
from .mileage_routing import (
    PartialRouteError,
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
    _safe_route_error,
    _selection_fingerprint,
    _set_widget_default,
    _same_selected_place,
)

if TYPE_CHECKING:
    from .mileage import MileageContext

MileageFormMode = Literal["add", "edit"]


def mileage_widget_key(prefix: str, name: str, scope: str = "") -> str:
    return "_".join(part for part in (prefix, name, scope) if part)


def validate_mileage_draft(draft: Mapping[str, object]) -> str | None:
    """Return validation shared by the Add and Edit mileage controllers."""
    start_selection = draft.get("start_selection")
    destination_selection = draft.get("destination_selection")
    if start_selection is None or destination_selection is None:
        return "Starting location and destination must be selected."
    if _same_selected_place(
        start_selection, destination_selection
    ):
        return "Starting location and destination must be different."
    return None


def render_mileage_fields(
    context: MileageContext,
    tags: Sequence[Mapping[str, object]],
    *,
    mode: MileageFormMode,
    defaults: Mapping[str, object],
    key_scope: str = "",
    record_id: str = "",
    allow_round_trip: bool = False,
) -> dict[str, object]:
    """Render common address, routing, and trip fields without owning persistence.

    Address controls intentionally remain outside ``st.form``. Autocomplete
    selection is a browser event that must be allowed to rerun without losing
    the rest of an unsubmitted draft.
    """
    prefix = "add_mileage" if mode == "add" else "edit_mileage_trip"
    raw_date = defaults.get("trip_date")
    try:
        trip_date_default = (
            raw_date
            if isinstance(raw_date, date)
            else date.fromisoformat(str(raw_date or date.today()))
        )
    except ValueError:
        trip_date_default = date.today()
    start_location = str(defaults.get("start_location") or "")
    destination_text = str(defaults.get("destination") or "")
    vehicle_default = str(defaults.get("vehicle") or "")
    purpose_default = str(defaults.get("business_purpose") or "")
    notes_default = str(defaults.get("notes") or "")
    miles_default = float(defaults.get("miles") or 0.0)
    default_tag_ids = defaults.get("tag_ids") or ()

    def key(name: str) -> str:
        return mileage_widget_key(prefix, name, key_scope)

    workflow = "add" if mode == "add" else f"edit_{record_id}"
    route_key = _route_key(context, workflow)
    miles_key = key("miles")
    return_miles_key = key("return_miles") if allow_round_trip else None
    start_key = key("start")
    destination_key = key("destination")

    address_columns = st.columns(2, gap="small")
    start = address_columns[0].empty()
    destination = address_columns[1].empty()
    with start:
        start_selection = address_autocomplete(
            "Starting location",
            key=start_key,
            api_key=context.maps_api_key,
            value=(
                ""
                if mode == "add"
                else _edit_address_initial_value(
                    start_location, context.maps_api_key
                )
            ),
            region_code=context.autocomplete_region_code,
        )
    with destination:
        destination_selection = address_autocomplete(
            "Destination",
            key=destination_key,
            api_key=context.maps_api_key,
            value=(
                ""
                if mode == "add"
                else _edit_address_initial_value(
                    destination_text, context.maps_api_key
                )
            ),
            region_code=context.autocomplete_region_code,
        )

    route_state = st.session_state.get(route_key)
    endpoint_fingerprint = _selection_fingerprint(
        start_selection, destination_selection
    )
    round_trip = (
        bool(st.session_state.get(key("round_trip"), False))
        if allow_round_trip
        else False
    )
    fingerprint = (*endpoint_fingerprint, round_trip)
    pending_key = f"{route_key}__pending_miles"
    _apply_pending_route_mileage(
        st.session_state.pop(pending_key, None),
        fingerprint=fingerprint,
        round_trip=round_trip,
        miles_key=miles_key,
        return_miles_key=return_miles_key,
    )
    _discard_modified_calculated_mileage_markers(
        miles_key=miles_key, return_miles_key=return_miles_key
    )
    route_changed = False
    address_changed = bool(st.session_state.get(f"{route_key}__stale"))
    if route_state and route_state.get("fingerprint") != fingerprint:
        endpoints_changed = not _route_state_has_current_endpoints(
            route_state, endpoint_fingerprint
        )
        if endpoints_changed:
            _clear_unchanged_calculated_mileage(
                route_state, miles_key=miles_key, return_miles_key=return_miles_key
            )
            st.session_state.pop(route_key, None)
            route_state = None
            st.session_state[f"{route_key}__stale"] = True
            address_changed = True
            route_changed = mode == "edit"
        else:
            updated = dict(route_state)
            updated["fingerprint"] = fingerprint
            if round_trip:
                updated["return"] = None
            else:
                updated.pop("return", None)
            st.session_state[route_key] = updated
            route_state = updated

    route_ready = _route_ready(
        start_selection, destination_selection, context.route_mileage
    )
    disabled_reason = _route_disabled_reason(
        start_selection,
        destination_selection,
        context.route_mileage,
        autocomplete_available=(
            context.maps_api_key is not None
            and _autocomplete_available(start_key, destination_key)
        ),
    )
    if allow_round_trip:
        round_trip = st.checkbox(
            "Round trip",
            help=(
                "Creates an outbound entry and a second entry with the starting "
                "and ending locations reversed. Outbound and return mileage can "
                "be reviewed independently."
            ),
            key=key("round_trip"),
        )
        round_trip_last_key = key("round_trip__last")
        last_round_trip = st.session_state.get(round_trip_last_key)
        if isinstance(last_round_trip, bool) and last_round_trip != round_trip:
            st.session_state.pop(return_miles_key, None)
            st.session_state.pop(f"{return_miles_key}__calculated", None)
        st.session_state[round_trip_last_key] = round_trip

    recorded_start = _ledger_location_text(
        start_selection,
        label="Starting location",
        key=key("recorded_start"),
        existing_value=start_location,
        always_render=bool(context.maps_api_key),
    )
    recorded_destination = _ledger_location_text(
        destination_selection,
        label="Destination",
        key=key("recorded_destination"),
        existing_value=destination_text,
        always_render=bool(context.maps_api_key),
    )
    calculate_requested = st.button(
        "Recalculate mileage" if route_state else "Calculate mileage",
        disabled=not route_ready,
        help=disabled_reason if not route_ready else None,
        key=key("calculate"),
    )
    if not route_ready and context.route_mileage is not None:
        st.caption(disabled_reason)
    recorded_changed = (
        bool(
            route_state
            and (
                st.session_state.get(f"{key('recorded_start')}__manually_edited", False)
                or st.session_state.get(
                    f"{key('recorded_destination')}__manually_edited", False
                )
            )
        )
        if mode == "add"
        else (
            _recorded_address_changed(
                recorded_start,
                start_location,
                start_selection,
                manually_edited=st.session_state.get(
                    f"{key('recorded_start')}__manually_edited", False
                ),
            )
            or _recorded_address_changed(
                recorded_destination,
                destination_text,
                destination_selection,
                manually_edited=st.session_state.get(
                    f"{key('recorded_destination')}__manually_edited", False
                ),
            )
        )
    )
    if recorded_changed:
        st.session_state[f"{route_key}__stale"] = True
        address_changed = True
    edit_address_changed = (
        _address_text_changed(
            start_selection,
            destination_selection,
            start_location,
            destination_text,
        )
        if mode == "edit"
        else False
    )
    if mode == "add":
        if route_state and route_state.get("partial"):
            st.warning(
                "Outbound mileage is ready. Enter return miles manually or retry the return route."
            )
        if address_changed:
            st.warning(
                "The selected addresses changed, so any mileage left in the boxes may not match the current route. "
                + (
                    "Calculate mileage again to refresh it before saving."
                    if route_ready
                    else "Review or enter mileage manually before saving."
                )
            )
        elif route_ready and (
            route_state is None or (round_trip and route_state.get("return") is None)
        ):
            st.warning(
                "No return-route mileage has been calculated for this round trip. Calculate mileage to compare the route, "
                "or review the entered mileage manually before saving."
                if round_trip
                else "No mileage has been calculated for the selected addresses. Calculate mileage to compare the route, or review the entered mileage manually before saving."
            )
    elif context.maps_api_key and _edit_route_warning_visible(
        edit_address_changed,
        route_changed,
        route_state,
        fingerprint,
        recorded_address_changed=recorded_changed,
    ):
        st.warning(
            "The address changed, so the existing mileage may not match the current route. Calculate mileage again to refresh it, "
            "or review and edit the mileage manually before saving."
        )

    with st.container():
        columns = st.columns(2, gap="small")
        trip_date = columns[0].date_input(
            "Trip date",
            trip_date_default,
            key=mileage_widget_key(
                prefix, "trip_date" if mode == "add" else "date", key_scope
            ),
        )
        vehicle = columns[1].text_input(
            "Vehicle (optional)",
            vehicle_default,
            help="For example: 2022 Honda Civic or Company van.",
            key=key("vehicle"),
        )
        columns = st.columns(2, gap="small")
        _set_widget_default(miles_key, miles_default)
        miles = columns[0].number_input(
            "Business miles",
            min_value=0.0 if mode == "add" else 0.1,
            step=0.1,
            format="%.1f",
            key=miles_key,
        )
        return_miles = miles
        if allow_round_trip and round_trip:
            _set_widget_default(return_miles_key, float(miles))
            return_miles = columns[1].number_input(
                "Return business miles",
                min_value=0.0,
                step=0.1,
                format="%.1f",
                key=return_miles_key,
                help="The return route is editable independently.",
            )
        elif allow_round_trip:
            columns[1].empty()
        selected_ids = list(default_tag_ids)
        chosen_tag_ids, new_tag_name = render_tag_selector(
            tags,
            label="Tags",
            key=key("tag_ids"),
            selected_ids=selected_ids,
            preserve_inactive_ids=selected_ids,
        )
        if _needs_google_maps_attribution(
            start_selection, destination_selection, route_state, fingerprint
        ):
            render_google_maps_attribution()
        business_purpose = st.text_input(
            "Business purpose", purpose_default, key=key("purpose")
        )
        notes = st.text_area("Notes (optional)", notes_default, key=key("notes"))

    route_error = st.empty()
    if calculate_requested and context.route_mileage is not None:
        with st.spinner("Calculating mileage…"):
            try:
                known_outbound = (
                    route_state.get("outbound")
                    if route_state and route_state.get("partial")
                    else None
                )
                preserve_manual = bool(
                    allow_round_trip
                    and route_state
                    and route_state.get("partial")
                    and st.session_state.get(f"{miles_key}__calculated") is None
                )
                outbound, returned = _calculate_routes(
                    start_selection,
                    destination_selection,
                    context.route_mileage,
                    round_trip=round_trip,
                    known_outbound=known_outbound,
                )
                st.session_state[route_key] = {
                    "fingerprint": fingerprint,
                    "outbound": outbound,
                    "return": returned,
                }
                st.session_state[pending_key] = {
                    "fingerprint": fingerprint,
                    "outbound": None if preserve_manual else outbound,
                    "return": returned,
                }
                _acknowledge_recorded_location_text(
                    key("recorded_start"), recorded_start
                )
                _acknowledge_recorded_location_text(
                    key("recorded_destination"), recorded_destination
                )
                st.session_state.pop(f"{route_key}__stale", None)
                st.rerun()
            except PartialRouteError as error:
                st.session_state[route_key] = {
                    "fingerprint": fingerprint,
                    "outbound": error.outbound,
                    "return": None,
                    "partial": True,
                }
                st.session_state[pending_key] = {
                    "fingerprint": fingerprint,
                    "outbound": None if preserve_manual else error.outbound,
                    "return": None,
                }
                _acknowledge_recorded_location_text(
                    key("recorded_start"), recorded_start
                )
                _acknowledge_recorded_location_text(
                    key("recorded_destination"), recorded_destination
                )
                st.session_state.pop(f"{route_key}__stale", None)
                st.rerun()
            except Exception as error:  # routing clients vary by provider
                route_error.error(_safe_route_error(error))

    return {
        "trip_date": trip_date,
        "miles": miles,
        "return_miles": return_miles,
        "vehicle": vehicle,
        "start_location": recorded_start,
        "destination": recorded_destination,
        "business_purpose": business_purpose,
        "notes": notes,
        "tag_ids": chosen_tag_ids,
        "new_tag_name": new_tag_name,
        "round_trip": round_trip,
        "start_selection": start_selection,
        "destination_selection": destination_selection,
        "fingerprint": fingerprint,
        "route_state": route_state if isinstance(route_state, Mapping) else None,
        "calculate_requested": calculate_requested,
    }
