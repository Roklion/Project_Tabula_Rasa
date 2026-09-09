from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from tabula_rasa.address_autocomplete import address_autocomplete, render_google_maps_attribution
from tabula_rasa.page_renderers.tag_selector import inline_tag_name_error, render_tag_selector, schedule_tag_selector_reset, tag_selector_error
from tabula_rasa.presentation import render_global_footer
from tabula_rasa.storage import StorageError, normalize_tag_name

from .mileage_locations import (
    _acknowledge_recorded_location_text,
    _edit_address_initial_value,
    _ledger_location_text,
    _recorded_address_changed,
)
from .mileage_routing import (
    _address_text_changed,
    _apply_pending_route_mileage,
    _calculate_routes,
    _clear_unchanged_calculated_mileage,
    _discard_modified_calculated_mileage_markers,
    _edit_route_warning_visible,
    _needs_google_maps_attribution,
    _route_key,
    _route_ready,
    _safe_route_error,
    _same_selected_place,
    _selection_fingerprint,
    _set_widget_default,
)

if TYPE_CHECKING:
    from .mileage import MileageContext

def _tag_records_by_id(tags: object) -> dict[str, Mapping[str, object]]:
    if isinstance(tags, Mapping):
        values = tags.values()
    elif isinstance(tags, (list, tuple)):
        values = tags
    else:
        values = ()
    return {
        str(item.get("id") or "").strip(): item
        for item in values
        if isinstance(item, Mapping) and str(item.get("id") or "").strip()
    }


def _tag_name(tag_id: object, tag_by_id: Mapping[str, Mapping[str, object]]) -> str:
    normalized = str(tag_id or "").strip()
    item = tag_by_id.get(normalized)
    return str(item.get("name") or normalized) if item else normalized


def _trip_tag_ids(
    trip: Mapping[str, object],
    tag_by_id: Mapping[str, Mapping[str, object]],
) -> list[str]:
    raw_ids = trip.get("tag_ids", ())
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    ids = (
        [str(value).strip() for value in raw_ids if str(value).strip()]
        if isinstance(raw_ids, (list, tuple, set))
        else []
    )
    if ids:
        return list(dict.fromkeys(ids))
    raw_tags = trip.get("tags", ())
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    names_to_ids = {
        normalize_tag_name(item.get("name") or ""): tag_id
        for tag_id, item in tag_by_id.items()
    }
    return (
        list(
            dict.fromkeys(
                names_to_ids.get(
                    normalize_tag_name(value), str(value).strip()
                )
                for value in raw_tags
                if str(value).strip()
            )
        )
        if isinstance(raw_tags, (list, tuple, set))
        else []
    )


def _tag_names_for_trip(
    trip: Mapping[str, object],
    tag_by_id: Mapping[str, Mapping[str, object]],
) -> str:
    raw_tags = trip.get("tags", ())
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    if isinstance(raw_tags, (list, tuple, set)) and raw_tags:
        names = [
            str(item.get("name") or "").strip()
            if isinstance(item, Mapping)
            else str(item).strip()
            for item in raw_tags
        ]
        names = [name for name in names if name]
        if names:
            return ", ".join(dict.fromkeys(names))
    return ", ".join(
        _tag_name(tag_id, tag_by_id)
        for tag_id in _trip_tag_ids(trip, tag_by_id)
        if _tag_name(tag_id, tag_by_id)
    )


def _render_tag_selector(
    tags: object,
    *,
    key: str,
    selected_ids: list[str] | tuple[str, ...] = (),
    label: str = "Tags",
) -> tuple[list[str], str | None]:
    """Render the shared optional multi-Tag selector for mileage forms."""
    if not isinstance(tags, (list, tuple)):
        return [], ""
    return render_tag_selector(
        tags,
        label=label,
        key=key,
        selected_ids=selected_ids,
        preserve_inactive_ids=selected_ids,
    )


def mileage_frame(
    trips: list[dict],
    tags: object = None,
) -> pd.DataFrame:
    """Return the stable, user-facing mileage table with resolved Tags."""
    tag_by_id = _tag_records_by_id(tags)
    return pd.DataFrame(
        [
            {
                "ID": trip["id"],
                "Date": trip["trip_date"],
                "Miles": float(trip["miles"]),
                "From": trip.get("start_location", ""),
                "Destination": trip.get("destination", ""),
                "Business purpose": trip.get("business_purpose", ""),
                "Vehicle": trip.get("vehicle", ""),
                "Tags": _tag_names_for_trip(trip, tag_by_id),
                "Notes": trip.get("notes", ""),
            }
            for trip in trips
        ],
        columns=[
            "ID",
            "Date",
            "Miles",
            "From",
            "Destination",
            "Business purpose",
            "Vehicle",
            "Tags",
            "Notes",
        ],
    )


