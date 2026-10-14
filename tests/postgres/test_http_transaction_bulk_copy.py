"""Existing transaction copy/batch owners through HTTP and two entity scopes."""

from dataclasses import replace
from unittest.mock import patch

from sqlalchemy import text

from tabula_rasa.errors import StorageError
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tests.postgres.core_support import expense
from tests.postgres.secondary_support import document, mixed
from tests.postgres.test_http_baselines import HEADERS, PREFIX, commercial as commercial, snapshot


def selected(client, identities):
    rows = client.get(PREFIX + 'transactions').json()['items']
    return {'transaction_ids': identities,
            'expected': [{'id': row['id'], 'baseline': row['baseline']} for row in rows if row['id'] in identities]}


def test_copy_prepares_independent_draft_active_associations_and_duplicate_safe_create(database, commercial):
    alpha, beta, (client, _), ids = commercial
    source = alpha.transactions.list()[0]
    alpha.transactions.update(source['id'], expected=source, description='Memo. Copy From old')
    alpha.tags.update(ids['tags'], active=False)
    alpha.payees.update(ids['payees'], active=False)
    row = client.get(PREFIX + 'transactions').json()['items'][0]
    before = snapshot(database)
    draft = client.post(PREFIX + 'transactions/expense/copy-draft', headers=HEADERS, json={'baseline': row['baseline']})
    assert draft.status_code == 200, draft.text
    fields = draft.json()
    assert fields['description'] == 'Memo. Copy From expense'
    assert fields['tag_ids'] == [] and fields['payee_id'] == ''
    assert not {'receipt_references', 'source_type', 'source_id', 'recurring_schedule_id'} & fields.keys()
    assert snapshot(database) == before  # Starting or cancelling a copy writes nothing.
    body = {**fields, 'transaction_id': 'copy', 'description': 'Edited memo. Copy From old', 'copied_from_transaction_id': 'expense'}
    created = client.post(PREFIX + 'transactions', headers=HEADERS, json=body)
    assert created.status_code == 201, created.text
    assert created.json()['id'] == 'copy' and created.json()['description'] == 'Edited memo. Copy From expense'
    copied = next(row for row in alpha.transactions.list() if row['id'] == 'copy')
    assert copied['receipt_references'] == [] and not copied.get('recurring_schedule_id') and not copied.get('source_type')
    after = snapshot(database)
    assert client.post(PREFIX + 'transactions', headers=HEADERS, json={**body, 'new_payee_name': 'Must not create'}).status_code == 409
    assert snapshot(database) == after and not beta.transactions.list()
    assert client.post(PREFIX.replace('alpha', 'beta') + 'transactions/expense/copy-draft', headers=HEADERS, json={'baseline': row['baseline']}).status_code == 403


def test_batch_updates_original_baselines_complete_selection_and_entity_scoped_references(database, commercial):
    alpha, beta, (client, other), ids = commercial
    alpha.transactions.create(transaction_id='second', **expense())
    beta.transactions.create(transaction_id='expense', **expense(description='Other entity'))
    loaded = selected(client, ['expense', 'second'])
    foreign = beta.tags.create('Other entity tag')
    before = snapshot(database)
    rejected = client.post(PREFIX + 'transactions/bulk/update', headers=HEADERS, json={**loaded, 'changes': {'tag_ids': [foreign['id']]}})
    assert rejected.status_code == 422 and snapshot(database) == before
    applied = client.post(PREFIX + 'transactions/bulk/update', headers=HEADERS, json={**loaded, 'changes': {'tag_ids': [ids['tags']], 'payee_id': ''}})
    assert applied.status_code == 200 and applied.json() == {'status': 'fully_applied', 'count': '2'}
    assert beta.transactions.list()[0]['description'] == 'Other entity'
    before = snapshot(database)
    stale = other.post(PREFIX + 'transactions/bulk/delete', headers=HEADERS, json=loaded)
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'stale'
    assert snapshot(database) == before
    latest = selected(client, ['expense', 'second'])
    for invalid in ({**latest, 'expected': latest['expected'][:1]}, {**latest, 'transaction_ids': ['expense', 'expense']},
                    {**latest, 'expected': [*latest['expected'], latest['expected'][0]]}):
        assert client.post(PREFIX + 'transactions/bulk/delete', headers=HEADERS, json=invalid).status_code in (409, 422)
        assert snapshot(database) == before
    changed_context = replace(client.app.state.runtime.resolve_context(None), entity_id='beta')
    original = client.app.state.runtime.resolve_context
    client.app.state.runtime.resolve_context = lambda request: changed_context
    try:
        wrong_entity = client.post(PREFIX.replace('alpha', 'beta') + 'transactions/bulk/delete', headers=HEADERS,
                                  json={'transaction_ids': ['expense'], 'expected': [next(row for row in loaded['expected'] if row['id'] == 'expense')]})
        assert wrong_entity.status_code == 409 and wrong_entity.json()['error']['code'] == 'stale'
        assert snapshot(database) == before
    finally:
        client.app.state.runtime.resolve_context = original


