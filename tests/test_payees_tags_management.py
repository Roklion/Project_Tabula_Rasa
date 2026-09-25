from __future__ import annotations

from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage


def select_managed_row(app, kind: str, record_id: str, profile: str = "north") -> None:
    """AppTest cannot click dataframe rows, so seed the callback's stable ID."""
    for checkbox in app.checkbox:
        if checkbox.key and checkbox.key.startswith("managed_"):
            # AppTest may retain a pre-rerun checkbox after a confirmed mutation.
            app.session_state[checkbox.key] = False
    app.session_state[f"managed_{kind}_{profile}_selected_id"] = record_id
    app.run()


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
        assert any("No payees yet. Add one below." in str(item.value) for item in app.info)
        assert any("No tags yet. Add one below." in str(item.value) for item in app.info)
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
    mixed_source = north.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        payee_id=source_payee["id"],
        tag_ids=[source_tag["id"]],
        description="Shared vehicle expense",
        allocation_rationale="Shared use",
    )
    mileage_trip = north.create_mileage_trip(
        trip_date="2026-09-04",
        miles="12.5",
        start_location="North office",
        destination="Client site",
        business_purpose="Client visit",
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
        managed_tables = [
            frame for frame in app.dataframe
            if frame.key and frame.key.startswith("managed_")
        ]
        assert len(managed_tables) == 2
        assert all(frame.selection_mode for frame in managed_tables)
        assert not any(
            item.label in {
                "Payee to rename", "Payee to remove", "Tag to rename", "Tag to remove"
            }
            for item in app.selectbox
        )

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
        assert next(
            item
            for item in north.list_mixed_use_expenses()
            if item["id"] == mixed_source["id"]
        )["payee_id"] == target_payee["id"]
        assert any("Payees merged." in str(item.value) for item in app.success)

        navigate_to(app, "Accounts")
        navigate_to(app, "Transactions")
        by_label(app.text_input, "New payee name").input("Created payee")
        by_label(app.button, "Add payee").click().run()
        created_payee = next(
            item for item in north.list_payees() if item["name"] == "Created payee"
        )
        select_managed_row(app, "payee", created_payee["id"])
        assert by_label(app.button, "Permanently remove payee").disabled is False
        assert next(
            item
            for item in app.checkbox
            if "I understand payee" in item.label
            and "permanently removed" in item.label
        ).disabled is False
        by_label(app.button, "Permanently remove payee").click().run()
        assert any(
            "Acknowledge permanent removal" in str(item.value)
            for item in app.error
        )
        assert any(item["id"] == created_payee["id"] for item in north.list_payees())
        assert next(
            item
            for item in app.checkbox
            if "I understand payee" in item.label
            and "permanently removed" in item.label
        ).disabled is False
        next(
            item
            for item in app.checkbox
            if "I understand payee" in item.label
            and "permanently removed" in item.label
        ).check()
        by_label(app.button, "Permanently remove payee").click().run()
        assert not any(item["id"] == created_payee["id"] for item in north.list_payees())
        select_managed_row(app, "payee", target_payee["id"])
        by_label(app.text_input, "Renamed payee name").set_value(
            "Renamed target"
        )
        by_label(app.button, "Rename payee").click().run()
        assert next(
            item for item in north.list_payees() if item["id"] == target_payee["id"]
        )["name"] == "Renamed target"

        select_managed_row(app, "payee", target_payee["id"])
        assert by_label(app.button, "Permanently remove payee").disabled is True
        assert any("3 references" in str(item.value) for item in app.info)

        by_label(app.text_input, "New tag name").input("Created tag")
        by_label(app.button, "Add tag").click().run()
        created_tag = next(
            item for item in north.list_tags() if item["name"] == "Created tag"
        )
        select_managed_row(app, "tag", created_tag["id"])
        assert by_label(app.button, "Permanently remove tag").disabled is False
        assert next(
            item
            for item in app.checkbox
            if "I understand tag" in item.label
            and "permanently removed" in item.label
        ).disabled is False
        by_label(app.button, "Permanently remove tag").click().run()
        assert any(
            "Acknowledge permanent removal" in str(item.value)
            for item in app.error
        )
        assert any(item["id"] == created_tag["id"] for item in north.list_tags())
        next(
            item
            for item in app.checkbox
            if "I understand tag" in item.label
            and "permanently removed" in item.label
        ).check()
        by_label(app.button, "Permanently remove tag").click().run()
        assert not any(item["id"] == created_tag["id"] for item in north.list_tags())
        select_managed_row(app, "tag", target_tag["id"])
        by_label(app.text_input, "Renamed tag name").set_value("Renamed target tag")
        by_label(app.button, "Rename tag").click().run()
        assert next(
            item for item in north.list_tags() if item["id"] == target_tag["id"]
        )["name"] == "Renamed target tag"

        by_label(app.selectbox, "Target tag").set_value(target_tag["id"]).run()
        by_label(app.multiselect, "Source tags").set_value(
            [source_tag["id"]]
        ).run()
        by_label(app.button, "Merge tags").click().run()
        assert any(
            "Acknowledge the permanent source removal" in str(item.value)
            for item in app.error
        )
        assert any(item["id"] == source_tag["id"] for item in north.list_tags())
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
        assert next(
            item
            for item in north.list_mileage_trips()
            if item["id"] == mileage_trip["id"]
        )["tag_ids"] == [target_tag["id"]]
        assert next(
            item
            for item in north.list_mixed_use_expenses()
            if item["id"] == mixed_source["id"]
        )["tag_ids"] == [target_tag["id"]]

        navigate_to(app, "Accounts")
        navigate_to(app, "Transactions")
        select_managed_row(app, "tag", target_tag["id"])
        assert any("4 references" in str(item.value) for item in app.info)
        assert by_label(app.button, "Permanently remove tag").disabled is True
        assert next(
            item
            for item in app.checkbox
            if "I understand tag" in item.label
            and "permanently removed" in item.label
        ).disabled is True

        navigate_to(app, "Transactions")
        by_label(app.selectbox, "Business").set_value("south").run()
        navigate_to(app, "Transactions")
        assert not app.session_state["managed_payee_south_selected_id"]
        assert not app.session_state["managed_tag_south_selected_id"]
        assert by_label(app.selectbox, "Target payee").options == ["South only"]
        assert by_label(app.selectbox, "Target tag").options == ["South only tag"]
