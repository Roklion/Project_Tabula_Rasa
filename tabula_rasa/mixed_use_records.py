"""Source/projection preparation and relationship rules without persistence."""

from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from uuid import uuid4
from decimal import Decimal, InvalidOperation
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.reference_data import (
    clean_text as _clean_text,
    normalize_tag_ids as _normalize_tag_ids,
)
from tabula_rasa.ledger_validation import (
    iso_date as _iso_date,
    decode_receipt_references,
)
from tabula_rasa.transaction import utc_now as _utc_now
from tabula_rasa.mixed_use import (
    MIXED_USE_SOURCE_TYPE,
    MixedUseAllocationError,
    validate_mixed_use_allocation,
)


def _decimal_values_match(actual: Any, expected: str) -> bool:
    try:
        return Decimal(str(actual).strip()) == Decimal(expected)
    except (InvalidOperation, ValueError):
        return False


def mixed_use_ledger_description(description: Any, rationale: Any) -> str:
    """Build the deterministic description for a mixed-use projection."""
    original = _clean_text(description, "Description")
    explanation = _clean_text(rationale, "Allocation rationale", required=True)
    prefix = f"{original}\n" if original else ""
    return f"{prefix}Allocation rationale: {explanation}"


def validate_mixed_use_records(sources, transactions):
    sources_by_id: dict[str, dict[str, str]] = {}
    linked_ids: set[str] = set()
    for source in sources:
        source_id = _clean_text(source.get("id"), "Mixed-use source ID", required=True)
        if source_id in sources_by_id:
            raise StorageValidationError("Mixed-use source IDs must be unique")
        sources_by_id[source_id] = source
        if (
            _clean_text(source.get("kind"), "Mixed-use kind", required=True)
            != "Expense"
        ):
            raise StorageValidationError("Mixed-use sources must be Expense records")
        _iso_date(source.get("txn_date"))
        _clean_text(source.get("account_id"), "Account", required=True)
        _clean_text(source.get("category_id"), "Category", required=True)
        linked_id = _clean_text(
            source.get("linked_transaction_id"),
            "Linked transaction ID",
            required=True,
        )
        if linked_id in linked_ids:
            raise StorageValidationError(
                "Mixed-use linked transaction IDs must be unique"
            )
        linked_ids.add(linked_id)
        try:
            allocation = validate_mixed_use_allocation(
                source.get("total_expense"),
                source.get("business_use_percentage"),
            )
        except MixedUseAllocationError as exc:
            raise StorageValidationError(str(exc)) from exc
        if not _decimal_values_match(
            source.get("total_expense"), allocation.total_expense
        ):
            raise StorageValidationError(
                "Mixed-use total expense has a non-canonical value"
            )
        if not _decimal_values_match(
            source.get("business_use_percentage"), allocation.business_use_percentage
        ):
            raise StorageValidationError(
                "Mixed-use business-use percentage has a non-canonical value"
            )
        if not _decimal_values_match(
            source.get("allocated_amount"), allocation.allocated_amount
        ):
            raise StorageValidationError(
                "Mixed-use allocated amount does not match its allocation"
            )
        _clean_text(
            source.get("allocation_rationale"), "Allocation rationale", required=True
        )
        decode_receipt_references(source.get("receipt_references", ""))
        _normalize_tag_ids(source.get("tag_ids", ""))

    transactions_by_id = {
        _clean_text(transaction.get("id"), "Transaction ID", required=True): transaction
        for transaction in transactions
    }
    if len(transactions_by_id) != len(transactions):
        raise StorageValidationError("Transaction IDs must be unique")
    linked_source_ids: set[str] = set()
    for transaction in transactions:
        source_type = _clean_text(
            transaction.get("source_type"), "Transaction source type"
        )
        source_id = _clean_text(transaction.get("source_id"), "Transaction source ID")
        if bool(source_type) != bool(source_id):
            raise StorageValidationError(
                "Transaction source type and source ID must be provided together"
            )
        if not source_type or source_type.lower() == "depreciation":
            continue
        if source_type != MIXED_USE_SOURCE_TYPE:
            raise StorageValidationError("Transaction source type is unsupported")
        source = sources_by_id.get(source_id)
        if source is None:
            raise StorageValidationError(
                "Mixed-use projection references an unknown source record"
            )
        transaction_id = _clean_text(
            transaction.get("id"), "Transaction ID", required=True
        )
        if source_id in linked_source_ids:
            raise StorageValidationError(
                "A mixed-use source has more than one projection transaction"
            )
        linked_source_ids.add(source_id)
        if source.get("linked_transaction_id") != transaction_id:
            raise StorageValidationError(
                "Mixed-use source and projection IDs do not match"
            )
        if transaction.get("kind") != "Expense":
            raise StorageValidationError(
                "Mixed-use projections must be Expense records"
            )
        if _clean_text(transaction.get("to_account_id"), "Destination account"):
            raise StorageValidationError(
                "Mixed-use projections cannot have a destination account"
            )
        for field in (
            "txn_date",
            "account_id",
            "category_id",
            "payee_id",
            "reference",
            "recurring_schedule_id",
            "recurring_scheduled_date",
            "recurring_source_kind",
            "recurring_occurrence_type",
        ):
            if _clean_text(transaction.get(field), field) != _clean_text(
                source.get(field), field
            ):
                raise StorageValidationError(
                    f"Mixed-use source and projection {field} values do not match"
                )
        if _clean_text(
            transaction.get("description"), "Description"
        ) != mixed_use_ledger_description(
            source.get("description"), source.get("allocation_rationale")
        ):
            raise StorageValidationError(
                "Mixed-use projection description is out of sync"
            )
        if not _decimal_values_match(
            transaction.get("amount"), source.get("allocated_amount")
        ):
            raise StorageValidationError(
                "Mixed-use projection amount does not match its source"
            )
        if transaction.get("receipt_references", "") != source.get(
            "receipt_references", ""
        ):
            raise StorageValidationError(
                "Mixed-use source and projection receipt references do not match"
            )
        if (
            "tag_ids" in source
            and "tag_ids" in transaction
            and _normalize_tag_ids(source.get("tag_ids", ""))
            != _normalize_tag_ids(transaction.get("tag_ids", ""))
        ):
            raise StorageValidationError(
                "Mixed-use source and projection tags do not match"
            )
    for source in sources:
        linked_id = source.get("linked_transaction_id")
        if linked_id not in transactions_by_id or _clean_text(
            transactions_by_id[linked_id].get("source_id"), "Transaction source ID"
        ) != source.get("id"):
            raise StorageValidationError(
                "Mixed-use source references a missing projection transaction"
            )


