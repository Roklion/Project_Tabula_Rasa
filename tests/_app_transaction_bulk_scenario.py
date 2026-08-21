from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def seed(storage: GoogleSheetsStorage, amount_offset: int) -> list[dict[str, str]]:
    account = storage.create_account("Checking", "Bank")
    office = storage.create_category("Office", "Expense")
    storage.create_category("Travel", "Expense")
    return [
        storage.create_transaction(
            txn_date=f"2026-07-{18 + index:02d}",
            kind="Expense",
            amount=amount_offset + index,
            account_id=account["id"],
            category_id=office["id"],
        )
        for index in range(2)
    ]


def main() -> None:
    north = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    south = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    north_transactions = seed(north, 1)
    south_transactions = seed(south, 10)
    storages = {"north-sheet": north, "south-sheet": south}

    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.secrets["business_profiles"] = {
        "north": {
            "name": "North Business",
            "spreadsheet_id": "north-sheet",
            "gcp_service_account": {"type": "service_account"},
        },
        "south": {
            "name": "South Business",
            "spreadsheet_id": "south-sheet",
            "gcp_service_account": {"type": "service_account"},
        },
    }

    with (
        TemporaryDirectory() as temp_dir,
        patch(
            "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
            Path(temp_dir) / "profiles.json",
        ),
        patch.object(
            GoogleSheetsStorage,
            "from_secrets",
            side_effect=lambda secrets: storages[secrets["spreadsheet_id"]],
        ),
    ):
        app.run()
        app.text_input[0].input(TEST_PASSWORD)
        app.button[0].click().run()
        app.radio[0].set_value("Transactions").run()

        assert by_label(app.segmented_control, "Ledger mode").value == "Edit"
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        assert not any(element.label == "Edit transaction" for element in app.expander)

        app.session_state["transaction_bulk_selected_ids_north"] = tuple(
            item["id"] for item in north_transactions
        )
        app.run()
        assert any(
            "2 transaction(s) selected" in str(element.value) for element in app.caption
        )
        assert by_label(app.download_button, "Export selected")
        warning_text = " ".join(str(element.value) for element in app.warning)
        assert "Google Drive files will remain" in warning_text
        delete_button = by_label(app.button, "Permanently delete selected")
        assert delete_button.disabled is False
        confirmation = by_label(
            app.checkbox,
            "I understand these transactions will be permanently deleted and cannot be undone",
        )
        confirmation.check()
        app.session_state["transaction_bulk_selected_ids_north"] = (
            north_transactions[0]["id"],
        )
        app.run()
        assert (
            by_label(
                app.checkbox,
                "I understand these transactions will be permanently deleted and cannot be undone",
            ).value
            is False
        )
        app.session_state["transaction_bulk_selected_ids_north"] = tuple(
            item["id"] for item in north_transactions
        )
        app.run()
        by_label(
            app.checkbox,
            "I understand these transactions will be permanently deleted and cannot be undone",
        ).check()
        by_label(app.button, "Permanently delete selected").click().run()
        assert len(north.list_transactions()) == 0
        assert len(south.list_transactions()) == len(south_transactions)


if __name__ == "__main__":
    main()
