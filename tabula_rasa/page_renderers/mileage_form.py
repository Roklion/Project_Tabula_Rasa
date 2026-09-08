from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import streamlit as st

from tabula_rasa.address_autocomplete import address_autocomplete, render_google_maps_attribution
from tabula_rasa.page_renderers.tag_selector import inline_tag_name_error, tag_selector_error

from .mileage_locations import (
    _acknowledge_recorded_location_text,
    _ledger_location_text,
)
from .mileage_routing import (
    PartialRouteError,
    _apply_pending_route_mileage,
    _autocomplete_available,
    _calculate_routes,
    _clear_unchanged_calculated_mileage,
    _discard_modified_calculated_mileage_markers,
    _needs_google_maps_attribution,
    _route_disabled_reason,
    _route_key,
    _route_ready,
    _route_state_has_current_endpoints,
    _same_selected_place,
    _save_round_trip,
    _safe_route_error,
    _selection_fingerprint,
    _set_widget_default,
)
from .mileage_ledger import _render_tag_selector

if TYPE_CHECKING:
    from .mileage import MileageContext

def render_add_mileage_form(context: MileageContext, tags: object) -> None:
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
        "reset_add_mileage_form",
        keys=mileage_form_keys,
    )

    st.subheader("Add trip")
    # Address widgets stay outside the form so browser selection events
    # can update their Place IDs without submitting the form.
    c1, c2 = st.columns(2, gap="small")
    start_selection = c1.empty()
    destination_selection = c2.empty()
    with start_selection:
        start = address_autocomplete(
            "Starting location",
            key="add_mileage_start",
            api_key=context.maps_api_key,
            region_code=context.autocomplete_region_code,
        )
    with destination_selection:
        destination_value = address_autocomplete(
            "Destination",
            key="add_mileage_destination",
            api_key=context.maps_api_key,
            region_code=context.autocomplete_region_code,
        )

    add_route_key = _route_key(context, "add")
    route_state = st.session_state.get(add_route_key)
    round_trip = bool(st.session_state.get("add_mileage_round_trip", False))
    last_round_trip = st.session_state.get("add_mileage_round_trip__last")
    round_trip_toggled = (
        isinstance(last_round_trip, bool) and last_round_trip != round_trip
    )
    endpoint_fingerprint = _selection_fingerprint(start, destination_value)
    fingerprint = (*endpoint_fingerprint, round_trip)
    pending_mileage_key = f"{add_route_key}__pending_miles"
    _apply_pending_route_mileage(
        st.session_state.pop(pending_mileage_key, None),
        fingerprint=fingerprint,
        round_trip=round_trip,
        miles_key="add_mileage_miles",
        return_miles_key="add_mileage_return_miles",
    )
    _discard_modified_calculated_mileage_markers(
        miles_key="add_mileage_miles",
        return_miles_key="add_mileage_return_miles",
    )
    stale_route_key = f"{add_route_key}__stale"
    address_changed = bool(st.session_state.get(stale_route_key))
    if route_state and route_state.get("fingerprint") != fingerprint:
        endpoints_changed = not _route_state_has_current_endpoints(
            route_state, endpoint_fingerprint
        )
        if endpoints_changed:
            # A changed address invalidates a previously calculated route.
            _clear_unchanged_calculated_mileage(
                route_state,
                miles_key="add_mileage_miles",
                return_miles_key="add_mileage_return_miles",
            )
            st.session_state.pop(add_route_key, None)
            route_state = None
            st.session_state[stale_route_key] = True
            address_changed = True
        else:
            # Changing trip direction does not invalidate the outbound draft.
            updated_route_state = dict(route_state)
            updated_route_state["fingerprint"] = fingerprint
            if round_trip:
                updated_route_state["return"] = None
            else:
                updated_route_state.pop("return", None)
            st.session_state[add_route_key] = updated_route_state
            route_state = updated_route_state
    route_error = st.empty()
    route_ready = _route_ready(start, destination_value, context.route_mileage)
    route_disabled_reason = _route_disabled_reason(
        start,
        destination_value,
        context.route_mileage,
        autocomplete_available=(
            context.maps_api_key is not None
            and _autocomplete_available(
                "add_mileage_start", "add_mileage_destination"
            )
        ),
    )
    calculate_requested = st.button(
        "Recalculate mileage" if route_state else "Calculate mileage",
        disabled=not route_ready,
        help=route_disabled_reason if not route_ready else None,
    )
    if not route_ready and context.route_mileage is not None:
        st.caption(route_disabled_reason)

    round_trip = st.checkbox(
        "Round trip",
        help=(
            "Creates an outbound entry and a second entry with the "
            "starting and ending locations reversed. Outbound and return "
            "mileage can be reviewed independently."
        ),
        key="add_mileage_round_trip",
    )
    if round_trip_toggled:
        st.session_state.pop("add_mileage_return_miles", None)
        st.session_state.pop("add_mileage_return_miles__calculated", None)
    st.session_state["add_mileage_round_trip__last"] = round_trip
    if route_state and route_state.get("partial"):
        st.warning(
            "Outbound mileage is ready. Enter return miles manually or "
            "retry the return route."
        )
    recorded_columns = st.columns(2, gap="small")
    with recorded_columns[0]:
        recorded_start = _ledger_location_text(
            start,
            label="Starting location",
            key="add_mileage_recorded_start",
            always_render=bool(context.maps_api_key),
        )
    with recorded_columns[1]:
        recorded_destination = _ledger_location_text(
            destination_value,
            label="Destination",
            key="add_mileage_recorded_destination",
            always_render=bool(context.maps_api_key),
        )
    recorded_text_changed = bool(
        route_state
        and (
            st.session_state.get(
                "add_mileage_recorded_start__manually_edited", False
            )
            or st.session_state.get(
                "add_mileage_recorded_destination__manually_edited", False
            )
        )
    )
    if recorded_text_changed:
        st.session_state[stale_route_key] = True
        address_changed = True
    if address_changed:
        if route_ready:
            st.warning(
                "The selected addresses changed, so any mileage left in "
                "the boxes may not match the current route. Calculate "
                "mileage again to refresh it before saving."
            )
        else:
            st.warning(
                "The selected addresses changed, so any mileage left in "
                "the boxes may not match the current route. Review or "
                "enter mileage manually before saving."
            )
    elif route_ready and (
        route_state is None or (round_trip and route_state.get("return") is None)
    ):
        if round_trip and route_state is not None:
            st.warning(
                "No return-route mileage has been calculated for this round "
                "trip. Calculate mileage to compare the route, or review the "
                "entered mileage manually before saving."
            )
        else:
            st.warning(
                "No mileage has been calculated for the selected addresses. "
                "Calculate mileage to compare the route, or review the entered "
                "mileage manually before saving."
            )

    # Keep draft widgets in page state so address-component reruns cannot
    # discard unsubmitted edits.
    with st.container():
        c1, c2 = st.columns(2, gap="small")
        trip_date = c1.date_input(
            "Trip date", date.today(), key="add_mileage_trip_date"
        )
        vehicle = c2.text_input(
            "Vehicle (optional)",
            help="For example: 2022 Honda Civic or Company van.",
            key="add_mileage_vehicle",
        )
        c1, c2 = st.columns(2, gap="small")
        _set_widget_default("add_mileage_miles", 0.0)
        miles = c1.number_input(
            "Business miles",
            min_value=0.0,
            step=0.1,
            format="%.1f",
            key="add_mileage_miles",
        )
        return_miles = miles
        if round_trip:
            _set_widget_default("add_mileage_return_miles", float(miles))
            return_miles = st.number_input(
                "Return business miles",
                min_value=0.0,
                step=0.1,
                format="%.1f",
                key="add_mileage_return_miles",
                help="The return route is editable independently.",
            )
        if _needs_google_maps_attribution(
            start, destination_value, route_state, fingerprint
        ):
            render_google_maps_attribution()
        business_purpose = st.text_input(
            "Business purpose", key="add_mileage_purpose"
        )
        notes = st.text_area("Notes (optional)", key="add_mileage_notes")
        tag_ids, new_tag_name = _render_tag_selector(
            tags,
            key="add_mileage_tag_ids",
        )
        save_error = st.empty()
        submitted = st.button("Save mileage trip", type="primary", width="stretch")
        if calculate_requested and context.route_mileage is not None:
            with st.spinner("Calculating mileage…"):
                try:
                    known_outbound = (
                        route_state.get("outbound")
                        if route_state and route_state.get("partial")
                        else None
                    )
                    preserve_manual_outbound = bool(
                        round_trip
                        and route_state
                        and route_state.get("partial")
                        and st.session_state.get("add_mileage_miles__calculated")
                        is None
                    )
                    outbound, returned = _calculate_routes(
                        start,
                        destination_value,
                        context.route_mileage,
                        round_trip=round_trip,
                        known_outbound=known_outbound,
                    )
                    st.session_state[add_route_key] = {
                        "fingerprint": fingerprint,
                        "outbound": outbound,
                        "return": returned,
                    }
                    st.session_state[pending_mileage_key] = {
                        "fingerprint": fingerprint,
                        "outbound": (
                            None if preserve_manual_outbound else outbound
                        ),
                        "return": returned,
                    }
                    _acknowledge_recorded_location_text(
                        "add_mileage_recorded_start", recorded_start
                    )
                    _acknowledge_recorded_location_text(
                        "add_mileage_recorded_destination",
                        recorded_destination,
                    )
                    st.session_state.pop(stale_route_key, None)
                    st.rerun()
                except PartialRouteError as error:
                    st.session_state[add_route_key] = {
                        "fingerprint": fingerprint,
                        "outbound": error.outbound,
                        "return": None,
                        "partial": True,
                    }
                    st.session_state[pending_mileage_key] = {
                        "fingerprint": fingerprint,
                        "outbound": (
                            None if preserve_manual_outbound else error.outbound
                        ),
                        "return": None,
                    }
                    _acknowledge_recorded_location_text(
                        "add_mileage_recorded_start", recorded_start
                    )
                    _acknowledge_recorded_location_text(
                        "add_mileage_recorded_destination",
                        recorded_destination,
                    )
                    st.session_state.pop(stale_route_key, None)
                    st.rerun()
                except Exception as error:  # routing clients vary by provider
                    route_error.error(_safe_route_error(error))
        if submitted:
            if _same_selected_place(start, destination_value):
                save_error.error(
                    "Starting location and destination must be different."
                )
            elif (tag_error := tag_selector_error("add_mileage_tag_ids")):
                save_error.error(tag_error)
            elif (tag_error := inline_tag_name_error(new_tag_name)):
                save_error.error(tag_error)
            elif start.place_id and not recorded_start.strip():
                save_error.error(
                    "Enter the starting location text to record in the ledger."
                )
            elif destination_value.place_id and not recorded_destination.strip():
                save_error.error(
                    "Enter the destination text to record in the ledger."
                )
            else:
                payload = {
                    "trip_date": trip_date,
                    "miles": miles,
                    "return_miles": return_miles,
                    "vehicle": vehicle,
                    "start_location": recorded_start,
                    "destination": recorded_destination,
                    "business_purpose": business_purpose,
                    "notes": notes,
                    "tag_ids": tag_ids,
                    "new_tag_name": new_tag_name,
                    "round_trip": round_trip,
                }
                context.confirmed_write(
                    "create_mileage_round_trip"
                    if round_trip
                    else "create_mileage_trip",
                    payload,
                    (
                        lambda: _save_round_trip(
                            context.storage,
                            trip_date=trip_date,
                            miles=miles,
                            return_miles=return_miles,
                            vehicle=vehicle,
                            start_location=recorded_start,
                            destination=recorded_destination,
                            business_purpose=business_purpose,
                            notes=notes,
                            tag_ids=tag_ids,
                            new_tag_name=new_tag_name,
                        )
                    )
                    if round_trip
                    else lambda: context.storage.create_mileage_trip(
                        trip_date=trip_date,
                        miles=miles,
                        vehicle=vehicle,
                        start_location=recorded_start,
                        destination=recorded_destination,
                        business_purpose=business_purpose,
                        notes=notes,
                        tag_ids=tag_ids,
                        new_tag_name=new_tag_name,
                    ),
                    (
                        "Round trip saved as two mileage entries."
                        if round_trip
                        else "Mileage trip saved."
                    ),
                    on_success=lambda: context.schedule_widget_reset(
                        "reset_add_mileage_form"
                    ),
                    report_error=save_error.error,
                )
