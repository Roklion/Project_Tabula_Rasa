from __future__ import annotations

from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook


def seed_editor(storage: GoogleSheetsStorage) -> dict[str, object]:
    account = storage.create_account("Checking", "Bank")
    office = storage.create_category("Office", "Expense")
    travel = storage.create_category("Travel", "Expense")
    alpha = storage.create_payee("Alpha Vendor")
    beta = storage.create_payee("Beta Vendor")
    project = storage.create_tag("Project")
    travel_tag = storage.create_tag("Travel")
    transactions = [
        storage.create_transaction(
            txn_date="2026-07-18",
            kind="Expense",
            amount=1,
            account_id=account["id"],
            category_id=office["id"],
            payee_id=alpha["id"],
            tag_ids=[project["id"]],
        ),
        storage.create_transaction(
            txn_date="2026-07-19",
            kind="Expense",
            amount=2,
            account_id=account["id"],
            category_id=travel["id"],
            payee_id=beta["id"],
            tag_ids=[travel_tag["id"]],
        ),
        storage.create_transaction(
            txn_date="2026-07-20",
            kind="Expense",
            amount=3,
            account_id=account["id"],
            category_id=office["id"],
            payee_id=alpha["id"],
            tag_ids=[project["id"]],
        ),
        storage.create_transaction(
            txn_date="2026-07-21",
            kind="Expense",
            amount=4,
            account_id=account["id"],
            category_id=office["id"],
            payee_id=alpha["id"],
            tag_ids=[project["id"]],
        ),
    ]
    return {
        "office": office,
        "travel": travel,
        "alpha": alpha,
        "project": project,
        "transactions": transactions,
    }


def caption_values(app) -> list[str]:
    return [str(element.value) for element in app.caption]


def bulk_widget(elements, label: str):
    return next(
        element
        for element in elements
        if element.label == label
        and str(getattr(element, "key", "")).startswith("transaction_bulk_")
    )


def main() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    fixture = seed_editor(storage)
    transactions = fixture["transactions"]
    assert isinstance(transactions, list)
    first, second, third, fourth = transactions
    office = fixture["office"]
    travel = fixture["travel"]
    alpha = fixture["alpha"]
    project = fixture["project"]
    assert isinstance(office, dict)
    assert isinstance(travel, dict)
    assert isinstance(alpha, dict)
    assert isinstance(project, dict)

    with authenticated_app(
        storage=storage,
        profiles={"test": profile_config()},
    ) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()

        app.session_state["transaction_bulk_selected_ids_test"] = (
            first["id"],
            second["id"],
        )
        app.run()

        assert bulk_widget(app.selectbox, "Category").value == (
            "__tabula_rasa_mixed__"
        )
        assert bulk_widget(app.selectbox, "Payee").value == (
            "__tabula_rasa_mixed__"
        )
        assert bulk_widget(app.multiselect, "Tags").value == []
        captions = caption_values(app)
        assert "Current Category: Mixed / Multiple values" in captions
        assert "Current Payee: Mixed / Multiple values" in captions
        assert "Current Tags: Mixed / Multiple values" in captions

        bulk_widget(app.selectbox, "Category").set_value(office["id"]).run()
        bulk_widget(app.selectbox, "Payee").set_value(alpha["id"]).run()
        bulk_widget(app.multiselect, "Tags").set_value([project["id"]]).run()
        assert any(
            "Review: change Category, Payee, Tags for 2 selected transaction(s)."
            in value
            for value in caption_values(app)
        )
        by_label(app.button, "Apply changes").click().run()

        updated = {
            item["id"]: item for item in storage.list_transactions(_force_refresh=True)
        }
        for transaction in (first, second):
            current = updated[transaction["id"]]
            assert current["category_id"] == office["id"]
            assert current["payee_id"] == alpha["id"]
            assert current["tag_ids"] == [project["id"]]
            assert current["amount"] == transaction["amount"]
            assert current["txn_date"] == transaction["txn_date"]
            assert current["account_id"] == transaction["account_id"]

    with authenticated_app(
        storage=storage,
        profiles={"test": profile_config()},
    ) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (
            third["id"],
            fourth["id"],
        )
        app.run()
        assert bulk_widget(app.selectbox, "Category").value == office["id"]
        assert bulk_widget(app.selectbox, "Payee").value == alpha["id"]
        assert bulk_widget(app.multiselect, "Tags").value == [project["id"]]

        by_label(app.button, "Apply changes").click().run()
        assert any(
            "No changes selected; no transactions were updated." in str(element.value)
            for element in app.info
        )

        bulk_widget(app.selectbox, "Category").set_value(travel["id"]).run()
        bulk_widget(app.selectbox, "Category").set_value(office["id"]).run()
        by_label(app.button, "Apply changes").click().run()
        assert any(
            "No changes selected; no transactions were updated." in str(element.value)
            for element in app.info
        )

        by_label(app.checkbox, "Apply Category to all selected").check().run()
        by_label(app.checkbox, "Apply Category to all selected").uncheck().run()
        by_label(app.button, "Apply changes").click().run()
        assert any(
            "No changes selected; no transactions were updated." in str(element.value)
            for element in app.info
        )

        by_label(app.checkbox, "Apply Category to all selected").check().run()
        by_label(app.checkbox, "Apply Payee to all selected").check().run()
        by_label(app.checkbox, "Apply Tags to all selected").check().run()
        by_label(app.button, "Apply changes").click().run()
        assert any(
            "Category, Payee, Tags updated for 0 transactions." in str(element.value)
            for element in app.success
        )
        final = {
            item["id"]: item for item in storage.list_transactions(_force_refresh=True)
        }
        assert final[third["id"]]["payee_id"] == alpha["id"]
        assert final[fourth["id"]]["payee_id"] == alpha["id"]


if __name__ == "__main__":
    main()
