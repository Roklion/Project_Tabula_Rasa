from __future__ import annotations

from datetime import date
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from tabula_rasa.google_drive import (
    DRIVE_SCOPE,
    GoogleDriveAccessError,
    GoogleDriveClient,
)
from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    storage.ensure_defaults()
    checking = next(
        account
        for account in storage.list_accounts(active_only=False)
        if account["name"] == "Checking"
    )
    office = next(
        category
        for category in storage.list_categories()
        if category["name"] == "Office"
    )
    transaction = storage.create_transaction(
        txn_date=date.today(),
        kind="Expense",
        amount=25,
        account_id=checking["id"],
        to_account_id="",
        category_id=office["id"],
        payee="Receipt vendor",
        reference="",
        description="Receipt deletion test",
    )
    receipts = [
        {
            "id": "receipt123456",
            "name": f"{transaction['id']}-statement.pdf",
            "webViewLink": "https://drive.google.com/file/d/receipt123456/view",
        }
    ]
    delete_calls: list[dict[str, str]] = []
    deletion_should_fail = {"value": False}

    def list_receipts(
        _client: GoogleDriveClient,
        **_scope: str,
    ) -> list[dict[str, str]]:
        return [dict(receipt) for receipt in receipts]

    def delete_receipt(
        _client: GoogleDriveClient,
        **scope: str,
    ) -> None:
        delete_calls.append(scope)
        if deletion_should_fail["value"]:
            raise GoogleDriveAccessError(
                "Google Drive could not complete the request. Retry deletion."
            )
        receipts[:] = [
            receipt
            for receipt in receipts
            if receipt["id"] != scope["file_id"]
        ]

    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.secrets["google_drive_oauth"] = {
        "client_id": "client.apps.googleusercontent.com",
        "client_secret": "client-secret",
        "redirect_uris": ["http://localhost:8501/"],
    }
    app.secrets["business_profiles"] = {
        "test": {
            "name": "Test Business",
            "spreadsheet_id": "test-sheet",
            "gcp_service_account": {"type": "service_account"},
            "google_drive": {
                "authorized_email": "owner@example.test",
                "authorized_name": "Test Owner",
                "refresh_token": "durable-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": [DRIVE_SCOPE],
                "receipt_folder": {
                    "id": "folder123456",
                    "name": "Receipts",
                },
            },
        }
    }

    with (
        TemporaryDirectory() as temp_dir,
        patch(
            "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
            Path(temp_dir) / "profiles.json",
        ),
        patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage),
        patch.object(GoogleDriveClient, "list_receipts", list_receipts),
        patch.object(GoogleDriveClient, "delete_receipt", delete_receipt),
    ):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()
        app.radio[0].set_value("Transactions").run()
        by_label(app.selectbox, "Transaction to edit").set_value(
            transaction["id"]
        ).run()

        assert any(
            button.label == "Delete receipt" for button in app.button
        ), {
            "buttons": [button.label for button in app.button],
            "errors": [str(error.value) for error in app.error],
            "info": [str(info.value) for info in app.info],
            "exceptions": [str(error.value) for error in app.exception],
        }
        by_label(app.button, "Delete receipt").click().run()
        assert delete_calls == []
        assert any(
            "permanently from Google Drive" in str(warning.value)
            for warning in app.warning
        )
        by_label(app.button, "Cancel").click().run()
        assert delete_calls == []
        assert by_label(app.button, "Delete receipt")
        assert len(storage.list_transactions()) == 1

        by_label(app.button, "Delete receipt").click().run()
        deletion_should_fail["value"] = True
        by_label(app.button, "Delete from Google Drive").click().run()
        assert len(delete_calls) == 1
        assert receipts
        assert any(
            "Receipt was not deleted" in str(error.value)
            and "Retry deletion" in str(error.value)
            for error in app.error
        )
        assert by_label(app.button, "Delete receipt")
        assert len(storage.list_transactions()) == 1

        deletion_should_fail["value"] = False
        by_label(app.button, "Delete from Google Drive").click().run()
        assert len(delete_calls) == 2
        assert delete_calls[-1] == {
            "profile_key": "test",
            "transaction_id": transaction["id"],
            "folder_id": "folder123456",
            "file_id": "receipt123456",
        }
        assert receipts == []
        assert not [
            button for button in app.button if button.label == "Delete receipt"
        ]
        assert any(
            "Receipt deleted from Google Drive" in str(success.value)
            for success in app.success
        )
        assert len(storage.list_transactions()) == 1


if __name__ == "__main__":
    main()
