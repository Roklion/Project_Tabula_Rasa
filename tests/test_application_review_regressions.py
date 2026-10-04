"""Preserve aggregate reads and established mileage error presentation."""

from unittest.mock import Mock, patch

import pytest

from tabula_rasa.application.mileage import MileageValidationError
from tabula_rasa.composition import create_sheets_application
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.page_renderers.data_backup.exports import prepare_csv_exports
from tabula_rasa.page_renderers.transactions.payees_tags import PayeesTagsContext, render_payees_tags
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
from tests.app_support import profile_config
from tests.fakes import FakeWorkbook


def _application(storage, profile):
    with patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage):
        return create_sheets_application(
            profile, {"business_profiles": {profile: profile_config()}}
        )


def test_transaction_workspace_batches_cold_and_expired_reads_with_profile_isolation():
    applications = []
    for profile in ("north", "south"):
        workbook = FakeWorkbook()
        storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
        app = _application(storage, profile)

        def batch_get(ranges, workbook=workbook):
            return {"valueRanges": [
                {"values": workbook.sheets[title.strip("'")].get_all_values()}
                for title in ranges
            ]}

        workbook.values_batch_get = Mock(side_effect=batch_get)
        applications.append((app, storage, workbook))

    north, north_storage, north_book = applications[0]
    south, _, south_book = applications[1]
    north.services.transactions.prepare_workspace()
    assert north_book.values_batch_get.call_count == 1
    assert len(north_book.values_batch_get.call_args.args[0]) == 8
    north.services.accounts.list(active_only=False)
    north.services.categories.list()
    north.services.transactions.list()
    north.services.mileage.list_trips()
    assert north_book.values_batch_get.call_count == 1
    assert south_book.values_batch_get.call_count == 0

    north.services.transactions.prepare_workspace()
    assert north_book.values_batch_get.call_count == 1
    north_storage._row_cache = {
        title: (0, rows) for title, (_, rows) in north_storage._row_cache.items()
    }
    north.services.transactions.prepare_workspace()
    assert north_book.values_batch_get.call_count == 2
    south.services.transactions.prepare_workspace()
    assert south_book.values_batch_get.call_count == 1


def test_transaction_workspace_preserves_backend_read_failure():
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    app = _application(storage, "north")
    with patch.object(storage, "prefetch_worksheets", side_effect=StorageUnavailableError("Unavailable")):
        with pytest.raises(StorageUnavailableError):
            app.services.transactions.prepare_workspace()


def test_mileage_validation_uses_existing_error_boundary_for_exports_and_management():
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    services = _application(storage, "north").services
    report = Mock()
    context = PayeesTagsContext("north", services, Mock(), report)
    with (
        patch.object(services.mileage, "list_trips", side_effect=MileageValidationError("Invalid trip date")),
        patch("tabula_rasa.page_renderers.transactions.payees_tags.st.caption"),
    ):
        with pytest.raises(StorageValidationError, match="Invalid trip date"):
            prepare_csv_exports(services, accounts=[], tags=[])
        render_payees_tags(context)
    report.assert_called_once()
    assert isinstance(report.call_args.args[0], StorageValidationError)