def test_copy_and_batch_reject_stale_journals_and_derived_sources_without_partial_writes(database, commercial):
    alpha, _, (client, _), _ = commercial
    original = selected(client, ['expense'])['expected'][0]
    source = alpha.transactions.list()[0]
    alpha.transactions.update('expense', expected=source, description='Fresh change')
    before = snapshot(database)
    stale = client.post(PREFIX + 'transactions/expense/copy-draft', headers=HEADERS, json={'baseline': original['baseline']})
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'stale'
    assert snapshot(database) == before
    derived = alpha.mixed_use.create(source_id='mixed', **mixed())
    projection = derived['linked_transaction_id']
    loaded = selected(client, ['expense', projection])
    before = snapshot(database)
    for action in ('update', 'delete'):
        body = {**loaded, **({'changes': {'payee_id': ''}} if action == 'update' else {})}
        assert client.post(PREFIX + 'transactions/bulk/' + action, headers=HEADERS, json=body).status_code == 422
        assert snapshot(database) == before
    token = next(row['baseline'] for row in loaded['expected'] if row['id'] == projection)
    assert client.post(PREFIX + f'transactions/{projection}/copy-draft', headers=HEADERS, json={'baseline': token}).status_code == 422
    journal = client.get(PREFIX + 'journals').json()['items'][0]
    assert client.post(PREFIX + 'transactions/bulk/delete', headers=HEADERS,
        json={'transaction_ids': ['expense', journal['id']], 'expected': [original, {'id': journal['id'], 'baseline': journal['baseline']}]}).status_code in (404, 409, 422)
    assert snapshot(database) == before


def test_batch_delete_atomic_failure_and_retained_document_files(database, commercial):
    alpha, _, (client, _), _ = commercial
    alpha.transactions.create(transaction_id='second', **expense())
    with database.transaction() as connection:
        receipt = document(connection, 'alpha')
    source = next(row for row in alpha.transactions.list() if row['id'] == 'expense')
    alpha.transactions.update('expense', expected=source, receipt_references=[receipt])
    loaded = selected(client, ['expense', 'second'])
    before = snapshot(database)
    original = PostgresTransactionRepository.delete_entry
    def fail_second(repository, connection, identity):
        if identity == 'second':
            raise StorageError('Synthetic mutation failure')
        original(repository, connection, identity)
    with patch.object(PostgresTransactionRepository, 'delete_entry', fail_second):
        failure = client.post(PREFIX + 'transactions/bulk/delete', headers=HEADERS, json=loaded)
    assert failure.status_code == 503 and snapshot(database) == before
    deleted = client.post(PREFIX + 'transactions/bulk/delete', headers=HEADERS, json=loaded)
    assert deleted.status_code == 200 and deleted.json()['count'] == '2'
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM documents')) == 1
        assert connection.scalar(text('SELECT count(*) FROM document_links')) == 0
