import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.http import composition
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.migrated_configuration import FILE_ENV, load_migrated_bindings


SETTINGS = HttpSettings('production', 'https://owner.example.test', access_mode='named_user')


def rows():
    return [{'entity_id': 'entity-' + profile, 'profile_key': profile,
             'spreadsheet_id': 'workbook-' + profile, 'receipt_folder_id': 'folder-' + profile,
             'mode': 'rehearsal'} for profile in ('alpha', 'beta')]


def write(tmp_path, payload):
    path = tmp_path / 'bindings.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


def test_explicit_bindings_preserve_two_profile_source_and_document_scopes(tmp_path):
    from tabula_rasa.business_profiles import select_profile_secrets
    entities, secrets = load_migrated_bindings(SETTINGS, {FILE_ENV: write(tmp_path, {'profiles': rows()})})
    assert entities == {'entity-alpha': 'alpha', 'entity-beta': 'beta'}
    for row in rows():
        selected = select_profile_secrets(secrets, row['profile_key'])
        assert selected['spreadsheet_id'] == row['spreadsheet_id']
        assert selected['google_drive']['receipt_folder']['id'] == row['receipt_folder_id']
        assert secrets['bookkeeping_backends'][row['profile_key']] == {
            'backend': 'postgres', 'entity_id': row['entity_id'], 'mode': 'rehearsal'}
    assert load_migrated_bindings(SETTINGS, {}) is None


@pytest.mark.parametrize('failure', ['missing', 'empty', 'json', 'unknown', 'duplicate_entity',
                                    'duplicate_profile', 'mode', 'source', 'folder', 'fixture'])
def test_invalid_config_never_falls_back_or_exposes_private_values(tmp_path, failure):
    values = rows()
    payload = {'profiles': values}
    settings = SETTINGS
    if failure == 'unknown':
        payload['private-secret-sentinel'] = 'private-value'
    elif failure == 'duplicate_entity':
        values[1]['entity_id'] = values[0]['entity_id']
    elif failure == 'duplicate_profile':
        values[1]['profile_key'] = values[0]['profile_key']
    elif failure == 'mode':
        values[0]['mode'] = 'sheets'
    elif failure == 'source':
        values[0]['spreadsheet_id'] = ''
    elif failure == 'folder':
        values[0]['receipt_folder_id'] = ''
    elif failure == 'fixture':
        settings = HttpSettings('test', 'http://testserver', trusted_entity_id='alpha-synthetic')
    path = write(tmp_path, payload)
    if failure == 'missing':
        path += '-private-missing'
    elif failure == 'empty':
        path = ''
    elif failure == 'json':
        (tmp_path / 'bindings.json').write_text('private-secret-sentinel', encoding='utf-8')
    with pytest.raises(RuntimeError, match='Invalid migrated runtime configuration') as caught:
        load_migrated_bindings(settings, {FILE_ENV: path})
    assert caught.value.__context__ is None
    assert 'private' not in str(caught.value)


@pytest.mark.parametrize('failure', [None, 'binding', 'schema'])
def test_container_runtime_uses_existing_named_binding_and_disables_bootstrap(tmp_path, monkeypatch, failure):
    from tabula_rasa.http.identity import NamedIdentity
    from tabula_rasa.infrastructure.postgres.migrations import head_revision
    monkeypatch.setenv(FILE_ENV, write(tmp_path, {'profiles': rows()}))
    monkeypatch.delenv('TABULA_RASA_ALPHA_DOCUMENTS_FILE', raising=False)
    database = Mock()
    database.health.return_value = {'connected': True, 'revision': 'old' if failure == 'schema' else head_revision()}
    monkeypatch.setattr(composition, 'Database', Mock(return_value=database))
    monkeypatch.setattr(composition.DatabaseSettings, 'from_environment', Mock())
    monkeypatch.setattr('tabula_rasa.infrastructure.oidc.OidcSettings.from_environment',
                        Mock(return_value=SimpleNamespace(configuration_hash='a' * 64)))
    provider = Mock()
    monkeypatch.setattr('tabula_rasa.infrastructure.oidc.OidcProvider', Mock(return_value=provider))
    sessions = Mock()
    sessions.database = database
    monkeypatch.setattr('tabula_rasa.infrastructure.postgres.sessions.PostgresSessionRepository',
                        Mock(return_value=sessions))
    scoped = {row['entity_id']: object() for row in rows()}
    services = Mock(side_effect=lambda context: scoped[context.entity_id])
    services.validate.side_effect = ValueError('private-provider-sentinel') if failure == 'binding' else None
    factory = Mock(return_value=services)
    monkeypatch.setattr('tabula_rasa.http.migrated.MigratedProfileServices', factory)
    native = Mock()
    monkeypatch.setattr(composition, 'create_postgres_services', native)
    if failure:
        with pytest.raises(RuntimeError, match='HTTP runtime startup failed') as caught:
            composition.open_runtime(SETTINGS)
        assert caught.value.__context__ is None
        assert 'private' not in str(caught.value)
        database.dispose.assert_called_once()
        provider.close.assert_called_once()
    else:
        runtime = composition.open_runtime(SETTINGS)
        assert isinstance(runtime.resolve_context, NamedIdentity)
        assert runtime.resolve_context.sessions is sessions
        sessions.configure.assert_called_once()
        services.validate.assert_called_once()
        assert factory.call_args.kwargs['connections'] is runtime.connections
        for entity in scoped:
            assert runtime.services(SimpleNamespace(entity_id=entity)) is scoped[entity]
        with pytest.raises(Exception, match='forbidden'):
            runtime.workspaces.bootstrap(SimpleNamespace(user_id='owner'), 'request', 'Org', 'Entity')
        runtime.close()
        database.dispose.assert_called_once()
    native.assert_not_called()
