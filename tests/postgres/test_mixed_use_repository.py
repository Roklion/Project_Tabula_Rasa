"""Native source/projection atomicity, receipts, incomplete states and isolation."""

from copy import deepcopy

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tabula_rasa.infrastructure.postgres.mixed_use import PostgresMixedUseRepository
from tests.postgres.core_support import seed_core
from tests.postgres.secondary_support import mixed, document


def test_pair_crud_projection_identity_provenance_and_entity_isolation(database):
    alpha, beta = seed_core(database)
    created = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection',
                                    **mixed(new_payee_name='Vendor', new_tag_name='Job'))
    assert created['allocated_amount'] == '33.33'
    assert created['business_use_percentage'] == '33.33333'
    beta_created = beta.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed(total_expense='300'))
    changed = alpha.mixed_use.update('source', expected_source=created, total_expense='90', description='Updated')
    assert changed['id'] == created['id'] and changed['linked_transaction_id'] == 'projection'
    assert changed['created_at'] == created['created_at'] and changed['baseline'] != created['baseline']
    projection = alpha.transactions.list()[0]
    assert projection['amount'] == '30.00'
    assert projection['source_type'] == 'mixed_use_expense' and projection['source_id'] == 'source'
    assert projection['tags'] == ['Job'] and projection['payee'] == 'Vendor'
    assert beta.mixed_use.get('source') == beta_created
    with pytest.raises(StorageConflictError):
        alpha.mixed_use.delete('source', expected_source=created)
    for action in (lambda: alpha.transactions.update('projection', amount='999'),
                   lambda: alpha.transactions.delete('projection'),
                   lambda: alpha.mixed_use.update('source', linked_transaction_id='other'),
                   lambda: alpha.mixed_use.update('source', recurring_schedule_id='foreign')):
        with pytest.raises(StorageValidationError):
            action()
    alpha.mixed_use.delete('source', expected_source=changed)
    assert alpha.transactions.list() == alpha.mixed_use.list() == []
    assert beta.transactions.list()[0]['amount'] == '100.00'


@pytest.mark.parametrize('operation', ['create', 'edit', 'delete'])
def test_sql_failure_rolls_back_entire_pair_and_inline_references(database, monkeypatch, operation):
    alpha, _ = seed_core(database)
    current = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed()) if operation != 'create' else None
    before_transactions = deepcopy(alpha.transactions.list())
    before_sources = deepcopy(alpha.mixed_use.sources())
    if operation == 'delete':
        original = PostgresMixedUseRepository.delete_row

        def fail(self, connection, table, identity):
            original(self, connection, table, identity)
            connection.execute(text('SELECT 1/0'))
        monkeypatch.setattr(PostgresMixedUseRepository, 'delete_row', fail)
    else:
        original = PostgresTransactionRepository.write_lines

        def fail(self, connection, identity, lines):
            original(self, connection, identity, lines)
            connection.execute(text('UPDATE postings SET amount=amount+1 WHERE entity_id=:scope AND entry_id=:id AND position=2'),
                               {'scope': self.entity_id, 'id': identity})
        monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail)
    with pytest.raises(StorageError):
        if operation == 'create':
            alpha.mixed_use.create(source_id='source', linked_transaction_id='projection',
                                   **mixed(new_payee_name='Rollback', new_tag_name='Rollback'))
        elif operation == 'edit':
            alpha.mixed_use.update('source', expected_source=current, total_expense='200',
                                   new_payee_name='Rollback', new_tag_name='Rollback')
        else:
            alpha.mixed_use.delete('source', expected_source=current)
    assert alpha.transactions.list() == before_transactions
    assert alpha.mixed_use.sources() == before_sources
    assert alpha.payees.list() == alpha.tags.list() == []


