from datetime import date

import pytest

from tabula_rasa.page_renderers.transactions.mixed_use import (
    _MixedUseReceiptStorage,
    _clear_mixed_use_copy,
    _fresh_mixed_use_copy_source,
    _mixed_use_copy_keys,
    _mixed_use_log_rows,
    _mixed_use_receipt_recovery_active,
    _mixed_use_selection_ids,
    _pending_create_ids,
    _preserve_pending_recurring_state,
    _start_mixed_use_copy,
    mixed_use_preview,
)
from tabula_rasa.ledger_presentation import ledger_frame
from tabula_rasa.ledger_reporting import (
    account_balances,
    category_activity_rollups,
    profit_and_loss,
)
from tabula_rasa.page_renderers.data_backup.exports import prepare_csv_exports
from tabula_rasa.page_renderers.transactions.search import filter_transaction_rows
from tabula_rasa.storage import decode_receipt_references, StorageValidationError
from tabula_rasa.page_renderers.transactions.receipts import (
    new_receipt_creation_workflow,
    receipt_creation_workflow_key,
    receipt_editor_workflow_key,
)
from tests.app_support import authenticated_app, by_label, navigate_to


def _mixed_tab(app):
    return next(tab for tab in app.tabs if tab.label == "Mixed-use expenses")


def _tab_field(tab, collection: str, label: str):
    return next(item for item in getattr(tab, collection) if item.label == label)


def test_pending_create_ids_remain_stable_for_uncertain_retries() -> None:
    state: dict[str, object] = {}
    first = _pending_create_ids(state, "north")
    second = _pending_create_ids(state, "north")

    assert first == second
    assert first[0] == state["mixed_use_pending_source_id_north"]
    assert first[1] == state["mixed_use_pending_transaction_id_north"]
    assert first != _pending_create_ids(state, "south")


def test_projection_conflicts_keep_recurring_retry_state() -> None:
    from tabula_rasa.storage import StorageConflictError

    assert _preserve_pending_recurring_state(
        StorageConflictError("Could not find the linked projection")
    )
    assert _preserve_pending_recurring_state(
        StorageConflictError("A source exists without its linked projection")
    )
    assert not _preserve_pending_recurring_state(
        StorageConflictError("Recurring schedule ID is already in use")
    )


def test_mixed_use_table_selection_maps_rows_to_stable_source_ids() -> None:
    assert _mixed_use_selection_ids(
        ["source-newest", "source-oldest"], [1, 0, 9, -1]
    ) == ("source-oldest", "source-newest")


def test_mixed_use_upload_is_blocked_during_linked_editor_recovery() -> None:
    profile = "north"
    transaction_id = "projection-1"

    assert _mixed_use_receipt_recovery_active(
        {receipt_editor_workflow_key(profile, transaction_id): {}},
        profile,
        transaction_id,
    )
    assert not _mixed_use_receipt_recovery_active({}, profile, transaction_id)


def test_mixed_use_log_puts_receipt_indicator_at_the_end() -> None:
    rows = _mixed_use_log_rows(
        [
            {
                "txn_date": "2026-09-08",
                "payee": "Vendor",
                "description": "Shared office supplies",
                "account_id": "account",
                "category_id": "category",
                "total_expense": "100.00",
                "business_use_percentage": "25",
                "allocated_amount": "25.00",
                "allocation_rationale": "Shared workspace",
                "receipt_references": (
                    '[{"id":"' + "a" * 32 + '","name":"receipt.pdf"}]'
                ),
            },
            {
                "txn_date": "2026-09-07",
                "payee": "Other vendor",
                "account_id": "account",
                "category_id": "category",
                "total_expense": "50.00",
                "business_use_percentage": "50",
                "allocated_amount": "25.00",
                "allocation_rationale": "Shared service",
                "receipt_references": "[]",
            },
        ],
        {"account": "Checking"},
        {"category": "Office"},
    )

    assert list(rows[0]) == [
        "Date",
        "Payee",
        "Account",
        "Category",
        "Total",
        "Business %",
        "Allocated",
        "Rationale",
            "Description",
            "Receipt",
            "Recurring",
    ]
    assert rows[0]["Receipt"] == "\U0001f4ce"
    assert rows[0]["Payee"] == "Vendor"
    assert rows[0]["Description"] == "Shared office supplies"
    assert rows[0]["Recurring"] == ""
    assert rows[1]["Receipt"] == ""


