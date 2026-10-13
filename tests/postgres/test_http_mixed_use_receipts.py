"""Source-owned receipt transport preserves pair, baseline and storage scope."""

from dataclasses import replace
from unittest.mock import patch

from sqlalchemy import text

from tabula_rasa.application.documents import DocumentError
from tabula_rasa.infrastructure.entity_documents import EntityDocumentStore
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
from tests.postgres.test_http_mileage_documents import (
    commercial as commercial, document_clients as document_clients,
    document_store as document_store, upload,
)
from tests.postgres.test_http_baselines import HEADERS, PREFIX, snapshot
from tests.postgres.secondary_support import mixed, schedule
from tests.test_application_documents import FakeDocumentStore


def source(client, identity='source', *, prefix=PREFIX):
    body = mixed(source_id=identity, linked_transaction_id=identity + ':projection')
    body.pop('kind')
    body.pop('amount')
    response = client.post(prefix + 'mixed-use', headers=HEADERS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def link(client, row, document_id, *, prefix=PREFIX):
    return client.post(prefix + 'mixed-use/' + row['id'] + '/receipts', headers=HEADERS,
                       json={'baseline': row['baseline'], 'document_id': document_id})


def test_source_receipts_share_projection_references_and_advance_loaded_baselines(database, commercial, document_clients, document_store):
    alpha, beta, _, _ = commercial
    client, _ = document_clients
    created = source(client)
    first, second = (upload(client, identity=identity * 32).json() for identity in ('a', 'b'))
    path = PREFIX + 'mixed-use/source/receipts'
    assert client.get(path).json()['items'] == []
    saved = link(client, created, first['id'])
    assert saved.status_code == 200, saved.text
    current = saved.json()
    assert current['baseline'] != created['baseline']
    saved = link(client, current, second['id'])
    assert saved.status_code == 200, saved.text
    current = saved.json()
    assert client.get(path).json()['items'] == [first, second]
    projection = next(row for row in alpha.transactions.list() if row['id'] == created['linked_transaction_id'])
    assert projection['receipt_references'] == alpha.mixed_use.get('source')['receipt_references']
    assert projection['amount'] == current['allocated_amount'] == '33.33'
    before = snapshot(database)
    generic = PREFIX + 'transactions/' + created['linked_transaction_id'] + '/receipts'
    assert client.post(generic, headers=HEADERS, json={'document_id': first['id']}).status_code == 422
    assert client.delete(generic + '/' + first['id'], headers=HEADERS).status_code == 422
    assert snapshot(database) == before
    removed = client.request('DELETE', path + '/' + first['id'], headers=HEADERS, json={'baseline': current['baseline']})
    assert removed.status_code == 200, removed.text
    assert client.get(path).json()['items'] == [second]
    assert client.get(PREFIX + 'documents').json()['items'] == [first]
    assert link(client, removed.json(), first['id']).status_code == 200
    assert client.get(path).json()['items'] == [second, first]
    assert document_store.upload_calls == 2 and document_store.delete_calls == 0
    # Financial editing after object-store attachment preserves opaque locators.
    loaded = client.get(PREFIX + 'mixed-use/source').json()
    edited = client.patch(PREFIX + 'mixed-use/source', headers=HEADERS,
                          json={'baseline': loaded['baseline'], 'changes': {
                              **{key: loaded[key] for key in ('txn_date', 'account_id', 'category_id',
                                  'total_expense', 'business_use_percentage', 'allocation_rationale')},
                              'description': 'Updated source'}})
    assert edited.status_code == 200, edited.text
    assert client.get(path).json()['items'] == [second, first]
    assert not beta.mixed_use.sources()
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM document_links WHERE entry_id IS NOT NULL')) == 0
        assert connection.scalar(text('SELECT count(*) FROM document_links WHERE mixed_use_source_id=\'source\'')) == 2


def test_stale_missing_and_wrong_source_baselines_stop_receipt_links_without_metadata(database, commercial, document_clients):
    alpha, _, _, _ = commercial
    client, other = document_clients
    created = source(client)
    document = upload(client).json()
    changed = alpha.mixed_use.update('source', expected_source=created, description='Other client edit')
    path = PREFIX + 'mixed-use/source/receipts'
    before = snapshot(database)
    for payload, code in [({'document_id': document['id']}, 'baseline_required'),
                          ({'baseline': '', 'document_id': document['id']}, 'baseline_required'),
                          ({'baseline': 'private-invalid', 'document_id': document['id']}, 'baseline_invalid')]:
        response = other.post(path, headers=HEADERS, json=payload)
        assert response.status_code == 422 and response.json()['error']['code'] == code
        assert 'private-invalid' not in response.text
    stale = link(other, created, document['id'])
    assert stale.status_code == 409 and stale.json()['error']['code'] == 'stale'
    assert snapshot(database) == before
    assert client.get(PREFIX + 'documents').json()['items'] == [document]
    fresh = link(client, changed, document['id'])
    assert fresh.status_code == 200
    before = snapshot(database)
    stale_remove = other.request('DELETE', path + '/' + document['id'], headers=HEADERS,
                                 json={'baseline': changed['baseline']})
    assert stale_remove.status_code == 409 and stale_remove.json()['error']['code'] == 'stale'
    unrelated = source(client, 'other')
    before = snapshot(database)
    wrong = link(other, {**fresh.json(), 'baseline': unrelated['baseline']}, document['id'])
    assert wrong.status_code == 409 and wrong.json()['error']['code'] == 'stale'
    assert snapshot(database) == before and client.get(path).json()['items'] == [document]


def test_uncertain_upload_failed_link_and_failed_unlink_keep_recoverable_bytes(database, commercial, document_clients, document_store, caplog):
    client, _ = document_clients
    created = source(client)
    document_store.fail_after_create = True
    assert upload(client).status_code == 503
    assert len(document_store.files) == document_store.upload_calls == 1
    document = upload(client).json()
    assert document_store.upload_calls == 1
    before = snapshot(database)
    with patch.object(PostgresReceiptRepository, 'link', side_effect=DocumentError('PRIVATE provider failure')), caplog.at_level('INFO', logger='tabula_rasa.http'):
        failed = link(client, created, document['id'])
    assert failed.status_code == 503 and 'PRIVATE' not in failed.text + caplog.text
    assert snapshot(database) == before
    assert client.get(PREFIX + 'documents').json()['items'] == [document]
    saved = link(client, created, document['id']).json()
    before = snapshot(database)
    with patch.object(PostgresReceiptRepository, 'unlink', side_effect=DocumentError('PRIVATE unlink failure')):
        failed = client.request('DELETE', PREFIX + 'mixed-use/source/receipts/' + document['id'],
                                headers=HEADERS, json={'baseline': saved['baseline']})
    assert failed.status_code == 503 and snapshot(database) == before
    assert client.get(PREFIX + 'mixed-use/source/receipts').json()['items'] == [document]
    assert document_store.upload_calls == 1 and document_store.delete_calls == 0


def test_two_selected_entities_keep_original_profile_grants_folders_and_same_portable_ids(database, commercial):
    _, _, (client, _), _ = commercial
    providers = {entity: FakeDocumentStore() for entity in ('alpha', 'beta')}
    for entity, provider in providers.items():
        provider.scope_key = entity + '-receipt-folder'
    stores = {entity: EntityDocumentStore(entity, entity + '-original-profile', provider)
              for entity, provider in providers.items()}
    runtime = client.app.state.runtime
    original = runtime.resolve_context
    runtime.resolve_context = lambda request: replace(original(request), entity_id=request.cookies.get('tabula_entity', 'alpha'))
    runtime.service_factory = lambda context: create_postgres_services(
        database, context.entity_id, document_store=stores[context.entity_id], document_store_kind='fake')
    created = source(client)
    alpha_document = upload(client, identity='a' * 32, content=b'%PDF alpha').json()
    alpha_only = upload(client, identity='b' * 32, content=b'%PDF alpha only').json()
    assert link(client, created, alpha_document['id']).status_code == 200
    client.cookies.set('tabula_entity', 'beta')
    beta_prefix = PREFIX.replace('alpha', 'beta')
    beta_source = source(client, prefix=beta_prefix)
    uploaded = client.put(beta_prefix + 'documents/' + 'a' * 32 + '/content', params={'filename': 'receipt.pdf'},
                          headers={**HEADERS, 'Content-Type': 'application/octet-stream'}, content=b'%PDF beta')
    assert uploaded.status_code == 200
    assert link(client, beta_source, uploaded.json()['id'], prefix=beta_prefix).status_code == 200
    before = snapshot(database)
    assert client.get(PREFIX + 'mixed-use/source/receipts').status_code == 403
    assert client.get(beta_prefix + 'documents/' + alpha_only['id'] + '/content').status_code == 404
    fresh_beta = client.get(beta_prefix + 'mixed-use/source').json()
    assert link(client, fresh_beta, alpha_only['id'], prefix=beta_prefix).status_code == 404
    assert snapshot(database) == before
    assert client.get(beta_prefix + 'documents/' + 'a' * 32 + '/content').content == b'%PDF beta'
    client.cookies.set('tabula_entity', 'alpha')
    assert client.get(PREFIX + 'documents/' + 'a' * 32 + '/content').content == b'%PDF alpha'
    assert tuple(providers['alpha'].files) == (('alpha-original-profile', 'a' * 32), ('alpha-original-profile', 'b' * 32))
    assert tuple(providers['beta'].files) == (('beta-original-profile', 'a' * 32),)
    with database.transaction(read_only=True) as connection:
        assert set(connection.execute(text('SELECT entity_id,store_scope_key FROM documents')).all()) == {
            ('alpha', 'alpha-receipt-folder'), ('beta', 'beta-receipt-folder')}


def test_generated_mixed_occurrences_own_receipts_and_inconsistent_pairs_refuse_changes(database, commercial, document_clients, document_store):
    alpha, _, _, _ = commercial
    client, _ = document_clients
    alpha.recurring.create_mixed_expense(schedule_id='schedule', **schedule(
        source_kind='mixed_use', total_expense='100.00', business_use_percentage='50', allocation_rationale='Business use'))
    alpha.recurring.reconcile(as_of='2026-02-01')
    rows = client.get(PREFIX + 'mixed-use').json()['items']
    assert len(rows) == 2
    generated = next(row for row in rows if row['recurring_occurrence_type'] == 'generated')
    initial = next(row for row in rows if row['recurring_occurrence_type'] == 'initial')
    document = upload(client).json()
    assert link(client, generated, document['id']).status_code == 200
    assert client.get(PREFIX + 'mixed-use/' + initial['id'] + '/receipts').json()['items'] == []
    assert client.get(PREFIX + 'recurring/schedule/receipts').status_code == 404
    assert 'receipt_references' not in client.get(PREFIX + 'recurring/schedule').json()['schedule']
    # An explicitly incomplete imported relationship cannot be repaired through receipts.
    with database.transaction() as connection:
        connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,total_expense,
            business_use_percentage,allocated_amount,account_id,category_id,allocation_rationale,
            expected_projection_entry_id,relationship_state)
            VALUES ('alpha','incomplete','incarnation','2026-01-01',100,50,50,'cash','office','Inspection','missing','missing_projection')"""))
    incomplete = next(row for row in client.get(PREFIX + 'mixed-use').json()['items'] if row['id'] == 'incomplete')
    before = snapshot(database)
    assert link(client, incomplete, document['id']).status_code == 422
    assert snapshot(database) == before and document_store.delete_calls == 0
