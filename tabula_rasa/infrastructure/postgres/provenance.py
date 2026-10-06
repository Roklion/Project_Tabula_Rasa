"""Accepted import attribution; no source file bytes or private error payloads."""

import hashlib
import json

from sqlalchemy import text

from tabula_rasa.errors import StorageValidationError
from .repository import insert, new_object


MAX_IMPORT_ROWS = 1000


def bounded_rows(rows):
    result = []
    for row in rows:
        if len(result) == MAX_IMPORT_ROWS:
            raise StorageValidationError('Import at most 1,000 rows per batch; split larger sources before submitting.')
        result.append(dict(row))
    return result


def import_identity(kind, values):
    payload = json.dumps([kind, values], sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def completed_import(connection, scope, identity):
    return connection.scalar(text(
        "SELECT status FROM import_batches WHERE entity_id=:scope AND id=:id"
    ), {'scope': scope, 'id': identity}) == 'complete'


def complete_import(connection, scope, identity, source, version, records):
    insert(connection, 'import_batches', new_object(
        scope, id=identity, source_kind=source, format_version=version, status='complete',
    ))
    for position, kind, target, fingerprint in records:
        insert(connection, 'import_records', {
            'entity_id': scope, 'batch_id': identity, 'source_position': position,
            'record_kind': kind, 'entry_id': target if kind == 'entry' else None,
            'mileage_id': target if kind == 'mileage' else None, 'fingerprint': fingerprint,
        })
