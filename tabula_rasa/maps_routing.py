"""Server-side client for the Google Routes Compute Routes API.

The client deliberately has a small boundary: callers provide Google Place
IDs and receive a typed distance result.  API responses and credentials stay
inside this module so neither can accidentally reach the UI or application
logs.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from typing import Any

import requests


ROUTES_API_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TIMEOUT_SECONDS = 60.0
METERS_PER_MILE = 1609.344
ROUTES_FIELD_MASK = "routes.distanceMeters"


class GoogleRoutesError(RuntimeError):
    """Base class for safe, user-displayable Routes API failures."""


class GoogleRoutesConfigurationError(GoogleRoutesError):
    """Raised when the deployment's Routes settings are incomplete."""


class GoogleRoutesTimeoutError(GoogleRoutesError):
    """Raised when the Routes API does not respond before the timeout."""


class GoogleRoutesQuotaError(GoogleRoutesError):
    """Raised when the Routes API quota or rate limit is exhausted."""


class GoogleRoutesAuthenticationError(GoogleRoutesError):
    """Raised when the Routes API rejects the request authorization."""


class GoogleRoutesBillingError(GoogleRoutesError):
    """Raised when the Google Cloud billing account cannot make the request."""


class GoogleRoutesInvalidKeyError(GoogleRoutesError):
    """Raised when the configured Google API key is invalid or unusable."""


class GoogleRoutesNoRouteError(GoogleRoutesError):
    """Raised when no usable primary route is returned."""


class GoogleRoutesTemporaryError(GoogleRoutesError):
    """Raised for transient network or Google service failures."""


