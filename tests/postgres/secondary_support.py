"""Shared synthetic inputs for secondary repository integration tests."""

from tests.postgres.core_support import expense


def schedule(**changes):
    return {**expense(txn_date='2026-01-01'), 'name': 'Synthetic recurring expense',
            'recurrence_unit': 'month', **changes}


def mixed(**changes):
    return {**expense(txn_date='2026-01-01'), 'total_expense': '100.00',
            'business_use_percentage': '33.33333', 'allocation_rationale': 'Synthetic business allocation', **changes}


def asset(offset, **changes):
    return dict(name='Synthetic equipment', asset_type='Computers & office equipment',
                acquisition_date='2026-01-01', depreciation_start_date='2026-01-01',
                cost_basis='100.00', salvage_value='0.00', useful_life_quarters=4,
                depreciation_expense_account_id='office', accumulated_depreciation_account_id=offset, **changes)


def document(connection, scope, identity='receipt', *, key=None):
    from sqlalchemy import text
    key = key or 'synthetic-drive-file-' + identity
    connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,
        original_filename,mime_type,store_kind,store_scope_key,storage_key,open_url)
        VALUES (:scope,:id,:id,'synthetic.pdf','synthetic.pdf','application/pdf',
                'google_drive','synthetic-folder',:key,'')"""),
        {'scope': scope, 'id': identity, 'key': key or identity})
    return {'id': key or identity, 'name': 'synthetic.pdf'}