def test_mixed_use_log_marks_recurring_sources() -> None:
    rows = _mixed_use_log_rows(
        [{
            "txn_date": "2026-09-08", "account_id": "a", "category_id": "c",
            "total_expense": "1", "business_use_percentage": "50",
            "allocated_amount": "0.50", "allocation_rationale": "Use",
            "recurring_schedule_id": "schedule",
        }],
        {"a": "Checking"}, {"c": "Office"},
    )
    assert rows[0]["Recurring"] == "Recurring"


def test_mixed_use_log_keeps_malformed_receipts_inspectable() -> None:
    rows = _mixed_use_log_rows(
        [
            {
                "txn_date": "2026-09-08",
                "payee": "Vendor",
                "receipt_references": "not-json",
            }
        ],
        {},
        {},
    )

    assert rows[0]["Receipt"] == ""


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


def test_mixed_use_copy_re_reads_pair_and_keeps_independent_snapshot(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=account["id"],
        category_id=category["id"],
        description="Original memo",
        allocation_rationale="Measured use",
    )

    fresh = _fresh_mixed_use_copy_source(default_storage, source["id"])
    state = {}
    new_source_id, new_transaction_id = _start_mixed_use_copy(
        state, "north", fresh
    )
    keys = _mixed_use_copy_keys("north")
    snapshot = state[keys["snapshot"]]
    assert new_source_id != source["id"]
    assert new_transaction_id != source["linked_transaction_id"]
    assert snapshot["txn_date"] == "2026-09-03"
    assert snapshot["description"] == (
        f"Original memo. Copy From {source['id']}"
    )

    # Mutating the returned source cannot mutate the copy's initialized data.
    fresh["description"] = "Changed after copy started"
    assert state[keys["snapshot"]]["description"] != fresh["description"]
    generation = state[keys["generation"]]
    _clear_mixed_use_copy(state, "north")
    _start_mixed_use_copy(state, "north", source)
    assert state[keys["generation"]] == generation + 1


def test_mixed_use_copy_snapshot_saves_after_original_edit(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=account["id"],
        category_id=category["id"],
        description="Original memo",
        allocation_rationale="Original rationale",
    )
    snapshot_state: dict[str, object] = {}
    _start_mixed_use_copy(
        snapshot_state,
        "north",
        _fresh_mixed_use_copy_source(default_storage, source["id"]),
    )
    keys = _mixed_use_copy_keys("north")
    snapshot = snapshot_state[keys["snapshot"]]
    default_storage.edit_mixed_use_expense(
        source["id"],
        total_expense="300",
        business_use_percentage="50",
        allocation_rationale="Changed after copy started",
    )

    copied = default_storage.create_mixed_use_expense(
        source_id=snapshot_state[keys["new_source_id"]],
        linked_transaction_id=snapshot_state[keys["new_transaction_id"]],
        txn_date=snapshot["txn_date"],
        total_expense=snapshot["total_expense"],
        business_use_percentage=snapshot["business_use_percentage"],
        account_id=snapshot["account_id"],
        category_id=snapshot["category_id"],
        payee_id=snapshot.get("payee_id", ""),
        reference=snapshot.get("reference", ""),
        description=snapshot["description"],
        tag_ids=snapshot.get("tag_ids", ()),
        allocation_rationale=snapshot["allocation_rationale"],
    )
    assert copied["description"] == f"Original memo. Copy From {source['id']}"
    assert copied["total_expense"] == "100.00"
    assert copied["allocated_amount"] == "25.00"
    assert default_storage.get_mixed_use_expense(source["id"])["total_expense"] == "300.00"


