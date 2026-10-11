"""Release tooling fails closed before touching retained synthetic staging."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

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
    with pytest.raises(alpha.AlphaError) as result:
        alpha.journey(context, Mock(), origin=ENV['TABULA_RASA_PUBLIC_ORIGIN'], entity='alpha-synthetic', marker='synthetic')
    assert result.value.operation == 'preflight'
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
    assert result.value.__suppress_context__
    assert 'secret URL' not in ''.join(traceback.format_exception(result.value))
    assert not capsys.readouterr().out


def test_nested_operation_preserves_label_without_exception_payload():
    with pytest.raises(alpha.AlphaError) as result:
        with alpha.operation('context_open'), alpha.operation('receipt_download'):
            raise RuntimeError('secret URL, private receipt and raw response')
    assert result.value.operation == 'receipt_download'
    assert 'secret' not in str(result.value)
    assert result.value.__suppress_context__
    assert 'secret URL' not in ''.join(traceback.format_exception(result.value))
    assert alpha.AlphaError('ignored', operation='private payload').operation is None


@pytest.mark.parametrize('failure', ['initial_smoke', 'browser_launch', 'context_open', 'receipt_download', 'browser_close', 'final_smoke'])
def test_failure_diagnostics_identify_only_safe_execution_context(monkeypatch, capsys, failure):
    import playwright.sync_api
    manager = MagicMock()
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', Mock(return_value=manager))
    browser = manager.__enter__.return_value.firefox.launch.return_value
    monkeypatch.setattr(alpha, 'ENGINES', ('firefox',))
    monkeypatch.setattr(alpha, 'WIDTHS', (390,))
    secret = RuntimeError('PRIVATE provider response, credential and receipt')
    monkeypatch.setattr(alpha, 'smoke', Mock(side_effect=[None, secret] if failure == 'final_smoke'
        else secret if failure == 'initial_smoke' else None))
    if failure == 'browser_launch':
        manager.__enter__.return_value.firefox.launch.side_effect = secret
    if failure == 'context_open':
        browser.new_context.side_effect = secret

    def journey(*args, **kwargs):
        if failure == 'receipt_download':
            with alpha.operation('receipt_download'):
                raise secret

    monkeypatch.setattr(alpha, 'journey', journey)
    # A secondary teardown failure must not mask receipt_download.
    if failure in {'receipt_download', 'browser_close'}:
        browser.close.side_effect = secret
    with pytest.raises(alpha.AlphaError) as result:
        alpha.run(ENV, RELEASE, allow_writes=True)
    assert result.value.operation == failure and result.value.__context__ is None
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    diagnostic = records[-1]
    shared = failure in {'initial_smoke', 'final_smoke'}
    viewport = shared or failure == 'browser_launch'
    assert diagnostic == {'run': records[0]['run'], 'release': RELEASE, 'status': 'failed', 'operation': failure,
        'engine': None if shared else 'firefox', 'width': None if viewport else 390,
        'height': None if viewport else 844}
    assert len(diagnostic['run']) == 32
    assert 'PRIVATE' not in json.dumps(records)


def test_success_runs_every_engine_viewport_and_both_smokes(monkeypatch, capsys):
    import playwright.sync_api
    manager = MagicMock()
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', Mock(return_value=manager))
    smoke, journey = Mock(), Mock()
    monkeypatch.setattr(alpha, 'smoke', smoke)
    monkeypatch.setattr(alpha, 'journey', journey)
    result = alpha.run(ENV, RELEASE, allow_writes=True)
    assert result['status'] == 'alpha_browser_passed' and result['release'] == RELEASE
    assert smoke.call_count == 2 and journey.call_count == 6
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert {(row['engine'], row['width'], row['height']) for row in records[1:]} == {
        (engine, width, 1000 if width == 1440 else 844) for engine in alpha.ENGINES for width in alpha.WIDTHS}
    assert all(row['status'] == 'passed' for row in records[1:])


@pytest.mark.parametrize('journey_fails', [True, False])
@pytest.mark.parametrize('closing_context', [0, 1])
def test_context_teardown_preserves_journey_failure(monkeypatch, capsys, journey_fails, closing_context):
    import playwright.sync_api
    manager = MagicMock()
    monkeypatch.setattr(playwright.sync_api, 'sync_playwright', Mock(return_value=manager))
    browser = manager.__enter__.return_value.firefox.launch.return_value
    contexts = [MagicMock(), MagicMock()]
    browser.new_context.side_effect = contexts
    contexts[closing_context].__exit__.side_effect = RuntimeError('PRIVATE teardown payload')
    monkeypatch.setattr(alpha, 'ENGINES', ('firefox',))
    monkeypatch.setattr(alpha, 'WIDTHS', (390,))
    smoke = Mock()
    monkeypatch.setattr(alpha, 'smoke', smoke)

    def journey(*args, **kwargs):
        if journey_fails:
            with alpha.operation('receipt_attach'):
                raise RuntimeError('PRIVATE journey payload')

    monkeypatch.setattr(alpha, 'journey', journey)
    with pytest.raises(alpha.AlphaError) as result:
        alpha.run(ENV, RELEASE, allow_writes=True)
    expected = 'receipt_attach' if journey_fails else 'context_open'
    assert result.value.operation == expected and result.value.__context__ is None
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[-1]['operation'] == expected and records[-1]['status'] == 'failed'
    assert not any(row['status'] == 'passed' for row in records)
    assert 'PRIVATE' not in json.dumps(records) + ''.join(traceback.format_exception(result.value))
    assert smoke.call_count == 1
    browser.close.assert_called_once()
    for context in contexts:
        context.__exit__.assert_called_once()


def test_invalid_release_never_enters_diagnostics(monkeypatch, capsys):
    smoke = Mock()
    monkeypatch.setattr(alpha, 'smoke', smoke)
    with pytest.raises(alpha.AlphaError):
        alpha.run(ENV, 'PRIVATE invalid release', allow_writes=True)
    record = json.loads(capsys.readouterr().out)
    assert record['release'] is None and record['operation'] == 'configuration'
    smoke.assert_not_called()


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


@pytest.mark.parametrize('release_exists', [True, False])
def test_gate_selects_approved_ancestor_and_stops_on_checkout_failure(tmp_path, release_exists):
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / '.github/workflows/commercial-alpha.yml').read_text(), Loader=yaml.BaseLoader)
    steps = workflow['jobs']['alpha']['steps']
    validation = next(step for step in steps if 'validated_main' in step.get('run', ''))
    selection = next(step for step in steps if step.get('name') == 'Check out validated release')
    gate = next(step for step in steps if 'python -m tabula_rasa.deployment.alpha' in step.get('run', ''))
    assert steps.index(validation) < steps.index(selection) < steps.index(gate)

    def git(*args):
        return subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    git('init', '-b', 'main')
    for version in ('selected', 'newer-main'):
        (tmp_path / 'journey.txt').write_text(version)
        git('add', 'journey.txt')
        git('-c', 'user.name=Alpha test', '-c', 'user.email=alpha@example.test',
            '-c', 'commit.gpgsign=false', 'commit', '-m', version)
        if version == 'selected':
            release = git('rev-parse', 'HEAD')
    newer_main = git('rev-parse', 'HEAD')
    assert release != newer_main
    git_path = Path(shutil.which('git'))
    bash = str(git_path.parent.parent / 'bin/bash.exe') if os.name == 'nt' else shutil.which('bash')
    result = subprocess.run([bash, '-e', '-c', selection['run']], cwd=tmp_path,
        env={**os.environ, 'RELEASE': release if release_exists else 'f' * 40}, capture_output=True, text=True)
    assert (result.returncode == 0) == release_exists
    assert git('rev-parse', 'HEAD') == (release if release_exists else newer_main)
    assert (tmp_path / 'journey.txt').read_text() == ('selected' if release_exists else 'newer-main')
