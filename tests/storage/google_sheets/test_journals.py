from __future__ import annotations

import csv
import hashlib
import io
import json
from unittest.mock import Mock
import zipfile

import pytest

from tabula_rasa.storage import (
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
)

from ._support import GoogleSheetsStorageTestCase
from ._support import FakeWorkbook, GoogleSheetsStorage


class TestJournalStorage(GoogleSheetsStorageTestCase):
    def setup_method(self) -> None:
        super().setup_method()
        self.account = self.storage.create_account("Checking", "Bank")
        self.category = self.storage.create_category("Office", "Expense")

    def postings(self, amount: str = "100.00") -> list[dict[str, str]]:
        return [
            {
                "id": "posting-1",
                "target_type": "category",
                "target_id": self.category["id"],
                "side": "Debit",
                "amount": amount,
                "payee_id": "",
                "description": "Office supplies",
            },
            {
                "id": "posting-2",
                "target_type": "account",
                "target_id": self.account["id"],
                "side": "Credit",
                "amount": amount,
                "payee_id": "",
                "description": "Cash paid",
            },
        ]

    def create(self) -> dict[str, object]:
        return self.storage.create_journal_entry(
            entry_id="journal-1",
            txn_date="2026-09-20",
            description="Split expense",
            postings=self.postings(),
        )

    def test_create_lists_one_complete_entry_with_one_batch(self) -> None:
        self.workbook.batch_update = Mock(wraps=self.workbook.batch_update)

        created = self.create()

        assert created["id"] == "journal-1"
        assert created["total_debits"] == "100.00"
        assert [posting["position"] for posting in created["postings"]] == [1, 2]
        assert self.storage.get_journal_entry("journal-1")["postings"] == created[
            "postings"
        ]
        requests = self.workbook.batch_update.call_args.args[0]["requests"]
        assert len(requests) == 2
        assert all("appendCells" in request for request in requests)

    def test_repeated_create_is_idempotent_but_conflicting_payload_is_rejected(
        self,
    ) -> None:
        created = self.create()
        self.workbook.batch_update = Mock(wraps=self.workbook.batch_update)

        repeated = self.create()

        assert repeated == created
        self.workbook.batch_update.assert_not_called()
        with pytest.raises(StorageConflictError, match="different data"):
            self.storage.create_journal_entry(
                entry_id="journal-1",
                txn_date="2026-09-21",
                description="Changed",
                postings=self.postings(),
            )

    def test_edit_replaces_complete_posting_set_and_preserves_stable_ids(self) -> None:
        original = self.create()
        edited_postings = [
            {**self.postings("60.00")[0], "amount": "60.00"},
            {
                "id": "posting-3",
                "target_type": "category",
                "target_id": self.category["id"],
                "side": "Debit",
                "amount": "40.00",
                "payee_id": "",
                "description": "Second split",
            },
            self.postings()[1],
        ]

        edited = self.storage.edit_journal_entry(
            "journal-1",
            expected_entry=original,
            description="Three lines",
            postings=edited_postings,
        )

        assert edited["description"] == "Three lines"
        assert [posting["id"] for posting in edited["postings"]] == [
            "posting-1",
            "posting-3",
            "posting-2",
        ]
        assert len(self.workbook.sheets["JournalEntries"].rows) == 2
        assert len(self.workbook.sheets["JournalPostings"].rows) == 4

    def test_edit_and_delete_require_the_complete_fresh_baseline(self) -> None:
        original = self.create()
        stale = {**original, "description": "Stale"}

        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.edit_journal_entry(
                "journal-1", expected_entry=stale, description="Updated"
            )
        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.delete_journal_entry("journal-1", expected_entry=stale)

        self.storage.delete_journal_entry("journal-1", expected_entry=original)
        assert self.storage.list_journal_entries(_force_refresh=True) == []
        assert len(self.workbook.sheets["JournalPostings"].rows) == 1

    def test_malformed_expected_posting_is_a_safe_stale_write_conflict(self) -> None:
        original = self.create()
        malformed = {
            **original,
            "postings": [
                {**original["postings"][0], "position": "not-a-position"},
                original["postings"][1],
            ],
        }

        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.edit_journal_entry(
                "journal-1", expected_entry=malformed, description="Updated"
            )

    def test_uncertain_committed_create_uses_one_readback_without_retry(self) -> None:
        original_batch = self.workbook.batch_update
        writes = 0

        def commit_then_timeout(body: dict[str, object]) -> None:
            nonlocal writes
            writes += 1
            original_batch(body)
            raise StorageUnavailableError("response lost", retryable=True)

        self.workbook.batch_update = Mock(side_effect=commit_then_timeout)

        created = self.create()

        assert created["id"] == "journal-1"
        assert writes == 1

    def test_uncertain_uncommitted_create_stops_without_retry(self) -> None:
        writes = 0

        def timeout(_body: dict[str, object]) -> None:
            nonlocal writes
            writes += 1
            raise StorageUnavailableError("response lost", retryable=True)

        self.workbook.batch_update = Mock(side_effect=timeout)

        with pytest.raises(StorageUnavailableError, match="could not confirm"):
            self.create()

        assert writes == 1
        assert len(self.workbook.sheets["JournalEntries"].rows) == 1
        assert len(self.workbook.sheets["JournalPostings"].rows) == 1

    @pytest.mark.parametrize("operation", ["edit", "delete"])
    def test_uncertain_committed_existing_mutation_uses_one_readback(
        self, operation: str
    ) -> None:
        original = self.create()
        original_batch = self.workbook.batch_update
        writes = 0

        def commit_then_timeout(body: dict[str, object]) -> None:
            nonlocal writes
            writes += 1
            original_batch(body)
            raise StorageUnavailableError("response lost", retryable=True)

        self.workbook.batch_update = Mock(side_effect=commit_then_timeout)

        if operation == "edit":
            result = self.storage.edit_journal_entry(
                "journal-1", expected_entry=original, description="Updated"
            )
            assert result["description"] == "Updated"
        else:
            self.storage.delete_journal_entry(
                "journal-1", expected_entry=original
            )
            assert self.storage.list_journal_entries(_force_refresh=True) == []
        assert writes == 1

    def test_stored_orphan_is_rejected(self) -> None:
        headers = self.workbook.sheets["JournalPostings"].rows[0]
        orphan = {
            "id": "posting-1",
            "parent_entry_id": "missing",
            "position": "1",
            "target_type": "account",
            "target_id": self.account["id"],
            "side": "Debit",
            "amount": "1.00",
        }
        self.workbook.sheets["JournalPostings"].rows.append(
            [str(orphan.get(header, "")) for header in headers]
        )

        with pytest.raises(StorageValidationError, match="unknown parent"):
            self.storage.list_journal_entries(_force_refresh=True)

    def test_stored_duplicate_ids_are_rejected(self) -> None:
        self.create()
        self.workbook.sheets["JournalEntries"].rows.append(
            list(self.workbook.sheets["JournalEntries"].rows[1])
        )

        with pytest.raises(StorageValidationError, match="Duplicate ID"):
            self.storage.list_journal_entries(_force_refresh=True)

    def test_write_rejects_posting_from_another_parent(self) -> None:
        postings = self.postings()
        postings[0]["parent_entry_id"] = "another-journal"

        with pytest.raises(StorageValidationError, match="different parent"):
            self.storage.create_journal_entry(
                entry_id="journal-1",
                txn_date="2026-09-20",
                postings=postings,
            )

    def test_category_delete_and_kind_change_reject_journal_reference(self) -> None:
        self.create()

        with pytest.raises(StorageConflictError, match="journal"):
            self.storage.delete_category(self.category["id"])
        with pytest.raises(StorageConflictError, match="journal"):
            self.storage.edit_category(self.category["id"], kind="Income")

    def test_payee_merge_rewrites_journal_posting_before_removal(self) -> None:
        target = self.storage.create_payee("Target")
        source = self.storage.create_payee("Source")
        postings = self.postings()
        postings[0]["payee_id"] = source["id"]
        self.storage.create_journal_entry(
            entry_id="journal-1",
            txn_date="2026-09-20",
            postings=postings,
        )

        self.storage.merge_payees(target["id"], [source["id"]])

        entry = self.storage.get_journal_entry("journal-1", _force_refresh=True)
        assert entry["postings"][0]["payee_id"] == target["id"]
        assert {payee["id"] for payee in self.storage.list_payees()} == {target["id"]}

    def test_inactive_account_may_be_retained_but_not_newly_selected(self) -> None:
        original = self.create()
        self.storage.deactivate_account(self.account["id"])

        retained = self.storage.edit_journal_entry(
            "journal-1",
            expected_entry=original,
            description="Historical account retained",
        )
        replacement = [dict(posting) for posting in retained["postings"]]
        replacement[1]["id"] = "posting-new"

        with pytest.raises(StorageValidationError, match="inactive"):
            self.storage.edit_journal_entry(
                "journal-1", expected_entry=retained, postings=replacement
            )

    def test_backup_roundtrip_preserves_complete_journal(self) -> None:
        original = self.create()
        backup = self.storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )
        restored = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        counts = restored.restore_backup_zip(backup)

        assert counts["JournalEntries"] == 1
        assert counts["JournalPostings"] == 2
        actual = restored.get_journal_entry("journal-1", _force_refresh=True)
        assert actual["txn_date"] == original["txn_date"]
        assert [posting["id"] for posting in actual["postings"]] == [
            "posting-1",
            "posting-2",
        ]

    def test_backup_validation_rejects_unbalanced_journal(self) -> None:
        self.create()
        backup = self.storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )
        with zipfile.ZipFile(io.BytesIO(backup)) as source:
            files = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(files["manifest.json"])
        rows = list(
            csv.reader(io.StringIO(files["JournalPostings.csv"].decode("utf-8")))
        )
        amount_index = rows[0].index("amount")
        rows[1][amount_index] = "99.00"
        buffer = io.StringIO(newline="")
        csv.writer(buffer, lineterminator="\n").writerows(rows)
        files["JournalPostings.csv"] = buffer.getvalue().encode("utf-8")
        manifest["sha256"]["JournalPostings.csv"] = hashlib.sha256(
            files["JournalPostings.csv"]
        ).hexdigest()
        files["manifest.json"] = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as destination:
            for name, content in files.items():
                destination.writestr(name, content)

        with pytest.raises(StorageValidationError, match="balance"):
            self.storage.validate_backup_zip(output.getvalue())

    def test_equal_ids_remain_isolated_between_profile_workbooks(self) -> None:
        self.create()
        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        other_account = other.create_account("Checking", "Bank")
        other_category = other.create_category("Office", "Expense")
        other.create_journal_entry(
            entry_id="journal-1",
            txn_date="2026-09-21",
            description="Other profile",
            postings=[
                {
                    "id": "posting-1",
                    "target_type": "category",
                    "target_id": other_category["id"],
                    "side": "Debit",
                    "amount": "12.00",
                },
                {
                    "id": "posting-2",
                    "target_type": "account",
                    "target_id": other_account["id"],
                    "side": "Credit",
                    "amount": "12.00",
                },
            ],
        )

        assert self.storage.get_journal_entry("journal-1")["description"] == (
            "Split expense"
        )
        assert other.get_journal_entry("journal-1")["description"] == "Other profile"
