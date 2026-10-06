"""Normalize the legacy domain snapshots accepted by the core SQL adapters."""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from tabula_rasa.errors import StorageConflictError
from tabula_rasa.ledger_validation import decode_receipt_references
from tabula_rasa.reference_data import as_bool, normalize_tag_ids


def check_expected_snapshot(current, expected, *, required_fields=()):
    if expected is None:
        if required_fields:
            raise StorageConflictError('A complete loaded record or baseline is required.')
        return
    if not isinstance(expected, Mapping):
        raise StorageConflictError('The loaded record is invalid; refresh it before changing it.')
    if required_fields and not expected.get('baseline') and set(required_fields) - set(expected):
        raise StorageConflictError('A complete loaded record or baseline is required.')
    ignored = {'baseline', 'payee', 'tags', 'total_debits', 'total_credits'}

    def normalized(key, value):
        if key in {'amount', 'opening_balance'}:
            number = Decimal(str(value))
            if not number.is_finite():
                raise ValueError
            return number
        if key == 'active':
            return as_bool(value)
        if key == 'tag_ids':
            return sorted(normalize_tag_ids(value))
        if key == 'receipt_references':
            return decode_receipt_references(value)
        if key == 'postings':
            return sorted(
                [{field: normalized(field, item) for field, item in line.items() if field not in ignored}
                 for line in value], key=lambda line: line['position'],
            )
        if key == 'position':
            return int(value)
        return str(value) if value is not None else ''

    try:
        matches = all(normalized(key, current[key]) == normalized(key, value)
                      for key, value in expected.items() if key in current and key not in ignored)
    except (InvalidOperation, TypeError, ValueError, AttributeError, KeyError):
        matches = False
    if not matches:
        raise StorageConflictError('The record changed. Reload it before trying again.')
