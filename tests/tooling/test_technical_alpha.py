"""Release tooling fails closed before touching retained synthetic staging."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from tabula_rasa.deployment import alpha

ENV = {'TABULA_RASA_ENVIRONMENT': 'staging', 'TABULA_RASA_PUBLIC_ORIGIN': 'https://stage.example.test',
       'TABULA_RASA_ALPHA_USERNAME': 'operator', 'TABULA_RASA_ALPHA_PASSWORD': 'synthetic'}
RELEASE = 'a' * 40


@pytest.mark.parametrize('changes', [
    {'TABULA_RASA_ENVIRONMENT': 'production'}, {'TABULA_RASA_ENVIRONMENT': 'development'},
    {'TABULA_RASA_PUBLIC_ORIGIN': 'http://stage.example.test'},
    {'TABULA_RASA_PUBLIC_ORIGIN': 'https://user:secret@stage.example.test'},
    {'TABULA_RASA_PUBLIC_ORIGIN': 'https://stage.example.test/path'},
    {'TABULA_RASA_PUBLIC_ORIGIN': 'https://stage.example.test?secret=value'},
    {'TABULA_RASA_PUBLIC_ORIGIN': 'https://127.0.0.1'},
    {'TABULA_RASA_ALPHA_PASSWORD': ''},
])
def test_invalid_environment_never_starts_smoke_or_browser(monkeypatch, changes):
    smoke = Mock()
    monkeypatch.setattr(alpha, 'smoke', smoke)
    with pytest.raises(alpha.AlphaError):
        alpha.run({**ENV, **changes}, RELEASE, allow_writes=True)
    smoke.assert_not_called()


def test_explicit_write_consent_and_immutable_release_are_required():
    with pytest.raises(alpha.AlphaError):
        alpha.configuration(ENV, RELEASE, False)
    for release in ('main', RELEASE + '\n', 'latest'):
        with pytest.raises(alpha.AlphaError):
            alpha.configuration(ENV, release, True)
    assert alpha.configuration(ENV, RELEASE, True) == (ENV['TABULA_RASA_PUBLIC_ORIGIN'], 'operator', 'synthetic')


def test_missing_document_store_stops_before_any_browser_create():
    context = Mock()
    context.request.get.side_effect = [
        SimpleNamespace(status=200, json=lambda: {'entity': {'id': 'alpha-synthetic'}, 'trusted_development': True,
            'capabilities': ['bookkeeping:read', 'bookkeeping:write'], 'csrf_token': 'csrf'}),
        SimpleNamespace(status=503),
    ]
    with pytest.raises(alpha.AlphaError, match='DocumentStore'):
        alpha.journey(context, Mock(), origin=ENV['TABULA_RASA_PUBLIC_ORIGIN'], entity='alpha-synthetic', marker='synthetic')
    context.new_page.assert_not_called()
    assert [call[0] for call in context.request.method_calls] == ['get', 'get']


@pytest.mark.parametrize('session', [
    {'entity': {'id': 'live'}, 'trusted_development': True, 'capabilities': ['bookkeeping:read', 'bookkeeping:write']},
    {'entity': {'id': 'alpha-synthetic'}, 'trusted_development': False, 'capabilities': ['bookkeeping:read', 'bookkeeping:write']},
    {'entity': {'id': 'alpha-synthetic'}, 'trusted_development': True, 'capabilities': ['bookkeeping:read']},
])
def test_unexpected_identity_stops_before_provider_inventory(session):
    context = Mock()
    context.request.get.return_value = SimpleNamespace(status=200, json=lambda: session)
    with pytest.raises(alpha.AlphaError, match='synthetic context'):
        alpha.preflight(context, 'alpha-synthetic', ENV['TABULA_RASA_PUBLIC_ORIGIN'])
    assert context.request.get.call_count == 1


def test_raw_browser_provider_failures_never_reach_cli_output(monkeypatch, capsys):
    monkeypatch.setattr(alpha, 'run', Mock(side_effect=RuntimeError('secret URL and private receipt')))
    with pytest.raises(SystemExit) as result:
        alpha.main(['--release', RELEASE, '--allow-synthetic-writes'])
    assert 'secret' not in str(result.value) and 'private' not in str(result.value)
    assert not capsys.readouterr().out


def test_preflight_returns_only_selected_scope_and_csrf_headers():
    context = Mock()
    context.request.get.side_effect = [
        SimpleNamespace(status=200, json=lambda: {'entity': {'id': 'alpha-synthetic'}, 'trusted_development': True,
            'capabilities': ['bookkeeping:read', 'bookkeeping:write'], 'csrf_token': 'csrf'}),
        SimpleNamespace(status=200),
    ]
    assert alpha.preflight(context, 'alpha-synthetic', ENV['TABULA_RASA_PUBLIC_ORIGIN']) == (
        '/api/v1/entities/alpha-synthetic/', {'Origin': ENV['TABULA_RASA_PUBLIC_ORIGIN'], 'X-CSRF-Token': 'csrf'})


def test_failure_status_alone_does_not_establish_baseline_contract():
    response = SimpleNamespace(status=409, json=lambda: {'error': {'code': 'duplicate'}})
    with pytest.raises(alpha.AlphaError, match='wrong failure contract'):
        alpha.rejected(response, 409, 'stale')


def test_staging_gate_shares_promotion_lock_and_has_no_admin_credentials():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / '.github/workflows/commercial-alpha.yml').read_text(), Loader=yaml.BaseLoader)
    job = workflow['jobs']['alpha']
    assert job['environment'] == 'staging'
    assert job['concurrency'] == {'group': 'commercial-deploy-staging', 'cancel-in-progress': 'false'}
    assert 'refs/heads/main' in job['if'] and 'allow_synthetic_writes' in job['if']
    assert 'allow_synthetic_writes' in workflow['on']['workflow_dispatch']['inputs']
    assert job['permissions'] == {'contents': 'read', 'actions': 'read'}
    payload = str(workflow)
    for secret in ('MIGRATION_DATABASE_URL', 'TEST_DATABASE_URL', 'RENDER_API_KEY', 'DATABASE_URL'):
        assert secret not in payload
    assert 'alpha --release' in payload and '--allow-synthetic-writes' in payload
