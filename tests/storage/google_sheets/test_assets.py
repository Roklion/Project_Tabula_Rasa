from datetime import date
import json

from tabula_rasa.depreciation import straight_line_schedule

from ._support import (
    FakeWorkbook,
    GoogleSheetsStorage,
    GoogleSheetsStorageTestCase,
    StorageConflictError,
    StorageValidationError,
    backup_receipt_manifest,
    pytest,
)


def _asset_data(**changes):
    data = {
        "name": "Office laptop",
        "asset_type": "Computers & office equipment",
        "notes": "Primary workstation",
        "acquisition_date": "2025-01-15",
        "depreciation_start_date": "2025-01-31",
        "cost_basis": "1200",
        "salvage_value": "0",
        "useful_life_quarters": 20,
        "depreciation_method": "Straight-line",
        "reference": "INV-100",
    }
    data.update(changes)
    return data


class TestAssetStorage(GoogleSheetsStorageTestCase):
    def test_asset_crud_and_reference_resolution(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Equipment", "Expense")
        payee = self.storage.create_payee("Computer Shop")
        tag = self.storage.create_tag("Technology")
        transaction = self.storage.create_transaction(
            txn_date="2025-01-15",
            kind="Expense",
            amount="1200",
            account_id=account["id"],
            category_id=category["id"],
            payee_id=payee["id"],
        )

        created = self.storage.create_asset(
            **_asset_data(
                payee_id=payee["id"],
                tag_ids=[tag["id"]],
                source_transaction_id=transaction["id"],
            )
        )
        listed = self.storage.list_assets()

        assert [item["id"] for item in listed] == [created["id"]]
        assert listed[0]["payee"] == "Computer Shop"
        assert listed[0]["tags"] == ["Technology"]
        assert listed[0]["cost_basis"] == "1200.00"
        assert listed[0]["useful_life_quarters"] == "20"

        edited = self.storage.edit_asset(
            created["id"],
            expected_asset=listed[0],
            name="Design laptop",
        )
        assert edited["id"] == created["id"]
        assert edited["name"] == "Design laptop"

        self.storage.delete_asset(created["id"])
        assert self.storage.list_assets() == []

    def test_asset_validates_dates_values_types_and_source(self) -> None:
        with pytest.raises(StorageValidationError, match="earlier"):
            self.storage.create_asset(
                **_asset_data(depreciation_start_date="2025-01-01")
            )
        with pytest.raises(StorageValidationError, match="less than cost"):
            self.storage.create_asset(**_asset_data(salvage_value="1200"))
        with pytest.raises(StorageValidationError, match="Unknown asset type"):
            self.storage.create_asset(**_asset_data(asset_type="Land"))
        with pytest.raises(StorageValidationError, match="does not exist"):
            self.storage.create_asset(
                **_asset_data(source_transaction_id="missing")
            )

    def test_missing_historical_source_does_not_block_metadata_edit(self) -> None:
        account = self.storage.create_account("Checking", "Bank")
        category = self.storage.create_category("Equipment", "Expense")
        transaction = self.storage.create_transaction(
            txn_date="2025-01-15",
            kind="Expense",
            amount="1200",
            account_id=account["id"],
            category_id=category["id"],
        )
        asset = self.storage.create_asset(
            **_asset_data(source_transaction_id=transaction["id"])
        )
        self.storage.delete_transaction(transaction["id"])

        updated = self.storage.edit_asset(asset["id"], notes="Source is missing")

        assert updated["source_transaction_id"] == transaction["id"]
        assert updated["notes"] == "Source is missing"

    def test_override_persists_and_locks_schedule_terms(self) -> None:
        asset = self.storage.create_asset(**_asset_data())
        baseline = self.storage.list_assets()[0]
        updated = self.storage.override_asset_period(
            asset["id"],
            2,
            "25.00",
            "Imported prior depreciation",
            as_of_date=date(2026, 1, 1),
            expected_asset=baseline,
        )
        overrides = json.loads(updated["schedule_overrides"])
        assert overrides == {
            "2": {"amount": "25.00", "reason": "Imported prior depreciation"}
        }
        schedule = straight_line_schedule(
            updated["cost_basis"],
            updated["salvage_value"],
            date.fromisoformat(updated["depreciation_start_date"]),
            int(updated["useful_life_quarters"]),
            overrides={int(key): value for key, value in overrides.items()},
        )
        assert schedule[1].depreciation_amount == 25
        assert schedule[-1].remaining_book_value == 0

        with pytest.raises(StorageConflictError, match="locked"):
            self.storage.edit_asset(asset["id"], cost_basis="1400")

        restored = self.storage.remove_asset_period_override(asset["id"], 2)
        assert restored["schedule_overrides"] == "{}"
        assert self.storage.edit_asset(asset["id"], cost_basis="1400")[
            "cost_basis"
        ] == "1400.00"

    def test_override_rejects_future_period_and_stale_snapshot(self) -> None:
        asset = self.storage.create_asset(
            **_asset_data(depreciation_start_date="2027-01-01")
        )
        stale = self.storage.list_assets()[0]
        with pytest.raises(StorageValidationError, match="due or past"):
            self.storage.override_asset_period(
                asset["id"],
                1,
                "10",
                "Too early",
                as_of_date=date(2026, 1, 1),
            )
        self.storage.edit_asset(asset["id"], name="Changed")
        with pytest.raises(StorageConflictError, match="changed"):
            self.storage.override_asset_period(
                asset["id"],
                1,
                "10",
                "Stale",
                as_of_date=date(2028, 1, 1),
                expected_asset=stale,
            )

    def test_retirement_stops_schedule_and_preserves_asset(self) -> None:
        asset = self.storage.create_asset(**_asset_data())
        retired = self.storage.retire_asset(asset["id"], "2025-06-30")
        schedule = straight_line_schedule(
            retired["cost_basis"],
            retired["salvage_value"],
            date.fromisoformat(retired["depreciation_start_date"]),
            int(retired["useful_life_quarters"]),
            retired_date=date.fromisoformat(retired["retired_date"]),
        )

        assert retired["status"] == "retired"
        assert len(schedule) == 2
        assert schedule[-1].remaining_book_value > 0

    def test_asset_data_isolated_by_workbook(self) -> None:
        other = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
        self.storage.create_asset(**_asset_data(name="North laptop"))
        other.create_asset(**_asset_data(name="South laptop"))

        assert [item["name"] for item in self.storage.list_assets()] == [
            "North laptop"
        ]
        assert [item["name"] for item in other.list_assets()] == ["South laptop"]

    def test_managed_payee_and_tag_operations_preserve_asset_references(self) -> None:
        old_payee = self.storage.create_payee("Old vendor")
        new_payee = self.storage.create_payee("New vendor")
        old_tag = self.storage.create_tag("Old asset tag")
        new_tag = self.storage.create_tag("New asset tag")
        self.storage.create_asset(
            **_asset_data(payee_id=old_payee["id"], tag_ids=[old_tag["id"]])
        )

        with pytest.raises(StorageConflictError, match="referenced"):
            self.storage.remove_payee(old_payee["id"])
        with pytest.raises(StorageConflictError, match="referenced"):
            self.storage.remove_tag(old_tag["id"])

        self.storage.merge_payees(new_payee["id"], [old_payee["id"]])
        self.storage.merge_tags(new_tag["id"], [old_tag["id"]])

        asset = self.storage.list_assets()[0]
        assert asset["payee_id"] == new_payee["id"]
        assert asset["tag_ids"] == [new_tag["id"]]

    def test_backup_restore_preserves_asset_and_override(self) -> None:
        asset = self.storage.create_asset(**_asset_data())
        self.storage.override_asset_period(
            asset["id"],
            1,
            "40.00",
            "Opening accumulated depreciation",
            as_of_date=date(2026, 1, 1),
        )
        backup = self.storage.export_backup_zip(
            backup_receipt_manifest(self.storage)
        )
        restored = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)

        counts = restored.restore_backup_zip(backup)

        assert counts["Assets"] == 1
        restored_asset = restored.list_assets()[0]
        assert restored_asset["id"] == asset["id"]
        assert json.loads(restored_asset["schedule_overrides"])["1"]["amount"] == (
            "40.00"
        )
    backup_receipt_manifest,
