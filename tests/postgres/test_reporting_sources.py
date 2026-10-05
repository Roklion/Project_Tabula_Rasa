"""Reporting consumes canonical secondary history without generating new activity."""

from datetime import date
from decimal import Decimal

from sqlalchemy import text

from tabula_rasa.application.reporting_contracts import LedgerFilter
from tabula_rasa.depreciation_posting import depreciation_entry_id
from tabula_rasa.mixed_use_records import mixed_use_ledger_description
from tests.postgres._support import account
from tests.postgres.core_support import expense, seed_core


def seed_source_history(connection, scope):
    params = {'scope': scope}
    account(connection, scope, 'accumulated')
    for identity in ('client', 'internal'):
        connection.execute(text("""INSERT INTO tags(entity_id,id,incarnation_id,name,name_key)
            VALUES (:scope,:id,:id,:name,:name)"""),
            {**params, 'id': identity, 'name': scope + ' ' + identity})
    connection.execute(text("""INSERT INTO recurring_schedules(entity_id,id,incarnation_id,name,source_kind,
        recurrence_unit,recurrence_interval,anchor_date,start_date,status,amount,total_expense,
        business_use_percentage,allocation_rationale,account_id,category_id)
        VALUES (:scope,'ordinary-schedule','ordinary-schedule','Ordinary','transaction','month',1,
                '2026-10-05','2026-10-05','paused',12.50,NULL,NULL,'','cash','office'),
               (:scope,'mixed-schedule','mixed-schedule','Mixed','mixed_use','month',1,
                '2026-10-05','2026-10-05','paused',12.50,25,50,'Synthetic allocation','cash','office')"""), params)
    connection.execute(text("""INSERT INTO mixed_use_sources(entity_id,id,incarnation_id,txn_date,total_expense,
        business_use_percentage,allocated_amount,account_id,category_id,description,
        allocation_rationale,expected_projection_entry_id)
        VALUES (:scope,'mixed','mixed','2026-10-05',25,50,12.50,'cash','office','Synthetic expense',
                'Synthetic allocation','projection')"""), params)
    connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,
        simple_kind,mixed_use_source_id,description)
        VALUES (:scope,'projection','projection','2026-10-05','simple','Expense','mixed',:description)"""),
        {**params, 'description': mixed_use_ledger_description('Synthetic expense', 'Synthetic allocation')})
    connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id,category_id)
        VALUES (:scope,'projection:1','projection','simple',1,'Debit',12.50,NULL,'office'),
               (:scope,'projection:2','projection','simple',2,'Credit',12.50,'cash',NULL)"""), params)
    connection.execute(text("""INSERT INTO recurring_occurrences(entity_id,schedule_id,scheduled_date,
        source_kind,occurrence_type,entry_id,mixed_use_source_id)
        VALUES (:scope,'ordinary-schedule','2026-10-05','transaction','initial','ordinary',NULL),
               (:scope,'mixed-schedule','2026-10-05','mixed_use','generated',NULL,'mixed')"""), params)
    for identity in ('client', 'internal'):
        connection.execute(text("INSERT INTO mixed_use_tags(entity_id,source_id,tag_id) VALUES (:scope,'mixed',:tag)"),
                           {**params, 'tag': identity})
        # Complete pairs retain matching tags, but reporting reads the source
        # owner once rather than joining both associations into duplicate rows.
        connection.execute(text("INSERT INTO entry_tags(entity_id,entry_id,tag_id) VALUES (:scope,'projection',:tag)"),
                           {**params, 'tag': identity})
    connection.execute(text("""INSERT INTO fixed_assets(entity_id,id,incarnation_id,name,asset_type,
        acquisition_date,depreciation_start_date,cost_basis,salvage_value,useful_life_quarters,
        depreciation_method,status,expense_category_id,accumulated_depreciation_account_id)
        VALUES (:scope,'asset','asset','Synthetic asset','Computers & office equipment',
        '2026-10-05','2026-10-05',16,0,2,'Straight-line','active','office','accumulated')"""), params)
    connection.execute(text("""INSERT INTO asset_period_overrides(entity_id,asset_id,sequence,amount,reason)
        VALUES (:scope,'asset',2,0,'Synthetic zero override')"""), params)
    for sequence, scheduled, amount in ((1, '2026-12-31', '8.00'), (2, '2027-03-31', '0.00')):
        values = {**params, 'id': depreciation_entry_id('asset', sequence),
                  'date': scheduled, 'amount': amount, 'sequence': sequence}
        connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,
            simple_kind,depreciation_asset_id) VALUES (:scope,:id,:id,:date,'simple','Expense','asset')"""), values)
        connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id,category_id)
            VALUES (:scope,:id||chr(58)||'1',:id,'simple',1,'Debit',:amount,NULL,'office'),
                   (:scope,:id||chr(58)||'2',:id,'simple',2,'Credit',:amount,'accumulated',NULL)"""), values)
        connection.execute(text("""INSERT INTO depreciation_events(entity_id,asset_id,sequence,entry_id,scheduled_date,amount)
            VALUES (:scope,'asset',:sequence,:id,:date,:amount)"""), values)
    for identity, entry, source, position in (
        ('ordinary-document', 'ordinary', None, 1), ('mixed-document-1', None, 'mixed', 1),
        ('mixed-document-2', None, 'mixed', 2), ('unlinked-document', None, None, 0),
    ):
        values = {**params, 'id': identity, 'entry': entry, 'source': source, 'position': position}
        connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
            VALUES (:scope,:id,:id,'synthetic.pdf','synthetic',:id)"""), values)
        if position:
            connection.execute(text("""INSERT INTO document_links(entity_id,document_id,entry_id,mixed_use_source_id,position)
                VALUES (:scope,:id,:entry,:source,:position)"""), values)


def test_owned_entries_keep_projection_identity_tags_receipt_owner_and_occurrence_metadata(database):
    alpha, beta = seed_core(database)
    for services in (alpha, beta):
        services.transactions.create(transaction_id='ordinary', **expense())
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            seed_source_history(connection, scope)
    for services, scope in ((alpha, 'alpha'), (beta, 'beta')):
        snapshot = services.reporting.read_ledger()
        assert len(snapshot.transactions) == 4 and snapshot.journals == ()
        records = {row.id: row for row in snapshot.transactions}
        ordinary, mixed = records['ordinary'], records['projection']
        assert (ordinary.source_type, ordinary.source_id, ordinary.receipt_count) == ('', '', 1)
        assert (ordinary.recurring_schedule_id, ordinary.recurring_scheduled_date,
                ordinary.recurring_source_kind, ordinary.recurring_occurrence_type) == (
            'ordinary-schedule', date(2026, 10, 5), 'transaction', 'initial',
        )
        assert (mixed.source_type, mixed.source_id, mixed.amount, mixed.receipt_count) == (
            'mixed_use_expense', 'mixed', Decimal('12.50'), 2,
        )
        assert mixed.tag_ids == ('client', 'internal') and mixed.tags == (scope + ' client', scope + ' internal')
        assert (mixed.recurring_schedule_id, mixed.recurring_scheduled_date,
                mixed.recurring_source_kind, mixed.recurring_occurrence_type) == (
            'mixed-schedule', date(2026, 10, 5), 'mixed_use', 'generated',
        )
        assert services.reporting.query_ledger(LedgerFilter(tag_ids=('client',))).entries[0].transaction == mixed
        for sequence, amount in ((1, '8.00'), (2, '0.00')):
            depreciation = records[depreciation_entry_id('asset', sequence)]
            assert (depreciation.source_type, depreciation.source_id, depreciation.amount,
                    depreciation.account_id, depreciation.receipt_count) == (
                'depreciation', 'asset', Decimal(amount), 'accumulated', 0,
            )
        # Only the allocated 12.50 posts; no 25.00 personal/full-cost activity,
        # no extra journal stream, and the zero period adds no expense.
        assert services.reporting.period_report(snapshot).totals == {'income': 0.0, 'expenses': 33.0, 'net': -33.0}
        assert {row['id']: row['balance'] for row in services.reporting.account_balances(snapshot)} == {
            'cash': -25.0, 'bank': 0.0, 'accumulated': -8.0,
        }
        assert services.reporting.balance_sheet(snapshot)['difference'] == 0.0
