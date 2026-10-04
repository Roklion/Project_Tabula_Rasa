"""Shared transaction rules, independent of UI and persistence providers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from tabula_rasa.errors import StorageValidationError
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE
from tabula_rasa.reference_data import (
    as_bool as _as_bool,
    clean_text as _clean_text,
    normalize_tag_ids as _normalize_tag_ids,
)
from tabula_rasa.ledger_validation import (
    iso_date as _iso_date,
    positive_amount as _positive_amount,
    decode_receipt_references,
)

TRANSACTION_KINDS = {"Income", "Expense", "Transfer"}

RECURRING_FIELDS = (
    "recurring_schedule_id",
    "recurring_scheduled_date",
    "recurring_source_kind",
    "recurring_occurrence_type",
)


@dataclass(frozen=True)
class TransactionReferences:
    """Fresh managed records from the repository's selected profile."""

    accounts: Mapping[str, Mapping[str, Any]]
    categories: Mapping[str, Mapping[str, Any]]
    payees: Mapping[str, Mapping[str, Any]]
    tags: Mapping[str, Mapping[str, Any]]


def validate_transaction_create(data: Mapping[str, Any]) -> None:
    if any(field in data for field in RECURRING_FIELDS):
        raise StorageValidationError(
            "Recurring provenance is created only by recurring expense APIs"
        )
    if data.get("source_type") or data.get("source_id"):
        reject_derived_transaction(data)


def validate_transaction_update(
    current: Mapping[str, Any], changes: Mapping[str, Any]
) -> None:
    if any(field in changes for field in RECURRING_FIELDS) and any(
        str(changes.get(field, current.get(field, "")) or "")
        != str(current.get(field, "") or "")
        for field in RECURRING_FIELDS
    ):
        raise StorageValidationError("Recurring provenance cannot be changed")


