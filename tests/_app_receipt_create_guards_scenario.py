from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from tabula_rasa.google_drive import DRIVE_SCOPE, GoogleDriveClient
from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageUnavailableError,
    StorageValidationError,
)
from tests.fakes import FakeWorkbook


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    storage.ensure_defaults()
    upload_calls: list[str] = []
    write_failure: dict[str, Exception | None] = {"error": None}
    original_create = GoogleSheetsStorage.create_transaction

    def create_transaction(
        storage_client: GoogleSheetsStorage,
        **payload: object,
    ) -> dict[str, str]:
        if write_failure["error"] is not None:
            raise write_failure["error"]
        return original_create(storage_client, **payload)

    def upload_receipt(
        _client: GoogleDriveClient,
        *,
        original_name: str,
        content: bytes,
        **_: object,
    ) -> dict[str, object]:
        upload_calls.append(original_name)
        return {
            "id": "drive123456789",
            "name": original_name,
            "mimeType": "application/pdf",
            "size": str(len(content)),
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": "b" * 64,
                "tabulaRasaOriginalName": original_name,
            },
        }

    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password("test-password-123")
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
                "storage_root": {"id": "rootfolder123456", "name": "Test Storage"},
                "receipt_folder": {"id": "folder123456", "name": "Receipts"},
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
        patch.object(GoogleSheetsStorage, "create_transaction", create_transaction),
        patch.object(GoogleDriveClient, "upload_receipt", upload_receipt),
        patch.object(GoogleDriveClient, "list_profile_receipts", return_value=[]),
    ):
        app.run()
        app.text_input[0].input("test-password-123")
        app.button[0].click().run()
        app.radio[0].set_value("Transactions").run()
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.selectbox, "From Account").set_value("Checking")
        by_label(app.selectbox, "Category").set_value("Office")

        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 1
        assert upload_calls == []

        by_label(app.file_uploader, "Receipt (optional)").set_value(
            ("bad.pdf", b"", "application/pdf")
        ).run()
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 1
        assert upload_calls == []
        assert any("Receipt validation failed" in str(error.value) for error in app.error)

        by_label(app.file_uploader, "Receipt (optional)").set_value(
            ("validation.pdf", b"receipt", "application/pdf")
        ).run()
        write_failure["error"] = StorageValidationError("transaction validation failed")
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 1
        assert upload_calls == []

        write_failure["error"] = StorageUnavailableError("Sheets write failed")
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 1
        assert upload_calls == []

        write_failure["error"] = None
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 2
        assert upload_calls == ["validation.pdf"]
        assert storage.list_transactions()[0]["receipt_references"].count('"id"') == 1


if __name__ == "__main__":
    main()
