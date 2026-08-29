from __future__ import annotations

from unittest.mock import patch

from tabula_rasa.google_drive import DRIVE_SCOPE, GoogleDriveClient
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook



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

    extra_secrets = {
        "google_drive_oauth": {
            "client_id": "client.apps.googleusercontent.com",
            "client_secret": "client-secret",
            "redirect_uris": ["http://localhost:8501/"],
        }
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
        patch.object(GoogleDriveClient, "upload_receipt", upload_receipt),
        patch.object(GoogleDriveClient, "list_profile_receipts", return_value=[]),
        patch.object(
            GoogleSheetsStorage,
            "link_transaction_receipt",
            link_transaction_receipt,
        ),
    ):
        navigate_to(app, "Transactions")
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

        by_label(app.number_input, "Amount").set_value(30)
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 2
        assert len(upload_calls) == 3
        assert any(str(success.value) == "Transaction saved." for success in app.success)
        assert not any(
            "2 receipt(s) linked" in str(success.value) for success in app.success
        )

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
        assert sum(
            transaction["receipt_references"].count('"id"')
            for transaction in storage.list_transactions()
        ) == 3

        by_label(app.file_uploader, "Upload receipt").set_value(
            [
                ("receipt.pdf", b"editor first", "application/pdf"),
                ("receipt.pdf", b"editor second", "application/pdf"),
            ]
        ).run()
        by_label(app.button, "Upload receipt to Google Drive").click().run()
        assert len(upload_calls) == 6
        assert len(link_calls) == 5
        assert sum(
            transaction["receipt_references"].count('"id"')
            for transaction in storage.list_transactions()
        ) == 5

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
        assert len(storage.list_transactions()) == 3
        assert len(upload_calls) == 9
        assert len(link_calls) == 8
        assert sum(
            transaction["receipt_references"].count('"id"')
            for transaction in storage.list_transactions()
        ) == 8

        by_label(app.number_input, "Amount").set_value(41)
        by_label(app.button, "Save transaction").click().run()
        assert len(storage.list_transactions()) == 4
        assert len(upload_calls) == 9
        assert any(str(success.value) == "Transaction saved." for success in app.success)
        assert not any(
            "2 receipt(s) linked" in str(success.value) for success in app.success
        )


if __name__ == "__main__":
    main()
