from __future__ import annotations

from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage

def test_transactions_exposes_profile_local_management_tab() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    with authenticated_app(storage=storage) as app:
        navigate_to(app, "Transactions")
        management = next(tab for tab in app.tabs if tab.label == "Payees & Tags")
        labels = [getattr(node, "label", "") for node in management]
        assert "Payees" in labels
        assert "Tags" in labels
        assert "New payee name" in labels
        assert "New tag name" in labels
        assert any(
            "Business profile:" in str(node.value)
            for node in app.caption
        )


def test_management_workflows_are_profile_scoped_and_require_confirmation() -> None:
    north = GoogleSheetsStorage(FakeWorkbook())
    south = GoogleSheetsStorage(FakeWorkbook())
    account = north.create_account("Checking", "Bank")
    category = north.create_category("Office", "Expense")
    target_payee = north.create_payee("North target")
    source_payee = north.create_payee("North source")
    target_tag = north.create_tag("North target tag")
    source_tag = north.create_tag("North source tag")
    referenced_transaction = north.create_transaction(
        txn_date="2026-09-01",
        kind="Expense",
        amount="10",
        account_id=account["id"],
        category_id=category["id"],
        payee_id=source_payee["id"],
        tag_ids=[source_tag["id"]],
    )
    north.create_transaction(
        txn_date="2026-09-02",
        kind="Expense",
        amount="11",
        account_id=account["id"],
        category_id=category["id"],
    )
    south.create_payee("South only")
    south.create_tag("South only tag")

    with authenticated_app(
        storages={"north-sheet": north, "south-sheet": south},
        profiles={
            "north": profile_config(name="North", spreadsheet_id="north-sheet"),
            "south": profile_config(name="South", spreadsheet_id="south-sheet"),
        },
    ) as app:
        navigate_to(app, "Transactions")

        by_label(app.selectbox, "Target payee").set_value(target_payee["id"]).run()
        by_label(app.multiselect, "Source payees").set_value(
            [source_payee["id"]]
        ).run()
        by_label(app.button, "Merge payees").click().run()
        assert any(
            "Acknowledge the permanent source removal" in str(item.value)
            for item in app.error
        )
        assert any(
            item["id"] == source_payee["id"] for item in north.list_payees()
        )

        by_label(
            app.checkbox,
            "I understand the selected source payees will be permanently removed",
        ).check()
        by_label(app.button, "Merge payees").click().run()
        assert not any(
            item["id"] == source_payee["id"] for item in north.list_payees()
        )
        assert next(
            item
            for item in north.list_transactions()
            if item["id"] == referenced_transaction["id"]
        )["payee_id"] == target_payee["id"]
        assert any("Payees merged." in str(item.value) for item in app.success)

        navigate_to(app, "Accounts")
        navigate_to(app, "Transactions")
        by_label(app.text_input, "New payee name").input("Created payee")
        by_label(app.button, "Add payee").click().run()
        created_payee = next(
            item for item in north.list_payees() if item["name"] == "Created payee"
        )
        by_label(app.selectbox, "Payee to rename").set_value(
            target_payee["id"]
        ).run()
        by_label(app.text_input, "Renamed payee name").set_value(
            "Renamed target"
        )
        by_label(app.button, "Rename payee").click().run()
        assert next(
            item for item in north.list_payees() if item["id"] == target_payee["id"]
        )["name"] == "Renamed target"
        assert created_payee["id"] in {
            item["id"] for item in north.list_payees()
        }

        by_label(app.selectbox, "Payee to remove").set_value(
            target_payee["id"]
        ).run()
        assert by_label(app.button, "Permanently remove payee").disabled is True
        assert any("1 references" in str(item.value) for item in app.info)

        by_label(app.text_input, "New tag name").input("Created tag")
        by_label(app.button, "Add tag").click().run()
        created_tag = next(
            item for item in north.list_tags() if item["name"] == "Created tag"
        )
        by_label(app.selectbox, "Tag to rename").set_value(target_tag["id"]).run()
        by_label(app.text_input, "Renamed tag name").set_value("Renamed target tag")
        by_label(app.button, "Rename tag").click().run()
        assert next(
            item for item in north.list_tags() if item["id"] == target_tag["id"]
        )["name"] == "Renamed target tag"
        assert created_tag["id"] in {item["id"] for item in north.list_tags()}

        by_label(app.selectbox, "Target tag").set_value(target_tag["id"]).run()
        by_label(app.multiselect, "Source tags").set_value(
            [source_tag["id"]]
        ).run()
        by_label(
            app.checkbox,
            "I understand the selected source tags will be permanently removed",
        ).check()
        by_label(app.button, "Merge tags").click().run()
        assert not any(
            item["id"] == source_tag["id"] for item in north.list_tags()
        )
        assert next(
            item
            for item in north.list_transactions()
            if item["id"] == referenced_transaction["id"]
        )["tag_ids"] == [target_tag["id"]]

        navigate_to(app, "Accounts")
        navigate_to(app, "Transactions")
        by_label(app.selectbox, "Business").set_value("south").run()
        navigate_to(app, "Transactions")
        assert target_payee["id"] not in by_label(
            app.selectbox, "Target payee"
        ).options
        assert target_tag["id"] not in by_label(
            app.selectbox, "Target tag"
        ).options
