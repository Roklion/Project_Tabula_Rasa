from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tabula_rasa.address_autocomplete import AddressSelection
from tabula_rasa.page_renderers.mileage import (
    PartialRouteError,
    _calculate_routes,
    _ledger_location_text,
    _needs_google_maps_attribution,
    _address_text_changed,
    _apply_pending_route_mileage,
    _discard_modified_calculated_mileage_markers,
    _clear_unchanged_calculated_mileage,
    _edit_address_initial_value,
    _edit_route_warning_visible,
    _recorded_address_changed,
    _route_state_is_current,
    _route_disabled_reason,
    _autocomplete_available,
    _same_selected_place,
    _save_round_trip,
)


def test_round_trip_calculation_uses_reversed_place_ids() -> None:
    calls: list[tuple[str, str]] = []

    def route(origin: str, destination: str) -> float:
        calls.append((origin, destination))
        return 12.4 if len(calls) == 1 else 13.1

    outbound, returned = _calculate_routes(
        AddressSelection("Office", "place-office", 2),
        AddressSelection("Client", "place-client", 3),
        route,
        round_trip=True,
    )

    assert (outbound, returned) == (12.4, 13.1)
    assert calls == [
        ("place-office", "place-client"),
        ("place-client", "place-office"),
    ]


def test_calculation_rejects_missing_or_identical_place_ids() -> None:
    def route(*_args: str) -> float:
        pytest.fail("route should not be called")
        return 0.0

    with pytest.raises(ValueError, match="both addresses"):
        _calculate_routes(
            AddressSelection("Office"),
            AddressSelection("Client"),
            route,
            round_trip=False,
        )
    with pytest.raises(ValueError, match="different"):
        _calculate_routes(
            AddressSelection("Office", "same"),
            AddressSelection("Client", "same"),
            route,
            round_trip=False,
        )


def test_save_guard_rejects_same_place_id_but_allows_manual_loop() -> None:
    assert _same_selected_place(
        AddressSelection("Office", "same"),
        AddressSelection("Office rear entrance", "same"),
    )
    assert not _same_selected_place(
        AddressSelection("Office"),
        AddressSelection("Office"),
    )


def test_edit_address_change_is_detected_before_recalculation() -> None:
    assert not _address_text_changed(
        AddressSelection(),
        AddressSelection(),
        "Office",
        "Client",
    )
    assert _address_text_changed(
        AddressSelection("Updated office", version=1),
        AddressSelection("Client"),
        "Office",
        "Client",
    )
    assert not _address_text_changed(
        AddressSelection("Office"),
        AddressSelection("Client"),
        "Office",
        "Client",
    )


def test_google_maps_attribution_uses_current_session_provenance() -> None:
    fingerprint = ("Office", "Client", 2, 3, False)
    selected_start = AddressSelection("Office", "place-office", 2)
    manual_destination = AddressSelection("Client", version=3)

    # A single current Google selection is enough to attribute the address
    # autocomplete content, even before a route is calculated.
    assert _needs_google_maps_attribution(
        selected_start, manual_destination, None, fingerprint
    )
    # A valid route state is also attributable even if the address widgets
    # have since been reconstructed without Place IDs.
    assert _needs_google_maps_attribution(
        AddressSelection("Office", version=2),
        AddressSelection("Client", version=3),
        {"fingerprint": fingerprint, "outbound": 12.4},
        fingerprint,
    )
    # Manual fallback and stale route state must not claim Google-derived data.
    stale = {"fingerprint": ("Old office", "Client", 1, 3, False)}
    assert not _needs_google_maps_attribution(
        AddressSelection("Office", version=2),
        manual_destination,
        stale,
        fingerprint,
    )
    assert not _route_state_is_current(stale, fingerprint)


def test_calculated_route_mileage_populates_editable_widgets(monkeypatch) -> None:
    import streamlit as st

    session_state: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", session_state)
    _apply_pending_route_mileage(
        {"outbound": 12.4, "return": 13.1, "fingerprint": ("current",)},
        fingerprint=("current",),
        round_trip=True,
        miles_key="add_mileage_miles",
        return_miles_key="add_mileage_return_miles",
    )

    assert session_state["add_mileage_miles"] == 12.4
    assert session_state["add_mileage_return_miles"] == 13.1
    assert session_state["add_mileage_miles__calculated"] == 12.4
    assert session_state["add_mileage_return_miles__calculated"] == 13.1


