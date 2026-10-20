"""Core alpha workflows through real HTTP/services/PostgreSQL, with two entities."""

from copy import deepcopy
from decimal import Decimal, localcontext

from fastapi.testclient import TestClient

from tabula_rasa.http.app import create_app
from tabula_rasa.http.composition import PostgresRuntime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import TrustedDevelopmentContext
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tests.postgres.core_support import expense, journal_lines
from tests.postgres.test_http_baselines import HEADERS, PREFIX, commercial as commercial, snapshot


def create(client, resource, body):
    result = client.post(PREFIX + resource, headers=HEADERS, json=body)
    assert result.status_code == 201, result.text
    return result.json()


def test_summary_preserves_native_numeric_precision_and_entity_isolation(commercial):
    alpha, beta, (client, _), _ = commercial
    amount = '99999999999999999999999999.99'
    parent = create(client, 'accounts', {'name': 'Large balance', 'type': 'Bank', 'opening_balance': amount})
    create(client, 'accounts', {'name': 'One cent child', 'type': 'Bank', 'opening_balance': '0.01', 'parent_id': parent['id']})
    create(client, 'transactions', dict(transaction_id='large-income', **expense(kind='Income', amount=amount, account_id=parent['id'], category_id='sales')))
    response = client.get(PREFIX + 'reports/summary')
    assert response.status_code == 200, response.text
    result = response.json()
    with localcontext(prec=60):
        direct = format(Decimal(amount) * 2, '.2f')
        rollup = format(Decimal(amount) * 2 + Decimal('0.01'), '.2f')
        total = format(Decimal(amount) * 2 + Decimal('0.01') - Decimal('25.00'), '.2f')
        net = format(Decimal(amount) - Decimal('25.00'), '.2f')
    assert result['profit_loss'] == {'income': amount, 'expenses': '25.00', 'net': net}
    assert result['balance_sheet']['current_earnings'] == net
    assert result['balance_sheet']['total_assets'] == total
    projected = next(row for row in result['balance_sheet']['assets'] if row['id'] == parent['id'])
    assert projected['direct_balance'] == direct and projected['rollup_balance'] == rollup
    assert next(row for row in result['account_balances'] if row['id'] == parent['id'])['balance'] == direct
    assert beta.reporting.period_report(beta.reporting.read_ledger()).totals == {'income': 0.0, 'expenses': 0.0, 'net': 0.0}
    assert not any(row.id == parent['id'] for row in beta.reporting.read_ledger().accounts)


def test_reference_setup_and_supported_removal(database, commercial):
    alpha, beta, (client, _), _ = commercial
    parent = create(client, 'accounts', {'name': 'Bank parent', 'type': 'Bank', 'opening_balance': '100.00'})
    child = create(client, 'accounts', {'name': 'Bank child', 'type': 'Bank', 'parent_id': parent['id']})
    result = client.patch(PREFIX + 'accounts/' + child['id'], headers=HEADERS,
        json={'baseline': child['baseline'], 'changes': {'name': 'Renamed child', 'type': 'Bank', 'classification': 'Asset',
              'opening_balance': '1.00', 'active': True, 'parent_id': parent['id']}})
    assert result.status_code == 200
    result = client.post(PREFIX + 'accounts/' + child['id'] + '/deactivate', headers=HEADERS, json={'baseline': result.json()['baseline']})
    assert result.status_code == 200 and result.json()['active'] is False
    category = create(client, 'categories', {'name': 'New expenses', 'kind': 'Expense'})
    category_child = create(client, 'categories', {'name': 'Subcategory', 'kind': 'Expense', 'parent_id': category['id']})
    before = snapshot(database)
    invalid = client.post(PREFIX + 'categories', headers=HEADERS, json={'name': 'Invalid child', 'kind': 'Income', 'parent_id': category['id']})
    assert invalid.status_code == 422 and snapshot(database) == before
    assert client.request('DELETE', PREFIX + 'categories/' + category_child['id'], headers=HEADERS, json={'baseline': category_child['baseline']}).status_code == 200
    for resource in ('payees', 'tags'):
        record = create(client, resource, {'name': 'New reference'})
        assert record['active'] and record['baseline']
        assert client.request('DELETE', PREFIX + resource + '/' + record['id'], headers=HEADERS, json={'baseline': record['baseline']}).status_code == 200
    assert not any(row['name'].startswith('Bank ') for row in beta.accounts.list(active_only=False))


