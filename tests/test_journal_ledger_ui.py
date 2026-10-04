from datetime import date

from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook


def journal_storage():
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    cash = storage.create_account("Checking", "Bank")
    office = storage.create_category("Office", "Expense")
    meals = storage.create_category("Meals", "Expense")
    payee = storage.create_payee("Cafe")
    entry = storage.create_journal_entry(
        entry_id="journal-one", txn_date=date.today(), description="Split purchase",
        postings=[
            {"id": "line-office", "target_type": "category", "target_id": office["id"], "side": "Debit", "amount": "100", "description": "Pens"},
            {"id": "line-meals", "target_type": "category", "target_id": meals["id"], "side": "Debit", "amount": "50", "payee_id": payee["id"], "description": "Lunch"},
            {"id": "line-cash", "target_type": "account", "target_id": cash["id"], "side": "Credit", "amount": "150"},
        ],
    )
    simple = storage.create_transaction(txn_date=date.today(), kind="Expense", amount="9", account_id=cash["id"], category_id=office["id"])
    return storage, entry, simple


def test_real_ledger_search_keeps_all_lines_and_routes_journal_editor():
    storage, entry, _ = journal_storage()
    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        assert not app.exception
        by_label(app.text_input, "Search transactions").set_value("Cafe").run()
        assert not app.exception
        frame = app.dataframe[0].value
        assert len(frame) == 4
        assert frame["Type"].tolist() == ["Journal", "↳ Posting", "↳ Posting", "↳ Posting"]
        assert by_label(app.selectbox, "Transaction to edit").value == "journal:journal-one"
        assert any(item.label == "Edit journal entry" for item in app.expander)
        assert by_label(app.button, "Copy transaction").disabled
        assert len(app.dataframe[0].selection_mode) == 2
        assert storage.get_journal_entry(entry["id"])["postings"] == entry["postings"]


def test_journal_bulk_selection_has_export_but_cannot_mutate_simple_subset():
    storage, entry, simple = journal_storage()
    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.segmented_control, "Ledger mode").set_value("Bulk").run()
        app.session_state["transaction_bulk_selected_ids_test"] = ("journal:journal-one", simple["id"])
        app.run()
        assert not app.exception
        assert by_label(app.button, "Copy transaction").disabled
        assert not any(item.label in {"Apply changes", "Permanently delete selected"} for item in app.button)
        assert any("Switch to Edit" in str(item.value) for item in app.info)
    assert len(storage.list_transactions()) == 1
    assert storage.get_journal_entry(entry["id"])


def test_journal_delete_from_unified_ledger_removes_complete_entry_only():
    storage, entry, simple = journal_storage()
    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.selectbox, "Transaction to edit").set_value("journal:journal-one").run()
        by_label(app.checkbox, "I understand this complete journal entry will be permanently deleted").check().run()
        by_label(app.button, "Permanently delete").click().run()
        assert not app.exception
    assert not storage.list_journal_entries()
    assert [row["id"] for row in storage.list_transactions()] == [simple["id"]]


def test_journal_edit_saves_whole_entry_and_preserves_posting_identity():
    storage, entry, simple = journal_storage()
    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.selectbox, "Transaction to edit").set_value("journal:journal-one").run()
        memo = next(item for item in app.text_input if item.label == "Description / memo" and "journal_edit" in str(item.key))
        memo.set_value("Updated split purchase").run()
        by_label(app.button, "Save changes").click().run()
        assert not app.exception
    updated = storage.get_journal_entry(entry["id"])
    assert updated["description"] == "Updated split purchase"
    assert updated["postings"] == entry["postings"]
    assert [row["id"] for row in storage.list_transactions()] == [simple["id"]]


def test_deleted_entries_between_query_and_edit_snapshot_are_not_offered(monkeypatch):
    from tabula_rasa.application.reporting import ReportingService

    storage, journal, simple = journal_storage()
    original_query = ReportingService.query_ledger

    def query_then_delete(service, *args, **kwargs):
        result = original_query(service, *args, **kwargs)
        # Model another session deleting entries and invalidating the shared
        # cache after a query returns but before mutation baselines are read.
        storage.delete_transaction(simple["id"])
        storage.delete_journal_entry(journal["id"], expected_entry=journal)
        return result

    with authenticated_app(storage) as app:
        monkeypatch.setattr(ReportingService, "query_ledger", query_then_delete)
        navigate_to(app, "Transactions")
        assert not app.exception
        assert not any(item.label == "Transaction to edit" for item in app.selectbox)
    assert storage.list_transactions() == []
    assert storage.list_journal_entries() == []
