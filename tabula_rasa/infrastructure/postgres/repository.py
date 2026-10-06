"""Small SQL and record helpers shared by entity-scoped repository slices."""

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text

from tabula_rasa.errors import StorageNotFoundError
from tabula_rasa.reference_data import clean_text
from .concurrency import AGGREGATE_TABLES, AggregateKey, baseline_for, check_baseline, lock_aggregates
from .operations import repository_operation
from .snapshots import check_expected_snapshot


TABLE_KINDS = {table: kind for kind, table in AGGREGATE_TABLES.items()}


def insert(connection, table, values):
    # Identifiers are private constants/field inventories, never caller input.
    columns = ', '.join(values)
    parameters = ', '.join(':' + key for key in values)
    return dict(connection.execute(
        text(f'INSERT INTO {table} ({columns}) VALUES ({parameters}) RETURNING *'), values,
    ).mappings().one())


def replace(connection, table, scope, identity, values):
    assignments = ', '.join(f'{key} = :{key}' for key in values)
    return dict(connection.execute(text(
        f'UPDATE {table} SET {assignments} '
        'WHERE entity_id = :scope AND id = :identity RETURNING *'
    ), {**values, 'scope': scope, 'identity': identity}).mappings().one())


def serialized(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    if isinstance(value, Decimal):
        return format(value, '.2f')
    return '' if value is None else value


def record(row, table, fields):
    result = {field: serialized(row[field]) for field in fields}
    result['baseline'] = baseline_for(AggregateKey(row['entity_id'], TABLE_KINDS[table], row['id']), row)
    return result


def new_object(scope, **values):
    return {'entity_id': scope, 'id': str(uuid4()), 'incarnation_id': str(uuid4()), **values}


class EntityRepository:
    def __init__(self, database, entity_id):
        self.database = database
        self.entity_id = clean_text(entity_id, 'Business entity', required=True)

    def operation(self, *, read_only=False):
        return repository_operation(self.database, read_only=read_only)

    def key(self, table, identity):
        return AggregateKey(self.entity_id, TABLE_KINDS[table], identity)

    def check_expected(self, row, table, expected, current, *, required_fields=()):
        if expected is not None and not isinstance(expected, Mapping):
            check_expected_snapshot(current, expected, required_fields=required_fields)
        token = expected.get('baseline') if expected is not None else None
        check_baseline(self.key(table, row['id']), row, token)
        check_expected_snapshot(current, expected, required_fields=required_fields)

    def get_row(self, connection, table, identity, *, lock=False):
        identity = clean_text(identity, 'Record ID', required=True)
        if lock:
            key = self.key(table, identity)
            return dict(lock_aggregates(connection, [key])[key])
        row = connection.execute(text(
            f'SELECT * FROM {table} WHERE entity_id = :scope AND id = :identity'
        ), {'scope': self.entity_id, 'identity': identity}).mappings().first()
        if row is None:
            raise StorageNotFoundError('The selected record no longer exists in this entity.')
        return dict(row)

    def rows(self, connection, table, *, lock=False):
        return [dict(row) for row in connection.execute(text(
            f'SELECT * FROM {table} WHERE entity_id = :scope ORDER BY id'
            + (' FOR SHARE' if lock else '')
        ), {'scope': self.entity_id}).mappings()]

    def lock_entity(self, connection, *, key_share=False):
        if connection.execute(text(
            'SELECT id FROM business_entities WHERE id = :scope '
            + ('FOR KEY SHARE' if key_share else 'FOR UPDATE')
        ), {'scope': self.entity_id}).first() is None:
            raise StorageNotFoundError('The selected business entity does not exist.')

    def delete_row(self, connection, table, identity):
        connection.execute(text(f'DELETE FROM {table} WHERE entity_id = :scope AND id = :identity'),
                           {'scope': self.entity_id, 'identity': identity})
