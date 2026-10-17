"""Drive-first backup and real isolated PostgreSQL snapshot recovery; no AWS."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import text

from scripts.manage_document_storage import execute, read_binding
from tabula_rasa.application.document_recovery import verify_entity_documents
from tabula_rasa.application.documents import DocumentError, DocumentValidationError
from tabula_rasa.errors import StorageConflictError
from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.http.connections import google_store
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.document_archive import DocumentArchive
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.connections import PostgresConnections
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tabula_rasa.infrastructure.postgres.identity import database_identity
from tests.alpha_documents_support import SyntheticDrive, binding
from tests.postgres._support import account, category
from tests.postgres.core_support import expense
from tests.postgres.document_restore_support import cloned_database
from tests.postgres.test_identity import setup


class RecoveryDrive(SyntheticDrive):
    def __init__(self, profile, folder):
        super().__init__(profile)
        self.folder = folder
        self.fail = False
        self.fail_after = None

    def list_profile_receipts(self, *, profile_key, folder_id, _force_refresh):
        assert profile_key == self.profile and folder_id == self.folder
        if self.fail:
            raise GoogleDriveAccessError('synthetic revoked provider')
        return list(self.files.values())

    def upload_receipt(self, *, stored_filename=None, **kwargs):
        if self.fail or self.fail_after == self.uploads:
            raise GoogleDriveAccessError('synthetic provider unavailable')
        key = 'provider-' + kwargs['receipt_id']
        new_key = hashlib.sha256((self.folder + key).encode()).hexdigest()
        if new_key in self.files:
            return self.files[new_key]
        result = super().upload_receipt(**kwargs)
        if stored_filename is not None:
            result['name'] = stored_filename
        # Actual Drive IDs differ by folder; canonical document IDs stay the same.
        self.files[new_key] = self.files.pop(key)
        self.bytes[new_key] = self.bytes.pop(key)
        self.files[new_key]['id'] = new_key
        return self.files[new_key]


def configurations():
    result = {}
    for entity in ('alpha', 'beta'):
        result[entity] = {}
        for mode in ('source', 'target'):
            original = binding(profile=entity + '-drive')
            grant = deepcopy(original['google_drive'])
            if mode == 'target':
                for name in ('storage_root', 'receipt_folder', 'backup_folder'):
                    grant[name]['id'] += '-recovery'
            result[entity][mode] = dict(profile_key=original['profile_key'],
                google_drive_oauth=original['google_drive_oauth'], google_drive=grant)
    return result


def fixture(database, tmp_path, monkeypatch):
    private = configurations()
    clients = {value['google_drive']['receipt_folder']['id']:
        RecoveryDrive(value['profile_key'], value['google_drive']['receipt_folder']['id'])
        for entity in private.values() for value in entity.values()}
    def factory(config, grant):
        return clients[grant['receipt_folder']['id']]
    monkeypatch.setattr('tabula_rasa.google_drive.GoogleDriveClient', factory)
    return prepare(database, tmp_path, private), clients


def prepare(database, tmp_path, private):
    _, _, _, a, b = setup(database)
    secrets = ConnectionSecrets(tmp_path / 'secrets', Fernet.generate_key().decode())
    secrets.directory.mkdir()
    payloads = {}
    for entity, org in [('alpha', a), ('beta', b)]:
        payloads[entity] = {}
        for mode in ('source', 'target'):
            config = private[entity][mode]
            payloads[entity][mode] = {**config, 'environment': 'staging', 'organization_id': org,
                'entity_id': entity, 'provider': 'google_drive', 'scope_key': config['google_drive']['receipt_folder']['id']}
        payload = payloads[entity]['source']
        store = google_store({**payload, 'store_scope_key': payload['scope_key'],
                              'required_scopes': payload['google_drive']['scopes']}, payload, validate=True)
        with database.transaction() as connection:
            account(connection, entity, 'cash')
            category(connection, entity, 'office', kind='Expense')
        services = create_postgres_services(database, entity, document_store=store, document_store_kind='google_drive')
        services.transactions.create(transaction_id='txn', **expense())
        # Fresh synthetic source folders are required by the real-provider drill.
        assert store.inventory(entity, fresh=True).documents == ()
        for index in (1, 2):
            doc = services.receipts.upload(uuid4().hex, f'receipt-{index}.pdf', entity.encode() + bytes([index]))
            doc = replace(doc, open_url='https://drive.google.com/file/d/' + doc.storage_key + '/view')
            services.receipts.repository.register_document(doc)
            if index == 1:
                services.receipts.link('txn', doc)
        PostgresConnections(database).stage(organization_id=org, entity_id=entity,
            profile_key=payload['profile_key'], scope_key=payload['scope_key'], secret_ref=secrets.put(payload),
            expected_revision=0)
    with database.transaction() as connection:
        connection.execute(text("UPDATE external_connections SET status='connected' WHERE provider='google_drive'"))
    return payloads, secrets


def backup(database, secrets, payload, path, *, apply=True):
    plan = execute(database, secrets, payload, operation='backup', environment='staging', archive_path=path)
    if not apply:
        return plan
    return execute(database, secrets, payload, operation='backup', environment='staging', archive_path=path,
        apply=True, expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)


def drill(database, payloads, secrets, path):
    path.mkdir(mode=0o700, exist_ok=True)
    for entity in ('alpha', 'beta'):
        assert backup(database, secrets, payloads[entity]['source'], path / entity)['verified'] == 2
    source_id = database_identity(database)
    with cloned_database(database) as restored:
        for entity in ('alpha', 'beta'):
            archive = DocumentArchive(path / entity, entity)
            original_links = deepcopy(archive.artifact['domains']['document_links'])
            kwargs = dict(operation='restore', environment='staging', archive_path=path / entity, revision=1,
                source_database_sha256=source_id, target_database_sha256=database_identity(restored))
            plan = execute(restored, secrets, payloads[entity]['target'], **kwargs)
            result = execute(restored, secrets, payloads[entity]['target'], **kwargs, apply=True,
                expected_plan=plan['plan_sha256'], approval_sha256='b' * 64)
            assert result['promoted'] and result['verified'] == 2
            assert execute(restored, secrets, payloads[entity]['target'], **kwargs)['already_restored']
            repo = PostgresReceiptRepository(restored, entity, store_kind='google_drive',
                                            store_scope_key=payloads[entity]['target']['scope_key'])
            target = google_store({**payloads[entity]['target'], 'store_scope_key': payloads[entity]['target']['scope_key'],
                'required_scopes': payloads[entity]['target']['google_drive']['scopes']}, payloads[entity]['target'])
            assert verify_entity_documents(repo, target) == 2
            for document in repo.retained_documents():
                old = next(item for item in archive.documents if item.metadata.document_id == document.metadata.document_id)
                assert old.metadata == document.metadata and old.storage_key != document.storage_key
                assert target.fetch(entity, document.storage_key) == archive.fetch(entity, old.storage_key)
            with restored.transaction(read_only=True) as connection:
                links = [dict(row) for row in connection.execute(text(
                    'SELECT * FROM document_links WHERE entity_id=:entity ORDER BY document_id'), {'entity': entity}).mappings()]
                assert [item['document_id'] for item in links] == [item['document_id'] for item in original_links]
                assert connection.scalar(text('SELECT count(*) FROM document_locations WHERE entity_id=:entity'), {'entity': entity}) == 2
        with pytest.raises(DocumentValidationError):
            DocumentArchive(path / 'alpha', 'beta')
    for entity in ('alpha', 'beta'):
        payload = payloads[entity]['source']
        source = google_store({**payload, 'store_scope_key': payload['scope_key'],
            'required_scopes': payload['google_drive']['scopes']}, payload, validate=True)
        assert verify_entity_documents(PostgresReceiptRepository(database, entity, store_kind='google_drive',
            store_scope_key=payload['scope_key']), source) == 2
    return {'entities': 2, 'documents': 4, 'isolated_db_and_drive': True, 'originals_retained': True}


def test_drive_only_snapshot_backup_and_isolated_restore_preserve_ids_links_bytes(database, tmp_path, monkeypatch):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    import builtins
    original_import = builtins.__import__
    def without_aws(name, *args, **kwargs):
        if name.split('.')[0] in {'boto3', 'botocore', 's3transfer'}:
            raise AssertionError('Drive storage/recovery must operate without AWS SDK dependencies.')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_aws)
    result = drill(database, payloads, secrets, tmp_path / 'archives')
    assert result['documents'] == 4
    assert all(client.deletes == 0 for client in clients.values())
    # Ordinary replay did not create extra files despite a different provider locator.
    assert all(client.uploads == 2 for client in clients.values())


@pytest.mark.parametrize('apply', [False, True])
def test_restore_rejects_original_drive_folder_before_completed_shortcut(database, tmp_path, monkeypatch, apply):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    source, path = payloads['alpha']['source'], tmp_path / 'archive'
    backup(database, secrets, source, path)
    uploads = {folder: client.uploads for folder, client in clients.items()}
    with cloned_database(database) as restored:
        def no_provider_access(*args, **kwargs):
            raise AssertionError('Reject source-folder restore before accessing the provider.')
        monkeypatch.setattr('scripts.drive_document_recovery.google_store', no_provider_access)
        with pytest.raises(DocumentValidationError, match='separate source and destination'):
            execute(restored, secrets, source, operation='restore', environment='staging', archive_path=path,
                    source_database_sha256=database_identity(database),
                    target_database_sha256=database_identity(restored), apply=apply)
        with restored.transaction(read_only=True) as connection:
            assert connection.scalar(text("SELECT store_scope_key FROM external_connections WHERE entity_id='alpha'")) == source['scope_key']
            assert connection.scalar(text("SELECT count(*) FROM document_locations WHERE entity_id='alpha'")) == 0
    assert {folder: client.uploads for folder, client in clients.items()} == uploads


@pytest.mark.parametrize('payload', [None, [], 'invalid', 42, True])
def test_private_binding_rejects_non_object_json(tmp_path, payload):
    path = tmp_path / 'binding.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(DocumentValidationError, match='JSON object'):
        read_binding(path)


def test_offline_archive_verification_and_restore_need_no_lost_source_grant(database, tmp_path, monkeypatch):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    payload = payloads['alpha']['source']
    path = tmp_path / 'archive'
    backup(database, secrets, payload, path)
    clients[payload['scope_key']].fail = True
    clients[payload['scope_key']].files.clear()
    clients[payload['scope_key']].bytes.clear()
    with database.transaction() as connection:
        connection.execute(text("UPDATE external_connections SET status='reconnect_required' WHERE entity_id='alpha'"))
    offline = {**payload, 'google_drive_oauth': {}, 'google_drive': {}}
    assert execute(database, secrets, offline, operation='verify-archive', environment='staging', archive_path=path)['verified'] == 2
    with cloned_database(database) as restored:
        kwargs = dict(operation='restore', environment='staging', archive_path=path, revision=1,
            source_database_sha256=database_identity(database), target_database_sha256=database_identity(restored))
        plan = execute(restored, secrets, payloads['alpha']['target'], **kwargs)
        result = execute(restored, secrets, payloads['alpha']['target'], **kwargs, apply=True,
            expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)
        assert result['promoted']


def test_dry_run_partial_backup_resume_and_missing_corrupt_unsafe_archive(database, tmp_path, monkeypatch):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    payload, path = payloads['alpha']['source'], tmp_path / 'archive'
    assert backup(database, secrets, payload, path, apply=False)['dry_run'] and not path.exists()
    backup(database, secrets, payload, path)
    archive = DocumentArchive(path, 'alpha')
    document = archive.documents[0]
    byte_path = path / (document.metadata.document_id + '.bin')
    original = byte_path.read_bytes()
    byte_path.write_bytes(b'corrupt')
    with pytest.raises(DocumentValidationError, match='retained metadata'):
        archive.fetch('alpha', document.storage_key)
    byte_path.unlink()
    with pytest.raises(DocumentError, match='missing'):
        archive.fetch('alpha', document.storage_key)
    # An incomplete generation is resumable; it is not accepted as a full archive.
    (path / 'bookkeeping.json').unlink()
    with pytest.raises(DocumentValidationError, match='incomplete'):
        DocumentArchive(path, 'alpha')
    backup(database, secrets, payload, path)
    assert byte_path.read_bytes() == original
    with pytest.raises(DocumentValidationError):
        archive.fetch('beta', document.storage_key)
    with pytest.raises(DocumentValidationError):
        archive.metadata('alpha', '../forged')
    monkeypatch.setattr(Path, 'is_symlink', lambda self: self == byte_path)
    with pytest.raises(DocumentValidationError, match='unsafe file path'):
        archive.fetch('alpha', document.storage_key)


def test_restore_partial_provider_failure_and_wrong_db_point_leave_source_metadata(database, tmp_path, monkeypatch):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    source, target = payloads['alpha']['source'], payloads['alpha']['target']
    path = tmp_path / 'archive'
    backup(database, secrets, source, path)
    with cloned_database(database) as restored:
        kwargs = dict(operation='restore', environment='staging', archive_path=path, revision=1,
            source_database_sha256=database_identity(database), target_database_sha256=database_identity(restored))
        plan = execute(restored, secrets, target, **kwargs)
        client = clients[target['scope_key']]
        client.fail_after = 1
        with pytest.raises(DocumentError):
            execute(restored, secrets, target, **kwargs, apply=True, expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)
        original_repo = PostgresReceiptRepository(restored, 'alpha', store_kind='google_drive', store_scope_key=source['scope_key'])
        assert len(original_repo.retained_documents()) == 2 and client.uploads == 1
        client.fail_after = None
        execute(restored, secrets, target, **kwargs, apply=True, expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)
        assert client.uploads == 2
    with cloned_database(database) as restored:
        services = create_postgres_services(restored, 'alpha')
        before = services.transactions.list()[0]
        services.transactions.update('txn', description='changed recovery point', expected=before)
        with pytest.raises(DocumentValidationError, match='different recovery points'):
            execute(restored, secrets, target, **{**kwargs, 'target_database_sha256': database_identity(restored)})
    with pytest.raises(DocumentValidationError, match='isolated staging database'):
        execute(database, secrets, target, **{**kwargs, 'target_database_sha256': database_identity(database)})


def test_drive_backup_refuses_orphans_stale_approval_and_repository_output(database, tmp_path, monkeypatch):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    source, path = payloads['alpha']['source'], tmp_path / 'archive'
    plan = backup(database, secrets, source, path, apply=False)
    with database.transaction() as connection:
        connection.execute(text("UPDATE external_connections SET revision=revision+1 WHERE entity_id='alpha'"))
    with pytest.raises(DocumentValidationError, match='exact reviewed'):
        execute(database, secrets, source, operation='backup', environment='staging', archive_path=path,
                apply=True, expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)
    assert not path.exists()
    # A provider orphan must be explicitly reconciled rather than omitted from recovery.
    store = google_store({**source, 'store_scope_key': source['scope_key'],
        'required_scopes': source['google_drive']['scopes']}, source)
    from tabula_rasa.application.documents import DocumentUpload
    store.upload('alpha', DocumentUpload(uuid4().hex, 'orphan.pdf', 'application/pdf',
                 hashlib.sha256(b'orphan').hexdigest(), b'orphan'))
    with pytest.raises(DocumentValidationError, match='unregistered'):
        backup(database, secrets, source, path)
    assert not path.exists()
    # Private artifacts cannot be written under any repository-like ancestor.
    private = tmp_path / 'repo-like'
    private.mkdir()
    (private / '.git').mkdir()
    from tabula_rasa.infrastructure.document_archive import _root
    with pytest.raises(DocumentValidationError, match='outside the repository'):
        _root(private / 'receipt-archive', create=True)
    assert all(client.deletes == 0 for client in clients.values())


def test_drive_restore_rechecks_link_recovery_point_at_atomic_promotion(database, tmp_path, monkeypatch):
    (payloads, secrets), clients = fixture(database, tmp_path, monkeypatch)
    source, target, path = payloads['alpha']['source'], payloads['alpha']['target'], tmp_path / 'archive'
    backup(database, secrets, source, path)
    with cloned_database(database) as restored:
        kwargs = dict(operation='restore', environment='staging', archive_path=path, revision=1,
            source_database_sha256=database_identity(database), target_database_sha256=database_identity(restored))
        plan = execute(restored, secrets, target, **kwargs)
        client = clients[target['scope_key']]
        upload = client.upload_receipt
        def change_link(**values):
            result = upload(**values)
            if client.uploads == 2:
                repo = PostgresReceiptRepository(restored, 'alpha', store_kind='google_drive', store_scope_key=source['scope_key'])
                document, = repo.references('alpha', 'txn')
                repo.unlink('alpha', 'txn', document.storage_key)
            return result
        monkeypatch.setattr(client, 'upload_receipt', change_link)
        with pytest.raises(StorageConflictError, match='recovery point changed'):
            execute(restored, secrets, target, **kwargs, apply=True, expected_plan=plan['plan_sha256'], approval_sha256='a' * 64)
        with restored.transaction(read_only=True) as connection:
            assert connection.scalar(text('SELECT count(*) FROM document_locations')) == 0
            assert connection.scalar(text("SELECT store_scope_key FROM documents WHERE entity_id='alpha' LIMIT 1")) == source['scope_key']
        assert client.uploads == 2 and client.deletes == 0


@pytest.mark.parametrize('field,value', [('version', 2), ('version', True), ('scope_key', 'wrong-folder'),
                                       ('content_sha256', '0' * 64)])
def test_drive_archive_rejects_unsupported_version_scope_or_checksum(database, tmp_path, monkeypatch, field, value):
    (payloads, secrets), _ = fixture(database, tmp_path, monkeypatch)
    path = tmp_path / 'archive'
    backup(database, secrets, payloads['alpha']['source'], path)
    manifest = json.loads((path / 'binding.json').read_text(encoding='utf-8'))
    manifest[field] = value
    (path / 'binding.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(DocumentValidationError):
        DocumentArchive(path, 'alpha')


@pytest.mark.skipif(os.environ.get('TABULA_RASA_ALLOW_DRIVE_RECOVERY_STAGING_DRILL') != 'approved',
                    reason='Real Drive drill requires approved synthetic grants/folders and disposable DB.')
def test_real_drive_staging_exact_byte_backup_and_isolated_restore(database, tmp_path):
    private = read_binding(os.environ['TABULA_RASA_DRIVE_RECOVERY_STAGING_BINDING'])
    assert set(private) == {'alpha', 'beta'}
    folders = []
    for values in private.values():
        assert set(values) == {'source', 'target'}
        assert values['source']['profile_key'] == values['target']['profile_key']
        assert values['source']['profile_key'].startswith('stage-')
        for config in values.values():
            assert set(config) == {'profile_key', 'google_drive_oauth', 'google_drive'}
            folders.append(config['google_drive']['receipt_folder']['id'])
    assert len(set(folders)) == 4
    payloads, secrets = prepare(database, tmp_path, private)
    result = drill(database, payloads, secrets, tmp_path / 'archives')
    print(json.dumps({'status': 'drive_recovery_drill_passed', **result}, sort_keys=True))
