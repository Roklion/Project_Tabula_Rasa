"""Canonical source relationships shared by secondary accounting adapters."""

from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError
from tabula_rasa.ledger_validation import validate_recurring_provenance, iso_date
from tabula_rasa.reference_data import normalize_tag_ids
from tabula_rasa.transaction import RECURRING_FIELDS
from .concurrency import check_baseline
from .repository import insert


def occurrence_fields(connection, scope, *, entry_id=None, source_id=None):
    column, identity = ('mixed_use_source_id', source_id) if source_id else ('entry_id', entry_id)
    row = connection.execute(text(
        f'SELECT * FROM recurring_occurrences WHERE entity_id=:scope AND {column}=:id'
    ), {'scope': scope, 'id': identity}).mappings().first()
    values = [row['schedule_id'], row['scheduled_date'].isoformat(), row['source_kind'],
              row['occurrence_type']] if row else ['', '', '', '']
    return dict(zip(RECURRING_FIELDS, values))


def write_occurrence(connection, scope, data, *, entry_id=None, source_id=None):
    validate_recurring_provenance(data, 'Recurring occurrence')
    insert(connection, 'recurring_occurrences', {
        'entity_id': scope, 'schedule_id': data['recurring_schedule_id'],
        'scheduled_date': iso_date(data['recurring_scheduled_date']),
        'source_kind': data['recurring_source_kind'], 'occurrence_type': data['recurring_occurrence_type'],
        'entry_id': entry_id, 'mixed_use_source_id': source_id,
    })


def tag_fields(connection, scope, table, column, identity):
    labels = connection.execute(text(
        f'SELECT t.id,t.name FROM {table} l JOIN tags t ON t.entity_id=l.entity_id AND t.id=l.tag_id '
        f'WHERE l.entity_id=:scope AND l.{column}=:id ORDER BY t.id'
    ), {'scope': scope, 'id': identity}).all()
    return {'tag_ids': [row.id for row in labels], 'tags': [row.name for row in labels]}


def write_tags(connection, scope, table, column, identity, tags):
    current = set(connection.scalars(text(
        f'SELECT tag_id FROM {table} WHERE entity_id=:scope AND {column}=:id'
    ), {'scope': scope, 'id': identity}))
    wanted = set(normalize_tag_ids(tags))
    for tag in sorted(current - wanted):
        connection.execute(text(f'DELETE FROM {table} WHERE entity_id=:scope AND {column}=:id AND tag_id=:tag'),
                           {'scope': scope, 'id': identity, 'tag': tag})
    for tag in sorted(wanted - current):
        insert(connection, table, {'entity_id': scope, column: identity, 'tag_id': tag})


def check_occurrence_schedule(repository, connection, identity, expected=None):
    """References acquire this schedule root in the shared order before checking."""
    row = repository.get_row(connection, 'recurring_schedules', identity)
    if expected is not None:
        if expected.get('id') != identity:
            raise StorageConflictError('The occurrence schedule changed; reconcile again.')
        check_baseline(repository.key('recurring_schedules', identity), row, expected.get('baseline'))
    if row['status'] != 'active':
        raise StorageConflictError('The occurrence schedule is no longer active; reconcile again.')
