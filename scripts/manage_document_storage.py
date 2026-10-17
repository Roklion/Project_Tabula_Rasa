"""Explicit private receipt binding/copy/verifier. Dry-run unless --apply.

Run as python -m scripts.manage_document_storage. Private JSON, SQL URL and
encrypted grants stay with the authorized recovery operator, outside Git.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import re

from sqlalchemy import text

from tabula_rasa.application.document_recovery import copy_entity_documents, verify_entity_documents
from tabula_rasa.application.documents import DocumentError, DocumentNotFoundError, DocumentValidationError
from tabula_rasa.errors import StorageConflictError
from tabula_rasa.http.connections import google_store, provider_store
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.infrastructure.postgres.managed_documents import install_managed_connection
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.infrastructure.postgres.repository import serialized
from tabula_rasa.migration.model import digest


def read_binding(path):
    with Path(path).open('rb') as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise DocumentValidationError('Private receipt binding is too large.')
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DocumentValidationError('Private receipt binding is not valid JSON.') from None
    if not isinstance(payload, dict):
        raise DocumentValidationError('Private receipt binding must be a JSON object.')
    return payload


def execute(database, secrets, payload, *, operation, environment, revision=0, apply=False,
            expected_plan=None, approval_sha256=None, source_payload=None,
            source_database_sha256=None, target_database_sha256=None, progress=None, archive_path=None):
    if payload.get('provider') == 'google_drive':
        from scripts.drive_document_recovery import execute_drive
        return execute_drive(database, secrets, payload, operation=operation, environment=environment,
            revision=revision, apply=apply, expected_plan=expected_plan, approval_sha256=approval_sha256,
            archive_path=archive_path, source_database_sha256=source_database_sha256,
            target_database_sha256=target_database_sha256, progress=progress)
    if (environment not in {'staging', 'production'} or payload.get('environment') != environment
            or set(payload) != {'environment', 'organization_id', 'entity_id', 'provider', 'profile_key', 'scope_key', 's3'}
            or payload['provider'] != 's3' or secrets is None
            or operation not in {'bind', 'rotate', 'copy', 'verify', 'restore'}):
        raise DocumentValidationError('Invalid private managed receipt plan.')
    entity = payload['entity_id']
    target_row = {**payload, 'store_scope_key': payload['scope_key']}
    target = provider_store(target_row, payload, validate=True)
    from tabula_rasa.infrastructure.postgres.cutover import database_identity
    database_sha256 = database_identity(database)
    if operation == 'restore':
        if (environment != 'staging' or not isinstance(source_payload, dict)
                or source_payload.get('entity_id') != entity
                or source_payload.get('organization_id') != payload['organization_id']
                or source_payload.get('provider') != 's3'
                or not re.fullmatch('[0-9a-f]{64}', source_database_sha256 or '')
                or not re.fullmatch('[0-9a-f]{64}', target_database_sha256 or '')
                or source_database_sha256 == target_database_sha256
                or database_sha256 != target_database_sha256):
            raise DocumentValidationError('Restore requires an isolated staging database and explicit source/target fingerprints.')
        source = provider_store({**source_payload, 'store_scope_key': source_payload['scope_key']}, source_payload, validate=True)
        if source.scope_key == target.scope_key:
            raise DocumentValidationError('Restore requires distinct source and destination storage bindings.')
    with database.transaction(read_only=True) as connection:
        rows = connection.execute(text('SELECT * FROM documents WHERE entity_id=:entity ORDER BY id'),
                                  {'entity': entity}).mappings().all()
        managed = connection.execute(text("SELECT * FROM external_connections WHERE entity_id=:entity AND provider='s3'"),
                                     {'entity': entity}).mappings().first()
        source_row = connection.execute(text("SELECT * FROM external_connections WHERE entity_id=:entity AND provider='google_drive'"),
                                        {'entity': entity}).mappings().first()
        # Exact snapshot digest includes links, so a changed linking decision invalidates approval.
        links = connection.execute(text('SELECT * FROM document_links WHERE entity_id=:entity ORDER BY document_id,entry_id,mixed_use_source_id,position'),
                                   {'entity': entity}).mappings().all()
    plan = digest({'payload_sha256': digest(payload), 'operation': operation, 'revision': revision,
                   'database_sha256': database_sha256,
                   'documents': [{key: serialized(value) for key, value in row.items()} for row in rows],
                   'links': [{key: serialized(value) for key, value in row.items()} for row in links],
                   'source_revision': source_row['revision'] if source_row else None,
                   'restore_source': digest(source_payload) if source_payload is not None else None,
                   'source_database_sha256': source_database_sha256, 'target_database_sha256': target_database_sha256})
    if apply and (expected_plan != plan or not re.fullmatch('[0-9a-f]{64}', approval_sha256 or '')):
        raise DocumentValidationError('Apply requires the exact reviewed plan and a private operator approval digest.')
    repository = PostgresReceiptRepository(database, entity, store_kind='s3', store_scope_key=target.scope_key)
    already_managed = (managed is not None and managed['organization_id'] == payload['organization_id']
                       and managed['store_scope_key'] == target.scope_key)
    if operation == 'verify' or operation in {'copy', 'restore'} and already_managed:
        count = verify_entity_documents(repository, target)
        return {'verified': count, 'applied': False, 'already_managed': already_managed, 'plan_sha256': plan}
    if operation in {'bind', 'rotate'}:
        if operation == 'bind' and rows:
            raise DocumentValidationError('Non-empty receipt metadata requires verified copy, not rebinding.')
        if operation == 'rotate' and not already_managed:
            raise DocumentValidationError('Credential rotation requires the same installed managed binding.')
        count = verify_entity_documents(repository, target) if operation == 'rotate' else 0
        if apply:
            reference = secrets.put(payload)
            with repository.operation() as connection:
                repository.lock_entity(connection)
                install_managed_connection(connection, entity, target.scope_key,
                    organization_id=payload['organization_id'], profile_key=payload['profile_key'],
                    secret_ref=reference, expected_revision=revision)
        return {'verified': count, 'applied': apply, 'plan_sha256': plan}
    if operation == 'restore':
        repository = PostgresReceiptRepository(database, entity, store_kind='s3', store_scope_key=source.scope_key)
        binding = None if not apply else dict(organization_id=payload['organization_id'], profile_key=payload['profile_key'],
            secret_ref=secrets.put(payload), expected_revision=revision, recovery_source_scope=source.scope_key)
        result = copy_entity_documents(repository, source, target, dry_run=not apply, promote=apply,
                                       connection_binding=binding, recovery_snapshot=True, progress=progress)
        return {**asdict(result), 'plan_sha256': plan}
    if (source_row is None or source_row['organization_id'] != payload['organization_id']
            or source_row['status'] != 'connected'):
        raise DocumentValidationError('Copy requires the explicit connected source Drive grant.')
    source_payload = secrets.get(source_row['secret_ref'], environment=environment,
        organization_id=payload['organization_id'], entity_id=entity, provider='google_drive')
    if (source_payload.get('profile_key') != source_row['profile_key']
            or source_payload.get('scope_key') != source_row['store_scope_key']):
        raise DocumentValidationError('Source Drive grant binding differs.')
    source = google_store(source_row, source_payload, validate=True)
    repository = PostgresReceiptRepository(database, entity, store_kind='google_drive', store_scope_key=source.scope_key)
    # Ciphertext written before promotion can remain an inert orphan on failure.
    binding = None
    if apply:
        binding = dict(organization_id=payload['organization_id'], profile_key=payload['profile_key'],
                       secret_ref=secrets.put(payload), expected_revision=revision,
                       source_revision=source_row['revision'], source_scope=source.scope_key)
    result = copy_entity_documents(repository, source, target, dry_run=not apply, promote=apply,
                                   connection_binding=binding, progress=progress)
    return {**asdict(result), 'plan_sha256': plan}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['backup', 'verify-archive', 'bind', 'rotate', 'copy', 'verify', 'restore'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--environment', choices=['staging', 'production'], required=True)
    parser.add_argument('--revision', type=int, default=0)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-plan')
    parser.add_argument('--approval-sha256')
    parser.add_argument('--source-input', type=Path)
    parser.add_argument('--source-database-sha256')
    parser.add_argument('--target-database-sha256')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args(argv)
    database = None
    try:
        database = Database(DatabaseSettings.from_environment(required=True))
        result = execute(database, ConnectionSecrets.from_environment(dict(os.environ)), read_binding(args.input),
            operation=args.operation, environment=args.environment, revision=args.revision, apply=args.apply,
            expected_plan=args.expect_plan, approval_sha256=args.approval_sha256,
            source_payload=read_binding(args.source_input) if args.source_input else None,
            source_database_sha256=args.source_database_sha256, target_database_sha256=args.target_database_sha256,
            archive_path=args.archive,
            progress=lambda value: print(json.dumps(value, sort_keys=True)))
        print(json.dumps(result, sort_keys=True))
        return 0
    except DocumentNotFoundError:
        failure = 'missing_bytes_or_retained_version'
    except DocumentValidationError:
        failure = 'invalid_plan_binding_or_integrity'
    except StorageConflictError:
        failure = 'metadata_or_connection_changed'
    except DocumentError:
        failure = 'provider_or_byte_verification_failed'
    except Exception:
        failure = 'unavailable'
    finally:
        if database is not None:
            database.dispose()
    print(json.dumps({'status': 'failed', 'code': failure,
        'guidance': 'Inspect current locations, copied inventory, grants and retained versions before retrying.'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
