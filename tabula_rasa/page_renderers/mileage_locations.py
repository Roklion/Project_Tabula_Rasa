from __future__ import annotations

import streamlit as st

from tabula_rasa.address_autocomplete import AddressSelection

def _ledger_location_text(
    selection: AddressSelection,
    *,
    label: str,
    key: str,
    existing_value: str = "",
    always_render: bool = False,
) -> str:
    """Return manual ledger text without persisting Google display content."""
    if not selection.place_id and not always_render:
        return selection.display_text
    if always_render:
        st.caption(
            "Enter the location text to record in the ledger. Google text is "
            "used only for route lookup."
        )
    elif selection.place_id:
        st.caption(
            "Google text is used only for route lookup. Enter the location text "
            "you want to record in the ledger."
        )
    version_key = f"{key}__autocomplete_version"
    autofill_key = f"{key}__autofill_value"
    manually_edited_key = f"{key}__manually_edited"
    if selection.place_id and st.session_state.get(version_key) != selection.version:
        st.session_state[key] = selection.display_text
        st.session_state[autofill_key] = selection.display_text
        st.session_state[manually_edited_key] = False
        st.session_state[version_key] = selection.version
    elif key not in st.session_state:
        initial_text = existing_value or selection.display_text
        st.session_state[key] = initial_text
        st.session_state[autofill_key] = initial_text
        st.session_state[manually_edited_key] = False
    text = st.text_input(
        f"{label} (recorded text)",
        key=key,
        help="This text is saved to the Mileage ledger when you save the trip.",
    )
    if (
        autofill_key in st.session_state
        and text.strip() != str(st.session_state[autofill_key]).strip()
    ):
        st.session_state.pop(autofill_key, None)
        st.session_state[manually_edited_key] = True
    return text


def _acknowledge_recorded_location_text(key: str, text: str) -> None:
    """Use the current recorded text as the next edit-tracking baseline."""
    st.session_state[f"{key}__autofill_value"] = text
    st.session_state[f"{key}__manually_edited"] = False


def _edit_address_initial_value(
    existing_value: object, maps_api_key: str | None
) -> str:
    """Keep edit lookups empty only when a separate Maps control exists."""
    return "" if maps_api_key else str(existing_value or "")


def _recorded_address_changed(
    edited_value: str,
    saved_value: object,
    selection: AddressSelection,
    *,
    manually_edited: bool = False,
) -> bool:
    """Ignore recorded text that was just populated from a Maps selection."""
    return manually_edited or (
        edited_value.strip() != str(saved_value or "").strip()
        and not (
            selection.place_id
            and edited_value.strip() == selection.display_text.strip()
        )
    )
