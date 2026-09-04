from datetime import date

import pytest

from tabula_rasa.page_renderers.transactions.mixed_use import (
    _MixedUseReceiptStorage,
    _incomplete_source_ids,
    _pending_create_ids,
    mixed_use_preview,
)
from tabula_rasa.page_renderers.transactions.ledger import (
    _mixed_use_transaction_ids,
    transaction_is_mixed_use,
)
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.ledger_reporting import (
    account_balances,
    category_activity_rollups,
    profit_and_loss,
)
from tabula_rasa.page_renderers.data_backup.exports import prepare_csv_exports
from tabula_rasa.page_renderers.transactions.search import filter_transaction_rows
from tabula_rasa.storage import (
    decode_receipt_references,
    StorageConflictError,
    StorageValidationError,
)
from tabula_rasa.page_renderers.transactions.receipts import (
    new_receipt_creation_workflow,
    receipt_creation_workflow_key,
)
from tests.app_support import authenticated_app, by_label, navigate_to


def _mixed_tab(app):
    return next(tab for tab in app.tabs if tab.label == "Mixed-use expenses")


def _tab_field(tab, collection: str, label: str):
    return next(item for item in getattr(tab, collection) if item.label == label)


def test_mixed_use_preview_uses_decimal_allocation_and_rationale() -> None:
    preview = mixed_use_preview(
        txn_date=date(2026, 9, 3),
        account="Operating > Checking",
        payee="Vendor",
        category="Office",
        description="Supplies",
        total_expense="123.45",
        business_use_percentage="33.33333",
        allocation_rationale="Measured workspace use",
    )
    assert preview["allocated_amount"] == "41.15"
    assert preview["status"] == "ready"
    assert preview["description"] == "Supplies\nAllocation rationale: Measured workspace use"


def test_mixed_use_preview_is_safe_for_incomplete_inputs() -> None:
    preview = mixed_use_preview(
        txn_date=None,
        account="",
        payee="",
        category="",
        description="",
        total_expense="",
        business_use_percentage="",
        allocation_rationale="",
    )
    assert preview["allocated_amount"] == "—"
    assert preview["status"] != "ready"
    assert preview["description"] == "—"


def test_pending_create_ids_remain_stable_for_uncertain_retries() -> None:
    state: dict[str, object] = {}
    first = _pending_create_ids(state, "north")
    second = _pending_create_ids(state, "north")

    assert first == second
    assert first[0] == state["mixed_use_pending_source_id_north"]
    assert first[1] == state["mixed_use_pending_transaction_id_north"]
    assert first != _pending_create_ids(state, "south")


def test_projection_provenance_blocks_source_only_repair() -> None:
    assert _incomplete_source_ids(
        [{"id": "source-1", "linked_transaction_id": "missing"}],
        [
            {
                "id": "projection-2",
                "source_type": "mixed_use_expense",
                "source_id": "source-1",
            }
        ],
    ) == set()


def test_only_phase_a_mixed_use_provenance_is_protected() -> None:
    assert transaction_is_mixed_use(
        {"source_type": "mixed_use_expense", "source_id": "source-1"}
    )
    assert not transaction_is_mixed_use(
        {"source_type": "transaction_copy", "source_id": "transaction-1"}
    )
    assert not transaction_is_mixed_use(
        {"source_type": "mixed_use_expense", "source_id": ""}
    )


def test_mixed_use_transaction_ids_can_be_derived_from_unfiltered_snapshot() -> None:
    mixed_projection = {
        "id": "projection-1",
        "source_type": "mixed_use_expense",
        "source_id": "source-1",
    }
    ordinary_transaction = {"id": "transaction-1"}

    assert _mixed_use_transaction_ids(
        [ordinary_transaction, mixed_projection]
    ) == {"projection-1"}


def test_generic_create_rejects_fabricated_mixed_use_projection(default_storage) -> None:
    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        default_storage.create_transaction(
            txn_date="2026-09-03",
            kind="Expense",
            amount="10",
            account_id="missing",
            category_id="missing",
            source_type="mixed_use_expense",
            source_id="source",
        )


def test_source_aware_receipt_path_preserves_pair_and_generic_path_rejects(
    default_storage,
) -> None:
    account = default_storage.create_account("Mixed Checking", "Bank")
    category = default_storage.create_category("Mixed Office", "Expense")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    reference = {"id": "a" * 32, "name": "receipt.pdf"}
    default_storage.link_mixed_use_receipt(
        source["id"], reference=reference, expected_source=source
    )
    projection = default_storage.list_transactions()[0]
    refreshed = default_storage.get_mixed_use_expense(source["id"])
    assert projection["receipt_references"] == refreshed["receipt_references"]
    with pytest.raises(StorageValidationError, match="changed through mixed-use"):
        default_storage.link_transaction_receipt(
            source["linked_transaction_id"],
            reference={"id": "b" * 32, "name": "other.pdf"},
        )
    with pytest.raises(StorageConflictError, match="changed"):
        default_storage.set_mixed_use_receipt_references(
            source["id"], [], expected_source=source
        )


