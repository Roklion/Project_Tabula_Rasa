from __future__ import annotations

from tabula_rasa.page_renderers.transactions.entry_creation import JOURNAL_MODE
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import (
    authenticated_app,
    by_key,
    by_label,
    navigate_to,
    profile_config,
)
from tests.fakes import FakeWorkbook


def _profile_storage(label: str) -> GoogleSheetsStorage:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account(f"{label} Checking", "Bank")
    category = storage.create_category(f"{label} Office", "Expense")
    storage.create_journal_entry(
        entry_id="shared-journal-id",
        txn_date="2026-09-20",
        description=f"{label} saved journal",
        postings=[
            {
                "id": "shared-debit-id",
                "target_type": "category",
                "target_id": category["id"],
                "side": "Debit",
                "amount": "30.00",
                "description": f"{label} debit",
            },
            {
                "id": "shared-credit-id",
                "target_type": "account",
                "target_id": account["id"],
                "side": "Credit",
                "amount": "30.00",
                "description": f"{label} credit",
            },
        ],
    )
    return storage


def test_journal_draft_and_selection_are_isolated_when_switching_profiles() -> None:
    north = _profile_storage("North")
    south = _profile_storage("South")

    with authenticated_app(
        storages={"north-sheet": north, "south-sheet": south},
        profiles={
            "north": profile_config(name="North", spreadsheet_id="north-sheet"),
            "south": profile_config(name="South", spreadsheet_id="south-sheet"),
        },
    ) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Entry Type").set_value(JOURNAL_MODE).run()
        by_key(app.text_input, "add_transaction_description").set_value(
            "North unsaved memo"
        ).run()
        debit = next(
            item
            for item in app.number_input
            if str(item.key).startswith("journal_create_north_")
            and str(item.key).endswith("_debit")
        )
        debit.set_value(7).run()

        selection = by_label(app.selectbox, "Transaction to edit")
        selection.set_value("journal:shared-journal-id").run()
        assert by_key(
            app.text_input, "journal_edit_north_shared-journal-id_description"
        ).value == "North saved journal"

        by_label(app.selectbox, "Business").set_value("south").run()

        assert by_key(app.text_input, "add_transaction_description").value == ""
        assert by_key(
            app.text_input, "journal_edit_south_shared-journal-id_description"
        ).value == "South saved journal"
        assert not any(
            str(key).startswith(("journal_create_north_", "journal_edit_north_"))
            for widget in (*app.text_input, *app.number_input, *app.selectbox)
            for key in (widget.key,)
        )
        assert "shared-journal-id" in south.list_journal_entries()[0]["id"]
        assert north.list_journal_entries()[0]["description"] == "North saved journal"
