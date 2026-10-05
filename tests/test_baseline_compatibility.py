"""Additive baselines retain legacy services and guarded Sheets behavior."""

from dataclasses import replace

import pytest

from tabula_rasa.application import AccountService, CategoryService
from tabula_rasa.application.baselines import RecordBaseline
from tabula_rasa.application.mileage import MileageService, MileageTrip
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.infrastructure.google_sheets import GoogleSheetsAccountRepository, GoogleSheetsCategoryRepository
from tabula_rasa.infrastructure.google_sheets_mileage import GoogleSheetsMileageRepository, mileage_trip_to_record
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


@pytest.mark.parametrize("service_type", [AccountService, CategoryService])
def test_reference_service_passes_the_opaque_baseline_separately_without_reads(service_type):
    token = RecordBaseline("alpha", "account" if service_type is AccountService else "category", "id", "life", 1).encode()
    expected = {"baseline": token}

    class Repository:
        def update(self, identity, *, changes, expected=None):
            assert identity == "id"
            assert changes == {"name": "New name"}
            assert expected is supplied
            return {"id": identity, "baseline": "new-token"}

    supplied = expected
    result = service_type(Repository()).update("id", name=" New name ", expected=supplied)
    assert result["baseline"] == "new-token"


def test_account_baseline_normalization_stale_detection_and_no_baseline_compatibility(storage):
    service = AccountService(GoogleSheetsAccountRepository(storage))
    created = service.create("Synthetic cash", "Cash", "1.20")
    loaded = service.list()[0]  # normalized bool/float read values
    updated = service.rename(created["id"], "Renamed", expected=loaded)
    assert updated["name"] == "Renamed"
    with pytest.raises(StorageConflictError, match="changed"):
        service.deactivate(created["id"], expected=loaded)
    with pytest.raises(StorageValidationError, match="complete"):
        service.rename(created["id"], "Invalid", expected={"id": created["id"]})
    service.deactivate(created["id"])
    assert service.list() == []


@pytest.mark.parametrize("invalid", ["sNaN", "NaN", "Infinity", "-Infinity"])
def test_nonfinite_expected_snapshots_fail_safely_before_mutation(storage, invalid):
    accounts = AccountService(GoogleSheetsAccountRepository(storage))
    accounts.create("Synthetic cash", "Cash", "1.20")
    account = accounts.list()[0]
    with pytest.raises(StorageValidationError, match="Invalid loaded account snapshot"):
        accounts.rename(account["id"], "Must not change", expected={**account, "opening_balance": invalid})
    assert accounts.list()[0] == account

    mileage = MileageService(GoogleSheetsMileageRepository(storage))
    trip = mileage.create_trip(
        trip_date="2026-10-05", miles=12.3, start_location="Synthetic start",
        destination="Synthetic end", business_purpose="Synthetic purpose",
    )
    with pytest.raises(StorageValidationError, match="Invalid loaded mileage trip snapshot"):
        mileage.edit_trip(
            trip.id, miles=20, new_tag_name="Must not exist",
            expected={**trip.as_record(), "miles": invalid},
        )
    assert mileage.list_trips() == (trip,)
    assert mileage.list_tags() == ()


@pytest.mark.parametrize("delete", [False, True])
def test_category_update_and_delete_carry_the_loaded_snapshot(storage, delete):
    service = CategoryService(GoogleSheetsCategoryRepository(storage))
    loaded = service.create("Synthetic category", "Expense")
    current = service.update(loaded["id"], name="Renamed", expected=loaded)
    with pytest.raises(StorageConflictError, match="changed"):
        if delete:
            service.delete(loaded["id"], expected=loaded)
        else:
            service.update(loaded["id"], name="Stale", expected=loaded)
    service.delete(loaded["id"], expected=current)
    assert service.list() == []


def test_mileage_guard_precedes_inline_tag_creation_and_delete(storage):
    service = MileageService(GoogleSheetsMileageRepository(storage))
    loaded = service.create_trip(
        trip_date="2026-10-05", miles=12.3, start_location="Synthetic start",
        destination="Synthetic end", business_purpose="Synthetic purpose",
    )
    updated = service.edit_trip(loaded.id, miles=15, expected=loaded.as_record())
    with pytest.raises(StorageConflictError, match="changed"):
        service.edit_trip(loaded.id, miles=20, new_tag_name="Must not exist", expected=loaded.as_record())
    assert service.list_tags() == ()
    with pytest.raises(StorageConflictError, match="changed"):
        service.delete_trip(loaded.id, expected=loaded.as_record())
    service.delete_trip(updated.id, expected=updated.as_record())
    assert service.list_trips() == ()
    # No-baseline edit/delete retains its existing calling path.
    created = service.create_trip(**{key: value for key, value in loaded.as_record().items() if key != "id"})
    service.edit_trip(created.id, miles=25)
    service.delete_trip(created.id)


def test_two_workbooks_with_the_same_ids_keep_guarded_mutations_isolated():
    storages = [GoogleSheetsStorage(FakeWorkbook()) for _ in range(2)]
    services = [AccountService(GoogleSheetsAccountRepository(storage)) for storage in storages]
    for service, storage in zip(services, storages):
        service.create("Synthetic cash", "Cash")
        storage._workbook.sheets["Accounts"].rows[1][0] = "same-id"
        storage._invalidate("Accounts")
    alpha, beta = [service.list()[0] for service in services]
    services[0].rename("same-id", "Alpha changed", expected=alpha)
    with pytest.raises(StorageConflictError):
        services[0].rename("same-id", "Stale", expected=alpha)
    services[1].rename("same-id", "Beta changed", expected=beta)
    assert services[0].list()[0]["name"] == "Alpha changed"
    assert services[1].list()[0]["name"] == "Beta changed"


def test_mileage_list_preserves_portable_metadata_without_writing_it_to_sheets():
    trip = MileageTrip("id", "2026-10-05", "12.3", "", "start", "end", "purpose", "", (), "created")
    guarded = replace(trip, baseline="opaque-loaded-token")

    class Repository:
        def list_tags(self, *, fresh=False):
            return ()

        def list_trips(self, *, fresh=False):
            return (guarded,)

    assert MileageService(Repository()).list_trips()[0].baseline == guarded.baseline
    assert "baseline" not in mileage_trip_to_record(guarded)
