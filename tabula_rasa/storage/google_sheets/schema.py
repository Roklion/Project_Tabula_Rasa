"""Worksheet schemas and domain constants shared by Sheets storage."""

from __future__ import annotations

# VERSION_* and legacy header definitions are migration-support schemas. They
# remain explicit here until the migration tooling can own them without making
# the current-format reader depend on a second package.
PRE_PAYEE_WORKSHEET_HEADERS = {
    "Accounts": (
        "id",
        "name",
        "type",
        "classification",
        "opening_balance",
        "active",
        "created_at",
    ),
    "Categories": ("id", "name", "kind"),
    "Transactions": (
        "id",
        "txn_date",
        "kind",
        "amount",
        "account_id",
        "to_account_id",
        "category_id",
        "payee",
        "description",
        "reference",
        "receipt_references",
        "created_at",
    ),
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
    ),
}

VERSION_5_WORKSHEET_HEADERS = PRE_PAYEE_WORKSHEET_HEADERS

VERSION_6_WORKSHEET_HEADERS = {
    **PRE_PAYEE_WORKSHEET_HEADERS,
    "Accounts": (*PRE_PAYEE_WORKSHEET_HEADERS["Accounts"], "parent_id"),
    "Categories": (*PRE_PAYEE_WORKSHEET_HEADERS["Categories"], "parent_id"),
}

VERSION_7_WORKSHEET_HEADERS = {
    **VERSION_6_WORKSHEET_HEADERS,
    "Payees": ("id", "name", "active", "created_at"),
    "Transactions": tuple(
        "payee_id" if header == "payee" else header
        for header in VERSION_6_WORKSHEET_HEADERS["Transactions"]
    ),
}

PRE_MIXED_USE_WORKSHEET_HEADERS = VERSION_7_WORKSHEET_HEADERS

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
    **PRE_MIXED_USE_WORKSHEET_HEADERS,
    "Transactions": (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        "source_type",
        "source_id",
    ),
    "MixedUseExpenses": MIXED_USE_WORKSHEET_HEADERS,
}

WORKSHEET_HEADERS = {
    **WORKSHEET_HEADERS,
    "Tags": ("id", "name", "active", "created_at"),
    "Transactions": (
        *WORKSHEET_HEADERS["Transactions"],
        "tag_ids",
    ),
    "Mileage": (
        *WORKSHEET_HEADERS["Mileage"],
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

LEGACY_TAGS_WORKBOOK_HEADERS = {
    **PRE_MIXED_USE_WORKSHEET_HEADERS,
    "Tags": WORKSHEET_HEADERS["Tags"],
    "Transactions": (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Transactions"],
        "tag_ids",
    ),
    "Mileage": (
        *PRE_MIXED_USE_WORKSHEET_HEADERS["Mileage"],
        "tag_ids",
    ),
}

VERSION_3_WORKSHEET_HEADERS = {
    title: (
        tuple(header for header in headers if header != "receipt_references")
        if title == "Transactions"
        else headers
    )
    for title, headers in PRE_PAYEE_WORKSHEET_HEADERS.items()
}

__all__ = [
    "PRE_PAYEE_WORKSHEET_HEADERS",
    "VERSION_5_WORKSHEET_HEADERS",
    "VERSION_6_WORKSHEET_HEADERS",
    "VERSION_7_WORKSHEET_HEADERS",
    "PRE_MIXED_USE_WORKSHEET_HEADERS",
    "MIXED_USE_WORKSHEET_HEADERS",
    "WORKSHEET_HEADERS",
    "LEGACY_TAGS_WORKBOOK_HEADERS",
    "VERSION_3_WORKSHEET_HEADERS",
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
