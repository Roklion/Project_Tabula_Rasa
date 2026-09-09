from __future__ import annotations

from datetime import date
from unittest.mock import patch

from tests.app_support import (
    authenticated_app,
    by_label,
    navigate_to,
    profile_config,
)
from tests.fakes import FakeWorkbook
from tabula_rasa.page_renderers.transactions.ledger import (
    _change_ledger_mode,
    _editable_account_ids,
    _make_created_copy_visible,
    copied_transaction_description,
)
from tabula_rasa.storage import GoogleSheetsStorage


def _transaction_fixture() -> tuple[GoogleSheetsStorage, dict[str, str]]:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    payee = storage.create_payee("Vendor")
    transaction = storage.create_transaction(
        txn_date=f"{date.today().year}-07-19",
        kind="Expense",
        amount=12.5,
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
        description="Original memo",
        reference="INV-123",
    )
    return storage, transaction


def test_copied_transaction_description_adds_current_provenance() -> None:
    assert copied_transaction_description(
        {"id": "source-123", "description": "Original memo"}
    ) == "Original memo. Copy From source-123"


def test_copied_transaction_description_does_not_double_period() -> None:
    assert copied_transaction_description(
        {"id": "source-123", "description": "Original memo."}
    ) == "Original memo. Copy From source-123"


def test_copied_transaction_description_strips_legacy_provenance() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": "Copied from transaction old-1: Original memo",
        }
    ) == "Original memo. Copy From source-123"


def test_copied_transaction_description_strips_multiple_stale_provenance_notes() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": (
                "Copied from transaction old-2: "
                "Copied from transaction old-1: Original memo. Copy From old-0"
            ),
        }
    ) == "Original memo. Copy From source-123"


def test_copied_transaction_description_preserves_non_provenance_text() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": "Copied from the vendor: Original memo",
        }
    ) == "Copied from the vendor: Original memo. Copy From source-123"


def test_copied_transaction_description_preserves_user_copy_text_at_end() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": "Reminder: Copy From project-123",
        }
    ) == "Reminder: Copy From project-123. Copy From source-123"


def test_copied_transaction_description_normalizes_punctuated_source_ids() -> None:
    assert copied_transaction_description(
        {
            "id": "source:1.2",
            "description": "Memo. Copy From source:1.2",
        }
    ) == "Memo. Copy From source:1.2"


def test_copied_transaction_description_strips_stale_punctuated_provenance() -> None:
    assert copied_transaction_description(
        {
            "id": "new-source",
            "description": "Memo. Copy From source:1.2",
        }
    ) == "Memo. Copy From new-source"


def test_copied_transaction_description_normalizes_whitespace_source_ids() -> None:
    assert copied_transaction_description(
        {
            "id": "source 1",
            "description": "Memo. Copy From source 1",
        }
    ) == "Memo. Copy From source 1"
    assert copied_transaction_description(
        {
            "id": "source 1",
            "description": "Copied from transaction source 1: Memo",
        }
    ) == "Memo. Copy From source 1"


def test_copied_transaction_description_preserves_multiword_copy_from_memo() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": "Copy From vendor invoice",
        }
    ) == "Copy From vendor invoice. Copy From source-123"


def test_copied_transaction_description_preserves_multiword_legacy_prefix_memo() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": (
                "Copied from transaction vendor invoice: awaiting approval"
            ),
        }
    ) == (
        "Copied from transaction vendor invoice: awaiting approval. "
        "Copy From source-123"
    )


def test_copied_transaction_description_preserves_delimited_copy_from_memo() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": "Copy From vendor invoice: awaiting approval",
        }
    ) == "Copy From vendor invoice: awaiting approval. Copy From source-123"


def test_copied_transaction_description_normalizes_blank_whitespace_id_memo() -> None:
    assert copied_transaction_description(
        {"id": "source 1", "description": "Copy From source 1"}
    ) == "Copy From source 1"


def test_copied_transaction_description_preserves_multiword_suffix_memo() -> None:
    assert copied_transaction_description(
        {
            "id": "source-123",
            "description": "My memo. Copy From vendor invoice",
        }
    ) == "My memo. Copy From vendor invoice. Copy From source-123"


def test_copied_transaction_description_has_no_separator_for_blank_memo() -> None:
    assert copied_transaction_description(
        {"id": "source-123", "description": "  Copy From old-1  "}
    ) == "Copy From source-123"


def test_copy_account_choices_exclude_inactive_source_account() -> None:
    accounts = [
        {"id": "inactive", "name": "Old account", "active": False},
        {"id": "active", "name": "Current account", "active": True},
    ]

    assert _editable_account_ids(
        accounts, ["inactive"], copy_mode=True
    ) == ["active"]
    assert _editable_account_ids(
        accounts, ["inactive"], copy_mode=False
    ) == ["active", "inactive"]


