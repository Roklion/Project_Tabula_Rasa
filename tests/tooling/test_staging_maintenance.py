from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from tabula_rasa.deployment import staging_maintenance as maintenance


@pytest.fixture(autouse=True)
def reviewed_image_head(monkeypatch):
    # The bridge executes inside its retained immutable 0014 image.
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)


def environment():
    return {**maintenance.SCOPE, 'MAINTENANCE_RECOVERY_SHA256': '1' * 64,
            'TABULA_RASA_RELEASE_ID': maintenance.RELEASE, 'RENDER_API_KEY': 'synthetic-private',
            'GH_TOKEN': 'synthetic-private'}


def provider(*, paused=True, pending=None):
    return Mock(side_effect=[{'id': maintenance.SCOPE['RENDER_SERVICE_ID'],
                              'suspended': 'suspended' if paused else 'not_suspended'},
                             [{'deploy': {'status': pending or 'live'}}]])


def test_preflight_requires_exact_tested_release_paused_service_and_no_deployments():
    read, verify = provider(), Mock()
    metadata = Mock(return_value={'release': maintenance.RELEASE, 'schema': maintenance.TARGET})
    env = environment()
    result = maintenance.preflight(env, metadata=metadata, verify=verify, read=read)
    assert result['status'] == 'preflight_passed'
    verify.assert_called_once_with(maintenance.RELEASE, env)
    assert all(not call.kwargs for call in read.call_args_list)  # GET only; never suspend/deploy here.


@pytest.mark.parametrize('key', maintenance.SCOPE)
def test_scope_changes_fail_before_provider_or_database_access(key, monkeypatch):
    env = environment()
    env[key] = 'unapproved'
    database, read, metadata, verify = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(maintenance, 'open_alpha_database', database)
    for operation in (lambda: maintenance.preflight(env, read=read, metadata=metadata, verify=verify),
                      lambda: maintenance.migrate(env)):
        with pytest.raises(ValueError):
            operation()
    assert not any(mock.mock_calls for mock in (database, read, metadata, verify))


@pytest.mark.parametrize('checkpoint', ['', None, '0' * 64, '1' * 63, 'A' * 64, '1' * 64 + '\n'])
def test_invalid_recovery_record_is_refused(checkpoint):
    with pytest.raises(ValueError):
        maintenance.validate_scope({**environment(), 'MAINTENANCE_RECOVERY_SHA256': checkpoint})


@pytest.mark.parametrize('changes', [{'release': 'a' * 40}, {'schema': maintenance.SOURCE}])
def test_wrong_candidate_is_refused_before_render_access(changes):
    metadata = Mock(return_value={'release': maintenance.RELEASE, 'schema': maintenance.TARGET, **changes})
    read = Mock()
    with pytest.raises(ValueError):
        maintenance.preflight(environment(), metadata=metadata, read=read, verify=Mock())
    read.assert_not_called()


@pytest.mark.parametrize('pending', ['created', 'queued', 'build_in_progress', 'update_in_progress', 'pre_deploy_in_progress'])
def test_in_progress_deployment_stops_the_maintenance_window(pending):
    with pytest.raises(ValueError):
        maintenance.preflight(environment(), read=provider(pending=pending), verify=Mock(),
                              metadata=lambda *args: {'release': maintenance.RELEASE, 'schema': maintenance.TARGET})


def test_active_service_is_never_implicitly_paused():
    read = provider(paused=False)
    with pytest.raises(ValueError):
        maintenance.preflight(environment(), read=read, verify=Mock(),
                              metadata=lambda *args: {'release': maintenance.RELEASE, 'schema': maintenance.TARGET})
    assert read.call_count == 1


def test_migration_reuses_bound_database_and_canonical_upgrade_and_disposes(monkeypatch):
    database = Mock()
    database.health.side_effect = [{'connected': True, 'revision': maintenance.SOURCE},
                                   {'connected': True, 'revision': maintenance.TARGET}]
    bound, upgrade = Mock(return_value=database), Mock()
    monkeypatch.setattr(maintenance, 'open_alpha_database', bound)
    monkeypatch.setattr(maintenance, 'upgrade', upgrade)
    assert maintenance.migrate(environment())['status'] == 'schema_upgraded'
    upgrade.assert_called_once_with(database)
    database.dispose.assert_called_once()


@pytest.mark.parametrize('revision', [None, 'unknown', maintenance.TARGET])
def test_wrong_or_already_upgraded_source_is_not_retried(revision, monkeypatch):
    database, upgrade = Mock(), Mock()
    database.health.return_value = {'connected': True, 'revision': revision}
    monkeypatch.setattr(maintenance, 'open_alpha_database', Mock(return_value=database))
    monkeypatch.setattr(maintenance, 'upgrade', upgrade)
    with pytest.raises(ValueError):
        maintenance.migrate(environment())
    upgrade.assert_not_called()
    database.dispose.assert_called_once()


def test_wrong_image_release_or_migration_head_stops_before_connecting(monkeypatch):
    bound = Mock()
    monkeypatch.setattr(maintenance, 'open_alpha_database', bound)
    with pytest.raises(ValueError):
        maintenance.migrate({**environment(), 'TABULA_RASA_RELEASE_ID': 'a' * 40})
    monkeypatch.setattr(maintenance, 'head_revision', lambda: 'future_schema')
    with pytest.raises(ValueError):
        maintenance.migrate(environment())
    bound.assert_not_called()


def test_cli_does_not_echo_credentials_on_failure(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['maintenance', 'upgrade'])
    monkeypatch.setattr(maintenance, 'migrate', Mock(side_effect=ValueError('synthetic-never-echo')))
    with pytest.raises(SystemExit) as error:
        maintenance.main()
    assert 'synthetic-never-echo' not in str(error.value) + capsys.readouterr().out


def test_workflow_is_manual_main_only_and_keeps_credentials_separate():
    root = Path(__file__).resolve().parents[2]
    path = root / '.github/workflows/commercial-staging-maintenance.yml'
    workflow = yaml.safe_load(path.read_text())
    triggers = workflow.get('on', workflow.get(True))
    assert list(triggers) == ['workflow_dispatch']
    job = workflow['jobs']['migrate']
    assert job['environment'] == 'staging'
    assert "github.ref == 'refs/heads/main'" in job['if']
    assert "vars.COMMERCIAL_DEPLOY_ENABLED == 'true'" in job['if']
    assert job['steps'][0]['with']['ref'] == '${{ github.sha }}'
    assert job['concurrency'] == {'group': 'commercial-deploy-staging', 'cancel-in-progress': False}
    assert job['env']['IMAGE'] == maintenance.IMAGE
    preflight, upgrade = job['steps'][-2:]
    assert 'TABULA_RASA_DATABASE_URL' not in preflight['env']
    assert 'RENDER_API_KEY' not in upgrade['env'] and 'GH_TOKEN' not in upgrade['env']
    assert upgrade['env']['TABULA_RASA_DATABASE_URL'] == '${{ secrets.TABULA_RASA_MIGRATION_DATABASE_URL }}'
    assert '-e RENDER_API_KEY' not in upgrade['run'] and '-e GH_TOKEN' not in upgrade['run']
    assert '--read-only' in upgrade['run'] and '/maintenance/run.py upgrade' in upgrade['run']
    assert 'restore' not in upgrade['run'] and 'seed' not in upgrade['run']
