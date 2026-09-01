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
    _render_google_route_suggestions,
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


def test_google_route_suggestion_is_not_copied_into_business_miles() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert "Google suggested distance: {float(outbound):.1f} mi" in source
    assert 'st.session_state["add_mileage_miles"] = suggestion[0]' not in source
    assert 'st.session_state["add_mileage_return_miles"] = suggestion[1]' not in source
    assert "distanceMeters" not in source
    assert "route_calculated_at" not in source
    assert "distance_source" not in source


def test_route_suggestions_render_as_current_transient_values(monkeypatch) -> None:
    import streamlit as st

    messages: list[str] = []
    monkeypatch.setattr(st, "info", messages.append)

    _render_google_route_suggestions(
        {"outbound": 12.4, "return": 13.1, "fingerprint": ("current",)}
    )

    assert messages == [
        "Google suggested distance: 12.4 mi",
        "Google suggested return distance: 13.1 mi",
    ]


def test_google_location_text_requires_a_separate_ledger_input(monkeypatch) -> None:
    import streamlit as st

    captions: list[str] = []
    inputs: list[tuple[str, str, str]] = []
    monkeypatch.setattr(st, "caption", captions.append)
    monkeypatch.setattr(
        st,
        "text_input",
        lambda label, *, value, key, help: inputs.append((label, value, key))
        or value,
    )

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

    assert google_text == ""
    assert manual_text == "Typed by user"
    assert inputs == [("Starting location (recorded text)", "", "ledger-start")]
    assert len(captions) == 1


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
    assert "The route changed, so the Google suggestion was cleared." in source
    assert "business mileage" in source


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
