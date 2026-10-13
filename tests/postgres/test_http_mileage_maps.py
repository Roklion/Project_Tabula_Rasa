"""Transient Maps transport, separate credential ownership and scoped saves."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.http.maps import MileageMapsAdapter, environment_maps, load_mileage_maps
from tabula_rasa.maps_routing import GoogleRoutesQuotaError, GoogleRoutesNoRouteError, GoogleRoutesTemporaryError
from tests.postgres.test_http_baselines import commercial as commercial, HEADERS, PREFIX, snapshot
from tests.postgres.test_http_mileage_documents import TRIP


def test_maps_credentials_are_deployment_wide_and_server_key_never_enters_configuration():
    adapter = environment_maps({'TABULA_RASA_MAPS_BROWSER_API_KEY': 'synthetic-browser',
        'TABULA_RASA_MAPS_ROUTES_API_KEY': 'synthetic-server', 'TABULA_RASA_MAPS_REGION_CODE': 'us'})
    try:
        assert adapter.configuration().model_dump() == dict(browser_api_key='synthetic-browser', routes_available=True, region_code='us')
        assert 'synthetic-server' not in adapter.configuration().model_dump_json() + repr(adapter)
        same = load_mileage_maps({'google_maps': {'browser_api_key': 'same', 'routes_api_key': 'same'}})
        try:
            assert same.configuration().browser_api_key is None
        finally:
            same.close()
        assert load_mileage_maps({'profiles': {'alpha': {'google_maps': {'browser_api_key': 'private'}}}}).browser_api_key is None
        regional = load_mileage_maps({'google_maps': {'browser_api_key': 'synthetic-browser', 'autocomplete_region_code': 'ca'}})
        assert regional.region_code == 'ca'
    finally:
        adapter.close()


@pytest.mark.parametrize('failure,code', [(GoogleRoutesQuotaError, 'quota'), (GoogleRoutesNoRouteError, 'no_route'),
                                        (GoogleRoutesTemporaryError, 'unavailable')])
def test_provider_failures_preserve_outbound_and_never_echo_provider_text(commercial, database, failure, code):
    _, _, (client, _), _ = commercial
    routes = Mock()
    routes.compute_route.side_effect = [SimpleNamespace(suggested_miles=Decimal('12.4')), failure('PRIVATE key and location')]
    client.app.state.runtime.maps = MileageMapsAdapter('synthetic-browser', routes)
    before = snapshot(database)
    result = client.post(PREFIX + 'mileage/routes', headers=HEADERS,
        json=dict(origin_place_id='origin', destination_place_id='destination', round_trip=True))
    assert result.status_code == 200 and result.json() == dict(outbound_miles='12.4', return_miles=None, error_code=code)
    assert 'PRIVATE' not in result.text
    assert snapshot(database) == before


def test_calculation_is_transient_and_confirmed_round_trip_saves_are_entity_isolated(commercial, database):
    alpha, beta, (client, _), _ = commercial
    routes = Mock()
    routes.compute_route.side_effect = [SimpleNamespace(suggested_miles=Decimal('12.4')), SimpleNamespace(suggested_miles=Decimal('14.6'))]
    runtime = client.app.state.runtime
    runtime.maps = MileageMapsAdapter('synthetic-browser', routes)
    before = snapshot(database)
    result = client.post(PREFIX + 'mileage/routes', headers=HEADERS,
        json=dict(origin_place_id='origin', destination_place_id='destination', round_trip=True))
    assert result.status_code == 200 and result.json()['return_miles'] == '14.6'
    assert routes.compute_route.call_args_list[0].args == ('origin', 'destination')
    assert routes.compute_route.call_args_list[1].args == ('destination', 'origin')
    assert snapshot(database) == before
    assert client.get(PREFIX.replace('alpha', 'beta') + 'mileage/maps').status_code == 403
    assert client.post(PREFIX + 'mileage/routes', json={'origin_place_id': 'a', 'destination_place_id': 'b'}).status_code == 403
    assert client.post(PREFIX + 'mileage/routes', headers=HEADERS, json={'origin_place_id': '', 'destination_place_id': 'b'}).status_code == 422
    saved = client.post(PREFIX + 'mileage', headers=HEADERS, json={**TRIP, 'miles': '12.4', 'return_miles': '14.6', 'round_trip': True})
    assert saved.status_code == 201
    assert [row['miles'] for row in saved.json()['items']] == ['12.4', '14.6']
    assert beta.mileage.list_trips() == () and len(alpha.mileage.list_trips()) == 3
    original = runtime.resolve_context
    runtime.resolve_context = lambda request: replace(original(request), entity_id='beta')
    assert client.get(PREFIX + 'mileage/maps').status_code == 403
    assert client.get(PREFIX.replace('alpha', 'beta') + 'mileage/maps').json()['browser_api_key'] == 'synthetic-browser'
    runtime.resolve_context = lambda request: replace(original(request), capabilities=frozenset({'bookkeeping:read'}))
    assert client.get(PREFIX + 'mileage/maps').status_code == 200
    assert client.post(PREFIX + 'mileage/routes', headers=HEADERS, json={'origin_place_id': 'a', 'destination_place_id': 'b'}).status_code == 403


def test_unconfigured_and_identical_endpoints_offer_manual_fallback(commercial):
    _, _, (client, _), _ = commercial
    assert client.get(PREFIX + 'mileage/maps').json() == dict(browser_api_key=None, routes_available=False, region_code=None)
    result = client.post(PREFIX + 'mileage/routes', headers=HEADERS, json={'origin_place_id': 'a', 'destination_place_id': 'b'})
    assert result.json()['error_code'] == 'unavailable'
    routes = Mock()
    assert MileageMapsAdapter(routes=routes).calculate('same', 'same').error_code == 'no_route'
    routes.compute_route.assert_not_called()
