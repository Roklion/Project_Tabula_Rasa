"""Secondary slices through HTTP/services/native PostgreSQL, with two entities."""

from copy import deepcopy

import pytest
from sqlalchemy import text

from tabula_rasa.depreciation_posting import depreciation_entry_id
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.infrastructure.postgres.accounting import PostgresTransactionRepository
from tests.postgres.secondary_support import asset, mixed
from tests.postgres.test_http_baselines import HEADERS, PREFIX, commercial as commercial, snapshot


def create(client, resource, data):
    if resource == 'assets':
        data = {**data, 'useful_life_quarters': str(data['useful_life_quarters'])}
    response = client.post(PREFIX + resource, headers=HEADERS, json=data)
    assert response.status_code == 201, response.text
    return response.json()


def schedule(**changes):
    return dict(schedule_id='schedule', name='Synthetic subscription', start_date='2026-01-01',
                recurrence_unit='month', amount='10.00', account_id='cash', category_id='office', **changes)


def test_recurring_initial_atomicity_provenance_readonly_navigation_and_explicit_generation(database, commercial):
    alpha, beta, (client, _), _ = commercial
    body = schedule()
    created = create(client, 'recurring', body)
    assert created['baseline']
    before = snapshot(database)
    assert client.post(PREFIX + 'recurring', headers=HEADERS, json=body).status_code == 201
    assert snapshot(database) == before
    for path in ('recurring', 'recurring/schedule', 'transactions', 'ledger', 'reports/summary'):
        response = client.get(PREFIX + path)
        assert response.status_code == 200, response.text
    assert snapshot(database) == before  # Visits never generate due occurrences.
    detail = client.get(PREFIX + 'recurring/schedule').json()
    assert detail['schedule']['next_due_date'] == '2026-02-01'
    assert detail['schedule']['latest_current_occurrence_date'] == '2026-01-01'
    assert len(detail['occurrences']) == 1
    assert detail['occurrences'][0]['recurring_occurrence_type'] == 'initial'
    result = client.post(PREFIX + 'recurring/reconcile', headers=HEADERS, json={'through_date': '2026-03-01'})
    assert result.status_code == 200 and result.json() == {'generated_count': 2, 'attention_count': 0}
    assert client.post(PREFIX + 'recurring/reconcile', headers=HEADERS, json={'through_date': '2026-03-01'}).json()['generated_count'] == 0
    occurrences = client.get(PREFIX + 'recurring/schedule').json()['occurrences']
    assert {row['recurring_scheduled_date'] for row in occurrences} == {'2026-01-01', '2026-02-01', '2026-03-01'}
    assert len({row['id'] for row in occurrences}) == 3
    assert not beta.recurring.list() and not beta.transactions.list()
    invalid = {**body, 'schedule_id': 'invalid', 'category_id': 'sales'}
    before = snapshot(database)
    assert client.post(PREFIX + 'recurring', headers=HEADERS, json=invalid).status_code == 422
    assert snapshot(database) == before


def test_schedule_edits_transitions_keep_occurrences_and_require_loaded_baselines(database, commercial):
    alpha, _, (client, other), _ = commercial
    create(client, 'recurring', schedule())
    loaded = client.get(PREFIX + 'recurring/schedule').json()['schedule']
    fields = {name: loaded[name] for name in ('name', 'recurrence_unit', 'recurrence_interval', 'end_date', 'amount', 'total_expense',
                                            'business_use_percentage', 'allocation_rationale', 'account_id', 'category_id', 'payee_id', 'tag_ids', 'description', 'reference')}
    fields['amount'] = '12.00'
    response = client.patch(PREFIX + 'recurring/schedule', headers=HEADERS, json={'baseline': loaded['baseline'], 'changes': fields})
    assert response.status_code == 200, response.text
    current = response.json()
    assert alpha.recurring.detail('schedule')['transactions'][0]['amount'] == '10.00'
    before = snapshot(database)
    for action in ('pause', 'resume', 'end'):
        stale = other.post(PREFIX + 'recurring/schedule/' + action, headers=HEADERS, json={'baseline': loaded['baseline']})
        assert stale.status_code == 409 and stale.json()['error']['code'] == 'stale'
        missing = other.post(PREFIX + 'recurring/schedule/' + action, headers=HEADERS, json={})
        assert missing.status_code == 422 and missing.json()['error']['code'] == 'baseline_required'
    assert snapshot(database) == before
    for action, expected in [('pause', 'paused'), ('resume', 'active'), ('end', 'ended')]:
        response = client.post(PREFIX + 'recurring/schedule/' + action, headers=HEADERS, json={'baseline': current['baseline']})
        assert response.status_code == 200 and response.json()['status'] == expected
        current = response.json()
    assert alpha.recurring.detail('schedule')['transactions'][0]['amount'] == '10.00'
    assert client.post(PREFIX + 'recurring/schedule/resume', headers=HEADERS, json={'baseline': current['baseline']}).status_code == 422


