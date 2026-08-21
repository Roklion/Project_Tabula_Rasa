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
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    storage.ensure_defaults()
    upload_calls: list[str] = []
    link_calls: list[str] = []
    fail_second_upload = {"value": True}
    fail_next_post_create_link = {"value": False}
    original_link_transaction_receipt = GoogleSheetsStorage.link_transaction_receipt

    def upload_receipt(
        _client: GoogleDriveClient,
        *,
        original_name: str,
        content: bytes,
        **_: object,
    ) -> dict[str, object]:
        upload_calls.append(original_name)
        if len(upload_calls) == 2 and fail_second_upload["value"]:
            raise RuntimeError("simulated Drive upload failure")
        receipt_id = "a" * 31 + str(len(upload_calls))
        return {
            "id": f"drive{len(upload_calls)}123456",
            "name": (
                "receipt.pdf"
                if len(upload_calls) == 1
                else "receipt (2).pdf"
            ),
            "mimeType": "application/pdf",
            "size": str(len(content)),
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaReceiptId": receipt_id,
                "tabulaRasaSha256": "b" * 64,
                "tabulaRasaOriginalName": original_name,
            },
        }

    def link_transaction_receipt(
        storage_client: GoogleSheetsStorage,
        transaction_id: str,
        *,
        reference: dict[str, object],
    ) -> dict[str, str]:
        if fail_next_post_create_link["value"]:
            fail_next_post_create_link["value"] = False
            raise StorageUnavailableError("simulated post-create link failure")
        link_calls.append(str(reference["id"]))
        return original_link_transaction_receipt(
            storage_client,
            transaction_id,
            reference=reference,
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
        patch.object(GoogleDriveClient, "upload_receipt", upload_receipt),
        patch.object(GoogleDriveClient, "list_profile_receipts", return_value=[]),
        patch.object(
            GoogleSheetsStorage,
            "link_transaction_receipt",
            link_transaction_receipt,
        ),
    ):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()
        app.radio[0].set_value("Transactions").run()
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.selectbox, "From Account").set_value("Checking")
        by_label(app.selectbox, "Category").set_value("Office")
        by_label(app.file_uploader, "Receipt (optional)").set_value(
            [
                ("receipt.pdf", b"first receipt", "application/pdf"),
                ("receipt.pdf", b"second receipt", "application/pdf"),
            ]
        )
        by_label(app.button, "Save transaction").click().run()

        transactions = storage.list_transactions()
        assert len(transactions) == 1
        assert len(upload_calls) == 2
        assert len(link_calls) == 1, {
            "uploads": upload_calls,
            "links": link_calls,
            "errors": [str(error.value) for error in app.error],
            "exceptions": [str(error.value) for error in app.exception],
            "warnings": [str(warning.value) for warning in app.warning],
        }
        assert any(
            "Transaction saved" in str(success.value) for success in app.success
        )
        assert any(
            "1 receipt(s) complete" in str(warning.value)
            and "1 receipt(s) unresolved" in str(warning.value)
            for warning in app.warning
        )
        assert any(
            "Retry unresolved receipts" in button.label for button in app.button
        )
        assert not any(button.label == "Save transaction" for button in app.button)

        fail_second_upload["value"] = False
        by_label(app.button, "Retry unresolved receipts").click().run()

        assert len(upload_calls) == 3
        assert len(link_calls) == 2
        references = storage.list_transactions()[0]["receipt_references"]
        assert references.count('"id"') == 2
        assert any(
            "2 receipt(s) linked" in str(success.value) for success in app.success
        ), [str(success.value) for success in app.success]

        fail_next_post_create_link["value"] = True
        by_label(app.file_uploader, "Upload receipt").set_value(
            ("later.pdf", b"later receipt", "application/pdf")
        ).run()
        by_label(app.button, "Upload receipt to Google Drive").click().run()
        assert len(upload_calls) == 4
        assert len(link_calls) == 2
        assert by_label(app.button, "Retry linking uploaded receipt")

        by_label(app.button, "Retry linking uploaded receipt").click().run()
        assert len(upload_calls) == 4
        assert len(link_calls) == 3
        assert storage.list_transactions()[0]["receipt_references"].count('"id"') == 3

        fail_second_upload["value"] = False
        by_label(app.number_input, "Amount").set_value(40)
        by_label(app.file_uploader, "Receipt (optional)").set_value(
            [
                ("receipt.pdf", b"third receipt", "application/pdf"),
                ("receipt.pdf", b"fourth receipt", "application/pdf"),
                ("other.png", b"fifth receipt", "image/png"),
            ]
        )
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 2
        assert len(upload_calls) == 7
        assert len(link_calls) == 6
        assert storage.list_transactions()[-1]["receipt_references"].count('"id"') == 3

        by_label(app.number_input, "Amount").set_value(41)
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 3
        assert len(upload_calls) == 7
        assert any(str(success.value) == "Transaction saved." for success in app.success)
        assert not any(
            "2 receipt(s) linked" in str(success.value) for success in app.success
        )


if __name__ == "__main__":
    main()
