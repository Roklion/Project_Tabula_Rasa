"""In-memory domain repositories with no provider or UI imports."""

from copy import deepcopy

from tabula_rasa.application import AssetService, MixedUseService, RecurringService
from tabula_rasa.application.recurring_contracts import RecurringSnapshot
from tabula_rasa.asset import assert_expected_asset
from tabula_rasa.errors import StorageConflictError, StorageNotFoundError
from tabula_rasa.mixed_use_records import (
    validate_mixed_use_records,
    validate_mixed_use_changes,
)
from tests.accounting_service_fakes import Transactions, Journals


class Assets:
    def __init__(self, transactions):
        self.transactions = transactions
        self.records = {}
        self.error = None
        self.calls = 0

    def _call(self):
        self.calls += 1
        if self.error is not None:
            raise self.error

    def _history(self, identity):
        return [
            deepcopy(record)
            for record in self.transactions.records.values()
            if record.get("source_type") == "depreciation"
            and record.get("source_id") == identity
        ]

    def _current(self, identity, expected):
        if identity not in self.records:
            raise StorageNotFoundError("Asset no longer exists")
        current = deepcopy(self.records[identity])
        assert_expected_asset(current, expected)
        return current

    def list(self, *, fresh=False):
        return deepcopy(list(self.records.values()))

    def create(self, record):
        self._call()
        if record["id"] in self.records:
            raise StorageConflictError("Asset ID already exists")
        self.records[record["id"]] = deepcopy(record)
        return deepcopy(record)

    def update(self, identity, *, expected, build):
        self._call()
        record = build(self._current(identity, expected), self._history(identity))
        self.records[identity] = deepcopy(record)
        return deepcopy(record)

    def delete(self, identity, *, expected, validate):
        self._call()
        validate(self._current(identity, expected), self._history(identity))
        del self.records[identity]

    def post(self, identity, *, expected, build):
        self._call()
        records = build(
            self._current(identity, expected),
            self.transactions._references(),
            deepcopy(list(self.transactions.records.values())),
        )
        for record in records:
            self.transactions.records[record["id"]] = deepcopy(record)
        return deepcopy(records)


class MixedUse:
    def __init__(self, transactions):
        self.transactions = transactions
        self.records = {}
        self.error = None
        self.calls = 0

    def _call(self):
        self.calls += 1
        if self.error is not None:
            raise self.error

    def sources(self, *, fresh=False):
        return deepcopy(list(self.records.values()))

    def list(self, *, fresh=False):
        validate_mixed_use_records(
            list(self.records.values()), list(self.transactions.records.values())
        )
        return self.sources(fresh=fresh)

    def get(self, identity, *, fresh=False):
        if identity not in self.records:
            raise StorageNotFoundError("Mixed-use source no longer exists")
        current = deepcopy(self.records[identity])
        validate_mixed_use_records(
            [current], [self.transactions.records[current["linked_transaction_id"]]]
        )
        return current

    def create(self, data, *, build, recurring=False):
        self._call()
        source, projection = build(
            data,
            self.transactions._references(),
            source_id=data["source_id"],
            linked_transaction_id=data["linked_transaction_id"],
        )
        if (
            source["id"] in self.records
            or projection["id"] in self.transactions.records
        ):
            raise StorageConflictError("Mixed-use identities already exist")
        validate_mixed_use_records([source], [projection])
        self.records[source["id"]] = deepcopy(source)
        self.transactions.records[projection["id"]] = deepcopy(projection)
        return deepcopy(source)

    def update(self, identity, changes, *, expected, build):
        self._call()
        current = self.get(identity, fresh=True)
        if expected is not None and current != expected:
            raise StorageConflictError("Mixed-use source changed")
        validate_mixed_use_changes(current, changes)
        original = self.transactions.records[current["linked_transaction_id"]]
        source, projection = build(
            {**current, **changes},
            self.transactions._references(),
            source_id=identity,
            linked_transaction_id=current["linked_transaction_id"],
            created_at=current["created_at"],
            original_transaction=original,
        )
        validate_mixed_use_records([source], [projection])
        self.records[identity] = deepcopy(source)
        self.transactions.records[projection["id"]] = deepcopy(projection)
        return deepcopy(source)

    def delete(self, identity, *, expected):
        self._call()
        current = self.get(identity, fresh=True)
        if expected is not None and current != expected:
            raise StorageConflictError("Mixed-use source changed")
        del self.transactions.records[current["linked_transaction_id"]]
        del self.records[identity]


class Recurring:
    def __init__(self, transactions, mixed_use):
        self.transactions, self.mixed_use = transactions, mixed_use
        self.records = {}

    def snapshot(self, *, fresh=False):
        return RecurringSnapshot(
            deepcopy(list(self.records.values())),
            deepcopy(list(self.transactions.records.values())),
            self.mixed_use.sources(fresh=fresh),
            self.transactions._references(),
        )

    def create(self, identity, *, build):
        record = build(self.transactions._references(), None)
        if identity in self.records:
            raise StorageConflictError("Schedule ID already exists")
        self.records[identity] = deepcopy(record)
        return deepcopy(record)

    def update(self, identity, *, expected, build):
        if identity not in self.records:
            raise StorageNotFoundError("Schedule no longer exists")
        current = deepcopy(self.records[identity])
        if expected is not None and any(
            key in current and current[key] != value
            for key, value in expected.items()
            if key not in {"updated_at", "attention_code", "attention_at"}
        ):
            raise StorageConflictError("Schedule changed")
        record = build(self.transactions._references(), current)
        self.records[identity] = deepcopy(record)
        return deepcopy(record)

    def reconcile(self, process):
        return process(self.snapshot(fresh=True))

    def attention(self, identity, code):
        self.records[identity]["attention_code"] = code


class Workflows:
    def __init__(self):
        self.transactions = Transactions()
        self.transactions.accounts["offset"] = {
            "id": "offset",
            "type": "Other",
            "classification": "Asset",
            "active": True,
        }
        self.transactions.accounts["cash"].update(type="Cash", classification="Asset")
        self.transaction_service = self.transactions.service()
        self.journal_service = Journals().service()
        self.asset_repository = Assets(self.transactions)
        self.assets = AssetService(self.asset_repository, journals=self.journal_service)
        self.mixed_repository = MixedUse(self.transactions)
        self.mixed_use = MixedUseService(
            self.mixed_repository, transactions=self.transaction_service
        )
        self.recurring_repository = Recurring(self.transactions, self.mixed_repository)
        self.recurring = RecurringService(
            self.recurring_repository,
            transactions=self.transaction_service,
            mixed_use=self.mixed_use,
        )