def test_mixed_use_copy_rejects_missing_projection(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    default_storage._worksheet("Transactions").rows.pop(1)
    default_storage._invalidate("Transactions")

    with pytest.raises(StorageValidationError, match="missing projection"):
        _fresh_mixed_use_copy_source(default_storage, source["id"])


def test_mixed_use_copy_fresh_lookup_allows_valid_pair_with_unrelated_orphan(
    default_storage,
) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    valid = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Valid source",
    )
    orphan = default_storage.create_mixed_use_expense(
        txn_date="2026-09-04",
        total_expense="200",
        business_use_percentage="50",
        account_id=account["id"],
        category_id=category["id"],
        allocation_rationale="Incomplete source",
    )
    worksheet = default_storage._worksheet("Transactions")
    id_column = worksheet.rows[0].index("id")
    worksheet.rows = [
        row
        for row in worksheet.rows
        if row[id_column] != orphan["linked_transaction_id"]
    ]
    default_storage._invalidate("Transactions")

    fresh = _fresh_mixed_use_copy_source(default_storage, valid["id"])

    assert fresh["id"] == valid["id"]
    assert fresh["linked_transaction_id"] == valid["linked_transaction_id"]


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
            "Recurring expenses",
            "Payees & Tags",
            "Payees",
            "Tags",
        ]
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Category").set_value(category["id"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Total Expense").set_value("100.00").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Business Use %").set_value("25").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Account").set_value(account["id"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Payee / customer").set_value(payee["id"]).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "multiselect", "Tags").set_value([tag["id"]]).run()
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
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        tab = _mixed_tab(app)
        assert _tab_field(tab, "text_input", "Total Expense").value == "100.00"
        _tab_field(tab, "text_input", "Business Use %").set_value("50").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Save changes").click().run()
        updated = default_storage.get_mixed_use_expense(source["id"])
        assert updated["id"] == source["id"]
        assert updated["linked_transaction_id"] == projection["id"]
        assert updated["allocated_amount"] == "50.00"

        # A fresh render after the confirmed edit starts in Add mode. Deletion
        # remains source-aware and is exercised by the storage/API coverage.
        assert any("Repeat this mixed-use Expense" in item.label for item in _mixed_tab(app).checkbox)


def test_mixed_use_app_test_recurring_create_creates_source_projection_pair(default_storage) -> None:
    default_storage.create_account("Recurring Mixed Checking", "Bank")
    default_storage.create_category("Recurring Mixed Office", "Expense")

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Total Expense").set_value("100.00").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Business Use %").set_value("25").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_area", "Allocation Rationale (required)").set_value("Recurring workspace").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "checkbox", "Repeat this mixed-use Expense").set_value(True).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Schedule name").set_value("Recurring workspace").run()
        _tab_field(tab, "button", "Save mixed-use expense").click().run()

        reset_tab = _mixed_tab(app)
        assert _tab_field(
            reset_tab, "checkbox", "Repeat this mixed-use Expense"
        ).value is False

    schedules = default_storage.list_recurring_schedules()
    sources = default_storage.list_mixed_use_expenses()
    projections = default_storage.list_transactions()
    assert len(schedules) == len(sources) == len(projections) == 1
    assert sources[0]["recurring_schedule_id"] == schedules[0]["id"]
    assert projections[0]["id"] == sources[0]["linked_transaction_id"]
    assert projections[0]["recurring_schedule_id"] == schedules[0]["id"]


def test_mixed_use_edit_can_create_schedule_from_existing_source(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03", total_expense="100",
        business_use_percentage="25", account_id=account["id"],
        category_id=category["id"], allocation_rationale="Measured use",
    )

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        tab = _mixed_tab(app)
        _tab_field(tab, "checkbox", "Repeat this mixed-use Expense").set_value(True).run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Schedule name").set_value("Monthly workspace").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Total Expense").set_value("120").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Save changes").click().run()

    schedules = default_storage.list_recurring_schedules()
    sources = default_storage.list_mixed_use_expenses()
    projections = default_storage.list_transactions()
    assert len(schedules) == len(sources) == len(projections) == 1
    assert sources[0]["id"] == source["id"]
    assert sources[0]["total_expense"] == "120.00"
    assert sources[0]["recurring_schedule_id"] == schedules[0]["id"]
    assert projections[0]["recurring_schedule_id"] == schedules[0]["id"]


def test_mixed_use_table_target_switch_and_delete_are_source_scoped(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item for item in default_storage.list_categories() if item["kind"] == "Expense"
    )
    first = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03", total_expense="100", business_use_percentage="25",
        account_id=account["id"], category_id=category["id"],
        allocation_rationale="First source",
    )
    second = default_storage.create_mixed_use_expense(
        txn_date="2026-09-04", total_expense="200", business_use_percentage="50",
        account_id=account["id"], category_id=category["id"],
        allocation_rationale="Second source",
    )

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = first["id"]
        app.run()
        tab = _mixed_tab(app)
        assert _tab_field(tab, "text_input", "Total Expense").value == "100.00"

        app.session_state["mixed_use_selected_source_id_test"] = second["id"]
        app.run()
        tab = _mixed_tab(app)
        assert _tab_field(tab, "text_input", "Total Expense").value == "200.00"
        _tab_field(tab, "checkbox", "I understand this deletion is permanent").set_value(True)
        tab = _mixed_tab(app)
        _tab_field(tab, "button", "Permanently delete").click().run()

    assert [item["id"] for item in default_storage.list_mixed_use_expenses()] == [
        first["id"]
    ]
    assert [item["id"] for item in default_storage.list_transactions()] == [
        first["linked_transaction_id"]
    ]


