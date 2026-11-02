"""The public ledger carries durable occurrence identity without changing kind."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.http.app import create_app
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import RequestContext
from tests.test_financial_csv import financial_snapshot


def test_ledger_exposes_initial_and_generated_provenance_in_selected_scope():
    runtime = SimpleNamespace(entity='alpha', operation=nullcontext, close=lambda: None, ready=lambda: True)
    base = financial_snapshot()
    occurrences = tuple(replace(base.transactions[0], id=f'{kind}-{phase}',
        source_type='mixed_use_expense' if kind == 'mixed_use' else '',
        source_id='source' if kind == 'mixed_use' else '',
        recurring_schedule_id=f'{kind}-schedule', recurring_scheduled_date=date(2026, 10, 1),
        recurring_source_kind=kind, recurring_occurrence_type=phase, description='Unchanged memo')
        for kind in ('transaction', 'mixed_use') for phase in ('initial', 'generated'))
    plain = replace(base.transactions[0], description='Recurring monthly expense')
    snapshots = {'alpha': replace(base, transactions=(*occurrences, plain, base.transactions[1])),
                 'beta': replace(base, transactions=(plain,))}
    repository = SimpleNamespace(read_ledger=lambda **_: snapshots[runtime.entity])
    runtime.services = lambda _: SimpleNamespace(reporting=ReportingService(repository),
        ledger=SimpleNamespace(get_info=lambda: SimpleNamespace(currency_code='USD')))
    runtime.resolve_context = lambda _: RequestContext('actor', 'org', runtime.entity,
        frozenset({'bookkeeping:read'}), 'scope:' + runtime.entity, 'csrf')
    with TestClient(create_app(settings=HttpSettings('test', 'http://testserver'),
                              runtime_factory=lambda _: runtime)) as client:
        response = client.get('/api/v1/entities/alpha/ledger?kind=Expense')
        assert response.status_code == 200
        rows = {row['record_id']: row for row in response.json()['items']}
        assert len(rows) == 5
        for kind in ('transaction', 'mixed_use'):
            for phase in ('initial', 'generated'):
                row = rows[f'{kind}-{phase}']
                assert row['recurring_schedule_id'] == f'{kind}-schedule'
                assert row['kind'] == 'Expense' and row['description'] == 'Unchanged memo'
                assert row['source_type'] == ('mixed_use_expense' if kind == 'mixed_use' else '')
        assert rows['simple']['recurring_schedule_id'] == ''
        all_rows = client.get('/api/v1/entities/alpha/ledger').json()['items']
        assert next(row for row in all_rows if row['entry_type'] == 'journal')['recurring_schedule_id'] == ''
        assert client.get('/api/v1/entities/alpha/ledger?kind=Recurring').status_code == 422
        runtime.entity = 'beta'
        assert client.get('/api/v1/entities/alpha/ledger').status_code == 403
        beta = client.get('/api/v1/entities/beta/ledger').json()['items']
        assert all(row['recurring_schedule_id'] == '' for row in beta)