def render_mileage_ledger(context: MileageContext, tags: object, tag_by_id: dict[str, Mapping[str, object]], page_footer) -> None:
    st.subheader("Mileage log")
    c1, c2 = st.columns(2, gap="small")
    start = c1.date_input(
        "From", date(date.today().year, 1, 1), key="mileage_start"
    )
    end = c2.date_input("To", date.today(), key="mileage_end")
    selected_tag_names = st.multiselect(
        "Tags",
        [
            tag_id
            for tag_id, item in tag_by_id.items()
            if str(tag_id).strip() and str(item.get("name") or "").strip()
        ],
        format_func=lambda value: _tag_name(value, tag_by_id),
        key=f"mileage_filter_tags_{context.profile_key}",
        placeholder="All tags",
        help="Show mileage rows with any selected Tag.",
    )
    selected_tag_ids = set(selected_tag_names)
    try:
        trips = context.storage.list_mileage_trips(start=start, end=end)
        if selected_tag_ids:
            trips = [
                trip
                for trip in trips
                if selected_tag_ids.intersection(_trip_tag_ids(trip, tag_by_id))
            ]
    except StorageError as error:
        context.report_storage_error(error)
        with page_footer.container():
            render_global_footer()
        st.stop()

    trip_frame = mileage_frame(trips, tags)
    metric_trips, metric_miles = st.columns(2, gap="small")
    metric_trips.metric("Trips", len(trips))
    metric_miles.metric(
        "Business miles",
        f"{trip_frame['Miles'].sum():,.1f}" if not trip_frame.empty else "0.0",
    )
    st.download_button(
        "Download filtered mileage CSV",
        trip_frame.to_csv(index=False).encode("utf-8"),
        f"tabula-rasa-mileage-{start}-to-{end}.csv",
        "text/csv",
    )

    trip_ids = trip_frame["ID"].tolist()

    mileage_table_key = (
        f"mileage_log_{context.profile_key}_"
        f"{st.session_state.get('mileage_log_generation', 0)}"
    )

    def select_mileage_trip() -> None:
        selected_rows = st.session_state[mileage_table_key].selection.rows
        if selected_rows:
            st.session_state["edit_mileage_trip_id"] = trip_ids[selected_rows[0]]

    mileage_event = st.dataframe(
        trip_frame,
        hide_index=True,
        width="stretch",
        key=mileage_table_key,
        on_select=select_mileage_trip,
        selection_mode="single-row",
        column_config={
            "Miles": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    if trip_frame.empty:
        st.info("No mileage trips in this period.")
    else:
        selected_rows = mileage_event.selection.rows
        if st.session_state.get("edit_mileage_trip_id") not in trip_ids:
            st.session_state["edit_mileage_trip_id"] = trip_ids[0]

        def mileage_trip_label(trip_id: str) -> str:
            row = trip_frame.loc[trip_frame["ID"] == trip_id].iloc[0]
            return (
                f"{row['Date']} - {row['Miles']:,.1f} mi - "
                f"{row['Destination']} - {trip_id[:8]}"
            )

        st.caption("Select a mileage row (or double-click it) to edit it.")
        with st.expander("Edit mileage trip", expanded=bool(selected_rows)):
            edit_id = st.selectbox(
                "Mileage trip to edit",
                trip_ids,
                format_func=mileage_trip_label,
                key="edit_mileage_trip_id",
            )
            selected = next(trip for trip in trips if trip["id"] == edit_id)
            edit_widget_scope = f"{context.profile_key}_{edit_id}"
            edit_start = address_autocomplete(
                "Edit starting location",
                key=f"edit_mileage_trip_start_{edit_widget_scope}",
                api_key=context.maps_api_key,
                value=_edit_address_initial_value(
                    selected.get("start_location", ""),
                    context.maps_api_key,
                ),
                region_code=context.autocomplete_region_code,
            )
            edit_destination = address_autocomplete(
                "Edit destination",
                key=f"edit_mileage_trip_destination_{edit_widget_scope}",
                api_key=context.maps_api_key,
                value=_edit_address_initial_value(
                    selected.get("destination", ""),
                    context.maps_api_key,
                ),
                region_code=context.autocomplete_region_code,
            )
            edit_route_key = _route_key(context, f"edit_{edit_id}")
            edit_fingerprint = _selection_fingerprint(edit_start, edit_destination)
            edit_route_state = st.session_state.get(edit_route_key)
            edit_route_changed = False
            _discard_modified_calculated_mileage_markers(
                miles_key=f"edit_mileage_trip_miles_{edit_widget_scope}",
            )
            if (
                edit_route_state
                and edit_route_state.get("fingerprint") != edit_fingerprint
            ):
                _clear_unchanged_calculated_mileage(
                    edit_route_state,
                    miles_key=f"edit_mileage_trip_miles_{edit_widget_scope}",
                )
                st.session_state.pop(edit_route_key, None)
                edit_route_state = None
                edit_route_changed = True
            edit_pending_mileage_key = f"{edit_route_key}__pending_miles"
            _apply_pending_route_mileage(
                st.session_state.pop(edit_pending_mileage_key, None),
                fingerprint=edit_fingerprint,
                round_trip=False,
                miles_key=f"edit_mileage_trip_miles_{edit_widget_scope}",
            )
            edited_start = _ledger_location_text(
                edit_start,
                label="Starting location",
                key=f"edit_mileage_trip_recorded_start_{edit_widget_scope}",
                existing_value=selected.get("start_location", ""),
                always_render=bool(context.maps_api_key),
            )
            edited_destination = _ledger_location_text(
                edit_destination,
                label="Destination",
                key=f"edit_mileage_trip_recorded_destination_{edit_widget_scope}",
                existing_value=selected.get("destination", ""),
                always_render=bool(context.maps_api_key),
            )
            edit_address_changed = _address_text_changed(
                edit_start,
                edit_destination,
                selected.get("start_location", ""),
                selected.get("destination", ""),
            )
            edit_recorded_address_changed = _recorded_address_changed(
                edited_start,
                selected.get("start_location", ""),
                edit_start,
                manually_edited=st.session_state.get(
                    f"edit_mileage_trip_recorded_start_{edit_widget_scope}"
                    "__manually_edited",
                    False,
                ),
            ) or _recorded_address_changed(
                edited_destination,
                selected.get("destination", ""),
                edit_destination,
                manually_edited=st.session_state.get(
                    f"edit_mileage_trip_recorded_destination_{edit_widget_scope}"
                    "__manually_edited",
                    False,
                ),
            )
            calculate_edit_requested = st.button(
                "Recalculate mileage" if edit_route_state else "Calculate mileage",
                disabled=not _route_ready(
                    edit_start,
                    edit_destination,
                    context.route_mileage,
                ),
                key=f"edit_mileage_trip_calculate_{edit_widget_scope}",
            )
            edit_error = st.empty()
            if _needs_google_maps_attribution(
                edit_start,
                edit_destination,
                edit_route_state,
                edit_fingerprint,
            ):
                render_google_maps_attribution()
            if context.maps_api_key and _edit_route_warning_visible(
                edit_address_changed,
                edit_route_changed,
                edit_route_state,
                edit_fingerprint,
                recorded_address_changed=edit_recorded_address_changed,
            ):
                st.warning(
                    "The address changed, so the existing mileage may not "
                    "match the current route. Calculate mileage again to "
                    "refresh it, or review and edit the mileage manually "
                    "before saving."
                )
            # Address autocomplete can rerun this page before save; a
            # container keeps the rest of the draft synchronized in state.
            with st.container():
                st.caption("Update this saved mileage row.")
                c1, c2 = st.columns(2, gap="small")
                edited_date = c1.date_input(
                    "Edit trip date",
                    date.fromisoformat(selected["trip_date"]),
                    key=f"edit_mileage_trip_date_{edit_widget_scope}",
                )
                edit_miles_key = f"edit_mileage_trip_miles_{edit_widget_scope}"
                _set_widget_default(edit_miles_key, float(selected["miles"]))
                edited_miles = c2.number_input(
                    "Edit business miles",
                    min_value=0.1,
                    step=0.1,
                    format="%.1f",
                    key=edit_miles_key,
                )
                selected_edit_tag_ids = _trip_tag_ids(selected, tag_by_id)
                edited_tag_ids, edited_new_tag_name = _render_tag_selector(
                    tags,
                    key=f"edit_mileage_trip_tag_ids_{edit_widget_scope}",
                    selected_ids=selected_edit_tag_ids,
                    label="Edit Tags",
                )
                edited_vehicle = st.text_input(
                    "Edit vehicle",
                    value=selected.get("vehicle", ""),
                    key=f"edit_mileage_trip_vehicle_{edit_widget_scope}",
                )
                edited_purpose = st.text_input(
                    "Edit business purpose",
                    value=selected.get("business_purpose", ""),
                    key=f"edit_mileage_trip_purpose_{edit_widget_scope}",
                )
                edited_notes = st.text_area(
                    "Edit notes",
                    value=selected.get("notes", ""),
                    key=f"edit_mileage_trip_notes_{edit_widget_scope}",
                )
                st.warning(
                    "Deleting this mileage trip is permanent and cannot be undone."
                )
                confirm_delete = st.checkbox(
                    "I understand this mileage trip will be permanently deleted",
                    key=f"edit_mileage_trip_confirm_delete_{edit_widget_scope}",
                )
                save_column, delete_column = st.columns(2, gap="small")
                save_requested = save_column.button(
                    "Save mileage changes",
                    type="primary",
                    width="stretch",
                    key=f"edit_mileage_trip_save_{edit_widget_scope}",
                )
                with delete_column:
                    with st.container(key="destructive_mileage_delete"):
                        delete_requested = st.button(
                            "Permanently delete mileage trip",
                            icon=":material/delete_forever:",
                            width="stretch",
                            key=f"edit_mileage_trip_delete_{edit_widget_scope}",
                        )
                if calculate_edit_requested and context.route_mileage is not None:
                    with st.spinner("Calculating mileage…"):
                        try:
                            outbound, _ = _calculate_routes(
                                edit_start,
                                edit_destination,
                                context.route_mileage,
                                round_trip=False,
                            )
                            st.session_state[edit_route_key] = {
                                "fingerprint": edit_fingerprint,
                                "outbound": outbound,
                            }
                            st.session_state[edit_pending_mileage_key] = {
                                "fingerprint": edit_fingerprint,
                                "outbound": outbound,
                            }
                            _acknowledge_recorded_location_text(
                                f"edit_mileage_trip_recorded_start_{edit_widget_scope}",
                                edited_start,
                            )
                            _acknowledge_recorded_location_text(
                                f"edit_mileage_trip_recorded_destination_{edit_widget_scope}",
                                edited_destination,
                            )
                            st.rerun()
                        except Exception as error:
                            edit_error.error(_safe_route_error(error))
                if save_requested:
                    if _same_selected_place(edit_start, edit_destination):
                        edit_error.error(
                            "Starting location and destination must be different."
                        )
                    elif (
                        tag_error := tag_selector_error(
                            f"edit_mileage_trip_tag_ids_{edit_widget_scope}"
                        )
                    ):
                        edit_error.error(tag_error)
                    elif (tag_error := inline_tag_name_error(edited_new_tag_name)):
                        edit_error.error(tag_error)
                    else:
                        payload = {
                            "id": edit_id,
                            "trip_date": edited_date,
                            "miles": edited_miles,
                            "vehicle": edited_vehicle,
                            "start_location": edited_start,
                            "destination": edited_destination,
                            "business_purpose": edited_purpose,
                            "notes": edited_notes,
                            "tag_ids": edited_tag_ids,
                            "new_tag_name": edited_new_tag_name,
                        }
                        context.confirmed_write(
                            "edit_mileage_trip",
                            payload,
                            lambda: context.storage.edit_mileage_trip(
                                edit_id,
                                trip_date=edited_date,
                                miles=edited_miles,
                                vehicle=edited_vehicle,
                                start_location=edited_start,
                                destination=edited_destination,
                                business_purpose=edited_purpose,
                                notes=edited_notes,
                                tag_ids=edited_tag_ids,
                                new_tag_name=edited_new_tag_name,
                            ),
                            "Mileage trip updated.",
                            on_success=lambda: schedule_tag_selector_reset(
                                f"edit_mileage_trip_tag_ids_{edit_widget_scope}"
                            ),
                            report_error=edit_error.error,
                        )
                if delete_requested:
                    if not confirm_delete:
                        edit_error.error(
                            "Confirm that you understand deletion is permanent."
                        )
                    else:
                        context.confirmed_write(
                            "delete_mileage_trip",
                            {"id": edit_id},
                            lambda: context.storage.delete_mileage_trip(edit_id),
                            "Mileage trip deleted.",
                            report_error=edit_error.error,
                        )