def test_mixed_use_copy_cancel_and_save_create_new_pair_without_receipts(
    default_storage,
) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=account["id"],
        category_id=category["id"],
        description="Original memo",
        allocation_rationale="Measured use",
    )
    original = default_storage.get_mixed_use_expense(source["id"])

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        tab = _mixed_tab(app)
        by_label(tab.button, "Copy mixed-use expense").click().run()
        tab = _mixed_tab(app)
        assert not tab.file_uploader
        assert _tab_field(tab, "date_input", "Date").value == date(2026, 9, 3)
        assert _tab_field(tab, "text_input", "Description / memo").value == (
            f"Original memo. Copy From {source['id']}"
        )
        by_label(tab.button, "Cancel copy").click().run()
        assert app.session_state["mixed_use_selected_source_id_test"] == source["id"]
        assert default_storage.get_mixed_use_expense(source["id"]) == original

        by_label(_mixed_tab(app).button, "Copy mixed-use expense").click().run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Description / memo").set_value(
            "Custom memo. Copy From stale-source. Copy From older-source"
        ).run()
        tab = _mixed_tab(app)
        assert any(
            str(item.value).startswith(f"Description: Custom memo. Copy From {source['id']}")
            for item in tab.caption
        )
        _tab_field(tab, "text_input", "Total Expense").set_value("240").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_input", "Business Use %").set_value("50").run()
        tab = _mixed_tab(app)
        _tab_field(tab, "text_area", "Allocation Rationale (required)").set_value(
            "Updated rationale"
        ).run()
        tab = _mixed_tab(app)
        by_label(tab.button, "Save copied mixed-use expense").click().run()

    copied = next(
        item
        for item in default_storage.list_mixed_use_expenses()
        if item["id"] != source["id"]
    )
    projection = next(
        item
        for item in default_storage.list_transactions()
        if item["id"] != source["linked_transaction_id"]
    )
    assert copied["linked_transaction_id"] == projection["id"]
    assert copied["id"] != source["id"]
    assert copied["linked_transaction_id"] != source["linked_transaction_id"]
    assert copied["description"] == f"Custom memo. Copy From {source['id']}"
    assert copied["total_expense"] == "240.00"
    assert copied["allocated_amount"] == "120.00"
    assert copied["receipt_references"] == "[]"
    assert default_storage.get_mixed_use_expense(source["id"]) == original


def test_mixed_use_copy_requires_active_account_before_save(default_storage) -> None:
    source_account = next(
        item for item in default_storage.list_accounts() if item["active"]
    )
    replacement = default_storage.create_account("Replacement Checking", "Bank")
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=source_account["id"],
        category_id=category["id"],
        description="Original memo",
        allocation_rationale="Measured use",
    )
    default_storage.deactivate_account(source_account["id"])

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        by_label(_mixed_tab(app).button, "Copy mixed-use expense").click().run()

        tab = _mixed_tab(app)
        account_selector = _tab_field(tab, "selectbox", "Account")
        assert source_account["id"] not in account_selector.options
        assert "Replacement Checking" in account_selector.options
        assert account_selector.value is None
        by_label(tab.button, "Save copied mixed-use expense").click().run()
        assert len(default_storage.list_mixed_use_expenses()) == 1
        assert any("Choose an active account" in str(item.value) for item in app.error)

        tab = _mixed_tab(app)
        _tab_field(tab, "selectbox", "Account").set_value(replacement["id"]).run()
        by_label(_mixed_tab(app).button, "Save copied mixed-use expense").click().run()

    copied = next(
        item
        for item in default_storage.list_mixed_use_expenses()
        if item["id"] != source["id"]
    )
    assert copied["account_id"] == replacement["id"]


