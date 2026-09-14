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

# v10 was the last schema before recurring Expense schedules.  Keep this
# explicit snapshot for the one-time workbook upgrader; runtime must accept
# only the current layout.
VERSION_10_WORKSHEET_HEADERS = {
    title: tuple(
        header for header in headers
        if header not in {"recurring_schedule_id", "recurring_scheduled_date", "recurring_occurrence_type"}
    )
    for title, headers in {
        **{title: headers for title, headers in VERSION_7_WORKSHEET_HEADERS.items()},
        "Payees": ("id", "name", "active", "created_at"),
        "Tags": ("id", "name", "active", "created_at"),
        "Transactions": (
            "id", "txn_date", "kind", "amount", "account_id", "to_account_id",
            "category_id", "payee_id", "description", "reference",
            "receipt_references", "created_at", "source_type", "source_id", "tag_ids",
        ),
        "Mileage": (
            "id", "trip_date", "miles", "vehicle", "start_location", "destination",
            "business_purpose", "notes", "created_at", "tag_ids",
        ),
        "MixedUseExpenses": (
            "id", "txn_date", "kind", "total_expense", "business_use_percentage",
            "allocated_amount", "account_id", "category_id", "payee_id", "description",
            "reference", "receipt_references", "allocation_rationale",
            "linked_transaction_id", "tag_ids", "created_at",
        ),
    }.items()
}

# v11 added recurring Expense schedules and was the last schema before the
# fixed-asset register. Keep the exact layout for explicit workbook and backup
# migration; runtime accepts only the current schema.
VERSION_11_WORKSHEET_HEADERS = {
    **VERSION_10_WORKSHEET_HEADERS,
    "Transactions": (
        "id", "txn_date", "kind", "amount", "account_id", "to_account_id",
        "category_id", "payee_id", "description", "reference",
        "receipt_references", "created_at", "source_type", "source_id", "tag_ids",
        "recurring_schedule_id", "recurring_scheduled_date",
        "recurring_source_kind", "recurring_occurrence_type",
    ),
    "MixedUseExpenses": (
        "id", "txn_date", "kind", "total_expense", "business_use_percentage",
        "allocated_amount", "account_id", "category_id", "payee_id", "description",
        "reference", "receipt_references", "allocation_rationale",
        "linked_transaction_id", "tag_ids", "recurring_schedule_id",
        "recurring_scheduled_date", "recurring_source_kind",
        "recurring_occurrence_type", "created_at",
    ),
    "RecurringSchedules": (
        "id", "name", "kind", "source_kind", "recurrence_unit",
        "recurrence_interval", "anchor_date", "start_date", "end_date",
        "status", "amount", "total_expense", "business_use_percentage",
        "account_id", "category_id", "payee_id", "description", "reference",
        "allocation_rationale", "tag_ids", "created_at", "updated_at",
        "attention_code", "attention_at",
    ),
}


__all__ = [
    "LEGACY_TAGS_WORKBOOK_HEADERS",
    "PRE_MIXED_USE_WORKSHEET_HEADERS",
    "PRE_PAYEE_WORKSHEET_HEADERS",
    "VERSION_3_WORKSHEET_HEADERS",
    "VERSION_5_WORKSHEET_HEADERS",
    "VERSION_6_WORKSHEET_HEADERS",
    "VERSION_7_WORKSHEET_HEADERS",
    "VERSION_10_WORKSHEET_HEADERS",
    "VERSION_11_WORKSHEET_HEADERS",
]
