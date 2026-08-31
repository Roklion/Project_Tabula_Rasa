"""Unit tests for the isolated Google Routes client."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
import requests

from tabula_rasa.maps_routing import (
    GoogleRouteResult,
    GoogleRoutesAuthenticationError,
    GoogleRoutesBillingError,
    GoogleRoutesClient,
    GoogleRoutesConfig,
    GoogleRoutesConfigurationError,
    GoogleRoutesInvalidKeyError,
    GoogleRoutesNoRouteError,
    GoogleRoutesQuotaError,
    GoogleRoutesTemporaryError,
    GoogleRoutesTimeoutError,
    load_routes_config,
)


def response(status_code: int, body: object) -> Mock:
    result = Mock(status_code=status_code)
    result.json.return_value = body
    return result


def client_with(response_value: Mock) -> tuple[GoogleRoutesClient, Mock]:
    session = Mock()
    session.post.return_value = response_value
    return GoogleRoutesClient(
        GoogleRoutesConfig(api_key="test-key", timeout_seconds=7.5),
        session=session,
    ), session


def test_load_routes_config_uses_app_wide_nested_secret() -> None:
    config = load_routes_config(
        {
            "google_maps": {
                "routes_api_key": " secret ",
                "routes_timeout_seconds": 4,
                "browser_api_key": "browser-key",
            }
        }
    )

    assert config == GoogleRoutesConfig(api_key="secret", timeout_seconds=4.0)
    assert "secret" not in repr(config)


@pytest.mark.parametrize(
    "secrets",
    [
        {},
        {"google_maps": "not a mapping"},
        {"google_maps": {"routes_api_key": ""}},
        {"google_maps": {"routes_api_key": "key", "routes_timeout_seconds": 0}},
        {"google_maps": {"routes_api_key": "key", "routes_timeout_seconds": 61}},
    ],
)
def test_load_routes_config_rejects_incomplete_or_unsafe_settings(
    secrets: dict[str, object],
) -> None:
    with pytest.raises(GoogleRoutesConfigurationError):
        load_routes_config(secrets)


def test_direct_config_construction_applies_secret_validation() -> None:
    with pytest.raises(GoogleRoutesConfigurationError):
        GoogleRoutesConfig(api_key="")

    config = GoogleRoutesConfig(api_key=" key ", timeout_seconds="4")
    assert config.api_key == "key"
    assert config.timeout_seconds == 4.0


def test_compute_route_sends_place_ids_drive_and_narrow_field_mask() -> None:
    route_client, session = client_with(
        response(200, {"routes": [{"distanceMeters": 3218}]})
    )

    result = route_client.compute_route(" origin-place ", "destination-place")

    assert result == GoogleRouteResult(
        origin_place_id="origin-place",
        destination_place_id="destination-place",
        distance_meters=3218,
        suggested_miles=2.0,
    )
    session.post.assert_called_once_with(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": "test-key",
            "X-Goog-FieldMask": "routes.distanceMeters",
        },
        json={
            "origin": {"placeId": "origin-place"},
            "destination": {"placeId": "destination-place"},
            "travelMode": "DRIVE",
            "computeAlternativeRoutes": False,
        },
        timeout=7.5,
    )


def test_compute_route_uses_exact_conversion_before_rounding() -> None:
    route_client, _ = client_with(
        response(200, {"routes": [{"distanceMeters": 16093}]})
    )

    result = route_client.get_distance("origin", "destination")

    assert result.distance_meters == 16093
    assert result.distance_miles == 10.0


@pytest.mark.parametrize(
    ("status", "body", "exception"),
    [
        (401, {"error": {"status": "UNAUTHENTICATED"}}, GoogleRoutesAuthenticationError),
        (403, {"error": {"status": "PERMISSION_DENIED"}}, GoogleRoutesAuthenticationError),
        (
            403,
            {"error": {"message": "The provided API key is invalid."}},
            GoogleRoutesInvalidKeyError,
        ),
        (400, {"error": {"status": "API_KEY_INVALID"}}, GoogleRoutesInvalidKeyError),
        (400, {"error": {"status": "INVALID_ARGUMENT"}}, GoogleRoutesNoRouteError),
        (404, {"error": {"status": "NOT_FOUND"}}, GoogleRoutesNoRouteError),
        (402, {"error": {"status": "BILLING_DISABLED"}}, GoogleRoutesBillingError),
        (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, GoogleRoutesQuotaError),
        (503, {"error": {"status": "UNAVAILABLE"}}, GoogleRoutesTemporaryError),
    ],
)
def test_compute_route_maps_safe_http_error_categories(
    status: int,
    body: dict[str, object],
    exception: type[Exception],
) -> None:
    route_client, _ = client_with(response(status, body))

    with pytest.raises(exception) as raised:
        route_client.compute_route("origin", "destination")

    assert "API_KEY_INVALID" not in str(raised.value)
    assert body["error"] != str(raised.value)


def test_compute_route_maps_request_timeout_without_raw_error() -> None:
    session = Mock()
    session.post.side_effect = requests.Timeout("secret transport detail")
    route_client = GoogleRoutesClient(
        GoogleRoutesConfig(api_key="secret-api-key"), session=session
    )

    with pytest.raises(GoogleRoutesTimeoutError, match="timed out") as raised:
        route_client.compute_route("origin", "destination")

    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_compute_route_maps_request_outage_without_raw_error() -> None:
    session = Mock()
    session.post.side_effect = requests.ConnectionError("private response")
    route_client = GoogleRoutesClient(
        GoogleRoutesConfig(api_key="secret-api-key"), session=session
    )

    with pytest.raises(GoogleRoutesTemporaryError, match="temporarily") as raised:
        route_client.compute_route("origin", "destination")

    assert "private" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"routes": []},
        {"routes": [{}]},
        {"routes": [{"distanceMeters": 0}]},
        {"routes": [{"distanceMeters": "3218"}]},
    ],
)
def test_compute_route_rejects_missing_or_unusable_primary_route(
    body: dict[str, object],
) -> None:
    route_client, _ = client_with(response(200, body))

    with pytest.raises(GoogleRoutesNoRouteError):
        route_client.compute_route("origin", "destination")


def test_compute_route_rejects_missing_place_ids_without_network_call() -> None:
    route_client, session = client_with(
        response(200, {"routes": [{"distanceMeters": 1}]})
    )

    with pytest.raises(GoogleRoutesNoRouteError):
        route_client.compute_route("", "destination")

    session.post.assert_not_called()