def test_recurring_mixed_initial_and_generated_pairs_share_provenance(commercial):
    alpha, beta, (client, _), _ = commercial
    body = schedule(source_kind='mixed_use', total_expense='100.00', business_use_percentage='33.33333', allocation_rationale='Business use')
    create(client, 'recurring', body)
    result = client.post(PREFIX + 'recurring/reconcile', headers=HEADERS, json={'through_date': '2026-02-01'})
    assert result.status_code == 200 and result.json()['generated_count'] == 1
    detail = client.get(PREFIX + 'recurring/schedule').json()
    assert len(detail['occurrences']) == len(detail['mixed_sources']) == 2
    for source in detail['mixed_sources']:
        projection = next(row for row in detail['occurrences'] if row['id'] == source['linked_transaction_id'])
        assert projection['amount'] == source['allocated_amount'] == '33.33'
        assert projection['source_id'] == source['id']
        for field in ('recurring_schedule_id', 'recurring_scheduled_date', 'recurring_occurrence_type'):
            assert source[field] == projection[field]
    assert len(alpha.mixed_use.list()) == 2 and not beta.mixed_use.sources()


def test_mixed_preview_pair_edits_failure_isolation_and_protected_delete(database, commercial):
    alpha, beta, (client, other), _ = commercial
    body = mixed(source_id='source', linked_transaction_id='projection')
    body.pop('kind')
    body.pop('amount')
    created = create(client, 'mixed-use', body)
    assert created['allocated_amount'] == '33.33'
    preview = client.post(PREFIX + 'mixed-use/allocation', headers=HEADERS, json={'total_expense': '19.99', 'business_use_percentage': '50'})
    assert preview.status_code == 200 and preview.json()['allocated_amount'] == '10.00'
    expected = deepcopy(created)
    changes = {key: value for key, value in body.items() if key not in {'source_id', 'linked_transaction_id'}}
    response = client.patch(PREFIX + 'mixed-use/source', headers=HEADERS, json={'baseline': created['baseline'], 'changes': {**changes, 'total_expense': '200.00'}})
    assert response.status_code == 200 and response.json()['allocated_amount'] == '66.67'
    projection = next(row for row in alpha.transactions.list(fresh=True) if row['id'] == 'projection')
    assert projection['amount'] == '66.67'
    before = snapshot(database)
    for method, data in [('PATCH', {'baseline': expected['baseline'], 'changes': changes}), ('DELETE', {'baseline': expected['baseline']})]:
        stale = other.request(method, PREFIX + 'mixed-use/source', headers=HEADERS, json=data)
        assert stale.status_code == 409 and stale.json()['error']['code'] == 'stale'
    alien = beta.accounts.create('Foreign', 'Cash')['id']
    before = snapshot(database)
    assert client.patch(PREFIX + 'mixed-use/source', headers=HEADERS, json={'baseline': response.json()['baseline'], 'changes': {**changes, 'account_id': alien}}).status_code == 422
    assert snapshot(database) == before
    assert client.request('DELETE', PREFIX + 'transactions/projection', headers=HEADERS,
                          json={'baseline': projection['baseline']}).status_code == 422
    assert client.request('DELETE', PREFIX + 'mixed-use/source', headers=HEADERS, json={'baseline': response.json()['baseline']}).status_code == 200
    assert alpha.mixed_use.sources() == [] and not any(row['id'] == 'projection' for row in alpha.transactions.list())
    assert not beta.mixed_use.sources()