def utc_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def prepare_transaction(
    data: Mapping[str, Any],
    *,
    accounts: Mapping[str, Mapping[str, Any]],
    categories: Mapping[str, Mapping[str, Any]],
    payees: Mapping[str, Mapping[str, Any]],
    tags: Mapping[str, Mapping[str, Any]],
    create_payee: Callable[[str], Mapping[str, Any]],
    create_tag: Callable[[str], Mapping[str, Any]],
    transaction_id: str | None = None,
    created_at: str | None = None,
    original_transaction: Mapping[str, Any] | None = None,
    preserve_existing_payee: bool = False,
    allow_zero_amount: bool = False,
) -> dict[str, Any]:
    """Validate against fresh references, then resolve inline managed identities.

    Adapters call this same rule at their mutation boundary. Only the supplied
    reference services can create a payee/tag; this function performs no I/O.
    """
    payees, tags = dict(payees), dict(tags)
    kind = _clean_text(data.get("kind"), "Transaction kind", required=True).title()
    if kind not in TRANSACTION_KINDS:
        raise StorageValidationError("Unknown transaction kind")
    account_id = _clean_text(data.get("account_id"), "Account", required=True)
    if account_id not in accounts:
        raise StorageValidationError("Source account does not exist")
    original_account_id = (
        _clean_text(original_transaction.get("account_id"), "Account")
        if original_transaction is not None
        else None
    )
    if (
        not _as_bool(accounts[account_id]["active"])
        and account_id != original_account_id
    ):
        raise StorageValidationError("Source account is inactive")

    to_account_id = _clean_text(data.get("to_account_id"), "Destination account")
    category_id = _clean_text(data.get("category_id"), "Category")
    if kind == "Transfer":
        if to_account_id not in accounts:
            raise StorageValidationError("Destination account does not exist")
        original_to_account_id = (
            _clean_text(
                original_transaction.get("to_account_id"),
                "Destination account",
            )
            if original_transaction is not None
            else None
        )
        if (
            not _as_bool(accounts[to_account_id]["active"])
            and to_account_id != original_to_account_id
        ):
            raise StorageValidationError("Destination account is inactive")
        if to_account_id == account_id:
            raise StorageValidationError("Transfer accounts must be different")
        category_id = ""
    else:
        if to_account_id:
            raise StorageValidationError(
                "Only transfers can have a destination account"
            )
        if category_id not in categories:
            raise StorageValidationError("Category does not exist")
        if categories[category_id]["kind"] != kind:
            raise StorageValidationError(
                "Category kind does not match transaction kind"
            )

    txn_date = _iso_date(data.get("txn_date"))
    is_zero_amount = False
    if allow_zero_amount:
        try:
            is_zero_amount = Decimal(str(data.get("amount"))) == 0
        except (InvalidOperation, ValueError):
            is_zero_amount = False
    amount = "0.00" if is_zero_amount else _positive_amount(data.get("amount"))
    receipt_references = (
        decode_receipt_references(data.get("receipt_references", []))
        if transaction_id is None or data.get("receipt_references", "") != ""
        else ""
    )
    payee_id = _clean_text(data.get("payee_id"), "Payee")
    new_payee_name = _clean_text(data.get("new_payee_name"), "New payee")
    legacy_payee = _clean_text(data.get("payee"), "Payee")
    if legacy_payee:
        raise StorageValidationError("Transactions must reference a stored payee")
    if payee_id and new_payee_name:
        raise StorageValidationError("Choose an existing payee or add a new payee")
    tag_ids = _normalize_tag_ids(data.get("tag_ids", ""))
    original_tag_ids = (
        _normalize_tag_ids(original_transaction.get("tag_ids", ""))
        if original_transaction is not None
        else []
    )
    for tag_id in tag_ids:
        tag = tags.get(tag_id)
        if tag is None:
            raise StorageValidationError("Tag does not exist")
        if not _as_bool(tag["active"], "Tag active") and tag_id not in original_tag_ids:
            raise StorageValidationError("Tag is inactive")
    original_payee_id = (
        _clean_text(original_transaction.get("payee_id"), "Payee")
        if original_transaction is not None
        else None
    )
    if (
        preserve_existing_payee
        and original_payee_id
        and not payee_id
        and new_payee_name
    ):
        if original_payee_id not in payees:
            raise StorageValidationError("Payee does not exist")
        payee_id = original_payee_id
        new_payee_name = ""
    provenance = {}
    recurring_schedule_id = _clean_text(
        data.get("recurring_schedule_id"), "Recurring schedule ID"
    )
    recurring_scheduled_date = _clean_text(
        data.get("recurring_scheduled_date"), "Recurring scheduled date"
    )
    recurring_occurrence_type = _clean_text(
        data.get("recurring_occurrence_type"), "Recurring occurrence type"
    )
    recurring_source_kind = _clean_text(
        data.get("recurring_source_kind"), "Recurring source kind"
    )
    if any(
        (
            recurring_schedule_id,
            recurring_scheduled_date,
            recurring_source_kind,
            recurring_occurrence_type,
        )
    ):
        if not (
            recurring_schedule_id
            and recurring_scheduled_date
            and recurring_source_kind
            and recurring_occurrence_type
        ):
            raise StorageValidationError(
                "Recurring provenance fields must be provided together"
            )
        provenance["recurring_schedule_id"] = recurring_schedule_id
        provenance["recurring_scheduled_date"] = _iso_date(recurring_scheduled_date)
        if recurring_source_kind not in {"transaction", "mixed_use"}:
            raise StorageValidationError("Unknown recurring source kind")
        provenance["recurring_source_kind"] = recurring_source_kind
        if recurring_occurrence_type not in {"initial", "generated"}:
            raise StorageValidationError("Unknown recurring occurrence type")
        provenance["recurring_occurrence_type"] = recurring_occurrence_type
    if original_transaction is not None:
        source_type = _clean_text(
            original_transaction.get("source_type"),
            "Transaction source type",
        )
        source_id = _clean_text(
            original_transaction.get("source_id"),
            "Transaction source ID",
        )
        if bool(source_type) != bool(source_id):
            raise StorageValidationError(
                "Transaction source type and source ID must be provided together"
            )
        if source_type:
            if source_type != MIXED_USE_SOURCE_TYPE:
                raise StorageValidationError("Transaction source type is unsupported")
            provenance["source_type"] = source_type
            provenance["source_id"] = source_id
    if not payee_id and new_payee_name:
        new_payee = create_payee(new_payee_name)
        payee_id = new_payee["id"]
        payees[payee_id] = new_payee
    if payee_id and payee_id not in payees:
        raise StorageValidationError("Payee does not exist")
    if (
        payee_id
        and not _as_bool(payees[payee_id]["active"], "Payee active")
        and payee_id != original_payee_id
    ):
        raise StorageValidationError("Payee is inactive")
    new_tag_name = _clean_text(data.get("new_tag_name"), "New tag")
    if new_tag_name:
        new_tag = create_tag(new_tag_name)
        if new_tag["id"] not in tag_ids:
            tag_ids.append(new_tag["id"])
        tags[new_tag["id"]] = new_tag
        tag_ids = _normalize_tag_ids(tag_ids)
    record = {
        "id": transaction_id or str(uuid4()),
        "txn_date": txn_date,
        "kind": kind,
        "amount": amount,
        "account_id": account_id,
        "to_account_id": to_account_id,
        "category_id": category_id,
        "payee_id": payee_id,
        "payee": payees.get(payee_id, {}).get("name", ""),
        "description": _clean_text(data.get("description"), "Description"),
        "reference": _clean_text(data.get("reference"), "Reference"),
        "receipt_references": receipt_references,
        "tag_ids": tag_ids,
        "created_at": created_at or utc_now(),
    }
    record.update(provenance)
    return record


