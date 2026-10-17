"""Drive-first operator orchestration over shared archive/copy/SQL owners."""
from dataclasses import asdict
from pathlib import Path
import re

from sqlalchemy import text

from tabula_rasa.application.document_recovery import copy_entity_documents, verify_entity_documents
from tabula_rasa.application.documents import DocumentValidationError
from tabula_rasa.http.connections import google_store
from tabula_rasa.google_drive import DRIVE_SCOPE
from tabula_rasa.infrastructure.document_archive import DocumentArchive, archive_documents
from tabula_rasa.infrastructure.postgres.composition import create_postgres_export_service
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.infrastructure.postgres.identity import database_identity
from tabula_rasa.infrastructure.postgres.repository import serialized
from tabula_rasa.migration.model import digest


def _same_recovery_point(expected, current, *, promoted):
    if not promoted:
        return expected['manifest']['content_sha256'] == current['manifest']['content_sha256']
    original, restored = expected['domains'], current['domains']
    if any(original[name] != restored[name] for name in original if name != 'documents'):
        return False
    moved_fields = {'store_kind', 'store_scope_key', 'storage_key', 'open_url', 'updated_at', 'version'}
    def stable(rows):
        return [{key: value for key, value in row.items() if key not in moved_fields} for row in rows]
    return stable(original['documents']) == stable(restored['documents'])


def execute_drive(database, secrets, payload, *, operation, environment, revision=0, apply=False,
                  expected_plan=None, approval_sha256=None, archive_path=None,
                  source_database_sha256=None, target_database_sha256=None, progress=None):
    if (environment not in {'staging', 'production'} or payload.get('environment') != environment
            or set(payload) != {'environment', 'provider', 'organization_id', 'entity_id', 'profile_key',
                               'scope_key', 'google_drive_oauth', 'google_drive'}
            or payload['provider'] != 'google_drive' or operation not in {'backup', 'verify', 'verify-archive', 'restore'}
            or operation != 'verify' and archive_path is None):
        raise DocumentValidationError('Invalid Drive recovery operation or private binding.')
    entity = payload['entity_id']
    fingerprint = database_identity(database)
    archive = DocumentArchive(archive_path, entity) if operation in {'restore', 'verify-archive'} else None
    if archive is not None and archive.store_kind != 'google_drive':
        raise DocumentValidationError('Drive recovery requires a Drive-backed canonical archive.')
    if operation == 'restore' and (
            environment != 'staging' or not re.fullmatch('[0-9a-f]{64}', source_database_sha256 or '')
            or target_database_sha256 != fingerprint or source_database_sha256 == fingerprint):
        raise DocumentValidationError('Restore requires an isolated staging database and explicit source/target fingerprints.')
    current = create_postgres_export_service(database, entity).export()
    with database.transaction(read_only=True) as connection:
        row = connection.execute(text("""SELECT * FROM external_connections
            WHERE entity_id=:entity AND provider='google_drive'"""), {'entity': entity}).mappings().first()
        managed = connection.scalar(text("SELECT EXISTS(SELECT 1 FROM external_connections WHERE entity_id=:entity AND provider='s3')"),
                                    {'entity': entity})
    if (managed or row is None or row['organization_id'] != payload['organization_id']
            or row['profile_key'] != payload['profile_key']):
        raise DocumentValidationError('The selected entity requires its exact Drive connection ownership.')
    already_restored = operation == 'restore' and row['store_scope_key'] == payload['scope_key']
    if operation == 'restore' and not already_restored and row['revision'] != revision:
        raise DocumentValidationError('The Drive connection revision changed. Inspect and re-plan recovery.')
    if operation != 'restore' and (row['store_scope_key'] != payload['scope_key']
            or operation != 'verify-archive' and row['status'] != 'connected'):
        raise DocumentValidationError('The source Drive connection is unavailable or differently bound.')
    if archive is not None and not _same_recovery_point(archive.artifact, current, promoted=already_restored):
        raise DocumentValidationError('The database and receipt archive are different recovery points.')
    plan = digest({'database_sha256': fingerprint, 'payload_sha256': digest(payload), 'operation': operation,
        'revision': revision, 'current_sha256': current['manifest']['content_sha256'],
        'archive_sha256': archive.artifact['manifest']['content_sha256'] if archive else None,
        'archive_path_sha256': digest(str(Path(archive_path).resolve())) if archive_path else None,
        'connection': {key: serialized(value) for key, value in row.items()},
        'source_database_sha256': source_database_sha256, 'target_database_sha256': target_database_sha256})
    if apply and (expected_plan != plan or not re.fullmatch('[0-9a-f]{64}', approval_sha256 or '')):
        raise DocumentValidationError('Apply requires the exact reviewed Drive recovery plan and private operator approval.')
    if operation == 'verify-archive':
        repo = PostgresReceiptRepository(database, entity, store_kind='google_drive', store_scope_key=archive.scope_key)
        return {'verified': verify_entity_documents(repo, archive), 'applied': False, 'plan_sha256': plan}
    # Archive verification above deliberately works without a functioning Google
    # grant. Restore needs only the approved destination grant, not lost source access.
    target = google_store({**payload, 'store_scope_key': payload['scope_key'], 'required_scopes': [DRIVE_SCOPE]},
                         payload, validate=True)
    if target.scope_key != payload['scope_key']:
        raise DocumentValidationError('The selected Drive receipt folder differs from its private binding.')
    repo = PostgresReceiptRepository(database, entity, store_kind='google_drive', store_scope_key=target.scope_key)
    if operation == 'verify' or already_restored:
        return {'verified': verify_entity_documents(repo, target), 'applied': False,
                'already_restored': already_restored, 'plan_sha256': plan}
    if operation == 'backup':
        result = archive_documents(repo, target, archive_path, current, dry_run=not apply, progress=progress)
        return {**result, 'plan_sha256': plan}
    if source_database_sha256 == fingerprint or target.scope_key == archive.scope_key:
        raise DocumentValidationError('Restore requires separate source and destination database/Drive bindings.')
    if apply and secrets is None:
        raise DocumentValidationError('Configure protected connection secret custody before restored binding installation.')
    repo = PostgresReceiptRepository(database, entity, store_kind='google_drive', store_scope_key=archive.scope_key)
    binding = None if not apply else dict(organization_id=payload['organization_id'], profile_key=payload['profile_key'],
        secret_ref=secrets.put(payload), expected_revision=revision, recovery_source_scope=archive.scope_key)
    result = copy_entity_documents(repo, archive, target, dry_run=not apply, promote=apply,
                                   connection_binding=binding, recovery_snapshot=True, progress=progress,
                                   expected_point_sha256=current['manifest']['content_sha256'])
    return {**asdict(result), 'plan_sha256': plan}
