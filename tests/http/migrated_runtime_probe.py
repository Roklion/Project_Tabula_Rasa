"""Synthetic migrated startup probe for the minimal production image."""

import importlib.abc
import sys
from unittest.mock import MagicMock, Mock, call, patch


class NoLegacyRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'gspread', 'streamlit'} or fullname == 'tabula_rasa.storage':
            raise ModuleNotFoundError('Legacy runtime is unavailable in the production image.')


def main():
    sys.meta_path.insert(0, NoLegacyRuntime())
    from sqlalchemy.engine import make_url
    from tabula_rasa.application.identity import IdentityError
    from tabula_rasa.http.migrated import MigratedProfileServices
    from tabula_rasa.infrastructure.postgres.cutover import CutoverError, database_identity
    from tabula_rasa.migration.model import digest

    database = MagicMock()
    database.engine.url = make_url('postgresql+psycopg://runtime@localhost/synthetic')
    claims = {profile: {'organization_id': 'org-' + profile, 'profile_key': profile}
              for profile in ('alpha', 'beta')}
    cutovers = {profile: dict(source_profile_key=profile, source_workbook_key='workbook-' + profile,
        state='postgres', activation_mode='rehearsal', divergent=False, run_id='run-' + profile,
        acceptance_sha256='a' * 64, accepted_export_sha256='b' * 64, source_snapshot_sha256='c' * 64,
        evidence={'database_sha256': database_identity(database), 'document_scope_sha256': digest('folder-' + profile)})
        for profile in claims}

    def execute(statement, parameters):
        rows = claims if 'legacy_entity_claims' in str(statement) else cutovers
        scope = parameters.get('entity', parameters.get('scope'))
        result = Mock()
        result.mappings.return_value.first.return_value = rows[scope]
        return result

    database.transaction.return_value.__enter__.return_value.execute.side_effect = execute
    connections = Mock()
    config = {'business_profiles': {profile: {'name': profile, 'spreadsheet_id': 'workbook-' + profile,
        'google_drive': {'receipt_folder': {'id': 'folder-' + profile}}} for profile in claims},
        'bookkeeping_backends': {profile: {'backend': 'postgres', 'entity_id': profile, 'mode': 'rehearsal'}
                                for profile in claims}}
    services = MigratedProfileServices(database, entity_profiles={profile: profile for profile in claims},
                                       secrets=config, connections=connections)
    services.validate()
    assert connections.validate_migrated_binding.call_args_list == [call(
        organization_id='org-' + profile, entity_id=profile, profile_key=profile, scope_key='folder-' + profile)
        for profile in claims]
    try:
        services._named_binding('alpha', 'org-beta')
    except IdentityError:
        pass
    else:
        raise AssertionError('Cross-owner binding was accepted.')
    config['business_profiles']['alpha']['google_drive']['receipt_folder']['id'] = 'folder-beta'
    try:
        services.validate()
    except CutoverError:
        pass
    else:
        raise AssertionError('Another profile receipt folder was accepted.')
    assert services._named_binding('beta', 'org-beta') == ('org-beta', 'beta', 'folder-beta')
    cutovers['beta']['state'] = 'prepared'
    try:
        services._named_binding('beta', 'org-beta')
    except CutoverError:
        pass
    else:
        raise AssertionError('An inactive authority was accepted.')
    assert not {'streamlit', 'gspread', 'tabula_rasa.storage'}.intersection(sys.modules)
    probe_maps_quota_startup()


def probe_maps_quota_startup():
    """Exercise HTTP lifespan and both composition paths using synthetic providers."""
    import asyncio
    import json

    from tabula_rasa.google_maps_quota_core import GoogleMapsQuotaMonitoringConfig
    from tabula_rasa.http.app import create_app
    from tabula_rasa.http.composition import open_migrated_runtime, open_runtime
    from tabula_rasa.http.config import HttpSettings
    from tabula_rasa.http.context import DenyContext
    from tabula_rasa.infrastructure.postgres.migrations import head_revision

    settings = HttpSettings('test', 'http://testserver')
    credential = dict(type='service_account', client_email='synthetic@example.test',
                      private_key='synthetic-key', token_uri='https://oauth2.googleapis.com/token')
    mapping = {'google_maps': {'quota_monitoring': {'project_number': '123456789', 'service_account': credential}}}
    database = MagicMock()
    database.health.return_value = {'connected': True, 'revision': head_revision()}
    response = Mock(status_code=200)
    response.json.return_value = {}
    session = Mock()
    session.get.return_value = response

    async def start(factory):
        app = create_app(settings=settings, runtime_factory=factory)
        async with app.router.lifespan_context(app):
            quota = app.state.runtime.maps_quota
            assert quota.status().status == 'not_loaded'
            assert quota._client is None
            assert quota.load().status == 'ready'
            assert [group.title for group in quota.load().services] == ['Routes API', 'Places API (New)']

    with patch('tabula_rasa.http.maps_quota.Path') as secret_file:
        secret_file.return_value.read_text.return_value = json.dumps(credential)
        environment = {'TABULA_RASA_MAPS_QUOTA_PROJECT_NUMBER': '123456789',
                       'TABULA_RASA_MAPS_QUOTA_SERVICE_ACCOUNT_FILE': '/synthetic/quota.json'}
        with patch.dict('os.environ', environment, clear=True), \
                patch('tabula_rasa.http.composition.Database', return_value=database), \
                patch('tabula_rasa.http.composition.DatabaseSettings.from_environment'), \
                patch('tabula_rasa.http.migrated.MigratedProfileServices.validate'), \
                patch.object(GoogleMapsQuotaMonitoringConfig, 'credentials', return_value=Mock()), \
                patch('tabula_rasa.google_maps_quota_core.AuthorizedSession', return_value=session):
            asyncio.run(start(open_runtime))
            with patch('tabula_rasa.http.migrated_configuration.load_migrated_bindings',
                       return_value=({'alpha': 'alpha'}, {})):
                asyncio.run(start(open_runtime))
            asyncio.run(start(lambda configured: open_migrated_runtime(configured,
                resolve_context=DenyContext(), entity_profiles={'alpha': 'alpha'}, profile_secrets=mapping)))
    assert session.close.call_count == 3
    assert not {'streamlit', 'gspread', 'tabula_rasa.storage'}.intersection(sys.modules)


if __name__ == '__main__':
    main()