def reject_derived_transaction(transaction: Mapping[str, Any]) -> None:
    source_type = _clean_text(transaction.get("source_type"), "Transaction source type")
    source_id = _clean_text(transaction.get("source_id"), "Transaction source ID")
    if not source_type and not source_id:
        return
    if bool(source_type) != bool(source_id):
        raise StorageValidationError(
            "Transaction source type and source ID must be provided together"
        )
    if source_type == "depreciation":
        raise StorageValidationError("Depreciation entries are managed from Assets")
    if source_type != MIXED_USE_SOURCE_TYPE:
        raise StorageValidationError("Transaction source type is unsupported")
    raise StorageValidationError(
        "Mixed-use projections must be changed through mixed-use expense APIs"
    )


def prepare_bulk_transaction_changes(
    changes, transactions, *, categories, payees, tags
):
    """Normalize Category/Payee/Tags changes against the fresh selection."""
    transactions = list(transactions)
    for transaction in transactions:
        reject_derived_transaction(transaction)
    normalized_changes = dict(changes)
    supported_fields = {"category_id", "payee_id", "tag_ids"}
    unknown_fields = sorted(set(normalized_changes) - supported_fields)
    if unknown_fields:
        raise StorageValidationError(
            "Unsupported bulk transaction fields: " + ", ".join(unknown_fields)
        )
    if not normalized_changes:
        return {}

    if "category_id" in normalized_changes:
        category_id = _clean_text(
            normalized_changes["category_id"], "Category", required=True
        )
        target = categories.get(category_id)
        if target is None:
            raise StorageValidationError("Category does not exist")
        kinds = {transaction["kind"] for transaction in transactions}
        if len(kinds) != 1 or kinds == {"Transfer"}:
            raise StorageValidationError(
                "Category changes require a homogeneous Income or Expense selection"
            )
        kind = next(iter(kinds))
        if kind not in {"Income", "Expense"} or target["kind"] != kind:
            raise StorageValidationError(
                "The selected category must match the transaction kind"
            )
        normalized_changes["category_id"] = category_id

    if "payee_id" in normalized_changes:
        payee_id = _clean_text(normalized_changes["payee_id"], "Payee")
        if payee_id:
            payee = payees.get(payee_id)
            if payee is None:
                raise StorageValidationError("Payee does not exist")
            if not _as_bool(payee["active"], "Payee active") and any(
                transaction["payee_id"] != payee_id for transaction in transactions
            ):
                raise StorageValidationError("Payee is inactive")
        normalized_changes["payee_id"] = payee_id

    if "tag_ids" in normalized_changes:
        tag_ids = _normalize_tag_ids(normalized_changes["tag_ids"])
        for tag_id in tag_ids:
            tag = tags.get(tag_id)
            if tag is None:
                raise StorageValidationError("Tag does not exist")
            if not _as_bool(tag["active"], "Tag active") and any(
                tag_id not in _normalize_tag_ids(transaction.get("tag_ids", ""))
                for transaction in transactions
            ):
                raise StorageValidationError("Tag is inactive")
        normalized_changes["tag_ids"] = tag_ids

    return normalized_changes
