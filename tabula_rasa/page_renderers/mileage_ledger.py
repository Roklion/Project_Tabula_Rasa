from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd
import streamlit as st

from tabula_rasa.page_renderers.tag_selector import (
    inline_tag_name_error,
    schedule_tag_selector_reset,
    tag_selector_error,
)
from tabula_rasa.presentation import render_global_footer
from tabula_rasa.storage import StorageError, normalize_tag_name

from .mileage_form_shared import (
    mileage_payload_from_draft,
    render_mileage_fields,
    validate_mileage_draft,
)
from .mileage_service import mileage_action, mileage_service

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
    trip: Mapping[str, object], tag_by_id: Mapping[str, Mapping[str, object]]
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
                names_to_ids.get(normalize_tag_name(value), str(value).strip())
                for value in raw_tags
                if str(value).strip()
            )
        )
        if isinstance(raw_tags, (list, tuple, set))
        else []
    )


def _tag_names_for_trip(
    trip: Mapping[str, object], tag_by_id: Mapping[str, Mapping[str, object]]
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
    """Compatibility facade for the shared Tag selector."""
    from tabula_rasa.page_renderers.tag_selector import render_tag_selector

    if not isinstance(tags, (list, tuple)):
        return [], ""
    return render_tag_selector(
        tags,
        label=label,
        key=key,
        selected_ids=selected_ids,
        preserve_inactive_ids=selected_ids,
    )


def mileage_frame(trips: list[dict], tags: object = None) -> pd.DataFrame:
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


def render_mileage_ledger(
    context: MileageContext,
    tags: object,
    tag_by_id: dict[str, Mapping[str, object]],
    page_footer,
) -> None:
    """Render the mileage table and keep edit/delete persistence in this controller."""
    st.subheader("Mileage log")
    c1, c2 = st.columns(2, gap="small")
    start = c1.date_input("From", date(date.today().year, 1, 1), key="mileage_start")
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
        trips = [trip.as_record() for trip in mileage_action(
            lambda: mileage_service(context).list_trips(start=start, end=end)
        )]
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
    mileage_table_key = f"mileage_log_{context.profile_key}_{st.session_state.get('mileage_log_generation', 0)}"

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
        column_config={"Miles": st.column_config.NumberColumn(format="%.1f")},
    )
    if trip_frame.empty:
        st.info("No mileage trips in this period.")
        return
    selected_rows = mileage_event.selection.rows
    if st.session_state.get("edit_mileage_trip_id") not in trip_ids:
        st.session_state["edit_mileage_trip_id"] = trip_ids[0]

    def mileage_trip_label(trip_id: str) -> str:
        row = trip_frame.loc[trip_frame["ID"] == trip_id].iloc[0]
        return f"{row['Date']} - {row['Miles']:,.1f} mi - {row['Destination']} - {trip_id[:8]}"

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
        selected_ids = tuple(_trip_tag_ids(selected, tag_by_id))
        draft = render_mileage_fields(
            context,
            tags if isinstance(tags, (list, tuple)) else [],
            mode="edit",
            defaults={**selected, "tag_ids": selected_ids},
            key_scope=edit_widget_scope,
            record_id=edit_id,
        )
        edit_error = st.empty()
        st.warning("Deleting this mileage trip is permanent and cannot be undone.")
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
        if save_requested:
            if draft_error := validate_mileage_draft(draft):
                edit_error.error(draft_error)
            elif tag_error := tag_selector_error(
                f"edit_mileage_trip_tag_ids_{edit_widget_scope}"
            ):
                edit_error.error(tag_error)
            elif tag_error := inline_tag_name_error(draft["new_tag_name"]):
                edit_error.error(tag_error)
            else:
                trip_data = mileage_payload_from_draft(draft)
                payload = {"id": edit_id, **trip_data}
                context.confirmed_write(
                    "edit_mileage_trip",
                    payload,
                    lambda: mileage_action(lambda: mileage_service(context).edit_trip(
                        edit_id,
                        **trip_data,
                    )),
                    "Mileage trip updated.",
                    on_success=lambda: schedule_tag_selector_reset(
                        f"edit_mileage_trip_tag_ids_{edit_widget_scope}"
                    ),
                    report_error=edit_error.error,
                )
        if delete_requested:
            if not confirm_delete:
                edit_error.error("Confirm that you understand deletion is permanent.")
            else:
                context.confirmed_write(
                    "delete_mileage_trip",
                    {"id": edit_id},
                    lambda: mileage_action(lambda: mileage_service(context).delete_trip(edit_id)),
                    "Mileage trip deleted.",
                    report_error=edit_error.error,
                )
