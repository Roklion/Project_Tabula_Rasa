"""Full RecurringService conformance, native failure isolation and provenance."""

from datetime import date

import pytest
from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tabula_rasa.infrastructure.postgres.recurring import PostgresRecurringRepository
from tabula_rasa.recurrence import occurrence_id
from tests.postgres.core_support import seed_core, expense
from tests.postgres.secondary_support import schedule, mixed, document


def test_schedule_crud_baselines_attention_and_entity_isolation(database):
    alpha, beta = seed_core(database)
    tag = alpha.tags.create('Synthetic job')
    created = alpha.recurring.create(schedule_id='schedule', **schedule(tag_ids=[tag['id']]))
    loaded = alpha.recurring.get('schedule')
    assert loaded['baseline'] == created['baseline']
    assert loaded['next_due_date'] == '2026-01-01'
    beta.recurring.create(schedule_id='schedule', **schedule(amount='99'))
    repo = PostgresRecurringRepository(database, 'alpha', transactions=alpha.transactions, mixed_use=alpha.mixed_use)
    repo.attention('schedule', 'storage')
    attention = alpha.recurring.get('schedule')
    assert attention['baseline'] == loaded['baseline']
    assert attention['attention_code'] == 'storage'
    paused = alpha.recurring.pause('schedule', expected_schedule=loaded)
    assert paused['status'] == 'paused'
    with pytest.raises(StorageConflictError):
        alpha.recurring.resume('schedule', expected_schedule=loaded)
    resumed = alpha.recurring.resume('schedule', expected_schedule=paused)
    assert resumed['status'] == 'active'
    assert beta.recurring.get('schedule')['amount'] == '99.00'
    alpha.recurring.end('schedule', expected_schedule=resumed)
    assert alpha.recurring.reconcile(as_of='2026-03-01')['generated'] == []


@pytest.mark.parametrize('failure', ['immediate', 'deferred'])
@pytest.mark.parametrize('fail_attention', [False, True])
def test_sql_failure_preserves_committed_results_later_schedule_attention_and_rerun(database, monkeypatch, failure, fail_attention):
    alpha, beta = seed_core(database)
    alpha.recurring.create(schedule_id='z-broken', **schedule())
    alpha.recurring.create(schedule_id='a-healthy', **schedule())
    beta.recurring.create(schedule_id='z-broken', **schedule(amount='99'))
    failed_id = occurrence_id('z-broken', date(2026, 2, 1), 'generated')
    write = PostgresTransactionRepository.write_lines

    def fail_one(self, connection, identity, lines):
        write(self, connection, identity, lines)
        if identity == failed_id and self.entity_id == 'alpha':
            if failure == 'immediate':
                connection.execute(text('SELECT 1/0'))
            else:
                connection.execute(text('UPDATE postings SET amount=amount+1 WHERE entity_id=:scope AND entry_id=:id AND position=2'),
                                   {'scope': self.entity_id, 'id': identity})
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail_one)
    if fail_attention:
        attention = PostgresRecurringRepository.attention

        def fail_mark(self, identity, code):
            if identity == 'z-broken' and code:
                with self.operation() as connection:
                    connection.execute(text('SELECT 1/0'))
            return attention(self, identity, code)
        monkeypatch.setattr(PostgresRecurringRepository, 'attention', fail_mark)
    result = alpha.recurring.reconcile(as_of='2026-03-01')
    code = 'storage' if failure == 'immediate' else 'validation'
    assert result['attention'] == {'z-broken': code}
    assert len(result['generated']) == 4
    persisted = alpha.transactions.list()
    assert {row['id'] for row in persisted} == {row['id'] for row in result['generated']}
    assert failed_id not in {row['id'] for row in persisted}
    assert alpha.recurring.get('z-broken')['attention_code'] == ('' if fail_attention else code)
    assert beta.transactions.list() == []
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM recurring_occurrences WHERE entity_id='alpha'")) == 4
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', write)
    rerun = alpha.recurring.reconcile(as_of='2026-03-01')
    assert len(rerun['generated']) == 2
    assert len(alpha.transactions.list()) == 6
    assert alpha.recurring.reconcile(as_of='2026-03-01') == {'generated': [], 'attention': {}}


