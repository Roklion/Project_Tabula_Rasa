"""Native metadata/link operations with a synthetic external byte store."""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from tabula_rasa.application.documents import (
    DocumentMetadata, DocumentReference, DocumentValidationError, MAX_RECEIPT_BYTES,
)
from tabula_rasa.errors import StorageConflictError, StorageNotFoundError, StorageValidationError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.concurrency import baseline_for, AggregateKey
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository, map_legacy_document
from tabula_rasa.receipt_records import document_to_receipt_reference
from tests.postgres.core_support import seed_core, expense, journal_lines
from tests.postgres._support import expense_references, mixed_pair, load_baseline
from tests.test_application_documents import FakeDocumentStore, prepared


def setup(database):
    seed_core(database)
    store = FakeDocumentStore()
    services = [create_postgres_services(database, scope, document_store=store, document_store_kind='fake')
                for scope in ('alpha', 'beta')]
    for item in services:
        item.transactions.create(transaction_id='txn', **expense())
    return *services, store


def test_metadata_receipt_recovery_unlink_and_two_entity_isolation(database):
    alpha, beta, store = setup(database)
    for item in (alpha, beta):
        workflow = {'transaction_id': 'txn', 'receipts': prepared(content=item.profile_key.encode())}
        item.receipts.process_recovery(workflow)
        assert workflow['receipts'] == [] and workflow['linked_count'] == 1
    document, = alpha.receipts.references('txn')
    other, = beta.receipts.references('txn')
    assert document.metadata.document_id == other.metadata.document_id
    assert document.metadata.sha256 != other.metadata.sha256
    assert document.storage_key.startswith('object/')  # Opaque address, no Drive API.
    with pytest.raises(DocumentValidationError):
        beta.receipts.link('txn', document)
    alpha.receipts.link('txn', document)  # Confirmed replay is idempotent.
    assert len(alpha.receipts.references('txn')) == 1
    assert alpha.receipts.unreferenced().documents == ()
    alpha.receipts.unlink('txn', document.storage_key)
    assert alpha.receipts.references('txn') == ()
    assert beta.receipts.references('txn') == (other,)
    assert alpha.receipts.unreferenced().documents == (document,)
    assert store.fetch('alpha', document.storage_key) == b'alpha'
    assert store.delete_calls == 0
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM documents")) == 2
        assert connection.scalar(text("SELECT count(*) FROM document_links")) == 1


def test_document_identity_locator_conflict_and_failure_keep_uploaded_bytes(database):
    alpha, _, store = setup(database)
    workflow = {'transaction_id': 'missing', 'receipts': prepared()}
    alpha.receipts.process_recovery(workflow)
    assert len(workflow['receipts']) == 1 and store.upload_calls == 1
    assert len(alpha.receipts.unreferenced().documents) == 1
    workflow['transaction_id'] = 'txn'
    alpha.receipts.process_recovery(workflow)
    assert workflow['receipts'] == [] and store.upload_calls == 1
    document, = alpha.receipts.references('txn')
    repo = alpha.receipts.repository
    for changed in (
        replace(document, storage_key='another-provider-object'),
        replace(document, metadata=replace(document.metadata, document_id='b'*32)),
        replace(document, metadata=replace(document.metadata, sha256='f'*64)),
    ):
        with pytest.raises(StorageConflictError):
            repo.register_document(changed)
    alpha.transactions.create(transaction_id='other', **expense())
    with pytest.raises(StorageConflictError):
        alpha.receipts.link('other', document)
    assert alpha.receipts.references('other') == ()
    assert len(alpha.receipts.references('txn')) == 1
    assert store.delete_calls == 0
    alpha.transactions.delete('txn')
    assert alpha.receipts.unreferenced().documents == (document,)
    assert repo.register_document(document) == document


def test_invalid_integrity_metadata_is_refused_without_a_partial_link(database):
    alpha, _, _ = setup(database)
    document = DocumentReference('alpha', DocumentMetadata(
        'a'*32, 'receipt.pdf', 'receipt.pdf', 'application/pdf', 7, 'f'*64,
    ), 'object-receipt')
    for metadata in (
        replace(document.metadata, byte_size=MAX_RECEIPT_BYTES + 1),
        replace(document.metadata, byte_size=-1),
        replace(document.metadata, original_filename=''),
        replace(document.metadata, sha256='invalid'),
    ):
        with pytest.raises(DocumentValidationError):
            alpha.receipts.link('txn', replace(document, metadata=metadata))
    assert alpha.receipts.references('txn') == ()
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM documents')) == 0


