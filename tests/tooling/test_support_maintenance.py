from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from tabula_rasa.deployment import support_maintenance as maintenance


def environment(stage='staging', operation='upgrade'):
    service, origin = maintenance.SERVICES[stage]
    return {'GITHUB_REPOSITORY': 'Roklion/Project_Tabula_Rasa', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_SHA': 'a' * 40, 'TABULA_RASA_RELEASE_ID': 'a' * 40,
            'TABULA_RASA_ENVIRONMENT': stage, 'TABULA_RASA_PUBLIC_ORIGIN': origin,
            'RENDER_SERVICE_ID': service, 'TABULA_RASA_ACCESS_MODE': 'named_user',
            'TABULA_RASA_DEPLOY_DATABASE_SHA256': 'b' * 64,
            'IMAGE': 'ghcr.io/roklion/project_tabula_rasa/commercial@sha256:' + 'c' * 64,
            'MAINTENANCE_OPERATION': operation, 'MAINTENANCE_APPROVAL': '0014_to_0015',
            'MAINTENANCE_RECOVERY_SHA256': 'd' * 64, 'RENDER_API_KEY': 'synthetic'}


@pytest.mark.parametrize('stage', maintenance.SERVICES)
def test_inspection_is_read_only_and_upgrade_is_confirmed(stage, monkeypatch):
    database, upgrade = Mock(), Mock()
    monkeypatch.setattr(maintenance, 'open_alpha_database', Mock(return_value=database))
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)
    monkeypatch.setattr(maintenance, 'upgrade', upgrade)
    database.health.return_value = {'connected': True, 'revision': maintenance.SOURCE}
    env = environment(stage, 'inspect')
    env.pop('MAINTENANCE_RECOVERY_SHA256')
    env['MAINTENANCE_APPROVAL'] = 'not_approved'
    assert maintenance.execute(env)['schema'] == maintenance.SOURCE
    upgrade.assert_not_called()
    database.dispose.assert_called_once()
    database.reset_mock()
    database.health.side_effect = [{'connected': True, 'revision': maintenance.SOURCE},
                                   {'connected': True, 'revision': maintenance.TARGET}]
    assert maintenance.execute(environment(stage))['status'] == 'schema_upgraded'
    upgrade.assert_called_once_with(database)
    database.dispose.assert_called_once()


@pytest.mark.parametrize('change', [
    {'TABULA_RASA_ENVIRONMENT': 'production'}, {'GITHUB_REF': 'refs/heads/unreviewed'},
    {'GITHUB_REPOSITORY': 'other/repo'}, {'RENDER_SERVICE_ID': maintenance.SERVICES['development'][0]},
    {'TABULA_RASA_PUBLIC_ORIGIN': maintenance.SERVICES['development'][1]},
    {'TABULA_RASA_ACCESS_MODE': 'restricted_alpha'}, {'GITHUB_SHA': 'invalid'},
    {'MAINTENANCE_APPROVAL': 'not_approved'}, {'MAINTENANCE_RECOVERY_SHA256': '0' * 64},
    {'IMAGE': 'ghcr.io/roklion/project_tabula_rasa/commercial:latest'},
    {'TABULA_RASA_DEPLOY_DATABASE_SHA256': ''}, {'MAINTENANCE_OPERATION': 'restore'},
])
def test_unapproved_scope_stops_before_io(change, monkeypatch):
    bound, metadata = Mock(), Mock()
    monkeypatch.setattr(maintenance, 'open_alpha_database', bound)
    env = {**environment(), **change}
    with pytest.raises(ValueError):
        maintenance.preflight(env, metadata=metadata)
    with pytest.raises(ValueError):
        maintenance.execute(env)
    metadata.assert_not_called()
    bound.assert_not_called()


@pytest.mark.parametrize('stage', maintenance.SERVICES)
def test_preflight_checks_tested_exact_image_and_paused_service(stage):
    env = environment(stage)
    read = Mock(side_effect=[{'id': env['RENDER_SERVICE_ID'], 'suspended': 'suspended'},
                            [{'deploy': {'status': 'live'}}]])
    verify = Mock()
    metadata = Mock(return_value={'release': env['GITHUB_SHA'], 'schema': maintenance.TARGET})
    assert maintenance.preflight(env, read=read, verify=verify, metadata=metadata)['operation'] == 'upgrade'
    verify.assert_called_once_with(env['GITHUB_SHA'], env)
    assert all(not call.kwargs for call in read.call_args_list)


def test_inspection_does_not_require_a_paused_service_or_recovery_attestation():
    env = environment('development', 'inspect')
    env['TABULA_RASA_ACCESS_MODE'] = 'restricted_alpha'
    env['MAINTENANCE_APPROVAL'] = 'not_approved'
    env.pop('MAINTENANCE_RECOVERY_SHA256')
    read = Mock(return_value={'id': env['RENDER_SERVICE_ID'], 'suspended': 'not_suspended'})
    result = maintenance.preflight(
        env, read=read, verify=Mock(),
        metadata=lambda *_: {'release': env['GITHUB_SHA'], 'schema': maintenance.TARGET})
    assert result['operation'] == 'inspect'
    assert read.call_count == 1