def test_stale_calculated_route_mileage_does_not_overwrite_edits(monkeypatch) -> None:
    import streamlit as st

    session_state: dict[str, object] = {
        "add_mileage_miles": 9.5,
        "add_mileage_return_miles": 10.0,
    }
    monkeypatch.setattr(st, "session_state", session_state)
    _apply_pending_route_mileage(
        {"outbound": 12.4, "return": 13.1, "fingerprint": ("old",)},
        fingerprint=("current",),
        round_trip=True,
        miles_key="add_mileage_miles",
        return_miles_key="add_mileage_return_miles",
    )

    assert session_state["add_mileage_miles"] == 9.5
    assert session_state["add_mileage_return_miles"] == 10.0


def test_partial_route_retry_preserves_manual_outbound_and_applies_return(
    monkeypatch,
) -> None:
    import streamlit as st

    session_state: dict[str, object] = {"add_mileage_miles": 9.5}
    monkeypatch.setattr(st, "session_state", session_state)
    _apply_pending_route_mileage(
        {
            "outbound": None,
            "return": 13.1,
            "fingerprint": ("current",),
        },
        fingerprint=("current",),
        round_trip=True,
        miles_key="add_mileage_miles",
        return_miles_key="add_mileage_return_miles",
    )

    assert session_state["add_mileage_miles"] == 9.5
    assert session_state["add_mileage_return_miles"] == 13.1
    assert session_state["add_mileage_return_miles__calculated"] == 13.1


def test_edit_route_warning_clears_after_successful_recalculation() -> None:
    fingerprint = ("Updated office", "Client", 2, 3, False)

    assert _edit_route_warning_visible(
        True,
        False,
        {"fingerprint": fingerprint, "outbound": 12.4},
        fingerprint,
    ) is False
    assert _edit_route_warning_visible(
        False,
        False,
        {"fingerprint": fingerprint, "outbound": 12.4},
        fingerprint,
        recorded_address_changed=True,
    ) is True
    assert _edit_route_warning_visible(
        True,
        False,
        None,
        fingerprint,
    ) is True
    assert _edit_route_warning_visible(
        False,
        True,
        {"fingerprint": fingerprint, "outbound": 12.4},
        fingerprint,
    ) is True


def test_maps_prefill_is_not_an_independent_recorded_address_change() -> None:
    selected = AddressSelection(
        display_text="Updated office",
        place_id="place-office",
        version=2,
    )

    assert not _recorded_address_changed(
        "Updated office", "Saved office", selected
    )
    assert _recorded_address_changed("Custom ledger text", "Saved office", selected)


def test_edit_lookup_uses_saved_address_only_without_maps() -> None:
    assert _edit_address_initial_value("Saved office", None) == "Saved office"
    assert _edit_address_initial_value("Saved office", "browser-key") == ""


def test_stale_calculated_route_mileage_clears_untouched_values(monkeypatch) -> None:
    import streamlit as st

    session_state: dict[str, object] = {
        "add_mileage_miles": 12.4,
        "add_mileage_return_miles": 9.5,
    }
    monkeypatch.setattr(st, "session_state", session_state)
    _clear_unchanged_calculated_mileage(
        {"outbound": 12.4, "return": 13.1},
        miles_key="add_mileage_miles",
        return_miles_key="add_mileage_return_miles",
    )

    assert "add_mileage_miles" not in session_state
    assert session_state["add_mileage_return_miles"] == 9.5


def test_modified_calculated_mileage_is_treated_as_manual(monkeypatch) -> None:
    import streamlit as st

    session_state: dict[str, object] = {
        "add_mileage_miles": 14.0,
        "add_mileage_miles__calculated": 12.4,
    }
    monkeypatch.setattr(st, "session_state", session_state)
    _discard_modified_calculated_mileage_markers(
        miles_key="add_mileage_miles",
    )

    assert session_state["add_mileage_miles"] == 14.0
    assert "add_mileage_miles__calculated" not in session_state


def test_google_location_text_prefills_the_ledger_input(monkeypatch) -> None:
    import streamlit as st

    captions: list[str] = []
    inputs: list[tuple[str, str, str]] = []
    monkeypatch.setattr(st, "caption", captions.append)
    monkeypatch.setattr(
        st,
        "text_input",
        lambda label, *, key, help: inputs.append(
            (label, st.session_state[key], key)
        )
        or st.session_state[key],
    )
    monkeypatch.setattr(st, "checkbox", lambda *args, **kwargs: False)

    google_text = _ledger_location_text(
        AddressSelection("Provider display text", "place-123", 4),
        label="Starting location",
        key="ledger-start",
    )
    manual_text = _ledger_location_text(
        AddressSelection("Typed by user", version=5),
        label="Starting location",
        key="ledger-start",
    )

    assert google_text == "Provider display text"
    assert manual_text == "Typed by user"
    assert inputs == [
        ("Starting location (recorded text)", "Provider display text", "ledger-start")
    ]
    assert len(captions) == 1