@pytest.mark.parametrize('is_mixed', [False, True])
def test_initial_creation_conversion_and_repeated_reconciliation(database, is_mixed):
    alpha, beta = seed_core(database)
    data = {**schedule(), **(mixed() if is_mixed else {})}
    create = alpha.recurring.create_mixed_expense if is_mixed else alpha.recurring.create_expense
    first = create(schedule_id='initial', **data, new_payee_name='Vendor', new_tag_name='Job')
    assert first['transaction']['recurring_occurrence_type'] == 'initial'
    assert first['transaction']['payee'] == 'Vendor' and first['transaction']['tags'] == ['Job']
    repeat = create(schedule_id='initial', **data, new_payee_name='Vendor', new_tag_name='Job')
    assert repeat['transaction']['id'] == first['transaction']['id']
    assert repeat['transaction']['created_at'] == first['transaction']['created_at']
    generated = alpha.recurring.reconcile(as_of='2026-03-01')['generated']
    assert len(generated) == 2
    assert alpha.recurring.reconcile(as_of='2026-03-01')['generated'] == []
    assert beta.transactions.list() == []
    alpha.recurring.update('initial', amount='25', total_expense='75' if is_mixed else '')
    assert next(row for row in alpha.transactions.list() if row['id'] == first['transaction']['id'])['amount'] == ('33.33' if is_mixed else '12.50')
    with database.transaction() as connection:
        receipt = document(connection, 'alpha')
    if is_mixed:
        current = alpha.mixed_use.create(source_id='existing', linked_transaction_id='projection', **mixed(), receipt_references=[receipt])
        converted = alpha.recurring.from_mixed_use('existing', expected_source=current, schedule_id='converted', name='Converted')
        assert converted['source']['id'] == 'existing'
    else:
        current = alpha.transactions.create(transaction_id='existing', **expense(txn_date='2026-01-01', receipt_references=[receipt]))
        converted = alpha.recurring.from_transaction('existing', expected_transaction=current, schedule_id='converted', name='Converted')
    assert converted['transaction']['id'] == current.get('linked_transaction_id', current['id'])
    assert converted['transaction']['created_at'] == current['created_at']
    assert converted['transaction']['receipt_references'] == [receipt]
    assert converted['transaction']['recurring_occurrence_type'] == 'initial'


def test_initial_failure_rolls_back_schedule_occurrence_and_inline_references(database, monkeypatch):
    alpha, _ = seed_core(database)
    original = PostgresTransactionRepository.write_lines

    def fail(self, connection, identity, lines):
        original(self, connection, identity, lines)
        connection.execute(text('SELECT 1/0'))
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail)
    with pytest.raises(StorageError):
        alpha.recurring.create_expense(schedule_id='failed', **schedule(new_payee_name='Rollback', new_tag_name='Rollback'))
    assert alpha.recurring.list() == alpha.transactions.list() == alpha.payees.list() == alpha.tags.list() == []


def test_occurrence_boundary_and_cross_entity_references(database):
    alpha, beta = seed_core(database)
    foreign = beta.categories.create('Foreign', 'Expense')
    with pytest.raises(StorageValidationError):
        alpha.recurring.create(**schedule(category_id=foreign['id']))
    alpha.recurring.create(schedule_id='one', **schedule())
    with pytest.raises(StorageError) as error:
        with database.transaction():
            alpha.recurring.reconcile(as_of='2026-01-01')
    assert error.value.code == 'boundary_mismatch'
    with pytest.raises(StorageError):
        with database.transaction():
            alpha.transactions.create_occurrence(transaction_id='nested', **expense(), recurring_schedule_id='one',
                recurring_scheduled_date='2026-01-01', recurring_source_kind='transaction', recurring_occurrence_type='generated')
    assert alpha.transactions.list() == []


def test_ordinary_occurrence_edits_keep_provenance_and_deletion_removes_current_association(database):
    alpha, _ = seed_core(database)
    first = alpha.recurring.create_expense(schedule_id='one', **schedule())['transaction']
    changed = alpha.transactions.update(first['id'], expected=first, amount='19')
    assert changed['recurring_schedule_id'] == 'one'
    with pytest.raises(StorageValidationError):
        alpha.transactions.update(first['id'], recurring_scheduled_date='2026-02-01')
    alpha.transactions.delete(first['id'], expected=changed)
    assert len(alpha.recurring.reconcile(as_of='2026-01-01')['generated']) == 1


def test_mixed_occurrence_failure_rolls_back_pair_but_allows_healthy_schedule(database, monkeypatch):
    alpha, _ = seed_core(database)
    alpha.recurring.create(schedule_id='z-mixed', **{**schedule(), **mixed(), 'source_kind': 'mixed_use'})
    alpha.recurring.create(schedule_id='a-healthy', **schedule())
    failed_id = occurrence_id('z-mixed', date(2026, 2, 1), 'generated-projection')
    write = PostgresTransactionRepository.write_lines

    def fail_one(self, connection, identity, lines):
        write(self, connection, identity, lines)
        if identity == failed_id:
            connection.execute(text('SELECT 1/0'))
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail_one)
    result = alpha.recurring.reconcile(as_of='2026-03-01')
    assert result['attention'] == {'z-mixed': 'storage'} and len(result['generated']) == 4
    assert len(alpha.mixed_use.sources()) == 1 and len(alpha.transactions.list()) == 4
    assert failed_id not in {row['id'] for row in alpha.transactions.list()}
    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', write)
    assert len(alpha.recurring.reconcile(as_of='2026-03-01')['generated']) == 2
    assert len(alpha.mixed_use.sources()) == 3 and len(alpha.transactions.list()) == 6


@pytest.mark.parametrize('is_mixed', [False, True])
def test_initial_request_can_confirm_the_existing_generated_occurrence(database, is_mixed):
    alpha, _ = seed_core(database)
    data = {**schedule(), **(mixed() if is_mixed else {}), 'source_kind': 'mixed_use' if is_mixed else 'transaction'}
    alpha.recurring.create(schedule_id='existing', **data)
    assert len(alpha.recurring.reconcile(as_of='2026-01-01')['generated']) == 1
    create = alpha.recurring.create_mixed_expense if is_mixed else alpha.recurring.create_expense
    result = create(schedule_id='existing', **data)
    assert result['transaction']['recurring_occurrence_type'] == 'generated'
    assert len(alpha.transactions.list()) == 1
