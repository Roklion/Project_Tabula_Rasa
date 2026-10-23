"""Synthetic migrated startup probe for the minimal production image."""

import importlib.abc
import sys
from unittest.mock import MagicMock, Mock, call


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


if __name__ == '__main__':
    main()
