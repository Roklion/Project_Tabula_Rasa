"""Sheets adapter integration, profile isolation, recovery and UI service routing."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock, patch

import pytest

from tabula_rasa.composition import create_sheets_application
from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.storage import GoogleSheetsStorage, StorageUnavailableError
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook
from tests.accounting_service_fakes import Transactions, Journals


def application(storage, key="test"):
    with patch.object(GoogleSheetsStorage, "from_secrets", return_value=storage):
        return create_sheets_application(
            key, {"business_profiles": {key: profile_config()}}
        )


def seed(application):
    account = application.services.accounts.create("Checking", "Bank")
    category = application.workbook_admin.create_category("Office", "Expense")
    return dict(
        txn_date="2026-10-04",
        kind="Expense",
        amount="10",
        account_id=account["id"],
        category_id=category["id"],
    )


def lines(payload):
    return [
        dict(
            id="debit",
            target_type="category",
            target_id=payload["category_id"],
            debit="10",
        ),
        dict(
            id="credit",
            target_type="account",
            target_id=payload["account_id"],
            credit="10",
        ),
    ]


def test_composition_keeps_transactions_journals_and_inline_references_profile_local():
    applications = {
        key: application(
            GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None), key
        )
        for key in ("north", "south")
    }
    payloads = {key: seed(app) for key, app in applications.items()}
    north, south = (applications[key] for key in ("north", "south"))
    created = north.services.transactions.create(
        transaction_id="same-id",
        **payloads["north"],
        new_payee_name="North vendor",
        new_tag_name="North tag",
    )
    assert south.services.transactions.list() == []
    assert south.services.payees.list() == south.services.tags.list() == []
    with pytest.raises(StorageValidationError, match="account does not exist"):
        south.services.transactions.create(**payloads["north"])
    with pytest.raises(StorageValidationError, match="does not exist"):
        south.services.transactions.create(
            **payloads["south"], payee_id=created["payee_id"]
        )
    south.services.transactions.create(transaction_id="same-id", **payloads["south"])
    north.services.transactions.update(
        "same-id", expected=created, description="North only"
    )
    assert south.services.transactions.list()[0]["description"] == ""
    entry = north.services.journals.create(
        entry_id="same-journal",
        txn_date="2026-10-04",
        postings=lines(payloads["north"]),
    )
    with pytest.raises(StorageValidationError, match="does not exist"):
        south.services.journals.create(
            entry_id="bad", txn_date="2026-10-04", postings=lines(payloads["north"])
        )
    south.services.journals.create(
        entry_id="same-journal",
        txn_date="2026-10-04",
        postings=lines(payloads["south"]),
    )
    north.services.journals.delete("same-journal", expected=entry)
    assert (
        north.services.journals.list() == []
        and len(south.services.journals.list()) == 1
    )


def test_expected_transaction_is_checked_fresh_before_inline_reference_writes(storage):
    app = application(storage)
    service = app.services.transactions
    record = service.create(transaction_id="stable", **seed(app))
    visible = service.list()[0]
    # A separate client changes the amount while the current client's cache is old.
    headers = storage._workbook.sheets["Transactions"].rows[0]
    storage._workbook.sheets["Transactions"].rows[1][headers.index("amount")] = "20.00"
    with pytest.raises(StorageConflictError, match="changed"):
        service.update("stable", expected=visible, new_payee_name="Must not create")
    with pytest.raises(StorageConflictError, match="changed"):
        service.delete("stable", expected=record)
    assert app.services.payees.list() == []
    fresh = service.list(fresh=True)[0]
    updated = service.update(
        "stable", expected=fresh, description="Fresh", new_tag_name="Tax"
    )
    assert (
        updated["amount"] == "20.00" and updated["created_at"] == record["created_at"]
    )
    assert service.list(fresh=True)[0]["tag_ids"] == [app.services.tags.list()[0]["id"]]


def test_transaction_service_confirms_lost_response_once_without_duplicate(storage):
    app = application(storage)
    payload = seed(app)
    worksheet = storage._workbook.sheets["Transactions"]
    original = worksheet.append_row

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("Synthetic response loss")

    worksheet.append_row = Mock(side_effect=lost_response)
    created = app.services.transactions.create(
        transaction_id="stable", **payload, new_payee_name="Vendor", new_tag_name="Tax"
    )
    assert created["id"] == "stable" and worksheet.append_row.call_count == 1
    assert len(app.services.transactions.list(fresh=True)) == 1
    assert len(app.services.payees.list()) == len(app.services.tags.list()) == 1


@pytest.mark.parametrize("committed", [True, False])
def test_journal_adapter_retains_one_batch_and_bounded_uncertain_readback(
    storage, committed
):
    app = application(storage)
    payload = seed(app)
    workbook = storage._workbook
    original = workbook.batch_update

    def uncertain_batch(body):
        if committed:
            original(body)
        raise OSError("Synthetic response loss")

    workbook.batch_update = Mock(side_effect=uncertain_batch)
    if committed:
        record = app.services.journals.create(
            entry_id="stable", txn_date="2026-10-04", postings=lines(payload)
        )
        assert record["total_debits"] == record["total_credits"] == "10.00"
        assert len(app.services.journals.list()) == 1
    else:
        with pytest.raises(StorageUnavailableError):
            app.services.journals.create(
                entry_id="stable", txn_date="2026-10-04", postings=lines(payload)
            )
        assert app.services.journals.list() == []
    assert workbook.batch_update.call_count == 1


def test_journal_adapter_fresh_stale_edit_and_delete_preserve_the_posting_set(storage):
    app = application(storage)
    payload = seed(app)
    service = app.services.journals
    entry = service.create(
        entry_id="journal", txn_date="2026-10-04", postings=lines(payload)
    )
    visible = service.get("journal")
    changed = service.update("journal", expected=entry, description="Revised")
    snapshot = deepcopy(storage._workbook.sheets["JournalPostings"].rows)
    for operation in (
        lambda: service.update("journal", expected=visible, postings=lines(payload)),
        lambda: service.delete("journal", expected=visible),
    ):
        with pytest.raises(StorageConflictError):
            operation()
    assert storage._workbook.sheets["JournalPostings"].rows == snapshot
    service.delete("journal", expected=changed)
    assert service.list() == []


def test_new_entry_ui_saves_through_a_persistence_free_transaction_service(storage):
    app_graph = application(storage)
    payload = seed(app_graph)
    repository = Transactions()
    repository.accounts = {
        payload["account_id"]: {"id": payload["account_id"], "active": True}
    }
    repository.categories = {
        payload["category_id"]: {"id": payload["category_id"], "kind": "Expense"}
    }
    graph = replace(
        app_graph,
        services=replace(app_graph.services, transactions=repository.service()),
    )
    with (
        patch("tabula_rasa.composition.create_sheets_application", return_value=graph),
        patch.object(
            storage,
            "create_transaction",
            side_effect=AssertionError("UI called storage directly"),
        ),
    ):
        with authenticated_app(storage) as app:
            navigate_to(app, "Transactions")
            by_label(app.number_input, "Amount").set_value(25).run()
            by_label(app.button, "Save transaction").click().run()
            assert not app.exception
    assert (
        len(repository.records) == 1
        and next(iter(repository.records.values()))["amount"] == "25.00"
    )


def test_new_entry_ui_saves_through_a_persistence_free_journal_service(storage):
    app_graph = application(storage)
    payload = seed(app_graph)
    references = Transactions()
    references.accounts = {
        payload["account_id"]: {"id": payload["account_id"], "active": True}
    }
    references.categories = {
        payload["category_id"]: {"id": payload["category_id"], "kind": "Expense"}
    }
    journals = Journals(references)
    journal_service = journals.service()
    graph = replace(
        app_graph, services=replace(app_graph.services, journals=journal_service)
    )
    with (
        patch("tabula_rasa.composition.create_sheets_application", return_value=graph),
        patch.object(
            storage,
            "create_journal_entry",
            side_effect=AssertionError("UI called storage directly"),
        ),
    ):
        with authenticated_app(storage) as app:
            navigate_to(app, "Transactions")
            by_label(app.segmented_control, "Entry Type").set_value(
                "Multi-line Journal"
            ).run()
            fields = [
                item
                for item in app.selectbox
                if item.label == "Account"
                and str(item.key).startswith("journal_create_")
            ]
            fields[0].set_value(f"account:{payload['account_id']}").run()
            fields = [
                item
                for item in app.selectbox
                if item.label == "Account"
                and str(item.key).startswith("journal_create_")
            ]
            fields[1].set_value(f"category:{payload['category_id']}").run()
            [item for item in app.number_input if item.label == "Debit"][0].set_value(
                40
            ).run()
            [item for item in app.number_input if item.label == "Credit"][1].set_value(
                40
            ).run()
            by_label(app.button, "Save journal entry").click().run()
            assert not app.exception
    assert len(journals.records) == 1
    assert [
        line["amount"] for line in next(iter(journals.records.values()))["postings"]
    ] == ["40.00", "40.00"]