def test_source_receipt_adapter_refreshes_snapshot_for_multiple_receipts(
    default_storage,
) -> None:
    account = default_storage.create_account("Adapter Checking", "Bank")
    category = default_storage.create_category("Adapter Office", "Expense")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    updated_sources = []
    adapter = _MixedUseReceiptStorage(
        default_storage,
        source["id"],
        source,
        on_source_changed=updated_sources.append,
    )
    adapter.link_transaction_receipt(
        source["linked_transaction_id"],
        reference={"id": "c" * 32, "name": "one.pdf"},
    )
    adapter.link_transaction_receipt(
        source["linked_transaction_id"],
        reference={"id": "d" * 32, "name": "two.pdf"},
    )
    refreshed = default_storage.get_mixed_use_expense(source["id"])
    assert len(decode_receipt_references(refreshed["receipt_references"])) == 2
    assert updated_sources[-1]["receipt_references"] == refreshed["receipt_references"]


def test_source_receipt_adapter_refreshes_only_receipt_baseline(
    default_storage, monkeypatch
) -> None:
    source = {
        "id": "source-baseline",
        "description": "Original description",
        "receipt_references": "[]",
    }
    refreshed_source = {
        **source,
        "description": "Concurrent description",
        "receipt_references": '[{"id":"receipt"}]',
    }
    monkeypatch.setattr(
        default_storage,
        "get_mixed_use_expense",
        lambda _source_id: refreshed_source,
    )
    updated_sources = []
    adapter = _MixedUseReceiptStorage(
        default_storage,
        source["id"],
        source,
        on_source_changed=updated_sources.append,
    )

    adapter._refresh_expected_source()

    assert adapter._expected_source["description"] == "Original description"
    assert adapter._expected_source["receipt_references"] == (
        '[{"id":"receipt"}]'
    )
    assert updated_sources == [adapter._expected_source]


def test_source_aware_receipt_api_normalizes_invalid_metadata(
    default_storage,
) -> None:
    account = default_storage.create_account("Invalid Receipt Checking", "Bank")
    category = default_storage.create_category("Invalid Receipt Office", "Expense")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    with pytest.raises(StorageValidationError, match="Receipt"):
        default_storage.link_mixed_use_receipt(
            source["id"], reference={"id": "", "name": ""}
        )


def test_mixed_use_app_test_create_edit_delete_and_transactions_tabs(default_storage) -> None:
    account = default_storage.create_account("App Mixed Checking", "Bank")
    category = default_storage.create_category("App Mixed Office", "Expense")
    payee = default_storage.create_payee("App Mixed Vendor")
    tag = default_storage.create_tag("App Mixed Tag")

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        assert [tab.label for tab in app.tabs] == [
            "Add transaction",
            "View & edit ledger",
            "Mixed-use expenses",
            "Payees & Tags",
            "Payees",
            "Tags",
        ]
        tab = _mixed_tab(app)
        tab.selectbox[0].set_value(account["id"]).run()
        tab.selectbox[1].set_value(category["id"]).run()
        tab.selectbox[2].set_value(payee["id"]).run()
        tab.multiselect[0].set_value([tag["id"]]).run()
        _tab_field(tab, "text_input", "Total Expense").set_value("100.00").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Business Use %").set_value("25").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_area", "Allocation Rationale (required)").set_value("Measured workspace use").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Save mixed-use expense").click().run()

        sources = default_storage.list_mixed_use_expenses()
        projections = default_storage.list_transactions()
        assert len(sources) == len(projections) == 1
        source = sources[0]
        projection = projections[0]
        assert source["linked_transaction_id"] == projection["id"]
        assert projection["amount"] == "25.00"
        assert projection["description"] == (
            "Allocation rationale: Measured workspace use"
        )
        assert source["payee_id"] == payee["id"]
        assert tag["id"] in source["tag_ids"]
        assert tag["id"] in projection["tag_ids"]
        assert any("Mixed-use expense saved." in str(item.value) for item in app.success)
        reset_tab = _mixed_tab(app)
        assert _tab_field(reset_tab, "text_input", "Total Expense").value == "0.00"
        assert _tab_field(reset_tab, "text_input", "Business Use %").value == "0"
        assert _tab_field(reset_tab, "text_area", "Allocation Rationale (required)").value == ""

        # Selecting the source rehydrates the edit surface with stable IDs.
        tab = _mixed_tab(app)
        tab.selectbox[0].set_value(source["id"]).run()
        tab = _mixed_tab(app)
        assert _tab_field(tab, "text_input", "Total Expense").value == "100.00"
        _tab_field(tab, "text_input", "Business Use %").set_value("50").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Save changes").click().run()
        updated = default_storage.get_mixed_use_expense(source["id"])
        assert updated["id"] == source["id"]
        assert updated["linked_transaction_id"] == projection["id"]
        assert updated["allocated_amount"] == "50.00"

        tab = _mixed_tab(app)
        assert tab.checkbox
        _tab_field(tab, "button", "Permanently delete").click().run()
        assert any("Confirm the permanent deletion" in str(item.value) for item in app.error)
        tab = _mixed_tab(app)
        tab.checkbox[0].set_value(True).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Permanently delete").click().run()
        assert default_storage.list_mixed_use_expenses() == []
        assert default_storage.list_transactions() == []