@pytest.mark.parametrize('state', ['not_suspended', 'suspended_with_pending'])
def test_upgrade_refuses_running_service_or_pending_deployment(state):
    env = environment()
    read = Mock(side_effect=[{'id': env['RENDER_SERVICE_ID'],
                             'suspended': 'suspended' if state.endswith('pending') else state},
                            [{'deploy': {'status': 'queued'}}]])
    with pytest.raises(ValueError):
        maintenance.preflight(env, read=read, verify=Mock(),
                              metadata=lambda *_: {'release': env['GITHUB_SHA'], 'schema': maintenance.TARGET})


@pytest.mark.parametrize('candidate', [{'release': 'e' * 40, 'schema': maintenance.TARGET},
                                     {'release': 'a' * 40, 'schema': maintenance.SOURCE}])
def test_wrong_candidate_stops_before_provider(candidate):
    read = Mock()
    with pytest.raises(ValueError):
        maintenance.preflight(environment(), read=read, verify=Mock(), metadata=lambda *_: candidate)
    read.assert_not_called()


@pytest.mark.parametrize('revision', [None, 'unexpected', maintenance.TARGET])
def test_upgrade_never_retries_wrong_or_already_upgraded_source(revision, monkeypatch):
    database, upgrade = Mock(), Mock()
    database.health.return_value = {'connected': True, 'revision': revision}
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)
    monkeypatch.setattr(maintenance, 'open_alpha_database', lambda _: database)
    monkeypatch.setattr(maintenance, 'upgrade', upgrade)
    with pytest.raises(ValueError):
        maintenance.execute(environment())
    upgrade.assert_not_called()
    database.dispose.assert_called_once()


def test_wrong_runtime_image_stops_before_database_access(monkeypatch):
    bound = Mock()
    monkeypatch.setattr(maintenance, 'open_alpha_database', bound)
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.SOURCE)
    with pytest.raises(ValueError):
        maintenance.execute(environment())
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)
    with pytest.raises(ValueError):
        maintenance.execute({**environment(), 'TABULA_RASA_RELEASE_ID': 'e' * 40})
    bound.assert_not_called()


def test_upgrade_health_is_not_assumed_after_forward_migration(monkeypatch):
    database, upgrade = Mock(), Mock()
    database.health.side_effect = [{'connected': True, 'revision': maintenance.SOURCE},
                                   {'connected': False, 'revision': None}]
    monkeypatch.setattr(maintenance, 'open_alpha_database', lambda _: database)
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)
    monkeypatch.setattr(maintenance, 'upgrade', upgrade)
    with pytest.raises(ValueError, match='unconfirmed'):
        maintenance.execute(environment())
    upgrade.assert_called_once_with(database)
    database.dispose.assert_called_once()


def test_failed_upgrade_disposes_and_cli_suppresses_private_error(monkeypatch, capsys):
    database = Mock()
    database.health.return_value = {'connected': True, 'revision': maintenance.SOURCE}
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)
    monkeypatch.setattr(maintenance, 'open_alpha_database', lambda _: database)
    monkeypatch.setattr(maintenance, 'upgrade', Mock(side_effect=RuntimeError('private-canary')))
    with pytest.raises(RuntimeError):
        maintenance.execute(environment())
    database.dispose.assert_called_once()
    monkeypatch.setattr('sys.argv', ['maintenance', 'execute'])
    monkeypatch.setattr(maintenance, 'execute', Mock(side_effect=RuntimeError('private-canary')))
    with pytest.raises(SystemExit) as error:
        maintenance.main()
    assert 'private-canary' not in str(error.value) + capsys.readouterr().out


def test_workflow_defaults_to_inspect_and_keeps_provider_credentials_out_of_database_container():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / '.github/workflows/commercial-support-maintenance.yml').read_text())
    triggers = workflow.get('on', workflow.get(True))
    assert list(triggers) == ['workflow_dispatch']
    assert triggers['workflow_dispatch']['inputs']['operation']['default'] == 'inspect'
    job = workflow['jobs']['maintenance']
    assert "github.ref == 'refs/heads/main'" in job['if']
    assert job['environment'] == '${{ inputs.environment }}'
    assert job['concurrency'] == {'group': 'commercial-deploy-${{ inputs.environment }}',
                                  'cancel-in-progress': False}
    assert job['steps'][0]['with']['ref'] == '${{ github.sha }}'
    preflight, execute = job['steps'][-2:]
    assert 'TABULA_RASA_DATABASE_URL' not in preflight['env']
    assert set(execute['env']) == {'TABULA_RASA_DATABASE_URL'}
    assert '-e RENDER_API_KEY' not in execute['run'] and '-e GH_TOKEN' not in execute['run']
    assert '--read-only' in execute['run']
