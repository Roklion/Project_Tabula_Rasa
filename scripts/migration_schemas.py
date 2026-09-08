"""Historical workbook layouts used only by explicit migration commands."""

from __future__ import annotations


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

LEGACY_TAGS_WORKBOOK_HEADERS = {
    **PRE_MIXED_USE_WORKSHEET_HEADERS,
    "Tags": ("id", "name", "active", "created_at"),
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
    "LEGACY_TAGS_WORKBOOK_HEADERS",
    "PRE_MIXED_USE_WORKSHEET_HEADERS",
    "PRE_PAYEE_WORKSHEET_HEADERS",
    "VERSION_3_WORKSHEET_HEADERS",
    "VERSION_5_WORKSHEET_HEADERS",
    "VERSION_6_WORKSHEET_HEADERS",
    "VERSION_7_WORKSHEET_HEADERS",
]
