"""Optional deployment-wide Maps adapter; never uses profile human grants."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
import secrets

from tabula_rasa.maps_routing import (
    GoogleRoutesClient, GoogleRoutesConfig, GoogleRoutesError,
    GoogleRoutesNoRouteError, GoogleRoutesQuotaError,
)

from .models.mileage import MileageMaps, MileageRoute


@dataclass
class MileageMapsAdapter:
    browser_api_key: str | None = field(default=None, repr=False)
    routes: GoogleRoutesClient | None = field(default=None, repr=False)
    region_code: str | None = None

    def configuration(self):
        return MileageMaps(browser_api_key=self.browser_api_key,
            routes_available=self.routes is not None, region_code=self.region_code)

    def calculate(self, origin, destination, *, round_trip=False):
        if origin == destination:
            return MileageRoute(error_code='no_route')
        if self.routes is None:
            return MileageRoute(error_code='unavailable')
        outbound = None
        try:
            outbound = f'{self.routes.compute_route(origin, destination).suggested_miles:.1f}'
            returned = (f'{self.routes.compute_route(destination, origin).suggested_miles:.1f}'
                        if round_trip else None)
            return MileageRoute(outbound_miles=outbound, return_miles=returned)
        except GoogleRoutesQuotaError:
            code = 'quota'
        except GoogleRoutesNoRouteError:
            code = 'no_route'
        except GoogleRoutesError:
            code = 'unavailable'
        return MileageRoute(outbound_miles=outbound, error_code=code)

    def close(self):
        if self.routes is not None:
            self.routes.session.close()


def _key(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    return (value if value and len(value) <= 256 and value.isascii()
            and not any(ord(char) < 32 for char in value) else None)


def load_mileage_maps(mapping):
    """Only the app-wide google_maps table owns keys; no profile fallback."""
    raw = mapping.get('google_maps', {}) if isinstance(mapping, Mapping) else {}
    if not isinstance(raw, Mapping):
        raise ValueError('Invalid Maps configuration.')
    browser, server = _key(raw.get('browser_api_key')), _key(raw.get('routes_api_key'))
    for name, value in [('browser_api_key', browser), ('routes_api_key', server)]:
        if raw.get(name) and value is None:
            raise ValueError('Invalid Maps configuration.')
    # A server key accidentally reused for Places must never cross the API.
    if browser and server and secrets.compare_digest(browser, server):
        browser = None
    region = raw.get('autocomplete_region_code') or None
    if region is not None and (not isinstance(region, str) or not re.fullmatch('[A-Za-z]{2}', region)):
        raise ValueError('Invalid Maps configuration.')
    routes = GoogleRoutesClient(GoogleRoutesConfig.from_secrets({'google_maps': raw})) if server else None
    return MileageMapsAdapter(browser, routes, region)


def environment_maps(environment):
    return load_mileage_maps({'google_maps': {
        'browser_api_key': environment.get('TABULA_RASA_MAPS_BROWSER_API_KEY'),
        'routes_api_key': environment.get('TABULA_RASA_MAPS_ROUTES_API_KEY'),
        'routes_timeout_seconds': environment.get('TABULA_RASA_MAPS_ROUTES_TIMEOUT_SECONDS', 15),
        'autocomplete_region_code': environment.get('TABULA_RASA_MAPS_REGION_CODE'),
    }})