def test_switching_ledger_mode_preserves_copy_editor_target() -> None:
    state = {
        "transaction_bulk_selection_generation": 0,
        "transaction_ledger_mode_generation": 0,
        "transaction_copy_source_test": "source-id",
        "edit_transaction_id": "source-id",
    }

    with patch(
        "tabula_rasa.page_renderers.transactions.ledger.st.session_state", state
    ):
        _change_ledger_mode("test")

    assert state["edit_transaction_id"] == "source-id"


def test_copy_save_clears_tag_filter_before_reopening_copy() -> None:
    state = {
        "ledger_start": date(2026, 1, 1),
        "ledger_end": date(2026, 12, 31),
        "ledger_filter_type_test": "Expense",
        "ledger_filter_accounts_test": ["checking"],
        "ledger_filter_tags_test": ["project"],
        "ledger_search_test_0": "Project",
    }

    with patch(
        "tabula_rasa.page_renderers.transactions.ledger.st.session_state", state
    ):
        _make_created_copy_visible(
            "test",
            {"id": "copy-id", "txn_date": "2026-07-19"},
        )

    assert state["ledger_filter_tags_test"] == []


def test_copy_form_can_be_canceled_without_creating_or_mutating_transaction() -> None:
    storage, source = _transaction_fixture()
    storage.create_payee("New vendor")
    original_rows = storage.list_transactions()
    original_source = next(
        item for item in original_rows if item["id"] == source["id"]
    )

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        assert by_label(app.button, "Copy transaction").disabled is True
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()

        copy_button = by_label(app.button, "Copy transaction")
        assert copy_button.disabled is False
        copy_button.click().run()
        assert any(item.label == "Copy transaction" for item in app.expander)
        assert by_label(app.date_input, "Edit date").value == date.fromisoformat(
            source["txn_date"]
        )
        assert by_label(app.text_input, "Edit description").value == (
            "Original memo. "
            f"Copy From {source['id']}"
        )
        assert by_label(app.date_input, "From").disabled is True
        assert by_label(app.date_input, "To").disabled is True
        assert by_label(app.selectbox, "Type").disabled is True
        assert by_label(app.multiselect, "Accounts").disabled is True
        assert by_label(app.text_input, "Search transactions").disabled is True
        assert app.dataframe[0].selection_mode == []

        by_label(app.button, "Cancel copy").click().run()

        assert storage.list_transactions() == original_rows
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.selectbox, "Edit payee / customer").set_value("New vendor").run()
        by_label(app.button, "Save copied transaction").click().run()
        copied = next(
            item for item in storage.list_transactions() if item["id"] != source["id"]
        )
        assert app.session_state["edit_transaction_id"] == copied["id"]
        assert "transaction_copy_source_test" not in app.session_state

    transactions = storage.list_transactions()
    assert len(transactions) == 2
    copied = next(item for item in transactions if item["id"] != source["id"])
    assert copied["txn_date"] == original_source["txn_date"]
    assert copied["payee"] == "New vendor"
    assert copied["description"] == (
        "Original memo. "
        f"Copy From {source['id']}"
    )
    assert copied["receipt_references"] == "[]"
    assert next(item for item in transactions if item["id"] == source["id"]) == (
        original_source
    )


def test_copy_uses_selected_existing_payee() -> None:
    storage, source = _transaction_fixture()
    other_payee = storage.create_payee("Other vendor")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.selectbox, "Edit payee / customer").set_value(
            other_payee["id"]
        ).run()
        by_label(app.button, "Save copied transaction").click().run()

    copied = next(
        item for item in storage.list_transactions() if item["id"] != source["id"]
    )
    assert copied["payee_id"] == other_payee["id"]
    assert copied["payee"] == "Other vendor"


def test_copy_does_not_preselect_inactive_source_payee() -> None:
    storage, source = _transaction_fixture()
    storage.edit_payee(source["payee_id"], active=False)

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()

        payee_selector = by_label(app.selectbox, "Edit payee / customer")
        assert source["payee_id"] not in payee_selector.options
        payee_selector.set_value("").run()
        by_label(app.button, "Save copied transaction").click().run()

    copied = next(
        item for item in storage.list_transactions() if item["id"] != source["id"]
    )
    assert copied["payee_id"] == ""


