"""Opt-in real S3 staging drill; no provider setup, expiry or permanent cleanup.

Requires explicitly approved synthetic-only source/target staging prefixes and
TABULA_RASA_TEST_DATABASE_URL. Keeps all object versions for operator inspection.
"""
import os
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest

from scripts.manage_document_storage import execute, read_binding
from tabula_rasa.application.document_recovery import verify_entity_documents
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.postgres.cutover import database_identity
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.infrastructure.postgres.managed_documents import install_managed_connection
from tabula_rasa.infrastructure.postgres.recovery import verify_recovery
from tabula_rasa.infrastructure.postgres.composition import create_postgres_export_service
from tabula_rasa.infrastructure.s3_documents import create_s3_document_store
from tests.postgres.document_restore_support import cloned_database
from tests.postgres.test_identity import setup
from tests.test_s3_documents import upload

pytestmark = pytest.mark.skipif(
    os.environ.get('TABULA_RASA_ALLOW_S3_STAGING_DRILL') != 'approved',
    reason='Real provider staging drill requires manual bucket/credential/cost approval.')


def test_real_provider_exact_bytes_version_recovery_and_isolated_database_restore(database, tmp_path):
    private = read_binding(os.environ['TABULA_RASA_S3_STAGING_BINDING'])
    run_drill(database, tmp_path, private)


def run_drill(database, tmp_path, private, *, clients=None):
    """Same staging drill runs locally with fake boundaries and truly on opt-in."""
    if (set(private) != {'source', 'target'}
            or not all(configuration['namespace'].startswith('staging/') for configuration in private.values())
            or tuple(private['source'][key] for key in ('bucket', 'region', 'namespace'))
               == tuple(private['target'][key] for key in ('bucket', 'region', 'namespace'))):
        raise ValueError('Staging drill requires isolated, synthetic-only staging prefixes.')
    _, _, _, alpha_org, beta_org = setup(database)
    secrets = ConnectionSecrets(tmp_path, Fernet.generate_key().decode())
    stores, payloads = {}, {}
    for entity, org in [('alpha', alpha_org), ('beta', beta_org)]:
        source = create_s3_document_store(entity, private['source'], client=clients[0] if clients else None)
        source.validate()
        stores[entity] = source
        payload = dict(environment='staging', organization_id=org, entity_id=entity, provider='s3', profile_key=entity,
                       scope_key=source.scope_key, s3=private['source'])
        payloads[entity] = payload
        repo = PostgresReceiptRepository(database, entity, store_kind='s3', store_scope_key=source.scope_key)
        repo.register_document(source.upload(entity, upload(uuid4().hex)))
        with repo.operation() as connection:
            repo.lock_entity(connection)
            install_managed_connection(connection, entity, source.scope_key, organization_id=org, profile_key=entity,
                secret_ref=secrets.put(payload), expected_revision=0)
    source = stores['alpha']
    target = create_s3_document_store('alpha', private['target'], client=clients[1] if clients else None)
    target.validate()
    expected = {entity: create_postgres_export_service(database, entity).export() for entity in ('alpha', 'beta')}
    source_id = database_identity(database)
    with cloned_database(database) as restored:
        target_id = database_identity(restored)
        for entity in ('alpha', 'beta'):
            verify_recovery(restored, entity, expected[entity], source_database_sha256=source_id, target_database_sha256=target_id)
        repo = PostgresReceiptRepository(restored, 'alpha', store_kind='s3', store_scope_key=source.scope_key)
        document, = repo.retained_documents()
        source.delete('alpha', document.storage_key)  # Approved staging-only delete marker, keeps version.
        assert verify_entity_documents(repo, source) == 1
        payload = {**payloads['alpha'], 'scope_key': target.scope_key, 's3': private['target']}
        kwargs = dict(operation='restore', environment='staging', revision=1,
            source_payload=payloads['alpha'], source_database_sha256=source_id, target_database_sha256=target_id)
        plan = execute(restored, secrets, payload, **kwargs)
        result = execute(restored, secrets, payload, **kwargs, apply=True,
                         expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)
        assert result['verified'] == 1 and result['promoted']
        recovered = PostgresReceiptRepository(restored, 'alpha', store_kind='s3', store_scope_key=target.scope_key)
        assert verify_entity_documents(recovered, target) == 1
        assert target.fetch('alpha', recovered.retained_documents()[0].storage_key) == source.fetch('alpha', document.storage_key)
        assert verify_entity_documents(PostgresReceiptRepository(restored, 'beta', store_kind='s3',
            store_scope_key=stores['beta'].scope_key), stores['beta']) == 1
        # A restart verifies the new binding without recopying, even with the old supplied revision.
        assert execute(restored, secrets, payload, **kwargs)['already_managed']
    print('document_staging_drill_passed: entities=2 source_versions_retained=true isolated_db_and_bytes=true')
