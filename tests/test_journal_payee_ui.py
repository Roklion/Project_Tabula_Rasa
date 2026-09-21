from __future__ import annotations

from tabula_rasa.page_renderers.transactions.payees_tags import (
    _payee_reference_counts,
)
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_label, navigate_to
from tests.fakes import FakeWorkbook


def test_payee_reference_counts_preserve_simple_counts_and_count_one_per_journal() -> None:
    payee_id = "payee-1"
    simple = [{"payee_id": payee_id}]
    mixed = [{"payee_id": payee_id}]
    schedules = [{"payee_id": payee_id}]
    journals = [
        {
            "postings": [
                {"payee_id": payee_id},
                {"payee_id": payee_id},
                {"payee_id": "payee-2"},
            ]
        }
    ]

    assert _payee_reference_counts(simple, mixed, schedules) == {payee_id: 3}
    assert _payee_reference_counts(simple, mixed, schedules, journals) == {
        payee_id: 4,
        "payee-2": 1,
    }


def test_journal_only_payee_is_shown_as_referenced_and_cannot_be_removed() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Office", "Expense")
    payee = storage.create_payee("Journal vendor")
    storage.create_journal_entry(
        entry_id="journal-payee-only",
        txn_date="2026-09-20",
        description="Journal purchase",
        postings=[
            {
                "id": "journal-line-debit",
                "target_type": "category",
                "target_id": category["id"],
                "side": "Debit",
                "amount": "25.00",
                "payee_id": payee["id"],
                "description": "Office supplies",
            },
            {
                "id": "journal-line-credit",
                "target_type": "account",
                "target_id": account["id"],
                "side": "Credit",
                "amount": "25.00",
                "payee_id": payee["id"],
                "description": "Cash paid",
            },
        ],
    )

    with authenticated_app(storage) as app:
        navigate_to(app, "Transactions")
        by_label(app.selectbox, "Payee to remove").set_value(payee["id"]).run()

        assert any("1 references" in str(item.value) for item in app.info)
        assert by_label(app.button, "Permanently remove payee").disabled
        assert next(
            item
            for item in app.checkbox
            if "I understand payee" in item.label
            and "permanently removed" in item.label
        ).disabled
