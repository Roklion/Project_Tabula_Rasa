"""Small persistence-free repositories for accounting application tests."""

from copy import deepcopy

from tabula_rasa.application.accounting_contracts import TransactionReferences
from tabula_rasa.application.reference_data import PayeeService, TagService
from tabula_rasa.application import TransactionService, JournalService
from tabula_rasa.errors import StorageConflictError, StorageNotFoundError
from tabula_rasa.journal import prepare_journal_postings
from tabula_rasa.transaction import (
    prepare_bulk_transaction_changes,
    reject_derived_transaction,
)


class References:
    def __init__(self, label):
        self.label = label
        self.records = {}
        self.calls = 0

    def create(self, name, *, active=True):
        self.calls += 1
        record = {
            "id": f"{self.label}-{len(self.records) + 1}",
            "name": name,
            "active": "TRUE" if active else "FALSE",
            "created_at": "test",
        }
        self.records[record["id"]] = record
        return deepcopy(record)


class Transactions:
    def prepare_workspace(self):
        """In-memory references are already available for workspace reads."""

    def __init__(self):
        self.accounts = {
            "cash": {"id": "cash", "active": True},
            "bank": {"id": "bank", "active": True},
        }
        self.categories = {
            "expense": {"id": "expense", "kind": "Expense"},
            "income": {"id": "income", "kind": "Income"},
        }
        self.payees, self.tags = References("payee"), References("tag")
        self.records = {}
        self.calls = 0
        self.error = None
        self.filters = None

    def _call(self):
        self.calls += 1
        if self.error is not None:
            raise self.error

    def _references(self):
        return TransactionReferences(
            self.accounts, self.categories, self.payees.records, self.tags.records
        )

    def _current(self, identity, expected):
        if identity not in self.records:
            raise StorageNotFoundError("Transaction no longer exists")
        current = self.records[identity]
        reject_derived_transaction(current)
        if expected is not None and current != expected:
            raise StorageConflictError("Transaction changed")
        return deepcopy(current)

    def list(self, **filters):
        self._call()
        self.filters = filters
        return deepcopy(list(self.records.values()))

    def create(self, transaction_id, *, build):
        self._call()
        if transaction_id in self.records:
            raise StorageConflictError("Transaction ID already exists")
        self.records[transaction_id] = dict(build(self._references(), None))
        return deepcopy(self.records[transaction_id])

    def update(self, transaction_id, *, build, expected=None):
        self._call()
        current = self._current(transaction_id, expected)
        self.records[transaction_id] = dict(build(self._references(), current))
        return deepcopy(self.records[transaction_id])

    def delete(self, transaction_id, *, expected=None):
        self._call()
        self._current(transaction_id, expected)
        del self.records[transaction_id]

    def _selection(self, identities, expected):
        if not identities or len(set(identities)) != len(identities):
            raise StorageConflictError("Invalid selection")
        by_id = {record["id"]: record for record in expected}
        if set(by_id) != set(identities) or len(by_id) != len(expected):
            raise StorageConflictError("Selection changed")
        return [self._current(identity, by_id[identity]) for identity in identities]

    def bulk_update(self, transaction_ids, *, expected, changes):
        self._call()
        current = self._selection(transaction_ids, expected)
        normalized = prepare_bulk_transaction_changes(
            changes,
            current,
            categories=self.categories,
            payees=self.payees.records,
            tags=self.tags.records,
        )
        for record in current:
            self.records[record["id"]].update(normalized)
        return {"status": "fully_applied", "count": str(len(current))}

    def bulk_delete(self, transaction_ids, *, expected):
        self._call()
        current = self._selection(transaction_ids, expected)
        for record in current:
            del self.records[record["id"]]
        return {"status": "fully_applied", "count": str(len(current))}

    def service(self):
        return TransactionService(
            self, payees=PayeeService(self.payees), tags=TagService(self.tags)
        )


class Journals:
    def __init__(self, references=None):
        self.references = references or Transactions()
        self.records = {}
        self.calls = 0
        self.error = None

    def _call(self):
        self.calls += 1
        if self.error is not None:
            raise self.error

    def _current(self, identity, expected):
        if identity not in self.records:
            raise StorageNotFoundError("Journal no longer exists")
        current = self.records[identity]
        if expected is not None and current != expected:
            raise StorageConflictError("Journal changed")
        return deepcopy(current)

    def list(self, **filters):
        self._call()
        return deepcopy(list(self.records.values()))

    def get(self, entry_id, *, fresh=False):
        self._call()
        return self._current(entry_id, None)

    def _prepare(self, entry_id, postings, original=None):
        prepared = prepare_journal_postings(
            entry_id,
            postings,
            accounts=self.references.accounts,
            categories=self.references.categories,
            payees=self.references.payees.records,
            original_entry=original,
        )
        other_ids = {
            posting["id"]
            for entry in self.records.values()
            if entry["id"] != entry_id
            for posting in entry["postings"]
        }
        if other_ids & {posting["id"] for posting in prepared}:
            raise StorageConflictError("Posting ID already exists")
        return prepared

    def create(self, *, entry_id, txn_date, description, postings):
        self._call()
        existing = self.records.get(entry_id)
        prepared = self._prepare(entry_id, postings, existing)
        record = {
            "id": entry_id,
            "txn_date": txn_date,
            "description": description,
            "postings": prepared,
            "created_at": "test",
            "updated_at": "test",
        }
        if existing is not None and existing != record:
            raise StorageConflictError("Journal ID already exists")
        self.records[entry_id] = record
        return deepcopy(record)

    def update(
        self, entry_id, *, expected, txn_date=None, description=None, postings=None
    ):
        self._call()
        current = self._current(entry_id, expected)
        current["postings"] = self._prepare(
            entry_id, current["postings"] if postings is None else postings, current
        )
        if txn_date is not None:
            current["txn_date"] = txn_date
        if description is not None:
            current["description"] = description
        self.records[entry_id] = current
        return deepcopy(current)

    def delete(self, entry_id, *, expected):
        self._call()
        self._current(entry_id, expected)
        del self.records[entry_id]

    def service(self):
        return JournalService(self)