def test_payee_selection_separates_duplicate_submission_fingerprints() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    storage.create_account("Checking", "Bank")
    storage.create_category("Office", "Expense")
    storage.create_payee("First vendor")
    storage.create_payee("Second vendor")

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.number_input, "Amount").set_value(10).run()
        by_label(app.selectbox, "From Account").set_value("Checking").run()
        by_label(app.selectbox, "Category").set_value("Office").run()
        by_label(app.selectbox, "Payee / customer").set_value("First vendor").run()
        by_label(app.button, "Save transaction").click().run()
        by_label(app.number_input, "Amount").set_value(10).run()
        by_label(app.selectbox, "From Account").set_value("Checking").run()
        by_label(app.selectbox, "Category").set_value("Office").run()
        by_label(app.selectbox, "Payee / customer").set_value("Second vendor").run()
        by_label(app.button, "Save transaction").click().run()

    assert {item["payee"] for item in storage.list_transactions()} == {
        "First vendor",
        "Second vendor",
    }


def test_copy_with_inactive_source_allows_active_account_replacement() -> None:
    storage, source = _transaction_fixture()
    replacement = storage.create_account("Replacement", "Bank")
    storage.deactivate_account(source["account_id"])

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()

        account_selector = by_label(app.selectbox, "Edit account")
        assert source["account_id"] not in account_selector.options
        assert "Replacement" in account_selector.options
        assert by_label(app.button, "Save copied transaction").disabled is False

        account_selector.set_value(replacement["id"]).run()
        by_label(app.button, "Save copied transaction").click().run()

    transactions = storage.list_transactions()
    assert len(transactions) == 2
    copied = next(item for item in transactions if item["id"] != source["id"])
    assert copied["account_id"] == replacement["id"]


def test_copy_save_adjusts_filters_to_keep_new_transaction_selected() -> None:
    storage, source = _transaction_fixture()
    created_date = date(date.today().year + 1, 1, 2)

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.date_input, "Edit date").set_value(created_date)
        by_label(app.button, "Save copied transaction").click().run()

        copied = next(
            item for item in storage.list_transactions() if item["id"] != source["id"]
        )
        assert copied["txn_date"] == created_date.isoformat()
        assert app.session_state["edit_transaction_id"] == copied["id"]
        assert copied["id"] in [
            str(transaction_id)
            for transaction_id in app.dataframe[0].value["ID"]
        ]


def test_copy_save_normalizes_user_edited_description_provenance() -> None:
    storage, source = _transaction_fixture()

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = (source["id"],)
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        by_label(app.text_input, "Edit description").set_value(
            "Updated memo. Copy From stale-1. Copy From stale-2"
        )
        by_label(app.button, "Save copied transaction").click().run()

    copied = next(
        item for item in storage.list_transactions() if item["id"] != source["id"]
    )
    assert copied["description"] == f"Updated memo. Copy From {source['id']}"


def test_copy_state_is_cleared_when_switching_profiles() -> None:
    storages = {
        "alpha-sheet": GoogleSheetsStorage(FakeWorkbook()),
        "beta-sheet": GoogleSheetsStorage(FakeWorkbook()),
    }
    profiles = {
        "alpha": profile_config(
            name="Alpha Business", spreadsheet_id="alpha-sheet"
        ),
        "beta": profile_config(name="Beta Business", spreadsheet_id="beta-sheet"),
    }
    alpha = storages["alpha-sheet"]
    alpha_account = alpha.create_account("Alpha Checking", "Bank")
    alpha_category = alpha.create_category("Alpha Office", "Expense")
    alpha_transaction = alpha.create_transaction(
        txn_date="2026-07-19",
        kind="Expense",
        amount=12.5,
        account_id=alpha_account["id"],
        category_id=alpha_category["id"],
        description="Alpha memo",
    )
    beta = storages["beta-sheet"]
    beta_account = beta.create_account("Beta Checking", "Bank")
    beta_category = beta.create_category("Beta Office", "Expense")
    beta.create_transaction(
        txn_date="2026-07-20",
        kind="Expense",
        amount=20.0,
        account_id=beta_account["id"],
        category_id=beta_category["id"],
        description="Beta memo",
    )

    with authenticated_app(storages=storages, profiles=profiles) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_alpha"] = (
            alpha_transaction["id"],
        )
        app.run()
        by_label(app.button, "Copy transaction").click().run()
        assert "transaction_copy_source_alpha" in app.session_state
        assert by_label(app.button, "Save copied transaction")

        by_label(app.selectbox, "Business").set_value("beta").run()

        assert "transaction_copy_source_alpha" not in app.session_state
        assert not any(
            item.label == "Save copied transaction" for item in app.button
        )
        assert not any(item.label == "Copy transaction" for item in app.expander)
