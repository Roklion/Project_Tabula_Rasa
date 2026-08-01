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
    GoogleDriveClient,
)
from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    StorageUnavailableError,
)
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
        description="Receipt unlink test",
    )
    receipt_reference = {
        "id": "receipt123456",
        "name": f"{transaction['id']}-statement.pdf",
        "receipt_id": "a" * 32,
        "original_filename": "statement.pdf",
        "mime_type": "application/pdf",
        "byte_size": 7,
        "sha256": "b" * 64,
    }
    storage.link_transaction_receipt(
        transaction["id"],
        reference=receipt_reference,
    )
    receipt = {
        "id": receipt_reference["id"],
        "name": receipt_reference["name"],
        "mimeType": receipt_reference["mime_type"],
        "size": str(receipt_reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "test",
            "tabulaRasaReceiptId": receipt_reference["receipt_id"],
            "tabulaRasaSha256": receipt_reference["sha256"],
            "tabulaRasaOriginalName": receipt_reference["original_filename"],
        },
    }
    drive_files = [dict(receipt)]
    unlink_calls: list[dict[str, str]] = []
    unlink_should_fail = {"value": False}
    original_unlink = GoogleSheetsStorage.unlink_transaction_receipt

    def list_profile_receipts(
        _client: GoogleDriveClient,
        **_scope: str,
    ) -> list[dict[str, str]]:
        return [dict(file) for file in drive_files]

    def unlink_receipt(
        storage_client: GoogleSheetsStorage,
        transaction_id: str,
        *,
        file_id: str,
    ) -> dict[str, str]:
        unlink_calls.append(
            {
                "transaction_id": transaction_id,
                "file_id": file_id,
            }
        )
        if unlink_should_fail["value"]:
            raise StorageUnavailableError(
                "Google Sheets could not save the change. Retry removal."
            )
        return original_unlink(
            storage_client,
            transaction_id,
            file_id=file_id,
        )

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
        patch.object(
            GoogleSheetsStorage,
            "unlink_transaction_receipt",
            unlink_receipt,
        ),
        patch.object(
            GoogleDriveClient,
            "list_profile_receipts",
            list_profile_receipts,
        ),
        patch.object(
            GoogleDriveClient,
            "delete_file",
            side_effect=AssertionError("Drive files must not be deleted"),
        ),
    ):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()
        app.radio[0].set_value("Transactions").run()
        by_label(app.selectbox, "Transaction to edit").set_value(
            transaction["id"]
        ).run()

        assert any(
            button.label == "Remove receipt" for button in app.button
        ), {
            "buttons": [button.label for button in app.button],
            "errors": [str(error.value) for error in app.error],
            "info": [str(info.value) for info in app.info],
            "exceptions": [str(error.value) for error in app.exception],
        }
        by_label(app.button, "Remove receipt").click().run()
        assert unlink_calls == []
        assert any(
            "file will remain in Google Drive" in str(warning.value)
            for warning in app.warning
        )
        by_label(app.button, "Cancel").click().run()
        assert unlink_calls == []
        assert by_label(app.button, "Remove receipt")
        assert drive_files == [receipt]
        assert len(storage.list_transactions()) == 1

        by_label(app.button, "Remove receipt").click().run()
        unlink_should_fail["value"] = True
        by_label(app.button, "Remove reference").click().run()
        assert len(unlink_calls) == 1
        assert decode_receipt_references(
            storage.list_transactions()[0]["receipt_references"]
        ) == [receipt_reference]
        assert any(
            "Receipt reference was not removed" in str(error.value)
            and "Retry removal" in str(error.value)
            for error in app.error
        )
        assert by_label(app.button, "Remove receipt")
        assert drive_files == [receipt]
        assert len(storage.list_transactions()) == 1

        unlink_should_fail["value"] = False
        by_label(app.button, "Remove reference").click().run()
        assert len(unlink_calls) == 2
        assert unlink_calls[-1] == {
            "transaction_id": transaction["id"],
            "file_id": "receipt123456",
        }
        assert decode_receipt_references(
            storage.list_transactions()[0]["receipt_references"]
        ) == []
        assert drive_files == [receipt]
        assert not [
            button for button in app.button if button.label == "Remove receipt"
        ]
        assert any(
            "file remains in Google Drive" in str(success.value)
            for success in app.success
        )
        assert len(storage.list_transactions()) == 1

        by_label(app.selectbox, "Unreferenced receipt").set_value(
            "receipt123456"
        )
        by_label(app.button, "Link selected receipt").click().run()
        assert decode_receipt_references(
            storage.list_transactions()[0]["receipt_references"]
        ) == [receipt_reference]
        assert drive_files == [receipt]
        assert by_label(app.button, "Remove receipt")
        assert any(
            "Receipt linked" in str(success.value)
            for success in app.success
        )


if __name__ == "__main__":
    main()
