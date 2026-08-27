"""Mileage page rendering and its explicit page context."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage, StorageError


@dataclass(frozen=True)
class MileageContext:
    """Dependencies supplied by the application shell for one profile."""

    profile_key: str
    storage: GoogleSheetsStorage
    confirmed_write: Callable[..., None]
    report_storage_error: Callable[[StorageError], None]
    reset_widget_state_if_requested: Callable[..., None]
    schedule_widget_reset: Callable[[str], None]


def mileage_frame(trips: list[dict]) -> pd.DataFrame:
    """Return the stable, user-facing eight-column mileage table."""
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
            "Notes",
        ],
    )


def render_mileage(context: MileageContext) -> None:
    """Render mileage entry, filtering, editing, export, and deletion."""
    render_page_header(
        "Mileage",
        "Keep a dated business-mileage log with the route, purpose, and vehicle.",
    )
    tab_add, tab_log = st.tabs(["Add trip", "View & edit mileage log"])

    with tab_add:
        mileage_form_keys = (
            "add_mileage_trip_date",
            "add_mileage_miles",
            "add_mileage_vehicle",
            "add_mileage_start",
            "add_mileage_destination",
            "add_mileage_round_trip",
            "add_mileage_purpose",
            "add_mileage_notes",
        )
        context.reset_widget_state_if_requested(
            "reset_add_mileage_form",
            keys=mileage_form_keys,
        )

        with st.form("add_mileage_trip", clear_on_submit=False):
            st.subheader("Add trip")
            c1, c2 = st.columns(2, gap="small")
            trip_date = c1.date_input(
                "Trip date",
                date.today(),
                key="add_mileage_trip_date",
            )
            vehicle = c2.text_input(
                "Vehicle (optional)",
                help="For example: 2022 Honda Civic or Company van.",
                key="add_mileage_vehicle",
            )
            c1, c2 = st.columns(2, gap="small")
            miles = c1.number_input(
                "Business miles",
                min_value=0.1,
                step=0.1,
                format="%.1f",
                key="add_mileage_miles",
            )
            round_trip = c2.checkbox(
                "Round trip",
                help=(
                    "Creates an outbound entry and a second entry with the "
                    "starting and ending locations reversed. Each entry uses "
                    "the mileage entered above."
                ),
                key="add_mileage_round_trip",
            )
            c1, c2 = st.columns(2, gap="small")
            start_location = c1.text_input(
                "Starting location",
                key="add_mileage_start",
            )
            destination = c2.text_input(
                "Destination",
                key="add_mileage_destination",
            )
            business_purpose = st.text_input(
                "Business purpose",
                key="add_mileage_purpose",
            )
            notes = st.text_area(
                "Notes (optional)",
                key="add_mileage_notes",
            )
            save_error = st.empty()
            submitted = st.form_submit_button(
                "Save mileage trip", type="primary", width="stretch"
            )
            if submitted:
                payload = {
                    "trip_date": trip_date,
                    "miles": miles,
                    "vehicle": vehicle,
                    "start_location": start_location,
                    "destination": destination,
                    "business_purpose": business_purpose,
                    "notes": notes,
                    "round_trip": round_trip,
                }
                context.confirmed_write(
                    "create_mileage_round_trip"
                    if round_trip
                    else "create_mileage_trip",
                    payload,
                    (
                        lambda: context.storage.create_mileage_round_trip(
                            trip_date=trip_date,
                            miles=miles,
                            vehicle=vehicle,
                            start_location=start_location,
                            destination=destination,
                            business_purpose=business_purpose,
                            notes=notes,
                        )
                    )
                    if round_trip
                    else lambda: context.storage.create_mileage_trip(
                        trip_date=trip_date,
                        miles=miles,
                        vehicle=vehicle,
                        start_location=start_location,
                        destination=destination,
                        business_purpose=business_purpose,
                        notes=notes,
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

    with tab_log:
        st.subheader("Mileage log")
        c1, c2 = st.columns(2, gap="small")
        start = c1.date_input(
            "From", date(date.today().year, 1, 1), key="mileage_start"
        )
        end = c2.date_input("To", date.today(), key="mileage_end")
        try:
            trips = context.storage.list_mileage_trips(start=start, end=end)
        except StorageError as error:
            context.report_storage_error(error)
            st.stop()

        trip_frame = mileage_frame(trips)
        metric_trips, metric_miles = st.columns(2, gap="small")
        metric_trips.metric("Trips", len(trips))
        metric_miles.metric(
            "Business miles",
            f"{trip_frame['Miles'].sum():,.1f}" if not trip_frame.empty else "0.0",
        )
        st.download_button(
            "Download filtered mileage CSV",
            trip_frame.to_csv(index=False).encode("utf-8"),
            f"tabula-rosa-mileage-{start}-to-{end}.csv",
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
                st.session_state["edit_mileage_trip_id"] = trip_ids[
                    selected_rows[0]
                ]

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
                with st.form("edit_mileage_trip"):
                    st.caption("Update this saved mileage row.")
                    c1, c2 = st.columns(2, gap="small")
                    edited_date = c1.date_input(
                        "Edit trip date",
                        date.fromisoformat(selected["trip_date"]),
                        key=f"edit_mileage_trip_date_{edit_widget_scope}",
                    )
                    edited_miles = c2.number_input(
                        "Edit business miles",
                        min_value=0.1,
                        step=0.1,
                        value=float(selected["miles"]),
                        format="%.1f",
                        key=f"edit_mileage_trip_miles_{edit_widget_scope}",
                    )
                    edited_vehicle = st.text_input(
                        "Edit vehicle",
                        value=selected.get("vehicle", ""),
                        key=f"edit_mileage_trip_vehicle_{edit_widget_scope}",
                    )
                    c1, c2 = st.columns(2, gap="small")
                    edited_start = c1.text_input(
                        "Edit starting location",
                        value=selected.get("start_location", ""),
                        key=f"edit_mileage_trip_start_{edit_widget_scope}",
                    )
                    edited_destination = c2.text_input(
                        "Edit destination",
                        value=selected.get("destination", ""),
                        key=f"edit_mileage_trip_destination_{edit_widget_scope}",
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
                    edit_error = st.empty()
                    save_column, delete_column = st.columns(2, gap="small")
                    save_requested = save_column.form_submit_button(
                        "Save mileage changes",
                        type="primary",
                        width="stretch",
                        key=f"edit_mileage_trip_save_{edit_widget_scope}",
                    )
                    delete_requested = delete_column.form_submit_button(
                        "Permanently delete mileage trip",
                        icon=":material/delete_forever:",
                        width="stretch",
                        key=f"edit_mileage_trip_delete_{edit_widget_scope}",
                    )
                    if save_requested:
                        payload = {
                            "id": edit_id,
                            "trip_date": edited_date,
                            "miles": edited_miles,
                            "vehicle": edited_vehicle,
                            "start_location": edited_start,
                            "destination": edited_destination,
                            "business_purpose": edited_purpose,
                            "notes": edited_notes,
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
                            ),
                            "Mileage trip updated.",
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
