"""Operator installation of a managed store, independent of Google grant custody."""
import re

from sqlalchemy import text

from tabula_rasa.application.documents import DocumentValidationError


def install_managed_connection(connection, entity_id, scope_key, *, organization_id, profile_key,
                               secret_ref, expected_revision, source_revision=None, source_scope=None,
                               recovery_source_scope=None):
    """Called in the same transaction as all location promotions (or empty setup).

    Existing Drive rows/grants are retained. A managed candidate must not rebind
    an existing bucket/entity connection. Rotation replaces only the secret ref.
    Live execution requires an exact operator-approved private plan.
    """
    if (not re.fullmatch('[0-9a-f]{32}', secret_ref)
            or not re.fullmatch('[a-z][a-z0-9_-]{0,47}', profile_key)):
        raise DocumentValidationError('Invalid managed receipt connection.')
    owner = connection.scalar(text('''SELECT entity_id FROM organization_entities
        WHERE entity_id=:entity AND organization_id=:org AND state='active' '''),
        {'entity': entity_id, 'org': organization_id})
    if owner is None:
        raise DocumentValidationError('The receipt connection belongs to a different organization.')
    if source_revision is not None:
        source = connection.execute(text("""SELECT * FROM external_connections
            WHERE entity_id=:entity AND provider='google_drive' FOR UPDATE"""), {'entity': entity_id}).mappings().first()
        if (source is None or source['organization_id'] != organization_id or source['revision'] != source_revision
                or source['store_scope_key'] != source_scope or source['status'] != 'connected'):
            raise DocumentValidationError('Source receipt connection changed during copy. Freeze writers and restart.')
    row = connection.execute(text("""SELECT * FROM external_connections
        WHERE entity_id=:entity AND provider='s3' FOR UPDATE"""), {'entity': entity_id}).mappings().first()
    if ((row['revision'] if row else 0) != expected_revision
            or row and (row['organization_id'] != organization_id or row['profile_key'] != profile_key
                        or row['store_scope_key'] not in {scope_key, recovery_source_scope})):
        raise DocumentValidationError('Managed receipt connection changed. Inspect the exact binding.')
    if connection.scalar(text('''SELECT EXISTS (SELECT 1 FROM documents WHERE entity_id=:entity
        AND (store_kind<>'s3' OR store_scope_key<>:scope))'''), {'entity': entity_id, 'scope': scope_key}):
        raise DocumentValidationError('Copy and verify all retained receipt locations before managed activation.')
    connection.execute(text("""INSERT INTO external_connections
        (entity_id,organization_id,provider,secret_ref,profile_key,store_scope_key,required_scopes,status)
        VALUES (:entity,:org,'s3',:secret,:profile,:scope,'[]','connected')
        ON CONFLICT (entity_id,provider) DO UPDATE SET secret_ref=EXCLUDED.secret_ref,
        store_scope_key=EXCLUDED.store_scope_key,
        status='connected',revision=external_connections.revision+1,updated_at=CURRENT_TIMESTAMP"""),
        {'entity': entity_id, 'org': organization_id, 'secret': secret_ref, 'profile': profile_key, 'scope': scope_key})