def test_source_owned_receipt_order_retention_limit_ownership_and_two_entities(database):
    alpha, beta = seed_core(database)
    with database.transaction() as connection:
        receipts = [document(connection, 'alpha', identity) for identity in ('first', 'second', 'third')]
        beta_receipt = document(connection, 'beta', 'first')
    created = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed(), receipt_references=receipts[:2])
    beta_created = beta.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed(), receipt_references=[beta_receipt])
    with database.transaction(read_only=True) as connection:
        instants = dict(connection.execute(text("SELECT document_id,created_at FROM document_links WHERE entity_id='alpha'")).all())
    changed = alpha.mixed_use.update('source', expected_source=created, receipt_references=[receipts[2], receipts[1], receipts[0]])
    assert alpha.transactions.list()[0]['receipt_references'] == changed['receipt_references']
    with database.transaction(read_only=True) as connection:
        assert all(instants[row.document_id] == row.created_at for row in connection.execute(text(
            "SELECT document_id,created_at FROM document_links WHERE entity_id='alpha' AND document_id IN ('first','second')")))
    other = alpha.mixed_use.create(source_id='other', linked_transaction_id='other-projection', **mixed())
    with pytest.raises(StorageConflictError):
        alpha.mixed_use.link_receipt('other', expected_source=other, reference=receipts[0])
    changed = alpha.mixed_use.unlink_receipt('source', expected_source=changed, file_id=receipts[0]['id'])
    other = alpha.mixed_use.link_receipt('other', expected_source=other, reference=receipts[0])
    assert alpha.mixed_use.link_receipt('other', expected_source=other, reference=receipts[0]) == other
    assert beta.mixed_use.get('source') == beta_created
    with pytest.raises(StorageValidationError):
        alpha.mixed_use.update('source', receipt_references=[{'id': 'synthetic-drive-file-unregistered', 'name': 'missing.pdf'}])
    alpha.mixed_use.delete('source', expected_source=changed)
    alpha.mixed_use.delete('other', expected_source=other)
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM documents WHERE entity_id='alpha'")) == 3
        assert connection.scalar(text("SELECT count(*) FROM document_links WHERE entity_id='alpha'")) == 0


@pytest.mark.parametrize('state', ['missing_projection', 'projection_mismatch'])
def test_incomplete_sources_remain_inspectable_and_never_silently_repaired(database, state):
    alpha, _ = seed_core(database)
    if state == 'projection_mismatch':
        alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed())
        with database.transaction() as connection:
            connection.execute(text("UPDATE entries SET description='Synthetic mismatch' WHERE entity_id='alpha' AND id='projection'"))
            connection.execute(text("UPDATE mixed_use_sources SET relationship_state='projection_mismatch' WHERE entity_id='alpha' AND id='source'"))
    else:
        with database.transaction() as connection:
            connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,
                total_expense,business_use_percentage,allocated_amount,account_id,category_id,
                allocation_rationale,expected_projection_entry_id,relationship_state)
                VALUES ('alpha','source','source','2026-01-01',100,50,50,'cash','office',
                        'Synthetic allocation','projection','missing_projection')"""))
    source = alpha.mixed_use.sources()[0]
    assert source['relationship_state'] == state
    for action in (alpha.mixed_use.list, lambda: alpha.mixed_use.get('source'),
                   lambda: alpha.mixed_use.update('source', total_expense='200')):
        with pytest.raises(StorageError):
            action()
    assert alpha.mixed_use.sources()[0] == source


def test_direct_repository_validation_and_foreign_entity_references(database):
    alpha, beta = seed_core(database)
    foreign = beta.categories.create('Foreign', 'Expense')
    repo = PostgresMixedUseRepository(database, 'alpha')
    with pytest.raises(StorageValidationError):
        alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed(category_id=foreign['id']))

    def corrupt(data, refs, **options):
        source, projection = alpha.mixed_use.prepare_pair(data, refs, **options)
        source['allocated_amount'] = '99'
        return source, projection
    with pytest.raises(StorageValidationError):
        repo.create({**mixed(), 'source_id': 'source', 'linked_transaction_id': 'projection'}, build=corrupt)
    assert alpha.mixed_use.sources() == alpha.transactions.list() == beta.mixed_use.sources() == []


def test_receipt_limit_uses_source_baseline_and_preserves_one_hundred_links(database):
    alpha, _ = seed_core(database)
    with database.transaction() as connection:
        receipts = [document(connection, 'alpha', f'receipt-{index}') for index in range(101)]
    created = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed(), receipt_references=receipts[:100])
    with pytest.raises(StorageValidationError):
        alpha.mixed_use.link_receipt('source', expected_source=created, reference=receipts[100])
    assert alpha.mixed_use.get('source') == created
    assert len(alpha.transactions.list()[0]['receipt_references']) == 100