def test_google_location_text_refreshes_for_a_new_selection_but_preserves_edits(
    monkeypatch,
) -> None:
    import streamlit as st

    inputs: list[str] = []
    monkeypatch.setattr(
        st,
        "text_input",
        lambda label, *, key, help: inputs.append(st.session_state[key])
        or st.session_state[key],
    )
    monkeypatch.setattr(st, "caption", lambda message: None)
    monkeypatch.setattr(st, "checkbox", lambda *args, **kwargs: False)

    _ledger_location_text(
        AddressSelection("First result", "place-1", 1),
        label="Starting location",
        key="ledger-start",
    )
    st.session_state["ledger-start"] = "User-confirmed text"
    _ledger_location_text(
        AddressSelection("First result", "place-1", 1),
        label="Starting location",
        key="ledger-start",
    )
    _ledger_location_text(
        AddressSelection("Second result", "place-2", 2),
        label="Starting location",
        key="ledger-start",
    )

    assert inputs == ["First result", "User-confirmed text", "Second result"]


def test_edit_recorded_location_text_is_visible_without_google_selection(
    monkeypatch,
) -> None:
    import streamlit as st

    captions: list[str] = []
    inputs: list[tuple[str, str]] = []
    monkeypatch.setattr(st, "session_state", {})
    monkeypatch.setattr(st, "caption", captions.append)
    monkeypatch.setattr(
        st,
        "text_input",
        lambda label, *, key, help: inputs.append(
            (label, st.session_state[key])
        )
        or st.session_state[key],
    )

    recorded = _ledger_location_text(
        AddressSelection(),
        label="Starting location",
        key="edit-recorded-start",
        existing_value="Saved office address",
        always_render=True,
    )

    assert recorded == "Saved office address"
    assert inputs == [
        ("Starting location (recorded text)", "Saved office address")
    ]
    assert captions == [
        "Enter the location text to record in the ledger. Google text is used only for route lookup."
    ]


def test_recorded_google_text_is_saved_only_by_the_explicit_save_action() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert 'st.checkbox(\n        f"Confirm {label.lower()} text"' not in source
    assert "_recorded_location_is_confirmed" not in source
    assert "context.confirmed_write(" in source
    assert '"create_mileage_trip"' in source


def test_add_trip_calculate_button_is_before_recorded_location_fields() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert source.index("calculate_requested = st.button(") < source.index(
        'recorded_start = _ledger_location_text(\n'
    )
    assert source.index("calculate_requested = st.button(") < source.index(
        'st.checkbox(\n            "Round trip"'
    )
    assert source.count("always_render=bool(context.maps_api_key)") >= 4


def test_edit_calculate_button_is_before_delete_controls() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()
    edit_address_section = source[
        source.index('edit_start = address_autocomplete(') : source.index(
            'edit_route_key = _route_key',
            source.index('edit_start = address_autocomplete('),
        )
    ]

    assert "value=selected.get" not in edit_address_section
    assert source.index("calculate_edit_requested = st.button(") < source.index(
        'st.caption("Update this saved mileage row.")'
    )
    assert source.index("calculate_edit_requested = st.button(") < source.index(
        'st.warning(\n                        "Deleting this mileage trip is permanent'
    )
    assert source.index("calculate_edit_requested = st.button(") < source.index(
        '"Permanently delete mileage trip"'
    )


def test_round_trip_preserves_outbound_when_return_lookup_fails() -> None:
    calls: list[tuple[str, str]] = []

    def route(origin: str, destination: str) -> float:
        calls.append((origin, destination))
        if len(calls) == 2:
            raise TimeoutError("provider detail must not reach the user")
        return 12.44

    with pytest.raises(PartialRouteError) as raised:
        _calculate_routes(
            AddressSelection("Office", "place-office", 2),
            AddressSelection("Client", "place-client", 3),
            route,
            round_trip=True,
        )

    assert raised.value.outbound == 12.4
    assert "provider detail" not in str(raised.value)
    assert calls == [
        ("place-office", "place-client"),
        ("place-client", "place-office"),
    ]


