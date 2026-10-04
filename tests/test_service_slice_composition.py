"""The production graph keeps extracted capabilities on the selected profile."""

import hashlib
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from tabula_rasa.application.documents import DocumentUpload, DocumentValidationError
from tabula_rasa.composition import create_sheets_application
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import profile_config
from tests.fakes import FakeWorkbook


def test_extracted_graph_is_isolated_and_drive_remains_lazy() -> None:
    storages = {
        key: GoogleSheetsStorage(FakeWorkbook()) for key in ("north", "south")
    }
    transactions = {}
    for key, amount in (("north", 25), ("south", 80)):
        storage = storages[key]
        storage.ensure_defaults()
        account = storage.list_accounts()[0]
        category = storage.list_categories("Income")[0]
        transactions[key] = storage.create_transaction(
            txn_date=date(2026, 1, 2), kind="Income", amount=amount,
            account_id=account["id"], category_id=category["id"],
        )
    secrets = {
        "business_profiles": {
            key: profile_config(name=key.title(), spreadsheet_id=key)
            for key in storages
        }
    }
    for key, profile in secrets["business_profiles"].items():
        profile["google_drive"]["receipt_folder"] = {"id": f"{key}folder01", "name": "Receipts"}
    clients = {key: Mock() for key in storages}
    factories = {key: Mock(return_value=clients[key]) for key in storages}
    with patch.object(
        GoogleSheetsStorage, "from_secrets",
        side_effect=lambda selected: storages[selected["spreadsheet_id"]],
    ):
        applications = {
            key: create_sheets_application(key, secrets, drive_client_factory=factories[key])
            for key in storages
        }
    north, south = (applications[key].services for key in ("north", "south"))
    for services, amount in ((north, 25), (south, 80)):
        report = services.reporting.period_report(services.reporting.read_ledger())
        assert report.totals["income"] == amount
        assert services.mileage.list_trips() == ()
        assert services.receipts.references(transactions[services.profile_key]["id"]) == ()
    for factory in factories.values():
        factory.assert_not_called()

    trip = north.mileage.create_trip(
        trip_date=date(2026, 1, 2), miles="12.3", vehicle="Car",
        start_location="Office", destination="Client", business_purpose="Meeting",
    )
    assert Decimal(trip.miles) == Decimal("12.3")
    assert [item.id for item in north.mileage.list_trips()] == [trip.id]
    assert south.mileage.list_trips() == ()

    content = b"synthetic receipt"
    document_id = "a" * 32
    sha256 = hashlib.sha256(content).hexdigest()
    clients["north"].upload_receipt.return_value = {
        "id": "northreceipt01", "name": "receipt.pdf", "mimeType": "application/pdf",
        "size": str(len(content)),
        "appProperties": {
            "tabulaRasaKind": "receipt", "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": document_id,
            "tabulaRasaOriginalName": "receipt.pdf", "tabulaRasaSha256": sha256,
        },
    }
    document = north.receipts.documents.upload(
        "north", DocumentUpload(document_id, "receipt.pdf", "application/pdf", sha256, content),
    )
    north.receipts.link(transactions["north"]["id"], document)
    assert north.receipts.references(transactions["north"]["id"])[0] == document
    assert south.receipts.references(transactions["south"]["id"]) == ()
    with pytest.raises(DocumentValidationError, match="different business profile"):
        south.receipts.link(transactions["south"]["id"], document)
    north.receipts.unlink(transactions["north"]["id"], document.storage_key)
    assert north.receipts.references(transactions["north"]["id"]) == ()
    clients["north"].delete_file.assert_not_called()
    factories["north"].assert_called_once()
    factories["south"].assert_not_called()


def test_graph_without_drive_setup_keeps_other_services_available() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    storage.ensure_defaults()
    profile = profile_config()
    profile.pop("google_drive")
    with patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage):
        application = create_sheets_application("north", {"business_profiles": {"north": profile}})
    assert application.services.reporting.query_ledger().entries == ()
    assert application.services.mileage.list_trips() == ()
    assert application.services.receipts.repository.associations("north") == ()
    # Receipt setup failure is deferred until receipt bytes are requested.
    from tabula_rasa.application.documents import DocumentError

    with pytest.raises(DocumentError, match="not configured"):
        application.services.receipts.unreferenced()
