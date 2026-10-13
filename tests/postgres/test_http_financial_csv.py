"""Existing export workflows through entity-scoped PostgreSQL reporting reads."""

from dataclasses import replace

from tests.postgres.test_http_baselines import commercial as commercial, PREFIX
from tests.postgres.test_http_workflows import create
from tests.postgres.core_support import expense
from tests.test_financial_csv import csv_rows


def test_downloads_preserve_financial_scope_and_whole_journals_with_two_entities(commercial):
    alpha, beta, (client, _), _ = commercial
    create(client, 'transactions', dict(transaction_id='transfer', **expense(kind='Transfer', amount='100.00',
        category_id='', to_account_id='bank')))
    before = client.get(PREFIX + 'reports/summary').json()
    full = csv_rows(client.get(PREFIX + 'exports/transactions.csv').content)[1]
    assert {row['ID'] for row in full} == {'expense', 'transfer'}
    assert next(row for row in full if row['ID'] == 'transfer')['Amount'] == '100.0'
    journals = csv_rows(client.get(PREFIX + 'exports/journal-postings.csv').content)[1]
    assert len(journals) == 2 and {row['Entry ID'] for row in journals} == {'journal'}
    result = client.get(PREFIX + 'ledger/selected.csv', params=[('entry_ids', 'journal:journal'), ('entry_ids', 'expense')])
    assert result.status_code == 200
    selected = csv_rows(result.content)[1]
    assert [row['Type'] for row in selected] == ['Journal', '↳ Posting', '↳ Posting', 'Expense']
    assert selected[1]['Debit'] == '12.5' and selected[2]['Credit'] == '12.5'
    assert client.get(PREFIX + 'reports/summary').json() == before  # Export never mutates or recategorizes accounting.
    runtime = client.app.state.runtime
    original = runtime.resolve_context
    runtime.resolve_context = lambda request: replace(original(request), entity_id='beta')
    assert client.get(PREFIX + 'exports/transactions.csv').status_code == 403
    for path in ('exports/transactions.csv', 'exports/journal-postings.csv'):
        result = client.get('/api/v1/entities/beta/' + path)
        assert result.status_code == 200 and csv_rows(result.content)[1] == []
    assert client.get('/api/v1/entities/beta/ledger/selected.csv?entry_ids=expense').status_code == 404
    assert not beta.reporting.read_ledger().transactions
    assert len(alpha.reporting.read_ledger().transactions) == 2
