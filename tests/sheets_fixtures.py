"""Synthetic format-13 rows for recovery tests, independent of retired writers.

These builders populate FakeWorkbook directly. They perform no provider writes
and make no claims about supported bookkeeping mutation APIs.
"""
import json
from uuid import uuid4

from tabula_rasa.asset import prepare_asset
from tabula_rasa.application.mileage import prepare_mileage_trip
from tabula_rasa.mixed_use_records import prepare_mixed_use_expense
from tabula_rasa.quickbooks_import import suggested_account_classification
from tabula_rasa.transaction import prepare_transaction

WHEN = "2026-07-31T00:00:00Z"


def put(storage, title, record):
    for key, value in list(record.items()):
        if isinstance(value, (list, dict)):
            record[key] = json.dumps(value)
    sheet = storage._workbook.sheets[title]
    sheet.rows.append([str(record.get(field, "")) for field in sheet.rows[0]])
    storage._invalidate(title)
    return record


def account(storage, name, account_type, opening_balance=0, *, classification=None, parent_id=""):
    return put(storage, "Accounts", dict(id=str(uuid4()), name=name, type=account_type,
        classification=classification or suggested_account_classification(name, account_type),
        opening_balance=f"{float(opening_balance):.2f}", parent_id=parent_id,
        active="TRUE", created_at=WHEN))


def category(storage, name, kind, *, parent_id=""):
    return put(storage, "Categories", dict(id=str(uuid4()), name=name, kind=kind, parent_id=parent_id))


def payee(storage, name):
    return put(storage, "Payees", dict(id=str(uuid4()), name=name, active="TRUE", created_at=WHEN))


def tag(storage, name):
    return put(storage, "Tags", dict(id=str(uuid4()), name=name, active="TRUE", created_at=WHEN))


def transaction(storage, *, transaction_id=None, **data):
    result = prepare_transaction(data, transaction_id=transaction_id, created_at=WHEN,
        accounts=storage._account_lookup(), categories=storage._category_lookup(),
        payees=storage._payee_lookup(), tags=storage._tag_lookup(),
        create_payee=lambda name: payee(storage, name), create_tag=lambda name: tag(storage, name))
    result['tag_ids'] = json.dumps(result.get('tag_ids', [])) if isinstance(result.get('tag_ids'), list) else result.get('tag_ids', '')
    return put(storage, "Transactions", result)


def mileage(storage, **data):
    record = prepare_mileage_trip(data, (), validate_tags=False).as_record()
    record['tag_ids'] = json.dumps(record.get('tag_ids', []))
    return put(storage, "Mileage", record)


def mixed(storage, **data):
    def prepare(data, **options):
        return prepare_transaction(data, accounts=storage._account_lookup(), categories=storage._category_lookup(),
            payees=storage._payee_lookup(), tags=storage._tag_lookup(),
            create_payee=lambda name: payee(storage, name), create_tag=lambda name: tag(storage, name), **options)
    source, projection = prepare_mixed_use_expense(prepare, data)
    for title, record in (("MixedUseExpenses", source), ("Transactions", projection)):
        if isinstance(record.get('tag_ids'), list):
            record['tag_ids'] = json.dumps(record['tag_ids'])
        put(storage, title, record)
    return source


def asset(storage, **data):
    record = prepare_asset(data)
    record['updated_at'] = record['created_at']
    return put(storage, "Assets", record)


def receipts(storage, transaction_id, *, reference=None, file_id=None, name=None, references=None):
    """Set test row references, including legacy cells needed by format-13 recovery."""
    row = storage._find_row("Transactions", transaction_id)
    new = reference or dict(id=file_id, name=name)
    refs = references if references is not None else [item for item in json.loads(row.values.get('receipt_references') or '[]') if item['id'] != new['id']] + [new]
    for title, identity in (("Transactions", transaction_id), ("MixedUseExpenses", row.values.get('source_id'))):
        if not identity:
            continue
        sheet = storage._workbook.sheets[title]
        fields = sheet.rows[0]
        target = next(r for r in sheet.rows[1:] if r[fields.index('id')] == identity)
        target[fields.index('receipt_references')] = json.dumps(refs)
        storage._invalidate(title)


def mixed_row(storage, source_id):
    return next(row for row in storage.list_mixed_use_expenses() if row['id'] == source_id)
