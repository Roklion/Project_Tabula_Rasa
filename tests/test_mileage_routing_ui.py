from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from tabula_rasa.address_autocomplete import AddressSelection
from tabula_rasa.page_renderers.mileage import (
    PartialRouteError,
    _calculate_routes,
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


def test_add_mileage_reset_clears_calculated_route_state() -> None:
    source = Path("tabula_rasa/page_renderers/mileage.py").read_text()

    assert '            _route_key(context, "add"),' in source