def prepare_mixed_use_expense(
    prepare_transaction,
    data: Mapping[str, Any],
    *,
    source_id: str | None = None,
    linked_transaction_id: str | None = None,
    created_at: str | None = None,
    original_transaction: Mapping[str, Any] | None = None,
    preserve_existing_payee: bool = False,
) -> tuple[dict[str, str], dict[str, str]]:
    try:
        allocation = validate_mixed_use_allocation(
            data.get("total_expense"),
            data.get("business_use_percentage"),
        )
    except MixedUseAllocationError as exc:
        raise StorageValidationError(str(exc)) from exc
    rationale = _clean_text(
        data.get("allocation_rationale"),
        "Allocation rationale",
        required=True,
    )
    source_id = _clean_text(
        source_id if source_id is not None else data.get("source_id", data.get("id")),
        "Mixed-use source ID",
    ) or str(uuid4())
    linked_transaction_id = _clean_text(
        linked_transaction_id
        if linked_transaction_id is not None
        else data.get("linked_transaction_id"),
        "Linked transaction ID",
    ) or str(uuid4())
    original_description = _clean_text(data.get("description"), "Description")
    transaction = prepare_transaction(
        {
            **data,
            "kind": "Expense",
            "amount": allocation.allocated_amount,
            "description": original_description,
        },
        created_at=(
            original_transaction.get("created_at")
            if original_transaction is not None
            else None
        ),
        original_transaction=original_transaction,
        preserve_existing_payee=preserve_existing_payee,
    )
    source = {
        "id": source_id,
        "txn_date": transaction["txn_date"],
        "kind": "Expense",
        "total_expense": allocation.total_expense,
        "business_use_percentage": allocation.business_use_percentage,
        "allocated_amount": allocation.allocated_amount,
        "account_id": transaction["account_id"],
        "category_id": transaction["category_id"],
        "payee_id": transaction["payee_id"],
        "description": original_description,
        "reference": transaction["reference"],
        "receipt_references": transaction["receipt_references"],
        "allocation_rationale": rationale,
        "linked_transaction_id": linked_transaction_id,
        "tag_ids": transaction["tag_ids"],
        "created_at": created_at or _utc_now(),
    }
    for field in (
        "recurring_schedule_id",
        "recurring_scheduled_date",
        "recurring_source_kind",
        "recurring_occurrence_type",
    ):
        value = _clean_text(transaction.get(field), field.replace("_", " ").title())
        if value:
            source[field] = value
    projection = {
        **transaction,
        "id": linked_transaction_id,
        "description": mixed_use_ledger_description(original_description, rationale),
        "source_type": MIXED_USE_SOURCE_TYPE,
        "source_id": source_id,
    }
    return source, projection


def validate_mixed_use_changes(current, changes):
    if "id" in changes or "source_id" in changes or "linked_transaction_id" in changes:
        raise StorageValidationError("Mixed-use source IDs cannot be edited")
    for field in (
        "recurring_schedule_id",
        "recurring_scheduled_date",
        "recurring_source_kind",
        "recurring_occurrence_type",
    ):
        if field in changes and str(changes[field] or "") != str(
            current.get(field, "") or ""
        ):
            raise StorageValidationError("Recurring provenance cannot be changed")
