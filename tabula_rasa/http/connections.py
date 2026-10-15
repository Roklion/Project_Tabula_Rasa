"""Authorized provider composition; existing Drive adapters own byte behavior."""
from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.postgres.connections import PostgresConnections


class TenantConnections:
    def __init__(self, database, environment, secrets, *, store_factory=None):
        self.repository = PostgresConnections(database)
        self.environment, self.secrets = environment, secrets
        self.store_factory = store_factory or google_store

    def _store(self, row, *, validate=False):
        if self.secrets is None:
            raise IdentityError('unavailable')
        payload = self.secrets.get(row['secret_ref'], environment=self.environment,
            organization_id=row['organization_id'], entity_id=row['entity_id'], provider=row['provider'])
        if (payload.get('profile_key') != row['profile_key']
                or payload.get('scope_key') != row['store_scope_key']):
            raise IdentityError('unavailable')
        try:
            store = self.store_factory(row, payload, validate=validate)
        except Exception:
            pass
        else:
            if store.scope_key == row['store_scope_key']:
                return store
        raise IdentityError('unavailable')

    def document_store(self, context):
        row = self.repository.grant(context, require_connected=False)
        return None if row is None else AuthorizedDocumentStore(self, context, row['store_scope_key'])

    def change(self, context, session, *, revision, connect):
        return self.repository.change(context, authenticated_at=session.authenticated_at,
            expected_revision=revision, connect=connect, validate=lambda row: self._store(row, validate=True))


def google_store(row, payload, *, validate=False):
    from tabula_rasa.google_drive import DRIVE_SCOPE, GoogleDriveClient, load_oauth_config, validate_drive_profile_settings
    from tabula_rasa.infrastructure.drive_composition import create_drive_document_store
    from tabula_rasa.infrastructure.entity_documents import EntityDocumentStore

    config = load_oauth_config(payload)
    grant = validate_drive_profile_settings(payload.get('google_drive'))
    if (grant['scopes'] != row['required_scopes'] or grant['scopes'] != [DRIVE_SCOPE]
            or grant.get('receipt_folder', {}).get('id') != row['store_scope_key']):
        raise IdentityError('unavailable')
    # Connection activation validates managed folder/profile ownership freshly.
    # Ordinary document calls retain the existing adapter's scoped validation.
    if validate:
        GoogleDriveClient(config, grant).validate_storage_configuration(row['profile_key'])
    store = create_drive_document_store(row['profile_key'], {'google_drive': grant}, payload)
    return EntityDocumentStore(row['entity_id'], row['profile_key'], store)


class AuthorizedDocumentStore:
    """Resolve fresh connection/membership before each byte operation, no grant cache."""
    def __init__(self, manager, context, scope_key):
        self.manager, self.context, self.scope_key = manager, context, scope_key

    def _call(self, method, entity_id, *args, **kwargs):
        from tabula_rasa.google_drive.errors import GoogleDriveAuthorizationError
        if entity_id != self.context.entity_id:
            raise IdentityError('forbidden')
        row = self.manager.repository.grant(self.context, action='write' if method in {'upload', 'delete'} else 'read')
        if row is None or row['store_scope_key'] != self.scope_key:
            raise IdentityError('unavailable')
        reconnect = False
        try:
            return getattr(self.manager._store(row), method)(entity_id, *args, **kwargs)
        except Exception as error:
            # Existing Drive facade wraps authorization failures in DocumentError.
            reconnect = isinstance(error, GoogleDriveAuthorizationError) or isinstance(error.__cause__, GoogleDriveAuthorizationError)
        if reconnect:
            self.manager.repository.require_reconnect(row)
        raise IdentityError('unavailable')

    def upload(self, entity_id, upload):
        return self._call('upload', entity_id, upload)

    def inventory(self, entity_id, *, fresh=False):
        return self._call('inventory', entity_id, fresh=fresh)

    def metadata(self, entity_id, storage_key):
        return self._call('metadata', entity_id, storage_key)

    def fetch(self, entity_id, storage_key):
        return self._call('fetch', entity_id, storage_key)

    def delete(self, entity_id, storage_key):
        return self._call('delete', entity_id, storage_key)