def test_legacy_mapping_preserves_drive_locator_without_fetching_bytes(database):
    alpha, _, store = setup(database)
    repo = PostgresReceiptRepository(database, 'alpha', store_kind='google_drive', store_scope_key='folder')
    legacy = DocumentReference('alpha', DocumentMetadata('', 'legacy:2026.pdf'), 'drivefile12345')
    mapped = map_legacy_document('alpha', 'google_drive', 'folder', legacy)
    assert mapped.metadata.document_id != legacy.storage_key
    assert mapped == map_legacy_document('alpha', 'google_drive', 'folder', legacy)
    assert mapped.metadata.document_id != map_legacy_document(
        'beta', 'google_drive', 'folder', replace(legacy, profile_key='beta')).metadata.document_id
    accepted = repo.register_document(legacy)
    assert accepted == mapped and accepted.metadata.sha256 == '' and accepted.metadata.byte_size is None
    assert document_to_receipt_reference(accepted) == {'id': 'drivefile12345', 'name': 'legacy:2026.pdf'}
    repo.link('alpha', 'txn', legacy)
    assert repo.references('alpha', 'txn') == (mapped,)
    loaded = alpha.transactions.list()[0]
    assert loaded['receipt_references'] == [{'id': 'drivefile12345', 'name': 'legacy:2026.pdf'}]
    alpha.transactions.update('txn', description='Legacy receipt retained', expected=loaded)
    assert store.upload_calls == store.delete_calls == 0


def test_receipts_target_limits_serialized_and_failed_metadata_rolls_back(database):
    alpha, _, _ = setup(database)
    repo = alpha.receipts.repository
    for number in range(99):
        repo.link('alpha', 'txn', DocumentReference(
            'alpha', DocumentMetadata(f'{number:032x}', f'{number}.pdf'), f'object-{number}'))
    docs = [DocumentReference('alpha', DocumentMetadata(f'{number:032x}', f'{number}.pdf'), f'object-{number}')
            for number in (99, 100)]

    def add(document):
        try:
            repo.link('alpha', 'txn', document)
        except StorageValidationError:
            return 'limit'
        return 'linked'

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(add, docs)) == ['limit', 'linked']
    assert len(alpha.receipts.references('txn')) == 100
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM documents')) == 100
    alpha.journals.create(entry_id='journal', txn_date='2026-10-05', postings=journal_lines())
    with pytest.raises(DocumentValidationError):
        repo.link('alpha', 'journal', docs[0])
    with pytest.raises(StorageNotFoundError):
        repo.link('alpha', 'absent', docs[0])


def test_mixed_receipts_use_one_source_link_set_and_loaded_baseline(database):
    with database.transaction() as connection:
        expense_references(connection)
        mixed_pair(connection)
    store = FakeDocumentStore()
    services = create_postgres_services(database, 'alpha', document_store=store, document_store_kind='fake')
    with database.transaction(read_only=True) as connection:
        row = connection.execute(text("SELECT * FROM mixed_use_sources WHERE entity_id='alpha'")).mappings().one()
        baseline = baseline_for(AggregateKey('alpha', 'mixed_use', 'source'), row)
    repository = services.receipts.repository.for_mixed_use('source', expected_source={'baseline': baseline})
    bound = services.receipts.with_repository(repository)
    document = DocumentReference('alpha', DocumentMetadata('a'*32, 'receipt.pdf'), 'object-one')
    with pytest.raises(DocumentValidationError, match='source-aware'):
        services.receipts.link('projection', document)
    bound.link('projection', document)
    assert services.receipts.references('projection') == (document,)
    assert services.receipts.repository.associations('alpha')[0].transaction_id == 'projection'
    with pytest.raises(StorageConflictError):
        bound.unlink('projection', document.storage_key)
    current = load_baseline(database, AggregateKey('alpha', 'mixed_use', 'source'))
    rebound = services.receipts.with_repository(services.receipts.repository.for_mixed_use(
        'source', expected_source={'baseline': current}))
    with database.transaction(read_only=True) as connection:
        assert tuple(connection.execute(text(
            "SELECT entry_id,mixed_use_source_id FROM document_links WHERE entity_id='alpha'"
        )).one()) == (None, 'source')
    rebound.unlink('projection', document.storage_key)
    assert services.receipts.references('projection') == ()
    assert store.delete_calls == 0