@dataclass(frozen=True)
class GoogleRoutesConfig:
    """Application-wide Google Routes settings.

    The API key is intentionally deployment-wide, like the other app-level
    Google API settings.  It is not sourced from a business profile, Sheets
    service account, or Drive OAuth configuration.
    """

    api_key: str = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """Keep direct construction subject to the same secret validation."""
        api_key = _clean_secret(self.api_key, maximum=256)
        if not api_key:
            raise GoogleRoutesConfigurationError(
                "Google Routes API key configuration is incomplete."
            )
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "timeout_seconds", _parse_timeout(self.timeout_seconds))

    @classmethod
    def from_secrets(cls, secrets_mapping: Mapping[str, Any]) -> "GoogleRoutesConfig":
        """Load Routes settings from the app-wide ``google_maps`` table.

        ``browser_api_key`` may be present beside the server key for Maps
        UI features, but is deliberately ignored by this server-side client.
        """
        if not isinstance(secrets_mapping, Mapping):
            raise GoogleRoutesConfigurationError(
                "Google Routes is not configured for this deployment."
            )
        raw = secrets_mapping.get("google_maps")
        if not isinstance(raw, Mapping):
            raise GoogleRoutesConfigurationError(
                "Google Maps routing is not configured for this deployment."
            )
        api_key = _clean_secret(raw.get("routes_api_key"), maximum=256)
        if not api_key:
            raise GoogleRoutesConfigurationError(
                "Google Routes API key configuration is incomplete."
            )
        timeout = _parse_timeout(
            raw.get("routes_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        )
        return cls(api_key=api_key, timeout_seconds=timeout)


def load_routes_config(secrets_mapping: Mapping[str, Any]) -> GoogleRoutesConfig:
    """Return the app-wide Routes config from Streamlit secrets."""
    return GoogleRoutesConfig.from_secrets(secrets_mapping)


@dataclass(frozen=True)
class GoogleRouteResult:
    """Validated distance returned by Compute Routes.

    ``suggested_miles`` is rounded only at the final presentation boundary;
    conversion uses the exact statutory factor represented by
    :data:`METERS_PER_MILE`.
    """

    origin_place_id: str
    destination_place_id: str
    distance_meters: int
    suggested_miles: float

    @property
    def distance_miles(self) -> float:
        """Alias useful to callers that do not need the suggestion wording."""
        return self.suggested_miles


class GoogleRoutesClient:
    """Minimal authenticated client for ``computeRoutes``."""

    def __init__(
        self,
        config: GoogleRoutesConfig,
        *,
        session: requests.Session | None = None,
        endpoint: str = ROUTES_API_ENDPOINT,
    ) -> None:
        if not isinstance(config, GoogleRoutesConfig):
            raise GoogleRoutesConfigurationError(
                "Google Routes configuration is invalid."
            )
        self.config = config
        self.session = session or requests.Session()
        self.endpoint = endpoint

    def compute_route(
        self,
        origin_place_id: str,
        destination_place_id: str,
    ) -> GoogleRouteResult:
        """Compute a driving distance between two Google Place IDs."""
        origin = _clean_place_id(origin_place_id)
        destination = _clean_place_id(destination_place_id)
        if not origin or not destination:
            raise GoogleRoutesNoRouteError(
                "A valid origin and destination are required for route distance."
            )

        payload = {
            "origin": {"placeId": origin},
            "destination": {"placeId": destination},
            "travelMode": "DRIVE",
            "computeAlternativeRoutes": False,
        }
        try:
            response = self.session.post(
                self.endpoint,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self.config.api_key,
                    "X-Goog-FieldMask": ROUTES_FIELD_MASK,
                },
                json=payload,
                timeout=self.config.timeout_seconds,
            )
        except requests.Timeout:
            raise GoogleRoutesTimeoutError(
                "Google Maps routing timed out. Try again."
            ) from None
        except requests.RequestException:
            raise GoogleRoutesTemporaryError(
                "Google Maps routing is temporarily unavailable. Try again."
            ) from None

        body = _response_json(response)
        if response.status_code < 200 or response.status_code >= 300:
            raise _error_for_response(response.status_code, body)

        distance_meters = _primary_distance_meters(body)
        if distance_meters is None:
            raise GoogleRoutesNoRouteError(
                "Google Maps did not return a usable route for those places."
            )
        return GoogleRouteResult(
            origin_place_id=origin,
            destination_place_id=destination,
            distance_meters=distance_meters,
            suggested_miles=round(distance_meters / METERS_PER_MILE, 1),
        )

    # A concise alias makes the client convenient in form submit handlers while
    # keeping ``compute_route`` as the descriptive canonical method.
    get_distance = compute_route


def _clean_secret(value: object, *, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        return ""
    return value


def _clean_place_id(value: object) -> str:
    return _clean_secret(value, maximum=512)


def _parse_timeout(value: object) -> float:
    if isinstance(value, bool):
        raise GoogleRoutesConfigurationError(
            "Google Routes timeout_seconds must be a positive number."
        )
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise GoogleRoutesConfigurationError(
            "Google Routes timeout_seconds must be a positive number."
        ) from error
    if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        raise GoogleRoutesConfigurationError(
            "Google Routes timeout_seconds must be between 0 and 60."
        )
    return timeout


def _response_json(response: Any) -> Mapping[str, Any]:
    try:
        body = response.json()
    except (ValueError, TypeError):
        return {}
    return body if isinstance(body, Mapping) else {}


def _primary_distance_meters(body: Mapping[str, Any]) -> int | None:
    routes = body.get("routes")
    if not isinstance(routes, list) or not routes:
        return None
    primary = routes[0]
    if not isinstance(primary, Mapping):
        return None
    value = primary.get("distanceMeters")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        return None
    distance = int(value)
    return distance if distance > 0 else None


def _error_for_response(status_code: int, body: Mapping[str, Any]) -> GoogleRoutesError:
    """Map a response to a safe category without exposing API response text."""
    error = body.get("error")
    details: list[str] = []
    if isinstance(error, Mapping):
        for key in ("status", "message", "reason"):
            value = error.get(key)
            if isinstance(value, str):
                details.append(value.casefold())
        error_details = error.get("details")
        if isinstance(error_details, list):
            details.extend(
                str(item).casefold()
                for item in error_details
                if isinstance(item, str)
            )
    markers = " ".join(details)

    if status_code in (408, 504):
        return GoogleRoutesTimeoutError(
            "Google Maps routing timed out. Try again."
        )
    if status_code == 429 or any(
        marker in markers for marker in ("quota", "rate limit", "resource_exhausted")
    ):
        return GoogleRoutesQuotaError(
            "Google Maps routing quota has been reached. Try again later."
        )
    if status_code == 402 or any(
        marker in markers for marker in ("billing", "billingenabled", "payment")
    ):
        return GoogleRoutesBillingError(
            "Google Maps routing billing is not enabled."
        )
    key_invalid = (
        "api_key_invalid" in markers
        or "invalid api key" in markers
        or ("api key" in markers and ("invalid" in markers or "not valid" in markers))
    )
    if key_invalid:
        return GoogleRoutesInvalidKeyError(
            "The Google Maps routing API key is invalid or not authorized."
        )
    if status_code in (400, 404) or any(
        marker in markers for marker in ("invalid_argument", "not_found")
    ):
        return GoogleRoutesNoRouteError(
            "Google Maps could not use one of those selected places. "
            "Choose the addresses again or enter mileage manually."
        )
    if status_code in (401, 403):
        return GoogleRoutesAuthenticationError(
            "Google Maps routing authorization was rejected."
        )
    if status_code >= 500 or any(
        marker in markers for marker in ("unavailable", "internal")
    ):
        return GoogleRoutesTemporaryError(
            "Google Maps routing is temporarily unavailable. Try again."
        )
    return GoogleRoutesTemporaryError(
        "Google Maps routing could not be completed. Try again."
    )
