from __future__ import annotations

from datetime import date
from unittest.mock import patch

from tabula_rasa.google_drive import (
    DRIVE_SCOPE,
    GoogleDriveClient,
)
from tabula_rasa.page_renderers.transactions.receipts import (
    new_receipt_creation_workflow,
    receipt_editor_workflow_key,
)
from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    StorageUnavailableError,
)
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook


def stored_transaction(storage: GoogleSheetsStorage, transaction_id: str) -> dict:
    return next(
        item
        for item in storage.list_transactions()
        if item["id"] == transaction_id
    )


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    storage.ensure_defaults()
    checking = next(
        account
        for account in storage.list_accounts(active_only=False)
        if account["name"] == "Checking"
    )
    savings = storage.create_account("Savings", "Bank")
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
    outside_transaction = storage.create_transaction(
        txn_date=date.today(),
        kind="Expense",
        amount=15,
        account_id=savings["id"],
        to_account_id="",
        category_id=office["id"],
        reference="",
        description="Receipt filter isolation test",
    )
    outside_receipt_reference = {
        "id": "receipt654321",
        "name": f"{outside_transaction['id']}-other.pdf",
        "receipt_id": "c" * 32,
        "original_filename": "other.pdf",
        "mime_type": "application/pdf",
        "byte_size": 9,
        "sha256": "d" * 64,
    }
    storage.link_transaction_receipt(
        outside_transaction["id"],
        reference=outside_receipt_reference,
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
    outside_receipt = {
        "id": outside_receipt_reference["id"],
        "name": outside_receipt_reference["name"],
        "mimeType": outside_receipt_reference["mime_type"],
        "size": str(outside_receipt_reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "test",
            "tabulaRasaReceiptId": outside_receipt_reference["receipt_id"],
            "tabulaRasaSha256": outside_receipt_reference["sha256"],
            "tabulaRasaOriginalName": outside_receipt_reference[
                "original_filename"
            ],
        },
    }
    drive_files = [dict(receipt), dict(outside_receipt)]
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
                "storage_root": {
                    "id": "rootfolder123456",
                    "name": "Test Storage",
                },
                "receipt_folder": {
                    "id": "folder123456",
                    "name": "Receipts",
                },
            }
        )
    }

    with (
        authenticated_app(storage, profiles=profiles, extra_secrets=extra_secrets) as app,
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
        navigate_to(app, "Transactions")
        by_label(app.multiselect, "Accounts").set_value(["Checking"]).run()
        by_label(app.selectbox, "Transaction to edit").set_value(
            transaction["id"]
        ).run()

        transaction_table = app.dataframe[0].value
        assert list(transaction_table.columns) == [
            "Date",
            "Type",
            "Account",
            "To account",
            "Category",
            "Payee",
            "Amount",
            "Tags",
            "Description",
            "Receipt",
            "Reference",
            "ID",
        ]
        selected_transaction_row = transaction_table.loc[
            transaction_table["ID"] == transaction["id"]
        ].iloc[0]
        assert selected_transaction_row["Receipt"] == "\U0001f4ce"

        assert not [
            selectbox
            for selectbox in app.selectbox
            if selectbox.label == "Unreferenced receipt"
            and outside_receipt_reference["id"] in selectbox.options
        ]

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
        assert drive_files == [receipt, outside_receipt]
        assert len(storage.list_transactions()) == 2

        by_label(app.button, "Remove receipt").click().run()
        unlink_should_fail["value"] = True
        by_label(app.button, "Remove reference").click().run()
        assert len(unlink_calls) == 1
        assert decode_receipt_references(
            stored_transaction(storage, transaction["id"])["receipt_references"]
        ) == [receipt_reference]
        assert any(
            "Receipt reference was not removed" in str(error.value)
            and "Retry removal" in str(error.value)
            for error in app.error
        )
        assert by_label(app.button, "Remove receipt")
        assert drive_files == [receipt, outside_receipt]
        assert len(storage.list_transactions()) == 2

        unlink_should_fail["value"] = False
        by_label(app.button, "Remove reference").click().run()
        assert len(unlink_calls) == 2
        assert unlink_calls[-1] == {
            "transaction_id": transaction["id"],
            "file_id": "receipt123456",
        }
        assert decode_receipt_references(
            stored_transaction(storage, transaction["id"])["receipt_references"]
        ) == []
        assert drive_files == [receipt, outside_receipt]
        assert not [
            button for button in app.button if button.label == "Remove receipt"
        ]
        assert any(
            "file remains in Google Drive" in str(success.value)
            for success in app.success
        )
        assert len(storage.list_transactions()) == 2

        by_label(app.selectbox, "Unreferenced receipt").set_value(
            "receipt123456"
        )
        by_label(app.button, "Link selected receipt").click().run()
        assert decode_receipt_references(
            stored_transaction(storage, transaction["id"])["receipt_references"]
        ) == [receipt_reference]
        assert drive_files == [receipt, outside_receipt]
        assert by_label(app.button, "Remove receipt")
        assert any(
            "Receipt linked" in str(success.value)
            for success in app.success
        )
        assert app.session_state["workbook_data_revision"] == 2

        workflow_key = receipt_editor_workflow_key("test", transaction["id"])
        app.session_state[workflow_key] = new_receipt_creation_workflow(
            transaction["id"],
            [
                {
                    "key": "pending-linked-receipt",
                    "receipt_id": receipt_reference["receipt_id"],
                    "sha256": receipt_reference["sha256"],
                    "original_name": receipt_reference["original_filename"],
                    "mime_type": receipt_reference["mime_type"],
                    "content": b"",
                    "reference": dict(receipt_reference),
                    "error": "The receipt link could not be confirmed.",
                }
            ],
            spreadsheet_id="test-sheet",
            receipt_folder_id="folder123456",
        )
        app.run()
        assert by_label(app.button, "Retry unresolved receipts")
        by_label(app.button, "Remove receipt").click().run()
        by_label(app.button, "Remove reference").click().run()
        assert decode_receipt_references(
            stored_transaction(storage, transaction["id"])["receipt_references"]
        ) == []
        assert workflow_key not in app.session_state
        assert not [
            button
            for button in app.button
            if button.label == "Retry unresolved receipts"
        ]
        assert drive_files == [receipt, outside_receipt]


if __name__ == "__main__":
    main()
