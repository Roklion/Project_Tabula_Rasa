"""Fixed assets and immutable depreciation history on canonical postings."""

import json

from sqlalchemy import text

from tabula_rasa.asset import prepare_asset, _decode_overrides
from tabula_rasa.depreciation_posting import (
    asset_schedule, depreciation_entry_id, validate_depreciation_accounts, validate_depreciation_history,
)
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.reference_data import normalize_tag_ids
from .accounting import PostgresTransactionRepository
from .repository import EntityRepository, insert, new_object, record, replace, serialized
from .source_accounting import tag_fields, write_tags


ASSET_FIELDS = ('id', 'name', 'asset_type', 'notes', 'cost_basis', 'salvage_value', 'depreciation_method',
                'accumulated_depreciation_account_id', 'payee_id', 'reference', 'status', 'created_at', 'updated_at')
ASSET_MAPPING = {'depreciation_expense_account_id': 'expense_category_id',
                 'source_transaction_id': 'source_entry_id'}


class PostgresAssetRepository(EntityRepository):
    def __init__(self, database, entity_id):
        super().__init__(database, entity_id)
        self.transactions = PostgresTransactionRepository(database, entity_id)

    def project(self, connection, row):
        result = record(row, 'fixed_assets', ASSET_FIELDS)
        for field in ('acquisition_date', 'depreciation_start_date', 'retired_date'):
            result[field] = row[field].isoformat() if row[field] else ''
        result['useful_life_quarters'] = str(row['useful_life_quarters'])
        for field, column in ASSET_MAPPING.items():
            result[field] = row[column] or ''
        overrides = connection.execute(text(
            'SELECT * FROM asset_period_overrides WHERE entity_id=:scope AND asset_id=:id ORDER BY sequence'
        ), {'scope': self.entity_id, 'id': row['id']}).mappings()
        result['schedule_overrides'] = json.dumps({str(item['sequence']): {
            'amount': serialized(item['amount']), 'reason': item['reason'],
        } for item in overrides}, separators=(',', ':'))
        result.update(tag_fields(connection, self.entity_id, 'asset_tags', 'asset_id', row['id']))
        result['payee'] = connection.scalar(text('SELECT name FROM payees WHERE entity_id=:scope AND id=:id'),
                                            {'scope': self.entity_id, 'id': row['payee_id']}) or ''
        return result

    def list(self, *, fresh=False):
        with self.operation(read_only=True) as connection:
            result = [self.project(connection, row) for row in self.rows(connection, 'fixed_assets')]
            return sorted(result, key=lambda item: (item['status'] != 'active', item['name'].casefold()))

    def history(self, connection, asset_id):
        rows = connection.execute(text(
            'SELECT e.* FROM depreciation_events d JOIN entries e ON e.entity_id=d.entity_id AND e.id=d.entry_id '
            'WHERE d.entity_id=:scope AND d.asset_id=:id ORDER BY d.sequence'
        ), {'scope': self.entity_id, 'id': asset_id}).mappings()
        return [self.transactions.project(connection, row) for row in rows]

    def read(self, asset_id, *, fresh=False):
        with self.operation(read_only=True) as connection:
            row = self.get_row(connection, 'fixed_assets', asset_id)
            return self.project(connection, row), self.history(connection, asset_id)

    def validate_references(self, connection, data, references):
        validate_depreciation_accounts(data, references.accounts, references.categories)
        if data['payee_id'] and data['payee_id'] not in references.payees:
            raise StorageValidationError('The asset payee does not exist in this entity.')
        if any(tag not in references.tags for tag in normalize_tag_ids(data['tag_ids'])):
            raise StorageValidationError('An asset tag does not exist in this entity.')
        if data['source_transaction_id']:
            # The FK protects deletion; projection kind cannot change through
            # the canonical accounting repositories.
            self.transactions.entry(connection, data['source_transaction_id'])

    def write(self, connection, prepared, *, create=False):
        values = {field: prepared[field] for field in ASSET_FIELDS if field not in {'id', 'created_at', 'updated_at'}}
        for field in ('acquisition_date', 'depreciation_start_date', 'retired_date', 'useful_life_quarters'):
            values[field] = prepared[field] or None
        for field, column in ASSET_MAPPING.items():
            values[column] = prepared[field] or None
        for field in ('payee_id', 'accumulated_depreciation_account_id'):
            values[field] = values[field] or None
        if create:
            insert(connection, 'fixed_assets', new_object(self.entity_id, id=prepared['id'],
                   created_at=prepared['created_at'], **values))
        else:
            replace(connection, 'fixed_assets', self.entity_id, prepared['id'], values)
        write_tags(connection, self.entity_id, 'asset_tags', 'asset_id', prepared['id'], prepared['tag_ids'])
        overrides = _decode_overrides(prepared['schedule_overrides'])
        current = {row['sequence']: row for row in connection.execute(text(
            'SELECT * FROM asset_period_overrides WHERE entity_id=:scope AND asset_id=:id'
        ), {'scope': self.entity_id, 'id': prepared['id']}).mappings()}
        for sequence in sorted(set(current) - set(overrides)):
            connection.execute(text('DELETE FROM asset_period_overrides WHERE entity_id=:scope AND asset_id=:id AND sequence=:seq'),
                               {'scope': self.entity_id, 'id': prepared['id'], 'seq': sequence})
        for sequence, details in sorted(overrides.items()):
            if sequence not in current:
                insert(connection, 'asset_period_overrides', {'entity_id': self.entity_id, 'asset_id': prepared['id'],
                       'sequence': sequence, **details})
            elif (serialized(current[sequence]['amount']), current[sequence]['reason']) != (details['amount'], details['reason']):
                connection.execute(text('UPDATE asset_period_overrides SET amount=:amount,reason=:reason '
                                        'WHERE entity_id=:scope AND asset_id=:id AND sequence=:seq'),
                                   {'scope': self.entity_id, 'id': prepared['id'], 'seq': sequence, **details})
        return self.project(connection, self.get_row(connection, 'fixed_assets', prepared['id']))

    def create(self, record):
        prepared = prepare_asset(record, asset_id=record['id'], created_at=record['created_at'])
        with self.operation() as connection:
            refs = self.transactions.references(connection, lock=True)
            self.validate_references(connection, prepared, refs)
            return self.write(connection, prepared, create=True)

    def update(self, asset_id, *, expected=None, build):
        with self.operation() as connection:
            refs = self.transactions.references(connection, lock=True, root_keys=[self.key('fixed_assets', asset_id)])
            row = self.get_row(connection, 'fixed_assets', asset_id)
            current = self.project(connection, row)
            self.check_expected(row, 'fixed_assets', expected, current)
            prepared = dict(build(current, self.history(connection, asset_id)))
            if prepared.get('id') != asset_id:
                raise StorageValidationError('Asset identity cannot change.')
            prepared = prepare_asset(prepared, asset_id=asset_id, created_at=current['created_at'])
            self.validate_references(connection, prepared, refs)
            return self.write(connection, prepared)

    def delete(self, asset_id, *, expected=None, validate):
        with self.operation() as connection:
            row = self.get_row(connection, 'fixed_assets', asset_id, lock=True)
            current = self.project(connection, row)
            self.check_expected(row, 'fixed_assets', expected, current)
            validate(current, self.history(connection, asset_id))
            self.delete_row(connection, 'fixed_assets', asset_id)

    def post(self, asset_id, *, expected=None, build):
        with self.operation() as connection:
            refs = self.transactions.references(connection, lock=True, root_keys=[self.key('fixed_assets', asset_id)])
            row = self.get_row(connection, 'fixed_assets', asset_id)
            asset = self.project(connection, row)
            self.check_expected(row, 'fixed_assets', expected, asset)
            period_ids = [depreciation_entry_id(asset_id, period.sequence) for period in asset_schedule(asset)]
            relevant = connection.execute(text(
                "SELECT * FROM entries WHERE entity_id=:scope AND projection_kind='simple' "
                "AND (depreciation_asset_id=:asset OR id=ANY(:ids)) ORDER BY txn_date,id"
            ), {'scope': self.entity_id, 'asset': asset_id, 'ids': period_ids}).mappings()
            # Preserve all asset history and period-ID collision checks without
            # projecting unrelated ledger records inside this mutation.
            transactions = [self.transactions.project(connection, entry) for entry in relevant]
            pending = list(build(asset, refs, transactions))
            validate_depreciation_accounts(asset, refs.accounts, refs.categories, required=True, active=True)
            history = self.history(connection, asset_id)
            validate_depreciation_history([asset], [*history, *pending], refs.accounts, refs.categories)
            periods = {depreciation_entry_id(asset_id, period.sequence): period for period in asset_schedule(asset)}
            result = []
            for prepared in pending:
                period = periods[prepared['id']]
                self.transactions.write(connection, prepared['id'], prepared, create=True,
                                        owner=('depreciation_asset_id', asset_id))
                insert(connection, 'depreciation_events', {'entity_id': self.entity_id, 'asset_id': asset_id,
                       'sequence': period.sequence, 'entry_id': prepared['id'], 'scheduled_date': prepared['txn_date'],
                       'amount': prepared['amount']})
                result.append(self.transactions.project(connection, self.transactions.entry(connection, prepared['id'])))
        return result
