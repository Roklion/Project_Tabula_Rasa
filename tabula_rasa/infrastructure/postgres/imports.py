"""Bounded, atomic imports through the existing reference/accounting services."""

from uuid import NAMESPACE_URL, uuid5
from dataclasses import replace

from sqlalchemy import text

from tabula_rasa.application.imports import (
    TransactionImportContext, csv_transaction_inputs, preview_quickbooks,
)
from tabula_rasa.application.reference_data import PayeeService, TagService
from tabula_rasa.application.transactions import TransactionService
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.quickbooks_import import fingerprint, normalize_rows
from tabula_rasa.reference_data import normalize_payee_name
from .accounting import PostgresTransactionRepository
from .concurrency import baseline_for
from .provenance import bounded_rows, complete_import, completed_import, import_identity
from .reference_data import (
    PostgresAccountRepository, PostgresCategoryRepository, PostgresPayeeRepository,
    PostgresTagRepository,
)
from .repository import EntityRepository


CSV_FIELDS = ('Date', 'Type', 'Amount', 'Account', 'Category', 'Payee', 'Description', 'Reference')
QUICKBOOKS_FIELDS = ('Date', 'Transaction Type', 'Num', 'Name', 'Memo/Description', 'Account', 'Split', 'Amount')


class PostgresTransactionImportRepository(EntityRepository):
    def __init__(self, database, entity_id):
        super().__init__(database, entity_id)
        self.accounts = PostgresAccountRepository(database, entity_id)
        self.categories = PostgresCategoryRepository(database, entity_id)
        self.payees = PostgresPayeeRepository(database, entity_id)
        self.tags = PostgresTagRepository(database, entity_id)
        self.accounting = PostgresTransactionRepository(database, entity_id)
        self.transactions = TransactionService(
            self.accounting,
            payees=PayeeService(self.payees), tags=TagService(self.tags),
        )

    def context(self, connection, *, lock=False):
        if lock:
            self.accounting.references(connection, lock=True)
        return TransactionImportContext(
            self.accounts.list(active_only=False), self.categories.list(), self.payees.list(),
            self.transactions.list(),
            tuple(connection.execute(text(
                "SELECT fingerprint FROM import_records WHERE entity_id=:scope AND record_kind='entry'"
            ), {'scope': self.entity_id}).scalars()),
        )

    def quickbooks_context(self):
        with self.operation(read_only=True) as connection:
            # All nested reads share one committed snapshot.
            self.lock_entity_read(connection)
            return self.context(connection)

    def lock_entity_read(self, connection):
        # Validate scope without taking a write lock in a read-only snapshot.
        if connection.scalar(text('SELECT id FROM business_entities WHERE id=:scope'),
                             {'scope': self.entity_id}) is None:
            from tabula_rasa.errors import StorageNotFoundError
            raise StorageNotFoundError('The selected business entity does not exist.')

    def identity(self, source, rows):
        fields = CSV_FIELDS if source == 'csv' else QUICKBOOKS_FIELDS
        return import_identity(source+'-v1', [
            [str(row.get(field) or '').strip() for field in fields] for row in rows
        ])

    def persist(self, connection, source, batch_id, positioned):
        records = []
        accepted = []
        for position, inputs in positioned:
            # Identity exists before a write and is reproducible after uncertainty.
            identity = uuid5(NAMESPACE_URL, f'tabula-rasa-import-v1:{self.entity_id}:{batch_id}:{position}').hex
            created = self.transactions.create(transaction_id=identity, **inputs)
            accepted.append(created)
            records.append((position, 'entry', identity, fingerprint(created)))
        complete_import(connection, self.entity_id, batch_id, source, source+'-v1', records)
        # Target-owned attribution advances entry baselines; project those versions.
        return [{**item, 'baseline': baseline_for(
            self.accounting.key('entries', item['id']), self.accounting.entry(connection, item['id']),
        )} for item in accepted]

    def import_csv(self, rows):
        rows = bounded_rows(rows)
        if not rows:
            return []
        batch_id = self.identity('csv', rows)
        with self.operation() as connection:
            # Serialize submitted import batches and supported reference/entry writes
            # before fresh selection. No application retry or Sheets fallback.
            self.lock_entity(connection)
            if completed_import(connection, self.entity_id, batch_id):
                return []
            inputs = csv_transaction_inputs(rows, self.context(connection, lock=True))
            return self.persist(connection, 'csv', batch_id, enumerate(inputs, 2))

    def import_quickbooks(self, rows, *, auto_create=False):
        rows = bounded_rows(rows)
        if not rows:
            return []
        batch_id = self.identity('quickbooks', rows)
        with self.operation() as connection:
            self.lock_entity(connection)
            if completed_import(connection, self.entity_id, batch_id):
                return []
            context = self.context(connection, lock=True)
            preview = preview_quickbooks(rows, context, auto_create=auto_create)
            if preview['errors']:
                raise StorageValidationError('QuickBooks contains invalid rows; correct the import preview before submitting.')
            if auto_create:
                for name in preview['new_accounts']:
                    self.accounts.create(
                        name, preview['new_account_types'][name], '0.00',
                        classification=preview['new_account_classifications'][name], parent_id='',
                    )
                for name, kind in preview['new_categories']:
                    self.categories.create(name, kind, parent_id='')
                context = replace(context, accounts=self.accounts.list(active_only=False),
                                  categories=self.categories.list())
                preview = preview_quickbooks(rows, context)
                if preview['errors']:
                    raise StorageValidationError('QuickBooks references could not be prepared; reload the import preview.')
            # Preserve actual source row numbers, including skipped duplicates.
            normalized, _ = normalize_rows(rows, context.accounts, context.categories)
            canonical_payees = {normalize_payee_name(item['name']): item['name'] for item in context.payees}
            positions = {}
            for item in normalized:
                name = item.get('payee', '')
                key = normalize_payee_name(name)
                if key:
                    item['payee'] = canonical_payees.setdefault(key, name)
                positions.setdefault(fingerprint(item), int(item['_source_row']))
            positioned = []
            for item in preview['rows']:
                inputs = {key: value for key, value in item.items() if key != 'payee'}
                inputs['new_payee_name'] = item.get('payee', '')
                positioned.append((positions[fingerprint(item)], inputs))
            return self.persist(connection, 'quickbooks', batch_id, positioned)
