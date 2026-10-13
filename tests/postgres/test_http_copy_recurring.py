"""Existing-workflow ports preserve independent copies and conversion ownership."""

import pytest
from sqlalchemy import text

from tests.postgres.core_support import expense
from tests.postgres.secondary_support import document, mixed
from tests.postgres.test_http_baselines import HEADERS, PREFIX, commercial as commercial, snapshot


def conversion(row, **changes):
    fields = ('txn_date', 'amount', 'account_id', 'category_id', 'payee_id', 'tag_ids', 'description', 'reference')
    return dict(baseline=row['baseline'], schedule_id='converted', name='Converted expense',
                recurrence_unit='month', recurrence_interval='1', end_date='',
                changes={**{field: row[field] for field in fields}, **changes})


@pytest.mark.parametrize('inline', [
    {'new_payee_name': 'Inline conversion vendor'},
    {'new_tag_name': 'Inline conversion tag'},
    {'new_payee_name': 'Inline conversion vendor', 'new_tag_name': 'Inline conversion tag'},
])
def test_full_conversion_draft_replay_confirms_inline_references_without_writes(database, commercial, inline):
    alpha, beta, (client, _), _ = commercial
    row = next(row for row in client.get(PREFIX + 'transactions').json()['items'] if row['id'] == 'expense')
    body = conversion(row, **{'payee_id': '', 'tag_ids': [], 'new_payee_name': '', 'new_tag_name': '', **inline})
    first = client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=body)
    assert first.status_code == 201, first.text
    committed = first.json()
    if 'new_payee_name' in inline:
        assert committed['schedule']['payee_id']
    if 'new_tag_name' in inline:
        assert len(committed['schedule']['tag_ids']) == 1
    saved = snapshot(database)
    repeated = client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=body)
    assert repeated.status_code == 201 and repeated.json() == committed
    assert snapshot(database) == saved
    assert len(alpha.recurring.list()) == len(alpha.transactions.list()) == 1
    assert not beta.recurring.list()
    if 'new_payee_name' in inline:
        changed_payee = {**body, 'changes': {**body['changes'], 'payee_id': row['payee_id']}}
        assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=changed_payee).status_code == 409
        assert snapshot(database) == saved
    different = {**body, 'changes': {**body['changes'], 'new_tag_name': 'A different requested tag'}}
    assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=different).status_code == 409
    assert snapshot(database) == saved


def test_mixed_copy_fresh_snapshot_new_pair_no_receipts_and_independent_save(database, commercial):
    alpha, beta, (client, _), ids = commercial
    source = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection',
                                   **mixed(description='Saved memo. Copy From older', payee_id=ids['payees'], tag_ids=[ids['tags']]))
    with database.transaction() as connection:
        receipt = document(connection, 'alpha')
    source = alpha.mixed_use.link_receipt('source', reference=receipt, expected_source=source)
    before = snapshot(database)
    response = client.post(PREFIX + 'mixed-use/source/copy-draft', headers=HEADERS)
    assert response.status_code == 200, response.text
    draft = response.json()
    assert snapshot(database) == before  # Initiation and cancellation create nothing.
    assert draft['source_id'] not in {'source', 'projection'}
    assert draft['linked_transaction_id'] not in {'source', 'projection', draft['source_id']}
    assert draft['copied_from_source_id'] == 'source'
    assert draft['description'] == 'Saved memo. Copy From source'
    assert draft['payee_id'] == ids['payees'] and draft['tag_ids'] == [ids['tags']]
    assert 'receipt_references' not in draft and 'recurring_schedule_id' not in draft
    changed = alpha.mixed_use.update('source', expected_source=source, description='Original changed', total_expense='200')
    response = client.post(PREFIX + 'mixed-use', headers=HEADERS, json={**draft, 'description': 'Edited copy memo. Copy From old',
                          'total_expense': '19.99', 'business_use_percentage': '50'})
    assert response.status_code == 201, response.text
    copied = alpha.mixed_use.get(draft['source_id'])
    assert copied['description'] == 'Edited copy memo. Copy From source'
    assert copied['allocated_amount'] == '10.00' and copied['receipt_references'] == []
    projection = next(row for row in alpha.transactions.list() if row['id'] == draft['linked_transaction_id'])
    assert projection['amount'] == '10.00' and projection['source_id'] == copied['id']
    assert not copied['recurring_schedule_id'] and not projection['recurring_schedule_id']
    assert alpha.mixed_use.get('source') == changed and not beta.mixed_use.sources()
    before = snapshot(database)
    assert client.post(PREFIX + 'mixed-use', headers=HEADERS, json={**draft, 'description': 'Edited copy memo. Copy From old',
                       'total_expense': '19.99', 'business_use_percentage': '50'}).status_code == 409
    assert snapshot(database) == before  # Stable identities block a duplicate after an uncertain save.


