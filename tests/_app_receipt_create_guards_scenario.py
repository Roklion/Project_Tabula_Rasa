from __future__ import annotations

from unittest.mock import patch

from tabula_rasa.google_drive import DRIVE_SCOPE, GoogleDriveClient
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageUnavailableError,
    StorageValidationError,
)
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    storage.ensure_defaults()
    upload_calls: list[str] = []
    uploaded_transaction_ids: list[str] = []
    created_transaction_ids: list[str] = []
    write_failure: dict[str, Exception | None] = {"error": None}
    original_create = GoogleSheetsStorage.create_transaction

    def create_transaction(
        storage_client: GoogleSheetsStorage,
        **payload: object,
    ) -> dict[str, str]:
        if write_failure["error"] is not None:
            raise write_failure["error"]
        transaction = original_create(storage_client, **payload)
        created_transaction_ids.append(transaction["id"])
        return transaction

    def upload_receipt(
        _client: GoogleDriveClient,
        *,
        transaction_id: str,
        original_name: str,
        content: bytes,
        **_: object,
    ) -> dict[str, object]:
        upload_calls.append(original_name)
        uploaded_transaction_ids.append(transaction_id)
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

    extra_secrets = {
        "google_drive_oauth": {
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "client-secret",
            "redirect_uris": ["http://localhost:8501/"],
        },
    }
    profiles = {
        "test": profile_config(
            google_drive={
                "authorized_email": "owner@example.test",
                "authorized_name": "Test Owner",
                "refresh_token": "durable-refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": [DRIVE_SCOPE],
                "storage_root": {"id": "rootfolder123456", "name": "Test Storage"},
                "receipt_folder": {"id": "folder123456", "name": "Receipts"},
            }
        )
    }

    with (
        authenticated_app(storage, profiles=profiles, extra_secrets=extra_secrets) as app,
        patch.object(GoogleSheetsStorage, "create_transaction", create_transaction),
        patch.object(GoogleDriveClient, "upload_receipt", upload_receipt),
        patch.object(GoogleDriveClient, "list_profile_receipts", return_value=[]),
    ):
        navigate_to(app, "Transactions")
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.selectbox, "From Account").set_value("Checking")
        by_label(app.selectbox, "Category").set_value("Office")
        by_label(app.text_input, "Payee / customer").input("Guard vendor")

        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 1
        assert upload_calls == []

        # A completed save resets new-entry fields to their zero defaults;
        # provide a positive amount for the next transaction workflow.
        by_label(app.number_input, "Amount").set_value(25)
        by_label(app.file_uploader, "Receipt (optional)").set_value(
            ("bad.pdf", b"", "application/pdf")
        ).run()
        by_label(app.text_input, "Payee / customer").input("Guard vendor invalid")
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
        transactions = {
            transaction["id"]: transaction
            for transaction in storage.list_transactions()
        }
        assert len(transactions) == 2
        assert len(created_transaction_ids) == 2
        assert upload_calls == ["validation.pdf"]
        assert len(uploaded_transaction_ids) == 1
        uploaded_transaction_id = uploaded_transaction_ids[0]
        assert uploaded_transaction_id in created_transaction_ids
        assert (
            transactions[uploaded_transaction_id]["receipt_references"].count(
                '"id"'
            )
            == 1
        )
        assert (
            sum(
                transaction["receipt_references"].count('"id"')
                for transaction in transactions.values()
            )
            == 1
        )


if __name__ == "__main__":
    main()
