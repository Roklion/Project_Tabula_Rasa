from threading import Event, Thread
from unittest.mock import Mock

from tabula_rasa.storage import StorageConflictError, StorageUnavailableError

from ._support import (
    GoogleSheetsStorageTestCase,
    FakeWorkbook,
    GoogleSheetsStorage,
    StorageValidationError,
    json,
    pytest,
)


class TestGoogleSheetsStorage(GoogleSheetsStorageTestCase):

    def test_tags_are_profile_local_and_deduplicated_by_normalized_name(self) -> None:
        first = self.storage.create_tag("  Client   Visit ")
        duplicate = self.storage.create_tag("client visit")

        assert duplicate["id"] == first["id"]
        assert duplicate["name"] == "Client   Visit"
        assert self.storage.list_tags()[0]["name"] == "Client   Visit"

        inactive = self.storage.create_tag("Internal", active=False)
        assert self.storage.list_tags(active_only=True) == [first]
        reactivated = self.storage.create_tag(" internal ")
        assert reactivated["id"] == inactive["id"]
        assert reactivated["active"] == "TRUE"

        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        other_tag = other.create_tag("client visit")
        assert other_tag["id"] != first["id"]

    def test_transaction_and_mileage_tags_round_trip_and_resolve_names(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        first = self.storage.create_tag("Client")
        second = self.storage.create_tag("Follow-up")
        transaction = self.storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount=10,
            account_id=account["id"],
            category_id=category["id"],
            tag_ids=[second["id"], first["id"]],
        )
        mileage = self.storage.create_mileage_trip(
            trip_date="2026-09-01",
            miles=4.5,
            start_location="Office",
            destination="Client",
            business_purpose="Visit",
            tag_ids=[first["id"], second["id"]],
        )

        assert transaction["tag_ids"] == json.dumps(
            sorted([first["id"], second["id"]]), separators=(",", ":")
        )
        listed_transaction = self.storage.list_transactions()[0]
        listed_mileage = self.storage.list_mileage_trips()[0]
        assert listed_transaction["tag_ids"] == sorted([first["id"], second["id"]])
        assert listed_transaction["tags"] == [
            {first["id"]: "Client", second["id"]: "Follow-up"}[tag_id]
            for tag_id in listed_transaction["tag_ids"]
        ]
        assert listed_mileage["tag_ids"] == sorted([first["id"], second["id"]])
        assert listed_mileage["tags"] == [
            {first["id"]: "Client", second["id"]: "Follow-up"}[tag_id]
            for tag_id in listed_mileage["tag_ids"]
        ]

        edited = self.storage.edit_transaction(transaction["id"], tag_ids=[first["id"]])
        edited_mileage = self.storage.edit_mileage_trip(
            mileage["id"], tag_ids=[second["id"]]
        )
        assert edited["tag_ids"] == json.dumps([first["id"]], separators=(",", ":"))
        assert edited_mileage["tag_ids"] == json.dumps(
            [second["id"]], separators=(",", ":")
        )

    @pytest.mark.parametrize("value", ["not-json", "{}", "[1]", '["tag", "tag"]'])
    def test_tag_ids_reject_invalid_payloads(self, value: str) -> None:
        with pytest.raises(StorageValidationError):
            self.storage._prepare_mileage_trip(
                {
                    "trip_date": "2026-09-01",
                    "miles": 1,
                    "start_location": "A",
                    "destination": "B",
                    "business_purpose": "C",
                    "tag_ids": value,
                }
            )

    def test_tag_ids_reject_unknown_references(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")
        with pytest.raises(StorageValidationError, match="Tag does not exist"):
            self.storage.create_transaction(
                txn_date="2026-09-01",
                kind="Expense",
                amount=10,
                account_id=account["id"],
                category_id=category["id"],
                tag_ids=["missing-tag"],
            )

    def test_invalid_tag_does_not_persist_new_payee(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Office", "Expense")

        with pytest.raises(StorageValidationError, match="Tag does not exist"):
            self.storage.create_transaction(
                txn_date="2026-09-01",
                kind="Expense",
                amount=10,
                account_id=account["id"],
                category_id=category["id"],
                new_payee_name="Orphan payee",
                tag_ids=["missing-tag"],
            )

        assert self.storage.list_payees() == []
        assert self.storage.list_transactions() == []

    def test_invalid_mileage_does_not_create_inline_tag(self) -> None:
        with pytest.raises(StorageValidationError, match="Miles must be greater"):
            self.storage.create_mileage_trip(
                trip_date="2026-09-01",
                miles=0,
                start_location="A",
                destination="B",
                business_purpose="C",
                new_tag_name="Should not persist",
            )

        assert self.storage.list_tags() == []

    def test_invalid_round_trip_return_does_not_create_inline_tag(self) -> None:
        with pytest.raises(StorageValidationError, match="Miles must be greater"):
            self.storage.create_mileage_round_trip(
                trip_date="2026-09-01",
                miles=1,
                return_miles=0,
                start_location="A",
                destination="B",
                business_purpose="C",
                new_tag_name="Should not persist",
            )

        assert self.storage.list_tags() == []
        assert self.storage.list_mileage_trips() == []



def _ledger_setup(storage):
    account = next(item for item in storage.list_accounts(active_only=False) if item["name"] == "Checking")
    category = next(item for item in storage.list_categories() if item["name"] == "Office")
    return account, category


def test_legacy_tag_aliases_remain_available(default_storage) -> None:
    target = default_storage.create_tag("Alias target")
    source = default_storage.create_tag("Alias source")
    assert default_storage.merge_tag(target["id"], [source["id"]])["status"] == "fully_applied"
    assert default_storage.delete_tag(target["id"])["status"] == "fully_applied"


def test_referenced_tag_remove_is_blocked_and_unreferenced_remove_succeeds(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    used = default_storage.create_tag("Used")
    default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"], tag_ids=[used["id"]],
    )
    with pytest.raises(StorageConflictError, match="referenced by 1"):
        default_storage.remove_tag(used["id"])
    unused = default_storage.create_tag("Unused")
    result = default_storage.remove_tag(unused["id"])
    assert result["status"] == "fully_applied"
    assert unused["id"] not in {item["id"] for item in default_storage.list_tags(active_only=False)}


def test_expected_tag_snapshot_protects_remove(default_storage) -> None:
    tag = default_storage.create_tag("Label")
    expected = dict(tag)
    default_storage.edit_tag(tag["id"], name="Changed label")
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.remove_tag(tag["id"], expected_tag=expected)


def test_expected_management_snapshot_preserves_falsy_values() -> None:
    current = {"tag-1": {"id": "tag-1", "active": "FALSE", "count": "0"}}
    expected = {"id": "tag-1", "active": False, "count": 0}
    GoogleSheetsStorage._assert_expected_managed_records(current, expected)


def test_tag_edit_preserves_id_and_supports_activation(default_storage) -> None:
    tag = default_storage.create_tag("Client")

    renamed = default_storage.edit_tag(tag["id"], name="Renamed client", active=False)
    reactivated = default_storage.edit_tag(tag["id"], active=True)

    assert renamed["id"] == tag["id"]
    assert renamed["name"] == "Renamed client"
    assert renamed["active"] == "FALSE"
    assert reactivated["id"] == tag["id"]
    assert reactivated["active"] == "TRUE"


def test_tag_rename_rejects_normalized_name_collision(default_storage) -> None:
    first = default_storage.create_tag("First label")
    second = default_storage.create_tag("Second label")

    with pytest.raises(StorageConflictError, match="already exists"):
        default_storage.edit_tag(second["id"], name=" first   label ")

    assert default_storage.list_tags(active_only=False) == [first, second]

def test_tag_merge_deduplicates_transactions_and_mileage(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    transaction = default_storage.create_transaction(
        txn_date="2026-01-01", kind="Expense", amount="10",
        account_id=account["id"], category_id=category["id"],
        tag_ids=[target["id"], source["id"]], description="keep",
    )
    mileage = default_storage.create_mileage_trip(
        trip_date="2026-01-01", miles="2", start_location="A", destination="B",
        business_purpose="Visit", vehicle="Car", tag_ids=[source["id"]],
    )

    default_storage.merge_tags(target["id"], [source["id"]])

    assert default_storage.list_transactions()[0]["tag_ids"] == [target["id"]]
    assert default_storage.list_transactions()[0]["description"] == transaction["description"]
    assert default_storage.list_mileage_trips()[0]["tag_ids"] == [target["id"]]
    assert source["id"] not in {item["id"] for item in default_storage.list_tags(active_only=False)}
    assert mileage["id"] == default_storage.list_mileage_trips()[0]["id"]


def test_tag_merge_rewrites_mixed_use_source_and_projection(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    mixed = default_storage.create_mixed_use_expense(
        txn_date="2026-01-01",
        account_id=account["id"],
        category_id=category["id"],
        total_expense="100",
        business_use_percentage="50",
        allocation_rationale="Shared use",
        tag_ids=[source["id"]],
    )

    default_storage.merge_tags(target["id"], [source["id"]])

    assert default_storage.list_transactions()[0]["tag_ids"] == [target["id"]]
    assert default_storage.list_mixed_use_expenses()[0]["tag_ids"] == [target["id"]]
    assert mixed["id"] == default_storage.list_mixed_use_expenses()[0]["id"]


def test_management_expected_snapshot_rejects_stale_merge(default_storage) -> None:
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    expected = default_storage.list_tags(active_only=False)
    default_storage.edit_tag(source["id"], name="Changed")

    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.merge_tags(target["id"], [source["id"]], expected_tags=expected)




def test_tag_merge_partial_write_stops_without_retry(default_storage, monkeypatch) -> None:
    account, category = _ledger_setup(default_storage)
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    default_storage.create_transaction(
        txn_date="2026-01-01",
        kind="Expense",
        amount="10",
        account_id=account["id"],
        category_id=category["id"],
        tag_ids=[source["id"]],
    )
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def partial_then_lose_response(body: dict[str, object]) -> None:
        nonlocal calls
        calls += 1
        original_batch_update({"requests": body["requests"][:1]})
        raise OSError("response lost after partial application")

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", partial_then_lose_response
    )

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.merge_tags(target["id"], [source["id"]])

    assert calls == 1
    assert "Tags" not in default_storage._row_cache


def test_create_transaction_cannot_interleave_management_remove(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    tag = default_storage.create_tag("In-flight")
    entered = Event()
    release = Event()
    original = default_storage._prepare_transaction

    def blocked_prepare(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    default_storage._prepare_transaction = blocked_prepare
    writer = Thread(
        target=lambda: default_storage.create_transaction(
            txn_date="2026-01-01", kind="Expense", amount="10",
            account_id=account["id"], category_id=category["id"], tag_ids=[tag["id"]],
        )
    )
    writer.start()
    assert entered.wait(timeout=5)
    management_done = Event()
    def remove_after_writer() -> None:
        try:
            default_storage.remove_tag(tag["id"])
        except StorageConflictError:
            pass
        finally:
            management_done.set()

    management = Thread(target=remove_after_writer)
    management.start()
    assert not management_done.wait(timeout=0.1)
    release.set()
    writer.join(timeout=5)
    management.join(timeout=5)
    assert not management.is_alive()
    assert tag["id"] in {item["id"] for item in default_storage.list_tags(active_only=False)}


def test_mileage_edit_cannot_interleave_tag_merge(default_storage) -> None:
    tag = default_storage.create_tag("In-flight")
    trip = default_storage.create_mileage_trip(
        trip_date="2026-01-01", miles="2", start_location="A", destination="B",
        business_purpose="Visit", vehicle="Car", tag_ids=[tag["id"]],
    )
    entered = Event()
    release = Event()
    original = default_storage._prepare_mileage_trip

    def blocked_prepare(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    default_storage._prepare_mileage_trip = blocked_prepare
    writer = Thread(
        target=lambda: default_storage.edit_mileage_trip(
            trip["id"], notes="edited", tag_ids=[tag["id"]]
        )
    )
    writer.start()
    assert entered.wait(timeout=5)
    source = default_storage.create_tag("Other")
    done = Event()
    management = Thread(
        target=lambda: (default_storage.merge_tags(source["id"], [tag["id"]]), done.set())
    )
    management.start()
    assert not done.wait(timeout=0.1)
    release.set()
    writer.join(timeout=5)
    management.join(timeout=5)
    assert done.is_set()


def test_mileage_import_cannot_interleave_management_remove(default_storage) -> None:
    tag = default_storage.create_tag("Import lock")
    entered = Event()
    release = Event()
    original = default_storage._prepare_mileage_trip

    def blocked_prepare(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    default_storage._prepare_mileage_trip = blocked_prepare
    rows = [
        {
            "Trip Date": "07/20/2026",
            "Trip Type": "Business",
            "Business Purpose": "Client meeting",
            "Vehicle Used": "Blue car",
            "Starting Point": "Office",
            "Ending Point": "Client site",
            "Distance (km)": "10 km",
        }
    ]
    writer = Thread(target=lambda: default_storage.import_quickbooks_mileage(rows))
    writer.start()
    assert entered.wait(timeout=5)
    done = Event()
    management = Thread(
        target=lambda: (default_storage.remove_tag(tag["id"]), done.set())
    )
    management.start()
    assert not done.wait(timeout=0.1)
    release.set()
    writer.join(timeout=5)
    management.join(timeout=5)
    assert not management.is_alive()
    assert tag["id"] not in {item["id"] for item in default_storage.list_tags(active_only=False)}


def test_tag_removal_retries_once_then_invalidates_on_unchanged_failure(
    default_storage, monkeypatch
) -> None:
    tag = default_storage.create_tag("Unused")
    batch_update = Mock(side_effect=OSError("temporary response lost"))
    monkeypatch.setattr(default_storage._workbook, "batch_update", batch_update)

    with pytest.raises(StorageUnavailableError, match="could not confirm"):
        default_storage.remove_tag(tag["id"])

    assert batch_update.call_count == 2
    assert "Tags" not in default_storage._row_cache


def test_tag_removal_rebuilds_row_after_shift_before_retry(default_storage, monkeypatch) -> None:
    tag = default_storage.create_tag("Shifted")
    worksheet = default_storage._worksheet("Tags")
    original_batch_update = default_storage._workbook.batch_update
    calls = 0

    def shift_then_lose_response(body: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            worksheet.rows.insert(1, list(worksheet.rows[1]))
            worksheet.rows[1][0] = "inserted-before-retry"
            raise OSError("temporary response lost")
        original_batch_update(body)

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", shift_then_lose_response
    )

    default_storage.remove_tag(tag["id"])

    assert calls == 2
    assert tag["id"] not in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }
    assert worksheet.rows[1][0] == "inserted-before-retry"


def test_tag_merge_accepts_commit_before_uncertain_response(
    default_storage, monkeypatch
) -> None:
    target = default_storage.create_tag("Target")
    source = default_storage.create_tag("Source")
    original_batch_update = default_storage._workbook.batch_update

    def commit_then_lose_response(body: object) -> None:
        original_batch_update(body)
        raise OSError("response lost after commit")

    monkeypatch.setattr(
        default_storage._workbook, "batch_update", commit_then_lose_response
    )

    result = default_storage.merge_tags(target["id"], [source["id"]])

    assert result["status"] == "fully_applied"
    assert source["id"] not in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }


def test_tag_removal_rechecks_references_after_retry_backoff(default_storage) -> None:
    account, category = _ledger_setup(default_storage)
    tag = default_storage.create_tag("Referenced during retry")
    calls = 0

    def add_reference_during_backoff(_: float) -> None:
        default_storage.create_transaction(
            txn_date="2026-01-01",
            kind="Expense",
            amount="10",
            account_id=account["id"],
            category_id=category["id"],
            tag_ids=[tag["id"]],
        )

    def fail_once(_: object) -> None:
        nonlocal calls
        calls += 1
        raise OSError("temporary response lost")

    default_storage._sleeper = add_reference_during_backoff
    default_storage._workbook.batch_update = fail_once

    with pytest.raises(StorageConflictError, match="became referenced"):
        default_storage.remove_tag(tag["id"])

    assert calls == 1
    assert tag["id"] in {
        item["id"] for item in default_storage.list_tags(active_only=False)
    }