def test_round_trip_retry_calls_only_failed_return_route() -> None:
    calls: list[tuple[str, str]] = []

    def initial_route(origin: str, destination: str) -> float:
        calls.append((origin, destination))
        if len(calls) == 2:
            raise TimeoutError("return failed")
        return 12.4

    with pytest.raises(PartialRouteError) as raised:
        _calculate_routes(
            AddressSelection("Office", "place-office", 2),
            AddressSelection("Client", "place-client", 3),
            initial_route,
            round_trip=True,
        )

    retry_calls: list[tuple[str, str]] = []

    def retry_route(origin: str, destination: str) -> float:
        retry_calls.append((origin, destination))
        return 13.1

    outbound, returned = _calculate_routes(
        AddressSelection("Office", "place-office", 2),
        AddressSelection("Client", "place-client", 3),
        retry_route,
        round_trip=True,
        known_outbound=raised.value.outbound,
    )

    assert (outbound, returned) == (12.4, 13.1)
    assert retry_calls == [("place-client", "place-office")]


def test_round_trip_save_passes_independent_return_miles() -> None:
    class Storage:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def create_mileage_round_trip(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    storage = Storage()
    _save_round_trip(
        storage,  # type: ignore[arg-type]
        trip_date=date(2026, 8, 31),
        miles=12.4,
        return_miles=13.1,
        vehicle="",
        start_location="Office",
        destination="Client",
        business_purpose="Meeting",
        notes="",
    )

    assert storage.kwargs["miles"] == 12.4
    assert storage.kwargs["return_miles"] == 13.1


def test_add_mileage_route_invalidation_preserves_business_miles() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert '            _route_key(context, "add"),' in source
    assert (
        '                st.session_state["add_mileage_miles"] = 0.0'
        not in source
    )
    assert (
        '                st.session_state["add_mileage_return_miles"] = 0.0'
        not in source
    )
    assert '                        st.session_state[miles_key] = 0.1' not in source
    assert "The selected addresses changed, so any mileage left in " in source
    assert "may not match the current route." in source
    assert "mileage manually" in source
    assert "edit_address_changed = _address_text_changed(" in source


def test_mileage_drafts_are_not_buffered_in_forms() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert 'with st.form("add_mileage_trip"' not in source
    assert 'with st.form("edit_mileage_trip")' not in source
    assert "st.form_submit_button" not in source


def test_manual_fallback_explains_why_calculation_is_disabled() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert "Choose a Google suggestion for both endpoints to enable mileage " in source
    assert "calculation. Manual entries can still be saved" in source
    assert "disabled=not route_ready" in source


def test_route_disabled_reason_reports_missing_autocomplete_before_routing() -> None:
    assert "suggestions are unavailable" in _route_disabled_reason(
        AddressSelection("Office"),
        AddressSelection("Client"),
        lambda *_: 1.0,
        autocomplete_available=False,
    )


def test_route_disabled_reason_reports_missing_routing_when_both_are_unavailable() -> None:
    assert "routing is not configured" in _route_disabled_reason(
        AddressSelection("Office"),
        AddressSelection("Client"),
        None,
        autocomplete_available=False,
    )


def test_route_disabled_reason_distinguishes_unconfigured_and_invalid_inputs() -> None:
    start = AddressSelection("Office", "office", 1)
    destination = AddressSelection("Client", "client", 1)
    assert "not configured" in _route_disabled_reason(start, destination, None)
    assert "both endpoints" in _route_disabled_reason(
        AddressSelection("Office"), destination, lambda *_: 1.0
    )
    assert "different" in _route_disabled_reason(
        start, AddressSelection("Office", "office", 2), lambda *_: 1.0
    )


def test_route_disabled_reason_explains_missing_browser_autocomplete() -> None:
    assert "suggestions are unavailable" in _route_disabled_reason(
        AddressSelection("Office"),
        AddressSelection("Client"),
        lambda *_: 1.0,
        autocomplete_available=False,
    )



def test_autocomplete_availability_distinguishes_manual_mode_from_failure(monkeypatch) -> None:
    import streamlit as st

    monkeypatch.setattr(
        st,
        "session_state",
        {"manual": {"manual_mode": True}, "failed": {"failed": True}},
    )
    assert _autocomplete_available("manual")
    assert not _autocomplete_available("failed")