def test_transaction_inline_creation_edit_delete_and_rejected_inputs(database, commercial):
    alpha, beta, (client, _), _ = commercial
    body = dict(transaction_id='new-transaction', **expense(amount='25.00', description='Created in HTTP', new_payee_name='Inline vendor', new_tag_name='Inline tag'))
    row = create(client, 'transactions', body)
    assert row['payee_id'] and len(row['tag_ids']) == 1
    before = snapshot(database)
    assert client.post(PREFIX + 'transactions', headers=HEADERS, json=body).status_code == 409
    assert snapshot(database) == before
    alien = beta.accounts.create('Beta only', 'Cash')['id']
    alien_payee = beta.payees.create('Beta vendor')['id']
    for changes in ({'account_id': alien}, {'payee_id': alien_payee}, {'amount': '-1'}, {'category_id': 'missing'}):
        before = snapshot(database)
        response = client.post(PREFIX + 'transactions', headers=HEADERS, json={**body, 'transaction_id': 'invalid', **changes})
        assert response.status_code == 422, response.text
        assert snapshot(database) == before
    edited = client.patch(PREFIX + 'transactions/' + row['id'], headers=HEADERS, json={'baseline': row['baseline'],
        'changes': expense(amount='30.00', description='Updated in HTTP')})
    assert edited.status_code == 200 and edited.json()['amount'] == '30.00'
    assert client.request('DELETE', PREFIX + 'transactions/' + row['id'], headers=HEADERS, json={'baseline': edited.json()['baseline']}).status_code == 200
    assert not beta.transactions.list()


def test_journal_create_invalid_atomicity_and_cross_entity_references(database, commercial):
    alpha, beta, (client, _), _ = commercial
    body = {'entry_id': 'new-journal', 'txn_date': '2026-10-06', 'description': 'New journal', 'postings': journal_lines(prefix='new-')}
    row = create(client, 'journals', body)
    assert len(row['postings']) == 2 and row['baseline']
    alien = beta.categories.create('Beta only', 'Expense')['id']
    for change in ({'amount': '1.00'}, {'target_id': alien}):
        invalid = deepcopy(body)
        invalid['entry_id'] = 'invalid-journal'
        invalid['postings'][0].update(change)
        before = snapshot(database)
        response = client.post(PREFIX + 'journals', headers=HEADERS, json=invalid)
        assert response.status_code == 422, response.text
        assert snapshot(database) == before
    updated = client.patch(PREFIX + 'journals/' + row['id'], headers=HEADERS, json={'baseline': row['baseline'], 'changes': {
        'txn_date': '2026-10-07', 'description': 'Updated journal', 'postings': row['postings']}})
    assert updated.status_code == 200
    assert client.request('DELETE', PREFIX + 'journals/' + row['id'], headers=HEADERS, json={'baseline': updated.json()['baseline']}).status_code == 200


