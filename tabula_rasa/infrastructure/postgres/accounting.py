"""Canonical entry/posting persistence with disjoint Simple Ledger/journal ports."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import text

from tabula_rasa.accounting_postings import accounting_postings
from tabula_rasa.errors import StorageConflictError, StorageNotFoundError, StorageValidationError
from tabula_rasa.journal import prepare_journal_postings
from tabula_rasa.ledger_validation import decode_receipt_references, iso_date
from tabula_rasa.reference_data import as_bool, clean_text, normalize_tag_ids
from tabula_rasa.transaction import (
    RECURRING_FIELDS, TransactionReferences, prepare_bulk_transaction_changes,
    prepare_transaction, reject_derived_transaction, validate_transaction_update,
)
from .reference_data import reference_record
from .repository import EntityRepository, insert, new_object, record, replace, serialized
from .concurrency import lock_aggregates
from .documents import receipt_reference, write_document_links


def entry_values(prepared):
    """Shared simple-entry payload for runtime and explicit historical loading."""
    return {'txn_date': iso_date(prepared['txn_date']), 'simple_kind': prepared['kind'],
            'description': prepared['description'], 'reference': prepared['reference'],
            'payee_id': prepared['payee_id'] or None}


class _AccountingRepository(EntityRepository):
    projection = ''

    def references(self, connection, *, lock=False, entry_ids=()):
        if lock:
            # Hierarchy writers acquire the entity before reference rows. This
            # FK-compatible lock avoids the opposite order at entry insert time.
            self.lock_entity(connection, key_share=True)
        lookups = []
        for table in ('accounts', 'categories', 'payees', 'tags'):
            if lock and table == 'payees':
                lock_aggregates(connection, [self.key('entries', identity) for identity in entry_ids])
            lookups.append({row['id']: reference_record(row, table) for row in self.rows(connection, table, lock=lock)})
        return TransactionReferences(*lookups)

    def entry(self, connection, identity, *, lock=False):
        row = self.get_row(connection, 'entries', identity, lock=lock)
        if row['projection_kind'] != self.projection:
            raise StorageNotFoundError('The selected entry is not available through this ledger projection.')
        return row

    def lines(self, connection, identity):
        return [dict(row) for row in connection.execute(text(
            'SELECT * FROM postings WHERE entity_id=:scope AND entry_id=:id ORDER BY position'
        ), {'scope': self.entity_id, 'id': identity}).mappings()]

    def entry_rows(self, connection, *, start=None, end=None):
        where = 'entity_id=:scope AND projection_kind=:projection'
        params = {'scope': self.entity_id, 'projection': self.projection}
        if start is not None:
            where += ' AND txn_date>=:start'
            params['start'] = iso_date(start)
        if end is not None:
            where += ' AND txn_date<=:end'
            params['end'] = iso_date(end)
        return [dict(row) for row in connection.execute(text(
            f'SELECT * FROM entries WHERE {where} ORDER BY txn_date DESC, created_at DESC, id DESC'
        ), params).mappings()]

    def write_lines(self, connection, identity, lines):
        connection.execute(text('DELETE FROM postings WHERE entity_id=:scope AND entry_id=:id'),
                           {'scope': self.entity_id, 'id': identity})
        for position, line in enumerate(lines, 1):
            insert(connection, 'postings', {
                'entity_id': self.entity_id, 'id': line['id'], 'entry_id': identity,
                'projection_kind': self.projection, 'position': position,
                'account_id': line['target_id'] if line['target_type'] == 'account' else None,
                'category_id': line['target_id'] if line['target_type'] == 'category' else None,
                'side': line['side'], 'amount': line['amount'],
                'payee_id': line.get('payee_id') or None, 'description': line.get('description', ''),
            })


class PostgresTransactionRepository(_AccountingRepository):
    projection = 'simple'

    def prepare_workspace(self):
        """SQL has no workbook preparation or process-local read cache."""

    def project(self, connection, row):
        result = record(row, 'entries', ('id', 'description', 'reference', 'created_at', 'payee_id'))
        result['txn_date'] = row['txn_date'].isoformat()
        kind = result['kind'] = row['simple_kind']
        first, second = self.lines(connection, row['id'])
        result.update(amount=serialized(first['amount']),
                      account_id=first['account_id'] if kind == 'Income' else second['account_id'],
                      to_account_id=first['account_id'] if kind == 'Transfer' else '',
                      category_id=(first['category_id'] or second['category_id'] or ''))
        result['payee'] = connection.scalar(text('SELECT name FROM payees WHERE entity_id=:scope AND id=:id'),
                                            {'scope': self.entity_id, 'id': row['payee_id']}) or ''
        source = row['mixed_use_source_id']
        tag_table, tag_owner = ('mixed_use_tags', 'source_id') if source else ('entry_tags', 'entry_id')
        labels = connection.execute(text(
            f'SELECT t.id,t.name FROM {tag_table} l JOIN tags t ON t.entity_id=l.entity_id AND t.id=l.tag_id '
            f'WHERE l.entity_id=:scope AND l.{tag_owner}=:id ORDER BY t.id'
        ), {'scope': self.entity_id, 'id': source or row['id']}).all()
        result['tag_ids'] = [item.id for item in labels]
        result['tags'] = [item.name for item in labels]
        result['source_type'] = 'mixed_use_expense' if source else 'depreciation' if row['depreciation_asset_id'] else ''
        result['source_id'] = source or row['depreciation_asset_id'] or ''
        occurrence = connection.execute(text(
            'SELECT * FROM recurring_occurrences WHERE entity_id=:scope AND '
            + ('mixed_use_source_id=:id' if source else 'entry_id=:id')
        ), {'scope': self.entity_id, 'id': source or row['id']}).mappings().first()
        values = [occurrence['schedule_id'], occurrence['scheduled_date'].isoformat(),
                  occurrence['source_kind'], occurrence['occurrence_type']] if occurrence else ['', '', '', '']
        result.update(zip(RECURRING_FIELDS, values))
        docs = connection.execute(text(
            'SELECT d.* FROM document_links l JOIN documents d ON d.entity_id=l.entity_id AND d.id=l.document_id '
            'WHERE l.entity_id=:scope AND ' + ('l.mixed_use_source_id=:id' if source else 'l.entry_id=:id')
            + ' ORDER BY l.position'
        ), {'scope': self.entity_id, 'id': source or row['id']}).mappings()
        result['receipt_references'] = [self.receipt_reference(doc) for doc in docs]
        return result

    @staticmethod
    def receipt_reference(doc):
        return receipt_reference(doc)

    def list(self, *, start=None, end=None, kind=None, account_ids=None, fresh=False):
        if kind is not None and kind not in {'Income', 'Expense', 'Transfer'}:
            raise StorageValidationError('Unknown transaction kind')
        selected = None if account_ids is None else set(account_ids)
        with self.operation(read_only=True) as connection:
            results = [self.project(connection, row) for row in self.entry_rows(connection, start=start, end=end)]
            return [row for row in results if (kind is None or row['kind'] == kind)
                    and (selected is None or {row['account_id'], row['to_account_id']} & selected)]

    def prepare(self, data, references, identity, *, current=None):
        if clean_text(data.get('id'), 'Transaction ID', required=True) != identity:
            raise StorageValidationError('Transaction identity cannot change.')
        reject_derived_transaction(data)
        validate_transaction_update(current or {}, data)
        if current is None and any(data.get(field) for field in RECURRING_FIELDS):
            raise StorageValidationError('Recurring creation requires the recurring repository.')

        def no_inline(name):
            raise StorageValidationError('Inline reference creation belongs to service preparation.')

        # Direct callbacks cannot bypass domain rules. The callback executes
        # once; its new references are visible in the shared transaction.
        inputs = {key: value for key, value in data.items() if key != 'payee'}
        return prepare_transaction(
            inputs, transaction_id=identity, created_at=current['created_at'] if current else data.get('created_at'),
            accounts=references.accounts, categories=references.categories, payees=references.payees, tags=references.tags,
            create_payee=no_inline, create_tag=no_inline, original_transaction=current,
        )

    def inline_references(self, connection, references, built):
        """Refresh selected new or previously inactive callback references."""
        lookups = []
        for table, originals, identities in (
            ('payees', references.payees, [built.get('payee_id')]),
            ('tags', references.tags, normalize_tag_ids(built.get('tag_ids'))),
        ):
            lookup = dict(originals)
            for identity in identities:
                if not identity or (identity in lookup and as_bool(lookup[identity]['active'])):
                    continue
                row = connection.execute(text(
                    f'SELECT * FROM {table} WHERE entity_id=:scope AND id=:id FOR SHARE'
                ), {'scope': self.entity_id, 'id': identity}).mappings().first()
                if row is None:
                    raise StorageValidationError('A prepared reference does not exist in this entity.')
                lookup[identity] = reference_record(row, table)
            lookups.append(lookup)
        return TransactionReferences(references.accounts, references.categories, *lookups)

    def write(self, connection, identity, prepared, *, create=False):
        values = entry_values(prepared)
        if create:
            insert(connection, 'entries', new_object(
                self.entity_id, id=identity, projection_kind='simple',
                created_at=datetime.fromisoformat(prepared['created_at'].replace('Z', '+00:00')), **values,
            ))
        else:
            replace(connection, 'entries', self.entity_id, identity, values)
        self.write_lines(connection, identity, accounting_postings([prepared]))
        connection.execute(text('DELETE FROM entry_tags WHERE entity_id=:scope AND entry_id=:id'),
                           {'scope': self.entity_id, 'id': identity})
        for tag_id in normalize_tag_ids(prepared['tag_ids']):
            insert(connection, 'entry_tags', {'entity_id': self.entity_id, 'entry_id': identity, 'tag_id': tag_id})
        self.write_receipts(connection, identity, prepared['receipt_references'])
        # Detail triggers advance the root after its INSERT/UPDATE RETURNING.
        return self.project(connection, self.entry(connection, identity))

    def write_receipts(self, connection, identity, references):
        # #251 owns document metadata acceptance and the external store. This
        # slice links existing metadata without fabricating its storage scope.
        documents = []
        for reference in decode_receipt_references(references):
            rows = connection.execute(text(
                'SELECT * FROM documents WHERE entity_id=:scope AND storage_key=:key '
                + ('AND id=:id ' if reference.get('receipt_id') else '') + 'FOR UPDATE'
            ), {'scope': self.entity_id, 'key': reference['id'], 'id': reference.get('receipt_id')}).mappings().all()
            if len(rows) != 1 or self.receipt_reference(rows[0]) != reference:
                raise StorageValidationError('Receipt metadata must already exist in this entity and match the reference.')
            documents.append(rows[0]['id'])
        write_document_links(connection, self.entity_id, 'entry_id', identity, documents)

    def create(self, transaction_id, *, build):
        identity = clean_text(transaction_id, 'Transaction ID', required=True)
        with self.operation() as connection:
            references = self.references(connection, lock=True)
            if connection.execute(text('SELECT 1 FROM entries WHERE entity_id=:scope AND id=:id'),
                                  {'scope': self.entity_id, 'id': identity}).first():
                raise StorageConflictError('The entry identity already exists; refresh the ledger.')
            built = dict(build(references, None))
            prepared = self.prepare(built, self.inline_references(connection, references, built), identity)
            return self.write(connection, identity, prepared, create=True)

    def update(self, transaction_id, *, build, expected=None):
        identity = clean_text(transaction_id, 'Transaction ID', required=True)
        with self.operation() as connection:
            references = self.references(connection, lock=True, entry_ids=[identity])
            row = self.entry(connection, identity, lock=True)
            current = self.project(connection, row)
            reject_derived_transaction(current)
            self.check_expected(row, 'entries', expected, current)
            built = dict(build(references, current))
            prepared = self.prepare(built, self.inline_references(connection, references, built), identity, current=current)
            return self.write(connection, identity, prepared)

    def delete_entry(self, connection, identity):
        connection.execute(text('DELETE FROM recurring_occurrences WHERE entity_id=:scope AND entry_id=:id'),
                           {'scope': self.entity_id, 'id': identity})
        self.delete_row(connection, 'entries', identity)

    def delete(self, transaction_id, *, expected=None):
        with self.operation() as connection:
            row = self.entry(connection, transaction_id, lock=True)
            current = self.project(connection, row)
            reject_derived_transaction(current)
            self.check_expected(row, 'entries', expected, current)
            self.delete_entry(connection, transaction_id)

    def selection(self, connection, identities, expected):
        identities = [clean_text(identity, 'Transaction ID', required=True) for identity in identities]
        if not identities or len(set(identities)) != len(identities):
            raise StorageValidationError('Select unique transaction identities.')
        by_id = {item['id']: item for item in expected}
        if len(by_id) != len(expected) or set(by_id) != set(identities):
            raise StorageConflictError('The loaded transaction selection does not match.')
        selected = []
        lock_aggregates(connection, [self.key('entries', identity) for identity in identities])
        for identity in sorted(identities):
            row = self.entry(connection, identity)
            current = self.project(connection, row)
            reject_derived_transaction(current)
            self.check_expected(row, 'entries', by_id[identity], current)
            selected.append(current)
        return selected

    def bulk_update(self, transaction_ids, *, expected, changes):
        transaction_ids = list(transaction_ids)
        with self.operation() as connection:
            references = self.references(connection, lock=True, entry_ids=transaction_ids)
            selected = self.selection(connection, transaction_ids, expected)
            changes = prepare_bulk_transaction_changes(changes, selected, categories=references.categories,
                                                       payees=references.payees, tags=references.tags)
            count = 0
            for current in selected:
                if not any(current.get(key) != value for key, value in changes.items()):
                    continue
                prepared = self.prepare({**current, **changes}, references, current['id'], current=current)
                self.write(connection, current['id'], prepared)
                count += 1
        return {'status': 'fully_applied', 'count': str(count)}

    def bulk_delete(self, transaction_ids, *, expected):
        with self.operation() as connection:
            selected = self.selection(connection, transaction_ids, expected)
            for current in selected:
                self.delete_entry(connection, current['id'])
        return {'status': 'fully_applied', 'count': str(len(selected))}


class PostgresJournalRepository(_AccountingRepository):
    projection = 'journal'
    expected_fields = ('id', 'txn_date', 'description', 'created_at', 'updated_at', 'postings')

    def project(self, connection, row):
        result = record(row, 'entries', ('id', 'description', 'created_at', 'updated_at'))
        result['txn_date'] = row['txn_date'].isoformat()
        postings = []
        for line in self.lines(connection, row['id']):
            posting = {key: serialized(line[key]) for key in ('id', 'position', 'side', 'amount', 'payee_id', 'description')}
            posting.update(parent_entry_id=row['id'], target_type='account' if line['account_id'] else 'category',
                           target_id=line['account_id'] or line['category_id'])
            posting['payee'] = connection.scalar(text('SELECT name FROM payees WHERE entity_id=:scope AND id=:id'),
                                                 {'scope': self.entity_id, 'id': line['payee_id']}) or ''
            postings.append(posting)
        result['postings'] = postings
        for side, key in [('Debit', 'total_debits'), ('Credit', 'total_credits')]:
            result[key] = format(sum((Decimal(line['amount']) for line in postings if line['side'] == side), Decimal('0.00')), '.2f')
        return result

    def list(self, *, start=None, end=None, fresh=False):
        with self.operation(read_only=True) as connection:
            return [self.project(connection, row) for row in self.entry_rows(connection, start=start, end=end)]

    def get(self, entry_id, *, fresh=False):
        with self.operation(read_only=True) as connection:
            return self.project(connection, self.entry(connection, entry_id))

    def create(self, *, entry_id, txn_date, description, postings):
        identity = clean_text(entry_id, 'Journal ID', required=True)
        with self.operation() as connection:
            refs = self.references(connection, lock=True)
            lines = prepare_journal_postings(identity, postings, accounts=refs.accounts, categories=refs.categories, payees=refs.payees)
            insert(connection, 'entries', new_object(self.entity_id, id=identity, projection_kind='journal',
                         txn_date=iso_date(txn_date), description=clean_text(description, 'Description')))
            self.write_lines(connection, identity, lines)
            return self.project(connection, self.entry(connection, identity))

    def update(self, entry_id, *, expected, txn_date=None, description=None, postings=None):
        if not expected:
            raise StorageValidationError('Journal mutations require a loaded record baseline.')
        with self.operation() as connection:
            refs = self.references(connection, lock=True, entry_ids=[entry_id])
            row = self.entry(connection, entry_id, lock=True)
            current = self.project(connection, row)
            self.check_expected(row, 'entries', expected, current, required_fields=self.expected_fields)
            lines = prepare_journal_postings(entry_id, postings if postings is not None else current['postings'],
                                            accounts=refs.accounts, categories=refs.categories, payees=refs.payees, original_entry=current)
            replace(connection, 'entries', self.entity_id, entry_id, {
                'txn_date': iso_date(txn_date if txn_date is not None else current['txn_date']),
                'description': clean_text(description if description is not None else current['description'], 'Description'),
            })
            self.write_lines(connection, entry_id, lines)
            return self.project(connection, self.entry(connection, entry_id))

    def delete(self, entry_id, *, expected):
        if not expected:
            raise StorageValidationError('Journal mutations require a loaded record baseline.')
        with self.operation() as connection:
            row = self.entry(connection, entry_id, lock=True)
            self.check_expected(row, 'entries', expected, self.project(connection, row),
                                required_fields=self.expected_fields)
            self.delete_row(connection, 'entries', entry_id)
