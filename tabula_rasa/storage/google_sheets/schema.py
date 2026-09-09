"""Worksheet schemas and domain constants shared by Sheets storage."""

from __future__ import annotations

MIXED_USE_WORKSHEET_HEADERS = (
    "id",
    "txn_date",
    "kind",
    "total_expense",
    "business_use_percentage",
    "allocated_amount",
    "account_id",
    "category_id",
    "payee_id",
    "description",
    "reference",
    "receipt_references",
    "allocation_rationale",
    "linked_transaction_id",
    "tag_ids",
    "created_at",
)

WORKSHEET_HEADERS = {
    "Accounts": (
        "id",
        "name",
        "type",
        "classification",
        "opening_balance",
        "active",
        "created_at",
        "parent_id",
    ),
    "Categories": ("id", "name", "kind", "parent_id"),
    "Payees": ("id", "name", "active", "created_at"),
    "Transactions": (
        "id",
        "txn_date",
        "kind",
        "amount",
        "account_id",
        "to_account_id",
        "category_id",
        "payee_id",
        "description",
        "reference",
        "receipt_references",
        "created_at",
        "source_type",
        "source_id",
        "tag_ids",
    ),
    "MixedUseExpenses": MIXED_USE_WORKSHEET_HEADERS,
    "Tags": ("id", "name", "active", "created_at"),
    "Mileage": (
        "id",
        "trip_date",
        "miles",
        "vehicle",
        "start_location",
        "destination",
        "business_purpose",
        "notes",
        "created_at",
        "tag_ids",
    ),
}

ACCOUNT_TYPES = {
    "Bank",
    "Cash",
    "Credit card",
    "Short-term debt",
    "Equity",
    "Other",
}

ACCOUNT_CLASSIFICATIONS = {"Asset", "Liability", "Equity"}

FIXED_TYPE_CLASSIFICATIONS = {
    "Bank": "Asset",
    "Cash": "Asset",
    "Credit card": "Liability",
    "Short-term debt": "Liability",
    "Equity": "Equity",
}

CATEGORY_KINDS = {"Income", "Expense"}

TRANSACTION_KINDS = {"Income", "Expense", "Transfer"}

BACKUP_FORMAT_VERSION = 10

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"

DEFAULT_ACCOUNTS = (("Checking", "Bank"), ("Cash", "Cash"))

DEFAULT_CATEGORIES = {
    "Income": ("Sales", "Services", "Interest", "Other income"),
    "Expense": (
        "Advertising",
        "Bank fees",
        "Insurance",
        "Meals",
        "Office",
        "Professional fees",
        "Rent",
        "Software",
        "Supplies",
        "Travel",
        "Utilities",
        "Other expense",
    ),
}

__all__ = [
    "MIXED_USE_WORKSHEET_HEADERS",
    "WORKSHEET_HEADERS",
    "ACCOUNT_TYPES",
    "ACCOUNT_CLASSIFICATIONS",
    "FIXED_TYPE_CLASSIFICATIONS",
    "CATEGORY_KINDS",
    "TRANSACTION_KINDS",
    "BACKUP_FORMAT_VERSION",
    "SHEETS_SCOPE",
    "SHEETS_READONLY_SCOPE",
    "DEFAULT_ACCOUNTS",
    "DEFAULT_CATEGORIES",
]
