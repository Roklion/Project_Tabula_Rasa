from __future__ import annotations

from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook


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

    profiles = {
        "north": profile_config(name="North Business", spreadsheet_id="north-sheet"),
        "south": profile_config(name="South Business", spreadsheet_id="south-sheet"),
    }
    with authenticated_app(storages=storages, profiles=profiles) as app:
        navigate_to(app, "Transactions")

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
        confirmation = by_label(
            app.checkbox,
            "I understand these transactions will be permanently deleted and cannot be undone",
        )
        confirmation.check()
        transaction_sheet = north._workbook.sheets["Transactions"]
        amount_index = transaction_sheet.rows[0].index("amount")
        transaction_sheet.rows[1][amount_index] = "99"
        north._invalidate("Transactions")
        app.run()
        assert (
            by_label(
                app.checkbox,
                "I understand these transactions will be permanently deleted and cannot be undone",
            ).value
            is False
        )
        by_label(
            app.checkbox,
            "I understand these transactions will be permanently deleted and cannot be undone",
        ).check()
        by_label(app.button, "Permanently delete selected").click().run()
        assert len(north.list_transactions()) == 0
        assert len(south.list_transactions()) == len(south_transactions)


if __name__ == "__main__":
    main()
