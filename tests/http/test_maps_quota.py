"""Lazy monitoring, sanitized display and selected-business authorization."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import json

from fastapi.testclient import TestClient
import pytest

from tabula_rasa.google_maps_quota_core import (
    GoogleMapsQuotaClient, GoogleMapsQuotaMonitoringConfig, GoogleMapsQuotaReport,
    GoogleMapsServiceReport, parse_quota_metrics, parse_usage_time_series,
)
from tabula_rasa.http.app import create_app
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import DenyContext, RequestContext
from tabula_rasa.http.maps_quota import MapsQuotaAdapter, environment_maps_quota, load_maps_quota


PATH = '/api/v1/entities/alpha/maps/usage'
HEADERS = {'Origin': 'http://testserver', 'X-CSRF-Token': 'csrf'}
CREDENTIAL = dict(type='service_account', client_email='private-reader@example.test',
                  private_key='private-key', token_uri='https://oauth2.googleapis.com/token')
CONFIG = GoogleMapsQuotaMonitoringConfig('123456789', CREDENTIAL)


def quota_payload(service):
    return {'metrics': [{'name': 'projects/private-project', 'displayName': 'Requests', 'metric': 'requests',
        'consumerQuotaLimits': [{'name': 'projects/private-project/limit', 'displayName': 'Requests - ' + service,
            'metric': 'requests', 'unit': '1/min/{project}/{user}',
            'quotaBuckets': [{'effectiveLimit': '9223372036854775807'}]}]}]}


def report():
    return GoogleMapsQuotaReport('123456789', tuple(GoogleMapsServiceReport(
        service, parse_quota_metrics(quota_payload(name)), parse_usage_time_series({
            'timeSeries': [{'resource': {'labels': {'project_id': 'private-project', 'user': 'private-user'}},
                'metric': {'labels': {'quota_metric': 'requests'}}, 'unit': '1/s',
                'points': [{'interval': {'endTime': '2026-10-01T00:00:00Z'}, 'value': {'doubleValue': 2}}]}]
        }, service=service) if name == 'ComputeRoutes' else {})
        for service, name in [('routes.googleapis.com', 'ComputeRoutes'), ('places.googleapis.com', 'Autocomplete requests')]))


@pytest.fixture
def quota_client():
    provider = Mock()
    provider.fetch_report.return_value = report()
    factory = Mock(return_value=provider)
    clock = Mock(return_value=1000)
    adapter = MapsQuotaAdapter(CONFIG, client_factory=factory, clock=clock)
    context = RequestContext('actor', 'org', 'alpha', frozenset({'bookkeeping:read'}), 'scope', 'csrf')
    runtime = SimpleNamespace(maps_quota=adapter, resolve_context=lambda _: context,
                              close=adapter.close, ready=lambda: True)
    with TestClient(create_app(settings=HttpSettings('test', 'http://testserver'),
                              runtime_factory=lambda _: runtime)) as client:
        yield client, runtime, provider, factory, clock


def load(client, refresh=False, path=PATH):
    return client.post(path, headers=HEADERS, json={'refresh': refresh})


def test_status_is_lazy_and_success_projects_only_compact_display_rows(quota_client):
    client, _, provider, factory, _ = quota_client
    assert client.get(PATH).json()['status'] == 'not_loaded'
    factory.assert_not_called()
    response = load(client)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert response.json()['services'] == [
        {'title': 'Routes API', 'rows': ['ComputeRoutes: 120/Unlimited (per minute)']},
        {'title': 'Places API (New)', 'rows': ['Autocomplete requests: 0/Unlimited (per minute)']}]
    for private in ('private-project', 'private-user', '123456789', 'private-key', 'private-reader', '{project}', '{user}'):
        assert private not in response.text
    assert client.get(PATH).json()['status'] == 'not_loaded'
    assert provider.fetch_report.call_count == 1


def test_bounded_cache_refresh_and_close_touch_only_quota_monitoring(quota_client):
    client, runtime, provider, factory, clock = quota_client
    runtime.maps = Mock()
    assert load(client).json()['cache_remaining_seconds'] == 120
    clock.return_value = 1119
    assert load(client).json()['cache_remaining_seconds'] == 1
    assert provider.fetch_report.call_count == 1
    assert load(client, True).json()['cache_remaining_seconds'] == 120
    clock.return_value = 1239
    assert load(client).json()['status'] == 'ready'
    assert provider.fetch_report.call_count == 3
    assert factory.call_count == 1
    runtime.maps.assert_not_called()
    assert runtime.maps.mock_calls == []
    runtime.maps_quota.close()
    provider.session.close.assert_called_once()


@pytest.mark.parametrize('method,denial', [
    (method, denial) for method in ('get', 'post') for denial in ('anonymous', 'foreign', 'capability')
] + [('post', 'csrf'), ('post', 'origin')])
def test_denials_happen_before_status_or_provider_access(quota_client, method, denial):
    client, runtime, provider, factory, _ = quota_client
    runtime.maps_quota = Mock()
    original = runtime.resolve_context
    headers = HEADERS.copy()
    path = PATH
    if denial == 'anonymous':
        runtime.resolve_context = DenyContext()
    elif denial == 'foreign':
        path = PATH.replace('alpha', 'beta')
    elif denial == 'capability':
        runtime.resolve_context = lambda request: replace(original(request), capabilities=frozenset())
    elif denial in {'csrf', 'origin'}:
        headers.pop('X-CSRF-Token' if denial == 'csrf' else 'Origin')
    response = client.request(method.upper(), path, headers=headers, **({'json': {}} if method == 'post' else {}))
    assert response.status_code == (401 if denial == 'anonymous' else 403)
    assert runtime.maps_quota.mock_calls == []
    factory.assert_not_called()
    provider.fetch_report.assert_not_called()


def test_two_authorized_businesses_use_only_deployment_reader_and_caller_cannot_select_config(quota_client):
    client, runtime, provider, factory, _ = quota_client
    assert load(client).json()['status'] == 'ready'
    original = runtime.resolve_context
    runtime.resolve_context = lambda request: replace(original(request), entity_id='beta', organization_id='other-org')
    assert load(client, True).status_code == 403  # Cached data is also guarded.
    assert client.get(PATH).status_code == 403
    beta = PATH.replace('alpha', 'beta')
    assert load(client, path=beta).json()['status'] == 'ready'
    assert provider.fetch_report.call_count == 1
    factory.assert_called_once_with(CONFIG)
    for field in ('project_number', 'service_account', 'profile_key'):
        assert client.post(beta, headers=HEADERS, json={field: 'arbitrary'}).status_code == 422
    assert provider.fetch_report.call_count == 1


@pytest.mark.parametrize('api,status,guidance', [
    ('Service Usage', 403, 'OAuth scopes and IAM roles'),
    ('Service Usage', 404, 'numeric Google Cloud project number'),
    ('Cloud Monitoring', 429, 'quota recovers'),
    ('Cloud Monitoring', 503, 'enabled API and quota-reader access'),
])
def test_provider_failures_keep_safe_status_guidance_and_never_show_zero(quota_client, api, status, guidance):
    client, runtime, _, _, _ = quota_client
    session = Mock()
    bad = Mock(status_code=status)
    bad.json.return_value = {'error': 'private-key private-reader private-project'}
    if api == 'Cloud Monitoring':
        ok = Mock(status_code=200)
        ok.json.return_value = quota_payload('ComputeRoutes')
        session.get.side_effect = [ok, bad]
    else:
        session.get.return_value = bad
    runtime.maps_quota = MapsQuotaAdapter(CONFIG,
        client_factory=lambda config: GoogleMapsQuotaClient(config, session=session))
    response = load(client)
    assert response.json()['status'] == 'error' and response.json()['services'] == []
    assert api in response.json()['message'] and str(status) in response.text and guidance in response.text
    assert 'private-' not in response.text and '0/' not in response.text
    bad.json.assert_not_called()


def test_failed_refresh_drops_old_report_and_retry_is_explicit(quota_client):
    client, _, provider, _, _ = quota_client
    assert load(client).json()['status'] == 'ready'
    provider.fetch_report.side_effect = RuntimeError('private-key')
    failed = load(client, True)
    assert failed.json()['status'] == 'error' and failed.json()['services'] == []
    assert 'private-key' not in failed.text
    client.get(PATH)
    assert provider.fetch_report.call_count == 2
    provider.fetch_report.side_effect = None
    assert load(client).json()['status'] == 'ready'
    assert provider.fetch_report.call_count == 3


def test_successful_empty_monitoring_is_zero_and_no_metrics_is_not_a_fake_counter(quota_client):
    client, runtime, _, _, _ = quota_client
    session = Mock()
    def response(payload):
        result = Mock(status_code=200)
        result.json.return_value = payload
        return result
    session.get.side_effect = [response(quota_payload('ComputeRoutes')), response({'timeSeries': []}),
                               response({'metrics': []}), response({'timeSeries': []})]
    runtime.maps_quota = MapsQuotaAdapter(CONFIG,
        client_factory=lambda config: GoogleMapsQuotaClient(config, session=session))
    services = load(client).json()['services']
    assert services[0]['rows'] == ['ComputeRoutes: 0/Unlimited (per minute)']
    assert services[1]['rows'] == []


def test_optional_configuration_is_server_only_and_profile_fallback_is_absent(tmp_path):
    assert environment_maps_quota({}).status().status == 'unconfigured'
    assert load_maps_quota({'business_profiles': {'alpha': {'google_maps': {'quota_monitoring': CREDENTIAL}}}}).status().status == 'unconfigured'
    path = tmp_path / 'synthetic-quota.json'
    path.write_text(json.dumps(CREDENTIAL), encoding='utf-8')
    environment = {'TABULA_RASA_MAPS_QUOTA_PROJECT_NUMBER': '123456789',
                   'TABULA_RASA_MAPS_QUOTA_SERVICE_ACCOUNT_FILE': str(path)}
    assert environment_maps_quota(environment).status().status == 'not_loaded'
    assert load_maps_quota({'google_maps': {'quota_monitoring': {
        'project_number': '123456789', 'service_account': CREDENTIAL}}}).status().status == 'not_loaded'
    for values in ({**environment, 'TABULA_RASA_MAPS_QUOTA_TIMEOUT_SECONDS': '0'},
                   {**environment, 'TABULA_RASA_MAPS_QUOTA_PROJECT_NUMBER': 'private-project'},
                   {**environment, 'TABULA_RASA_MAPS_QUOTA_SERVICE_ACCOUNT_FILE': str(path) + '-missing'}):
        result = environment_maps_quota(values)
        assert result.status().status == 'error'
        assert result.load().status == 'error'
        assert 'private-' not in result.load().model_dump_json()
    path.write_text('private invalid JSON', encoding='utf-8')
    assert environment_maps_quota(environment).status().status == 'error'


def test_missing_configuration_leaves_authenticated_status_and_load_usable(quota_client):
    client, runtime, provider, _, _ = quota_client
    runtime.maps_quota = environment_maps_quota({})
    for response in (client.get(PATH), load(client)):
        assert response.json()['status'] == 'unconfigured'
        assert 'dedicated Maps quota reader' in response.json()['message']
    provider.fetch_report.assert_not_called()
