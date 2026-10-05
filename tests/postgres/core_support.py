"""Core repository fixtures use only synthetic, entity-local bookkeeping."""

from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tests.postgres._support import account, category, entity


def seed_core(database):
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            entity(connection, scope)
            account(connection, scope, 'cash')
            account(connection, scope, 'bank')
            category(connection, scope, 'sales', kind='Income')
            category(connection, scope, 'office', kind='Expense')
    return create_postgres_services(database, 'alpha'), create_postgres_services(database, 'beta')


def expense(**changes):
    return {**dict(txn_date='2026-10-05', kind='Expense', amount='12.50',
                   account_id='cash', category_id='office'), **changes}


def journal_lines(*, prefix='', payee_id=''):
    return [dict(id=prefix+'debit', target_type='category', target_id='office', side='Debit', amount='12.50', payee_id=payee_id),
            dict(id=prefix+'credit', target_type='account', target_id='cash', side='Credit', amount='12.50')]


def asset_sql():
    return """INSERT INTO fixed_assets(entity_id,id,incarnation_id,name,asset_type,
        acquisition_date,depreciation_start_date,cost_basis,salvage_value,useful_life_quarters,
        depreciation_method,status,source_entry_id,payee_id)
        VALUES (:scope,'asset','asset','Synthetic asset','Computers & office equipment',
        '2026-10-05','2026-10-05',100,0,4,'Straight-line','active',:entry,:payee)"""