def test_mixed_use_app_test_exposes_source_only_projection_repair(default_storage) -> None:
    tag = default_storage.create_tag("Repair tag")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=next(item for item in default_storage.list_accounts() if item["active"])["id"],
        category_id=next(item for item in default_storage.list_categories() if item["kind"] == "Expense")["id"],
        allocation_rationale="Measured use",
        tag_ids=[tag["id"]],
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    transaction_sheet.rows.pop(1)
    default_storage._invalidate("Transactions")

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        assert any("without its ledger projection" in str(item.value) for item in app.warning)
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Repair ledger projection").click().run()

    assert len(default_storage.list_transactions()) == 1
    assert default_storage.list_mixed_use_expenses()[0]["id"] == source["id"]
    assert default_storage.list_mixed_use_expenses()[0]["tag_ids"] == [tag["id"]]
    assert default_storage.list_transactions()[0]["tag_ids"] == [tag["id"]]


def test_mixed_use_app_test_clears_recovery_after_source_deletion(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    transaction = default_storage.list_transactions()[0]
    default_storage.delete_mixed_use_expense(source["id"])

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state[receipt_creation_workflow_key("test")] = (
            new_receipt_creation_workflow(
                transaction["id"],
                [],
                profile_key="test",
                mixed_use_source_id=source["id"],
            )
        )
        app.run()
        assert receipt_creation_workflow_key("test") not in app.session_state
        assert any("source and projection no longer exist" in str(item.value) for item in app.warning)


def test_mixed_use_app_test_validation_preserves_inputs(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(item for item in default_storage.list_categories() if item["kind"] == "Expense")
    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Account").set_value(account["id"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Category").set_value(category["id"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Total Expense").set_value("17.25").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Business Use %").set_value("33.33333").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Save mixed-use expense").click().run()
        assert default_storage.list_transactions() == []
        tab = _mixed_tab(app)
        assert _tab_field(tab, "text_input", "Total Expense").value == "17.25"
        assert _tab_field(tab, "text_input", "Business Use %").value == "33.33333"
        assert any("Allocation rationale is required" in str(item.value) for item in app.error)


def test_mixed_use_app_test_reuses_inline_payee_and_tag_creation(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(item for item in default_storage.list_categories() if item["kind"] == "Expense")
    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Account").set_value(account["id"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Category").set_value(category["id"]).run()
        tab = _mixed_tab(app)
        payee_selector = _tab_field(tab, "selectbox", "Payee / customer")
        payee_selector.options.append("Inline Vendor")
        payee_selector.set_value("Inline Vendor").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Payee / customer").options.append("Inline Vendor")
        tag_selector = _tab_field(tab, "multiselect", "Tags")
        tag_selector.options.append("Inline Tag")
        tag_selector.set_value(["Inline Tag"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Payee / customer").options.append("Inline Vendor")
        _tab_field(tab, "multiselect", "Tags").options.append("Inline Tag")
        _tab_field(tab, "text_input", "Total Expense").set_value("40").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Payee / customer").options.append("Inline Vendor")
        _tab_field(tab, "multiselect", "Tags").options.append("Inline Tag")
        _tab_field(tab, "text_input", "Business Use %").set_value("50").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Payee / customer").options.append("Inline Vendor")
        _tab_field(tab, "multiselect", "Tags").options.append("Inline Tag")
        _tab_field(tab, "text_area", "Allocation Rationale (required)").set_value("Inline setup").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Payee / customer").options.append("Inline Vendor")
        _tab_field(tab, "multiselect", "Tags").options.append("Inline Tag")
        _tab_field(tab, "button", "Save mixed-use expense").click().run()

    source = default_storage.list_mixed_use_expenses()[0]
    payee = next(item for item in default_storage.list_payees() if item["name"] == "Inline Vendor")
    tag = next(item for item in default_storage.list_tags() if item["name"] == "Inline Tag")
    assert source["payee_id"] == payee["id"]
    assert tag["id"] in source["tag_ids"]
    assert default_storage.list_transactions()[0]["tag_ids"] == source["tag_ids"]


def test_mixed_use_app_test_is_profile_scoped_and_derived_ledger_is_read_only() -> None:
    from tests.app_support import profile_config
    from tests.fakes import FakeWorkbook
    from tabula_rasa.storage import GoogleSheetsStorage

    north = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    south = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    for storage, prefix in ((north, "North"), (south, "South")):
        storage.ensure_defaults()
        account = next(item for item in storage.list_accounts() if item["name"] == "Checking")
        category = next(item for item in storage.list_categories() if item["name"] == "Office")
        storage.create_mixed_use_expense(
            txn_date="2026-09-03",
            total_expense="80",
            business_use_percentage="50",
            account_id=account["id"],
            category_id=category["id"],
            allocation_rationale=f"{prefix} use",
        )

    with authenticated_app(
        storages={"north-sheet": north, "south-sheet": south},
        profiles={
            "north": profile_config(name="North", spreadsheet_id="north-sheet"),
            "south": profile_config(name="South", spreadsheet_id="south-sheet"),
        },
    ) as app:
        navigate_to(app, "Transactions")
        source = north.list_mixed_use_expenses()[0]
        app.session_state["mixed_use_selected_source_id_north"] = source["id"]
        app.run()
        assert app.session_state["mixed_use_selected_source_id_north"] == source["id"]
        by_label(app.selectbox, "Business").set_value("south").run()
        assert app.session_state["mixed_use_selected_source_id_south"] == ""
        tab = _mixed_tab(app)
        assert south.list_mixed_use_expenses()[0]["allocation_rationale"] == "South use"
        assert all(
            str(item.value) != north.list_mixed_use_expenses()[0]["allocation_rationale"]
            for item in tab.caption
        )

        projection = south.list_transactions()[0]
        app.session_state["edit_transaction_id"] = projection["id"]
        app.run()
        assert any(
            "managed from the Mixed-use expenses tab" in str(item.value)
            for item in app.info
        )
        ledger_tab = next(tab for tab in app.tabs if tab.label == "View & edit ledger")
        ledger_labels = {item.label for item in ledger_tab.button}
        assert "Save changes" not in ledger_labels
        assert "Permanently delete" not in ledger_labels
        assert "Remove receipt" not in ledger_labels
        assert "Link selected receipt" not in ledger_labels


def test_mixed_use_projection_is_counted_once_across_read_paths(default_storage) -> None:
    account = default_storage.create_account("Read Path Checking", "Bank")
    category = default_storage.create_category("Read Path Office", "Expense")
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100.00",
        business_use_percentage="25",
        account_id=account["id"],
        category_id=category["id"],
        description="Shared office",
        allocation_rationale="Measured use",
    )
    transactions = default_storage.list_transactions()
    accounts = default_storage.list_accounts(active_only=False)
    categories = default_storage.list_categories()
    tags = default_storage.list_tags()

    assert [row["id"] for row in transactions] == [source["linked_transaction_id"]]
    assert profit_and_loss(transactions)["expenses"] == 25.0
    balances = account_balances(accounts, transactions)
    checking = next(row for row in balances if row["id"] == account["id"])
    assert checking["balance"] == -25.0
    rollups = category_activity_rollups(transactions, categories, kind="Expense")
    assert [row["rollup_total"] for row in rollups if row["id"] == category["id"]] == [25.0]

    frame = ledger_frame(transactions, accounts, categories, tags=tags)
    assert len(frame) == 1
    assert frame.iloc[0]["ID"] == source["linked_transaction_id"]
    assert frame.iloc[0]["Amount"] == 25.0
    matched = filter_transaction_rows(frame.to_dict(orient="records"), "Shared office")
    assert len(matched) == 1
    assert matched[0]["ID"] == source["linked_transaction_id"]

    exports = prepare_csv_exports(default_storage)
    csv_text = exports["transactions"].decode("utf-8")
    assert csv_text.count(source["linked_transaction_id"]) == 1
    assert source["id"] not in csv_text
    assert ",25.0," in csv_text or ",25.00," in csv_text