def test_ledger_and_reports_preserve_filters_accounting_and_history(commercial):
    alpha, beta, (client, _), ids = commercial
    transfer = create(client, 'transactions', dict(transaction_id='transfer', **expense(kind='Transfer', amount='100.00', category_id='', to_account_id='bank')))
    alpha.payees.update(ids['payees'], active=False)
    ledger = client.get(PREFIX + 'ledger').json()['items']
    assert {row['id'] for row in ledger} == {'expense', 'transfer', 'journal:journal'}
    assert next(row for row in ledger if row['id'] == 'expense')['payee'] == 'Vendor'
    assert len(next(row for row in ledger if row['id'] == 'journal:journal')['postings']) == 2
    for query, expected in [('kind=Transfer', {transfer['id']}), ('kind=Journal', {'journal:journal'}),
                            ('start=2026-10-05&end=2026-10-05', {'expense', 'transfer', 'journal:journal'}),
                            ('start=2026-10-06', set()), ('account_ids=bank', {'transfer'}),
                            ('category_ids=office', {'expense', 'journal:journal'}),
                            ('account_ids=bank&category_ids=office', {'expense', 'transfer', 'journal:journal'}),
                            ('tag_ids=' + ids['tags'], {'expense'})]:
        response = client.get(PREFIX + 'ledger?' + query)
        assert response.status_code == 200
        assert {row['id'] for row in response.json()['items']} == expected
    report = client.get(PREFIX + 'reports/summary').json()
    snapshot_ = alpha.reporting.read_ledger(force_refresh=True)
    totals = alpha.reporting.period_report(snapshot_).totals
    assert report['profit_loss'] == {key: f'{value:.2f}' for key, value in totals.items()}
    assert report['profit_loss']['expenses'] == '25.00'  # One simple expense, one journal. Transfer/mileage excluded.
    assert client.get(PREFIX + 'reports/summary?start=2026-10-06').json()['profit_loss']['expenses'] == '0.00'
    for path in ('ledger', 'reports/summary'):
        assert client.get('/api/v1/entities/beta/' + path).status_code == 403
        assert client.get(PREFIX + path + '?start=2026-10-07&end=2026-10-01').status_code == 422
    assert not beta.reporting.read_ledger().transactions


def test_alpha_entity_selection_is_per_client_and_server_bounded(database, commercial):
    resolver = TrustedDevelopmentContext('alpha', 'csrf', entity_ids=('beta',))
    runtime = PostgresRuntime(database, resolver, service_factory=lambda context: create_postgres_services(database, context.entity_id))
    runtime.close = lambda: None
    settings = HttpSettings('test', 'http://testserver')
    with TestClient(create_app(settings=settings, runtime_factory=lambda _: runtime), client=('127.0.0.1', 50000)) as first, \
            TestClient(create_app(settings=settings, runtime_factory=lambda _: runtime), client=('127.0.0.1', 50001)) as second:
        assert {row['id'] for row in first.get('/api/v1/entities').json()['items']} == {'alpha', 'beta'}
        assert first.post('/api/v1/session/entity', headers=HEADERS, json={'entity_id': 'outside'}).status_code == 403
        assert first.post('/api/v1/session/entity', json={'entity_id': 'beta'}).status_code == 403
        switched = first.post('/api/v1/session/entity', headers=HEADERS, json={'entity_id': 'beta'})
        assert switched.status_code == 200 and switched.json()['entity']['id'] == 'beta'
        assert 'HttpOnly' in switched.headers['set-cookie'] and 'SameSite=strict' in switched.headers['set-cookie']
        assert first.get(PREFIX + 'transactions').status_code == 403
        assert first.get('/api/v1/entities/beta/transactions').json()['items'] == []
        assert second.get('/api/v1/session').json()['entity']['id'] == 'alpha'
        assert len(second.get(PREFIX + 'transactions').json()['items']) == 1
        # Development selection cannot bypass the named membership resolver.
        assert commercial[2][0].post('/api/v1/session/entity', headers=HEADERS, json={'entity_id': 'alpha'}).status_code == 403


def test_transaction_create_rejects_reserved_projection_identity(database, commercial):
    _, beta, (client, _), _ = commercial
    body = dict(transaction_id='journal:reserved', **expense(new_payee_name='Must not create', new_tag_name='Must not create'))
    for identity in ('journal:reserved', ' journal:reserved '):
        before = snapshot(database)
        response = client.post(PREFIX + 'transactions', headers=HEADERS, json={**body, 'transaction_id': identity})
        assert response.status_code == 422 and response.json()['error']['code'] == 'validation'
        assert snapshot(database) == before
    create(client, 'journals', dict(entry_id='reserved', txn_date='2026-10-06', description='Valid journal', postings=journal_lines(prefix='reserved-')))
    before = snapshot(database)
    assert client.post(PREFIX + 'transactions', headers=HEADERS, json=body).status_code == 422
    assert snapshot(database) == before
    assert client.get(PREFIX + 'ledger').status_code == 200
    assert not beta.transactions.list()
