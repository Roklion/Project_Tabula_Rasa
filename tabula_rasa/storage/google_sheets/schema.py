"""Frozen format-13 Sheets source contract; see docs/SHEETS_SOURCE_CONTRACT.md."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import StorageValidationError
from tabula_rasa.reference_data import (
    ACCOUNT_CLASSIFICATIONS,
    ACCOUNT_TYPES,
    FIXED_TYPE_CLASSIFICATIONS,
)

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
    "recurring_schedule_id",
    "recurring_scheduled_date",
    "recurring_source_kind",
    "recurring_occurrence_type",
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
        "recurring_schedule_id",
        "recurring_scheduled_date",
        "recurring_source_kind",
        "recurring_occurrence_type",
    ),
    "JournalEntries": (
        "id",
        "txn_date",
        "description",
        "created_at",
        "updated_at",
    ),
    "JournalPostings": (
        "id",
        "parent_entry_id",
        "position",
        "target_type",
        "target_id",
        "side",
        "amount",
        "payee_id",
        "description",
    ),
    "MixedUseExpenses": MIXED_USE_WORKSHEET_HEADERS,
    "RecurringSchedules": (
        "id",
        "name",
        "kind",
        "source_kind",
        "recurrence_unit",
        "recurrence_interval",
        "anchor_date",
        "start_date",
        "end_date",
        "status",
        "amount",
        "total_expense",
        "business_use_percentage",
        "account_id",
        "category_id",
        "payee_id",
        "description",
        "reference",
        "allocation_rationale",
        "tag_ids",
        "created_at",
        "updated_at",
        "attention_code",
        "attention_at",
    ),
    "Assets": (
        "id",
        "name",
        "asset_type",
        "notes",
        "acquisition_date",
        "depreciation_start_date",
        "cost_basis",
        "salvage_value",
        "useful_life_quarters",
        "depreciation_method",
        "depreciation_expense_account_id",
        "accumulated_depreciation_account_id",
        "payee_id",
        "reference",
        "tag_ids",
        "source_transaction_id",
        "retired_date",
        "status",
        "schedule_overrides",
        "created_at",
        "updated_at",
    ),
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

CATEGORY_KINDS = {"Income", "Expense"}

TRANSACTION_KINDS = {"Income", "Expense", "Transfer"}

WORKBOOK_FORMAT_VERSION = 13
BACKUP_FORMAT_VERSION = WORKBOOK_FORMAT_VERSION


def validate_worksheet_headers(title: str, headers: Sequence[str]) -> None:
    """Require exactly the frozen fields, preserving name-based column order."""
    required = set(WORKSHEET_HEADERS[title])
    if not headers:
        raise StorageValidationError(
            f"{title} header row is empty; format 13 is required"
        )
    if any(not header for header in headers):
        raise StorageValidationError(
            f"{title} has a blank header; format 13 is required"
        )
    if len(headers) != len(set(headers)):
        raise StorageValidationError(
            f"{title} has duplicate headers; format 13 is required"
        )
    missing = sorted(required - set(headers))
    if missing:
        raise StorageValidationError(
            f"{title} is missing headers: {', '.join(missing)}. "
            "Only the frozen format-13 Sheets schema is supported; "
            "preserve this workbook and select a supported workbook."
        )
    if set(headers) != required:
        raise StorageValidationError(
            f"{title} has unsupported headers. Only the frozen format-13 "
            "Sheets schema is supported; preserve this workbook and select "
            "a supported workbook."
        )


def validate_workbook_headers(headers: Mapping[str, Sequence[str]]) -> None:
    """Read-only schema preflight shared with future migration extraction."""
    missing = sorted(set(WORKSHEET_HEADERS) - set(headers))
    if missing:
        raise StorageValidationError(
            "Workbook is missing worksheets: "
            + ", ".join(missing)
            + ". Only the frozen format-13 Sheets schema is supported; "
            "preserve this workbook and select a supported workbook."
        )
    for title in WORKSHEET_HEADERS:
        validate_worksheet_headers(title, headers[title])


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
    "WORKBOOK_FORMAT_VERSION",
    "validate_worksheet_headers",
    "validate_workbook_headers",
    "SHEETS_SCOPE",
    "SHEETS_READONLY_SCOPE",
    "DEFAULT_ACCOUNTS",
    "DEFAULT_CATEGORIES",
]