def test_mixed_copy_filters_inactive_associations_and_blocks_incomplete_foreign_sources(database, commercial):
    alpha, beta, (client, _), ids = commercial
    alpha.mixed_use.create(source_id='source', linked_transaction_id='projection',
                           **mixed(payee_id=ids['payees'], tag_ids=[ids['tags']]))
    alpha.payees.update(ids['payees'], active=False)
    alpha.tags.update(ids['tags'], active=False)
    draft = client.post(PREFIX + 'mixed-use/source/copy-draft', headers=HEADERS).json()
    assert draft['payee_id'] == '' and draft['tag_ids'] == []
    with database.transaction() as connection:
        connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,total_expense,
            business_use_percentage,allocated_amount,account_id,category_id,allocation_rationale,
            expected_projection_entry_id,relationship_state)
            VALUES ('alpha','incomplete','incarnation','2026-01-01',100,50,50,'cash','office','Inspection','missing','missing_projection')"""))
    beta.mixed_use.create(source_id='foreign', linked_transaction_id='foreign-projection', **mixed())
    before = snapshot(database)
    assert client.post(PREFIX + 'mixed-use/incomplete/copy-draft', headers=HEADERS).status_code == 422
    assert client.post(PREFIX + 'mixed-use/foreign/copy-draft', headers=HEADERS).status_code == 404
    assert client.post('/api/v1/entities/beta/mixed-use/foreign/copy-draft', headers=HEADERS).status_code == 403
    assert client.post(PREFIX + 'mixed-use/source/copy-draft').status_code == 403
    assert snapshot(database) == before


def test_existing_expense_conversion_updates_initial_only_and_preserves_receipts_identity_and_isolation(database, commercial):
    alpha, beta, (client, _), _ = commercial
    original = next(row for row in alpha.transactions.list() if row['id'] == 'expense')
    with database.transaction() as connection:
        receipt = document(connection, 'alpha')
    original = alpha.transactions.update('expense', receipt_references=[receipt], expected=original)
    row = next(row for row in client.get(PREFIX + 'transactions').json()['items'] if row['id'] == 'expense')
    body = conversion(row, txn_date='2026-01-31', amount='25.00', description='Converted saved edit')
    response = client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=body)
    assert response.status_code == 201, response.text
    detail = response.json()
    initial = alpha.transactions.list()[0]
    assert initial['id'] == original['id'] and initial['created_at'] == original['created_at']
    assert initial['receipt_references'] == original['receipt_references']
    assert initial['amount'] == '25.00' and initial['recurring_occurrence_type'] == 'initial'
    assert initial['recurring_scheduled_date'] == detail['schedule']['start_date'] == '2026-01-31'
    assert detail['schedule']['amount'] == '25.00' and len(detail['occurrences']) == 1
    before = snapshot(database)
    assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=body).status_code == 201
    assert snapshot(database) == before
    generated = alpha.recurring.reconcile(as_of='2026-02-28')['generated']
    assert len(generated) == 1 and generated[0]['receipt_references'] in ([], '[]')
    assert generated[0]['amount'] == '25.00' and generated[0]['recurring_occurrence_type'] == 'generated'
    assert not beta.recurring.list() and not beta.transactions.list()


def test_conversion_rejects_missing_stale_invalid_linked_derived_and_foreign_without_changes(database, commercial):
    alpha, beta, (client, _), _ = commercial
    row = next(row for row in client.get(PREFIX + 'transactions').json()['items'] if row['id'] == 'expense')
    body = conversion(row)
    changed = alpha.transactions.update('expense', expected={'baseline': row['baseline']}, amount='30.00')
    before = snapshot(database)
    response = client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=body)
    assert response.status_code == 409 and response.json()['error']['code'] == 'stale'
    assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS,
                       json={key: value for key, value in body.items() if key != 'baseline'}).json()['error']['code'] == 'baseline_required'
    assert snapshot(database) == before
    body = conversion(changed, amount='-1')
    assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=body).status_code == 422
    income = alpha.transactions.create(transaction_id='income', **expense(kind='Income', category_id='sales'))
    source = alpha.mixed_use.create(source_id='source', linked_transaction_id='projection', **mixed())
    projection = next(row for row in alpha.transactions.list() if row['id'] == source['linked_transaction_id'])
    foreign = beta.transactions.create(transaction_id='foreign', **expense())
    before = snapshot(database)
    for record in (income, projection):
        assert client.post(PREFIX + 'recurring/from-transaction/' + record['id'], headers=HEADERS,
                           json=conversion(record)).status_code == 422
    assert client.post(PREFIX + 'recurring/from-transaction/foreign', headers=HEADERS,
                       json=conversion(foreign)).status_code == 404
    assert client.post('/api/v1/entities/beta/recurring/from-transaction/foreign', headers=HEADERS,
                       json=conversion(foreign)).status_code == 403
    assert client.post(PREFIX + 'recurring/from-transaction/expense', json=conversion(changed)).status_code == 403
    assert snapshot(database) == before
    assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS, json=conversion(changed)).status_code == 201
    linked = next(row for row in alpha.transactions.list() if row['id'] == 'expense')
    before = snapshot(database)
    assert client.post(PREFIX + 'recurring/from-transaction/expense', headers=HEADERS,
                       json={**conversion(linked), 'schedule_id': 'second'}).status_code == 422
    assert snapshot(database) == before
