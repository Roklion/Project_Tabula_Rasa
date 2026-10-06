"""Entity-scoped, source-authoritative mixed-use pairs and receipt links."""

from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.ledger_validation import decode_receipt_references, iso_date
from tabula_rasa.mixed_use_records import validate_mixed_use_changes, validate_mixed_use_records
from tabula_rasa.reference_data import clean_text
from tabula_rasa.transaction import RECURRING_FIELDS, prepare_transaction
from .accounting import PostgresTransactionRepository
from .concurrency import lock_aggregates
from .operations import repository_operation
from .repository import EntityRepository, insert, new_object, record, replace
from .source_accounting import occurrence_fields, tag_fields, write_occurrence, write_tags


SOURCE_FIELDS = ('id', 'total_expense', 'allocated_amount', 'account_id', 'category_id', 'payee_id',
                 'description', 'reference', 'allocation_rationale', 'created_at', 'updated_at',
                 'relationship_state')


class PostgresMixedUseRepository(EntityRepository):
    def __init__(self, database, entity_id):
        super().__init__(database, entity_id)
        self.transactions = PostgresTransactionRepository(database, entity_id)

    def project(self, connection, row):
        result = record(row, 'mixed_use_sources', SOURCE_FIELDS)
        result.update(kind='Expense', txn_date=row['txn_date'].isoformat(),
                      business_use_percentage=format(row['business_use_percentage'].normalize(), 'f'),
                      linked_transaction_id=row['expected_projection_entry_id'],
                      ledger_status='linked' if row['relationship_state'] == 'complete' else row['relationship_state'])
        result.update(tag_fields(connection, self.entity_id, 'mixed_use_tags', 'source_id', row['id']))
        result.update(occurrence_fields(connection, self.entity_id, source_id=row['id']))
        result['payee'] = connection.scalar(text('SELECT name FROM payees WHERE entity_id=:scope AND id=:id'),
                                            {'scope': self.entity_id, 'id': row['payee_id']}) or ''
        result['receipt_references'] = [self.transactions.receipt_reference(doc) for doc in connection.execute(text(
            'SELECT d.* FROM document_links l JOIN documents d ON d.entity_id=l.entity_id AND d.id=l.document_id '
            'WHERE l.entity_id=:scope AND l.mixed_use_source_id=:id ORDER BY l.position'
        ), {'scope': self.entity_id, 'id': row['id']}).mappings()]
        return result

    def sources(self, *, fresh=False):
        with self.operation(read_only=True) as connection:
            return [self.project(connection, row) for row in self.rows(connection, 'mixed_use_sources')]

    def complete_pair(self, connection, row):
        if row['relationship_state'] != 'complete':
            raise StorageValidationError('Mixed-use source needs inspection before editing or linking its projection.')
        source = self.project(connection, row)
        projection = self.transactions.project(connection, self.transactions.entry(connection, source['linked_transaction_id']))
        validate_mixed_use_records([source], [projection])
        return source, projection

    def list(self, *, fresh=False):
        with self.operation(read_only=True) as connection:
            results = [self.complete_pair(connection, row)[0] for row in self.rows(connection, 'mixed_use_sources')]
            return sorted(results, key=lambda item: (item['txn_date'], item['created_at'], item['id']), reverse=True)

    def get(self, source_id, *, fresh=False):
        with self.operation(read_only=True) as connection:
            return self.complete_pair(connection, self.get_row(connection, 'mixed_use_sources', source_id))[0]

    def locked_pair(self, connection, source_id, *, references=False, root_keys=()):
        # The expected projection identity is immutable through this adapter.
        # Discover it without locking, then acquire the complete ordered set.
        row = self.get_row(connection, 'mixed_use_sources', source_id)
        if row['relationship_state'] != 'complete':
            raise StorageValidationError('Mixed-use source needs inspection before editing or linking its projection.')
        entry_id = row['expected_projection_entry_id']
        keys = [*root_keys, self.key('mixed_use_sources', source_id), self.key('entries', entry_id)]
        refs = self.transactions.references(connection, lock=True, root_keys=keys) if references else None
        if not references:
            lock_aggregates(connection, keys)
        row = self.get_row(connection, 'mixed_use_sources', source_id)
        source, projection = self.complete_pair(connection, row)
        if source['linked_transaction_id'] != entry_id:
            raise StorageConflictError('The source relationship changed; reload before trying again.')
        return row, source, projection, refs

    def validate_pair(self, connection, source, projection, references, *, current=None):
        refs = self.transactions.inline_references(connection, references, projection)

        def no_inline(name):
            raise StorageValidationError('Inline references must be resolved during service preparation.')

        # Independently validate callback output with the existing domain owners.
        checked = prepare_transaction(
            {key: value for key, value in projection.items() if key != 'payee'},
            transaction_id=projection['id'], created_at=projection['created_at'],
            accounts=refs.accounts, categories=refs.categories, payees=refs.payees, tags=refs.tags,
            create_payee=no_inline, create_tag=no_inline, original_transaction=current,
        )
        checked.update(source_type='mixed_use_expense', source_id=source['id'])
        validate_mixed_use_records([source], [checked])
        return checked

    def write_pair(self, connection, source, projection, *, create=False, recurring=False):
        values = {field: source[field] for field in SOURCE_FIELDS if field not in
                  {'id', 'created_at', 'updated_at', 'relationship_state'}}
        values.update(txn_date=iso_date(source['txn_date']),
                      business_use_percentage=source['business_use_percentage'], payee_id=source['payee_id'] or None,
                      expected_projection_entry_id=source['linked_transaction_id'], relationship_state='complete')
        if create:
            insert(connection, 'mixed_use_sources', new_object(self.entity_id, id=source['id'],
                   created_at=source['created_at'], **values))
        else:
            replace(connection, 'mixed_use_sources', self.entity_id, source['id'], values)
        write_tags(connection, self.entity_id, 'mixed_use_tags', 'source_id', source['id'], source['tag_ids'])
        self.transactions.write(connection, projection['id'], projection, create=create,
                                owner=('mixed_use_source_id', source['id']))
        self.transactions.write_receipts(connection, source['id'], source['receipt_references'],
                                         target_column='mixed_use_source_id')
        if recurring:
            write_occurrence(connection, self.entity_id, source, source_id=source['id'])
        return self.project(connection, self.get_row(connection, 'mixed_use_sources', source['id']))

    def create_pair(self, connection, data, *, build, recurring=False):
        source_id = clean_text(data.get('source_id', data.get('id')), 'Source ID', required=True)
        entry_id = clean_text(data.get('linked_transaction_id'), 'Projection ID', required=True)
        refs = self.transactions.references(connection, lock=True)
        if (connection.execute(text('SELECT 1 FROM mixed_use_sources WHERE entity_id=:scope AND id=:id'),
                               {'scope': self.entity_id, 'id': source_id}).first()
                or connection.execute(text('SELECT 1 FROM entries WHERE entity_id=:scope AND id=:id'),
                                      {'scope': self.entity_id, 'id': entry_id}).first()):
            raise StorageConflictError('The source or projection identity already exists.')
        if not recurring and any(data.get(field) for field in RECURRING_FIELDS):
            raise StorageValidationError('Recurring provenance is reserved for recurring creation.')
        source, projection = build(data, refs, source_id=source_id, linked_transaction_id=entry_id)
        if source['id'] != source_id or projection['id'] != entry_id:
            raise StorageValidationError('Source and projection identities cannot change.')
        projection = self.validate_pair(connection, source, projection, refs)
        return self.write_pair(connection, source, projection, create=True, recurring=recurring)

    def create(self, data, *, build, recurring=False):
        with repository_operation(self.database, require_outer=recurring) as connection:
            return self.create_pair(connection, data, build=build, recurring=recurring)

    def update(self, source_id, changes, *, expected=None, build):
        with self.operation() as connection:
            row, source, projection, refs = self.locked_pair(connection, source_id, references=True)
            self.check_expected(row, 'mixed_use_sources', expected, source)
            validate_mixed_use_changes(source, changes)
            updated, prepared = build({**{key: value for key, value in source.items() if key != 'payee'}, **changes}, refs, source_id=source_id,
                                      linked_transaction_id=projection['id'], created_at=source['created_at'],
                                      original_transaction=projection)
            if updated['id'] != source_id or prepared['id'] != projection['id']:
                raise StorageValidationError('Source and projection identities cannot change.')
            prepared = self.validate_pair(connection, updated, prepared, refs, current=projection)
            return self.write_pair(connection, updated, prepared)

    def delete(self, source_id, *, expected=None):
        with self.operation() as connection:
            row, source, projection, _ = self.locked_pair(connection, source_id)
            self.check_expected(row, 'mixed_use_sources', expected, source)
            connection.execute(text('DELETE FROM recurring_occurrences WHERE entity_id=:scope AND mixed_use_source_id=:id'),
                               {'scope': self.entity_id, 'id': source_id})
            connection.execute(text('DELETE FROM document_links WHERE entity_id=:scope AND mixed_use_source_id=:id'),
                               {'scope': self.entity_id, 'id': source_id})
            self.transactions.delete_entry(connection, projection['id'])
            self.delete_row(connection, 'mixed_use_sources', source_id)

    def change_receipts(self, source_id, *, expected, change):
        with self.operation() as connection:
            row, source, _, _ = self.locked_pair(connection, source_id)
            self.check_expected(row, 'mixed_use_sources', expected, source)
            references = decode_receipt_references(change(source['receipt_references']))
            self.transactions.write_receipts(connection, source_id, references, target_column='mixed_use_source_id')
            return self.project(connection, self.get_row(connection, 'mixed_use_sources', source_id))

    def link_receipt(self, source_id, *, reference, expected=None):
        def add(references):
            if reference in references:
                return references
            if any(item['id'] == reference.get('id') for item in references):
                raise StorageConflictError('The receipt identity already has different metadata.')
            return [*references, reference]
        return self.change_receipts(source_id, expected=expected, change=add)

    def unlink_receipt(self, source_id, *, file_id, expected=None):
        return self.change_receipts(source_id, expected=expected,
                                    change=lambda refs: [item for item in refs if item['id'] != file_id])