def test_mixed_use_copy_cancel_remains_available_without_active_account(
    default_storage,
) -> None:
    source_account = next(
        item for item in default_storage.list_accounts() if item["active"]
    )
    category = next(
        item
        for item in default_storage.list_categories()
        if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="25",
        account_id=source_account["id"],
        category_id=category["id"],
        allocation_rationale="Measured use",
    )
    for account in default_storage.list_accounts():
        if account["active"]:
            default_storage.deactivate_account(account["id"])
    original_sources = default_storage.list_mixed_use_expenses()
    original_transactions = default_storage.list_transactions()

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        by_label(_mixed_tab(app).button, "Copy mixed-use expense").click().run()

        tab = _mixed_tab(app)
        assert by_label(tab.button, "Cancel copy")
        by_label(tab.button, "Cancel copy").click().run()
        assert app.session_state["mixed_use_selected_source_id_test"] == source["id"]

    assert default_storage.list_mixed_use_expenses() == original_sources
    assert default_storage.list_transactions() == original_transactions


def test_mixed_use_selection_clears_after_revision_change(default_storage) -> None:
    account = next(item for item in default_storage.list_accounts() if item["active"])
    category = next(
        item for item in default_storage.list_categories() if item["kind"] == "Expense"
    )
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03", total_expense="100", business_use_percentage="25",
        account_id=account["id"], category_id=category["id"],
        allocation_rationale="Revision source",
    )
    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        assert app.session_state["mixed_use_selected_source_id_test"] == source["id"]
        app.session_state["workbook_data_revision"] = 1
        app.run()
        assert app.session_state["mixed_use_selected_source_id_test"] == ""


def test_mixed_use_app_test_exposes_source_only_state_for_inspection(default_storage) -> None:
    source = default_storage.create_mixed_use_expense(
        txn_date="2026-09-03",
        total_expense="100",
        business_use_percentage="50",
        account_id=next(item for item in default_storage.list_accounts() if item["active"])["id"],
        category_id=next(item for item in default_storage.list_categories() if item["kind"] == "Expense")["id"],
        allocation_rationale="Measured use",
    )
    transaction_sheet = default_storage._worksheet("Transactions")
    transaction_sheet.rows.pop(1)
    default_storage._invalidate("Transactions")

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state["mixed_use_selected_source_id_test"] = source["id"]
        app.run()
        assert any(
            "inspection only" in str(item.value).lower()
            and "mixed-use expenses" in str(item.value).lower()
            and "ledger" in str(item.value).lower()
            for item in (*app.warning, *app.info)
        )
        tab = _mixed_tab(app)
        save_button = _tab_field(tab, "button", "Save changes")
        assert save_button.disabled is True
        assert not any(
            item.label == "Repair ledger projection" for item in tab.button
        )
        assert not any(
            item.label == "Permanently delete" for item in tab.button
        )

    assert default_storage.list_transactions() == []
    assert default_storage.list_mixed_use_expense_sources()[0]["id"] == source["id"]


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
        app.session_state[receipt_creation_workflow_key("test")] = transaction["id"]
        app.session_state[receipt_editor_workflow_key("test", transaction["id"])] = (
            new_receipt_creation_workflow(
                transaction["id"],
                [],
                spreadsheet_id="test-sheet",
                mixed_use_source_id=source["id"],
            )
        )
        app.run()
        assert receipt_creation_workflow_key("test") not in app.session_state
        assert any("source and projection no longer exist" in str(item.value) for item in app.warning)


def test_mixed_use_app_test_ignores_ordinary_receipt_recovery(default_storage) -> None:
    transaction = default_storage.create_transaction(
        txn_date="2026-09-03",
        kind="Expense",
        amount="10.00",
        account_id=next(
            item for item in default_storage.list_accounts() if item["active"]
        )["id"],
        category_id=next(
            item
            for item in default_storage.list_categories()
            if item["kind"] == "Expense"
        )["id"],
    )

    with authenticated_app(default_storage) as app:
        navigate_to(app, "Transactions")
        app.session_state[receipt_creation_workflow_key("test")] = transaction["id"]
        app.session_state[receipt_editor_workflow_key("test", transaction["id"])] = (
            new_receipt_creation_workflow(
                transaction["id"],
                [],
                spreadsheet_id="test-sheet",
            )
        )
        app.run()

        assert receipt_creation_workflow_key("test") in app.session_state
        assert not any(
            "source and projection no longer exist" in str(item.value)
            for item in app.warning
        )


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