def test_incomplete_mixed_source_remains_inspectable_without_mutations(database, commercial):
    alpha, _, (client, _), _ = commercial
    # The supported migration path can preserve an inspectable missing projection.
    with database.transaction() as connection:
        connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,total_expense,
            business_use_percentage,allocated_amount,account_id,category_id,allocation_rationale,
            expected_projection_entry_id,relationship_state)
            VALUES ('alpha','incomplete','incarnation','2026-01-01',100,50,50,'cash','office','Inspection','missing','missing_projection')"""))
    response = client.get(PREFIX + 'mixed-use')
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()['items'] if row['id'] == 'incomplete')
    assert row['ledger_status'] != 'linked'
    before = snapshot(database)
    assert client.request('DELETE', PREFIX + 'mixed-use/incomplete', headers=HEADERS, json={'baseline': row['baseline']}).status_code == 422
    assert snapshot(database) == before
    assert alpha.mixed_use.sources()[0]['id'] == 'incomplete'


def test_asset_schedule_override_posting_immutability_duplicate_prevention_and_isolation(database, commercial):
    alpha, beta, (client, _), _ = commercial
    offset = alpha.accounts.create('Accumulated depreciation', 'Other', classification='Asset')['id']
    body = asset(offset, asset_id='asset')
    types = client.get(PREFIX + 'assets/types')
    assert types.status_code == 200 and 'Computers & office equipment' in types.json()['items'], types.text
    row = create(client, 'assets', body)
    detail = client.get(PREFIX + 'assets/asset').json()
    assert [period['depreciation_amount'] for period in detail['schedule']] == ['25.00'] * 4
    assert detail['can_delete'] and detail['history'] == []
    before = snapshot(database)
    assert client.get(PREFIX + 'assets/asset').status_code == 200 and snapshot(database) == before
    overridden = client.put(PREFIX + 'assets/asset/overrides/1', headers=HEADERS, json={'baseline': row['baseline'], 'amount': '10.00', 'reason': 'Historical correction', 'as_of_date': '2026-12-31'})
    assert overridden.status_code == 200, overridden.text
    detail = client.get(PREFIX + 'assets/asset').json()
    assert detail['terms_locked'] and not detail['posting_accounts_locked'] and not detail['can_delete']
    assert detail['schedule'][0]['override_reason'] == 'Historical correction'
    row = client.request('DELETE', PREFIX + 'assets/asset/overrides/1', headers=HEADERS, json={'baseline': overridden.json()['baseline']}).json()
    posted = client.post(PREFIX + 'assets/asset/post', headers=HEADERS, json={'baseline': row['baseline'], 'through_date': '2026-06-30'})
    assert posted.status_code == 200 and posted.json() == {'posted_count': 2, 'entry_ids': [depreciation_entry_id('asset', 1), depreciation_entry_id('asset', 2)]}
    detail = client.get(PREFIX + 'assets/asset').json()
    assert [period['posting_status'] for period in detail['schedule']] == ['Posted', 'Posted', 'Pending', 'Pending']
    assert len(detail['history']) == 2 and all(item['source_type'] == 'depreciation' and item['source_id'] == 'asset' for item in detail['history'])
    assert detail['posting_accounts_locked'] and not detail['can_delete']
    assert client.post(PREFIX + 'assets/asset/post', headers=HEADERS, json={'baseline': detail['asset']['baseline'], 'through_date': '2026-06-30'}).json()['posted_count'] == 0
    before = snapshot(database)
    for method, suffix, extra in [('POST', '/post', {'through_date': '2026-09-30'}), ('DELETE', '', {}),
                                  ('PUT', '/overrides/3', {'amount': '0.00', 'reason': 'No', 'as_of_date': '2026-12-31'})]:
        result = client.request(method, PREFIX + 'assets/asset' + suffix, headers=HEADERS, json={'baseline': row['baseline'], **extra})
        assert result.status_code == 409 and result.json()['error']['code'] == 'stale'
    assert snapshot(database) == before
    assert not beta.assets.list() and not beta.transactions.list()
    current = client.get(PREFIX + 'assets/asset').json()['asset']
    changes = {name: current[name] for name in ('name', 'asset_type', 'notes', 'acquisition_date', 'depreciation_start_date', 'cost_basis',
               'salvage_value', 'useful_life_quarters', 'depreciation_expense_account_id', 'accumulated_depreciation_account_id', 'payee_id',
               'tag_ids', 'reference', 'source_transaction_id', 'status', 'retired_date')}
    before = snapshot(database)
    assert client.patch(PREFIX + 'assets/asset', headers=HEADERS, json={'baseline': current['baseline'], 'changes': {**changes, 'cost_basis': '200.00'}}).status_code == 409
    assert client.put(PREFIX + 'assets/asset/overrides/3', headers=HEADERS, json={'baseline': current['baseline'], 'amount': '0.00', 'reason': 'No', 'as_of_date': '2026-12-31'}).status_code == 409
    assert client.request('DELETE', PREFIX + 'assets/asset', headers=HEADERS, json={'baseline': current['baseline']}).status_code == 409
    assert snapshot(database) == before
    changed = client.patch(PREFIX + 'assets/asset', headers=HEADERS, json={'baseline': current['baseline'], 'changes': {**changes, 'notes': 'Descriptive correction'}})
    assert changed.status_code == 200 and changed.json()['baseline'] != current['baseline']


def test_reconciliation_failure_reports_attention_without_false_generation(commercial):
    alpha, _, (client, _), _ = commercial
    create(client, 'recurring', schedule())
    alpha.accounts.deactivate('cash')
    response = client.post(PREFIX + 'recurring/reconcile', headers=HEADERS, json={'through_date': '2026-02-01'})
    assert response.status_code == 200 and response.json() == {'generated_count': 0, 'attention_count': 1}
    detail = client.get(PREFIX + 'recurring/schedule').json()
    assert detail['schedule']['attention_code'] and detail['schedule']['attention_message']
    assert len(detail['occurrences']) == 1


def test_posting_failure_rolls_back_all_periods_and_preserves_loaded_token(database, commercial, monkeypatch):
    alpha, _, (client, _), _ = commercial
    offset = alpha.accounts.create('Accumulated depreciation', 'Other', classification='Asset')['id']
    row = create(client, 'assets', asset(offset, asset_id='asset'))
    original = PostgresTransactionRepository.write_lines

    def fail(self, connection, identity, lines):
        original(self, connection, identity, lines)
        if identity == depreciation_entry_id('asset', 2):
            raise StorageValidationError('synthetic private diagnostic')

    monkeypatch.setattr(PostgresTransactionRepository, 'write_lines', fail)
    before = snapshot(database)
    response = client.post(PREFIX + 'assets/asset/post', headers=HEADERS, json={'baseline': row['baseline'], 'through_date': '2026-06-30'})
    assert response.status_code == 422 and 'private' not in response.text
    assert snapshot(database) == before
    assert client.get(PREFIX + 'assets/asset').json()['history'] == []


@pytest.mark.parametrize('resource', ['assets', 'mixed-use', 'recurring'])
def test_secondary_routes_enforce_context_csrf_and_missing_baseline(commercial, resource):
    _, _, (client, _), _ = commercial
    assert client.get('/api/v1/entities/beta/' + resource).status_code == 403
    assert client.post(PREFIX + resource, json={}).status_code == 403
    response = client.patch(PREFIX + resource + '/missing', headers=HEADERS, json={'changes': {}})
    assert response.status_code == 422 and response.json()['error']['code'] == 'baseline_required'
