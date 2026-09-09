from __future__ import annotations

from tabula_rasa.storage import GoogleSheetsStorage


def expense_inputs(storage: GoogleSheetsStorage) -> dict[str, str]:
    account = next(
        account
        for account in storage.list_accounts(active_only=False)
        if account["name"] == "Checking"
    )
    category = next(
        category
        for category in storage.list_categories()
        if category["name"] == "Office"
    )
    payee = storage.create_payee("Office vendor")
    return {
        "txn_date": "2026-09-01",
        "account_id": account["id"],
        "category_id": category["id"],
        "payee_id": payee["id"],
        "description": "Internet service",
        "reference": "INV-119",
    }
