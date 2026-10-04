"""Recurring expense templates, occurrence identities, and state rules."""

from __future__ import annotations
from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import uuid4
from tabula_rasa.errors import StorageValidationError, StorageConflictError
from tabula_rasa.reference_data import (
    clean_text as _clean_text,
    as_bool as _as_bool,
    normalize_tag_ids as _normalize_tag_ids,
)
from tabula_rasa.ledger_validation import (
    iso_date as _iso_date,
    encode_tag_ids as _encode_tag_ids,
    positive_integer as _positive_integer,
    positive_amount as _positive_amount,
    decode_receipt_references,
    validate_recurring_provenance as _validate_recurring_provenance,
)
from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE, validate_mixed_use_allocation
from tabula_rasa.recurrence import normalize_unit, next_occurrence, occurrence_id
from tabula_rasa.transaction import utc_now as _utc_now

_PENDING_INITIAL_LINK = "pending_initial_link"


def _as_date(value):
    return date.fromisoformat(_iso_date(value))


SCHEDULE_FIELDS = (
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
)


def schedule_status(value: Any) -> str:
    status = _clean_text(value, "Schedule status", required=True).casefold()
    if status not in {"active", "paused", "ended"}:
        raise StorageValidationError("Schedule status must be active, paused, or ended")
    return status


def schedule_template(
    data: Mapping[str, Any],
    *,
    schedule_id: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
    account_lookup: Mapping[str, Any] | None = None,
    category_lookup: Mapping[str, Any] | None = None,
    payee_lookup: Mapping[str, Any] | None = None,
    tag_lookup: Mapping[str, Any] | None = None,
    require_active_references: bool = False,
) -> dict[str, str]:
    schedule_id = _clean_text(
        schedule_id or data.get("schedule_id") or data.get("id"), "Schedule ID"
    ) or str(uuid4())
    name = _clean_text(data.get("name"), "Schedule name", required=True)
    kind = _clean_text(
        data.get("kind", "Expense"), "Schedule kind", required=True
    ).title()
    if kind != "Expense":
        raise StorageValidationError("Recurring schedules support Expense records only")
    try:
        unit = normalize_unit(
            data.get("recurrence_unit", data.get("unit", "month"))
        ).value
    except ValueError as exc:
        raise StorageValidationError(str(exc)) from exc
    source_kind = _clean_text(
        data.get("source_kind", "transaction"), "Source kind"
    ).casefold()
    if source_kind not in {"transaction", "mixed_use"}:
        raise StorageValidationError("Source kind must be transaction or mixed_use")
    interval = _positive_integer(
        data.get("recurrence_interval", data.get("interval", 1)),
        "Recurrence interval",
    )
    anchor = _iso_date(
        data.get("anchor_date", data.get("start_date", data.get("txn_date")))
    )
    start = _iso_date(data.get("start_date", anchor))
    status = schedule_status(data.get("status", "active"))
    end_value = _clean_text(data.get("end_date"), "Schedule end date")
    end = _iso_date(end_value) if end_value else ""
    if end and end < start and status != "ended":
        raise StorageValidationError(
            "Schedule end date must not precede its start date"
        )
    if anchor != start:
        # The first occurrence is the anchor; exposing two dates that differ
        # makes a schedule ambiguous and causes month/year drift.
        raise StorageValidationError("Schedule anchor date must equal its start date")
    account_id = _clean_text(data.get("account_id"), "Account", required=True)
    category_id = _clean_text(data.get("category_id"), "Category", required=True)
    accounts = account_lookup if account_lookup is not None else {}
    categories = category_lookup if category_lookup is not None else {}
    if account_id not in accounts:
        raise StorageValidationError("Source account does not exist")
    if require_active_references and not _as_bool(
        accounts[account_id].get("active"), "Account active"
    ):
        raise StorageValidationError("Source account is inactive")
    if (
        category_id not in categories
        or categories[category_id].get("kind") != "Expense"
    ):
        raise StorageValidationError("Category kind does not match transaction kind")
    payee_id = _clean_text(data.get("payee_id"), "Payee")
    payees = payee_lookup if payee_lookup is not None else {}
    if payee_id and payee_id not in payees:
        raise StorageValidationError("Payee does not exist")
    if (
        payee_id
        and require_active_references
        and not _as_bool(payees[payee_id].get("active"), "Payee active")
    ):
        raise StorageValidationError("Payee is inactive")
    tags = _normalize_tag_ids(data.get("tag_ids", ""))
    known_tags = tag_lookup if tag_lookup is not None else {}
    if any(tag not in known_tags for tag in tags):
        raise StorageValidationError("Tag does not exist")
    if require_active_references and any(
        not _as_bool(known_tags[tag].get("active"), "Tag active") for tag in tags
    ):
        raise StorageValidationError("Tag is inactive")
    try:
        receipt_references = decode_receipt_references(
            data.get("receipt_references", "")
        )
    except StorageValidationError as exc:
        raise StorageValidationError(
            "Receipts cannot be part of a recurring template"
        ) from exc
    if receipt_references:
        raise StorageValidationError("Receipts cannot be part of a recurring template")
    timestamp = created_at or _utc_now()
    allocation = None
    if source_kind == "mixed_use":
        try:
            allocation = validate_mixed_use_allocation(
                data.get("total_expense", data.get("amount")),
                data.get("business_use_percentage", "100"),
            )
        except Exception as exc:
            raise StorageValidationError(str(exc)) from exc
    allocation_rationale = _clean_text(
        data.get("allocation_rationale"),
        "Allocation rationale",
        required=source_kind == "mixed_use",
    )
    return {
        "id": schedule_id,
        "name": name,
        "kind": "Expense",
        "source_kind": source_kind,
        "recurrence_unit": unit,
        "recurrence_interval": str(interval),
        "anchor_date": start,
        "start_date": start,
        "end_date": end,
        "status": status,
        "amount": _positive_amount(
            data.get("amount")
            if source_kind == "transaction"
            else allocation.allocated_amount
        ),
        "total_expense": allocation.total_expense if allocation else "",
        "business_use_percentage": allocation.business_use_percentage
        if allocation
        else "",
        "account_id": account_id,
        "category_id": category_id,
        "payee_id": payee_id,
        "description": _clean_text(data.get("description"), "Description"),
        "reference": _clean_text(data.get("reference"), "Reference"),
        "allocation_rationale": allocation_rationale,
        "tag_ids": _encode_tag_ids(tags),
        "created_at": timestamp,
        "updated_at": updated_at or timestamp,
        "attention_code": _clean_text(data.get("attention_code"), "Attention code"),
        "attention_at": _clean_text(data.get("attention_at"), "Attention timestamp"),
    }


def decode_schedule(values: Mapping[str, Any]) -> dict[str, str]:
    """Normalize stored schedule fields without validating references."""
    schedule = {header: str(values.get(header, "") or "") for header in SCHEDULE_FIELDS}
    schedule["id"] = _clean_text(schedule.get("id"), "Schedule ID")
    schedule["kind"] = schedule.get("kind", "Expense").strip().title()
    schedule["source_kind"] = (
        schedule.get("source_kind", "transaction").strip().casefold()
    )
    try:
        schedule["recurrence_unit"] = normalize_unit(
            schedule.get("recurrence_unit", "month")
        ).value
    except ValueError:
        schedule["recurrence_unit"] = str(schedule.get("recurrence_unit", ""))
    try:
        schedule["status"] = schedule_status(schedule.get("status", "active"))
    except StorageValidationError:
        schedule["status"] = str(schedule.get("status", ""))
    attention_messages = {
        "validation": "Invalid template references; edit the schedule.",
        "storage": "Storage unavailable; retry or inspect the workbook.",
        _PENDING_INITIAL_LINK: (
            "Initial occurrence link needs confirmation; end this schedule "
            "and retry the expense edit if it remains pending."
        ),
    }
    schedule["attention_message"] = attention_messages.get(
        schedule.get("attention_code", ""), ""
    )
    if not schedule["id"]:
        schedule["attention_code"] = "validation"
        schedule["attention_message"] = "Missing schedule ID; edit the workbook."
    try:
        schedule["tag_ids"] = _encode_tag_ids(
            _normalize_tag_ids(schedule.get("tag_ids", ""))
        )
    except StorageValidationError:
        schedule["tag_ids"] = str(values.get("tag_ids", "") or "")
    return schedule


def validate_recurring_occurrence_rows(
    rows,
    schedule_values: Mapping[str, Mapping[str, Any]],
    label: str,
    *,
    mixed_source: bool,
    filter_schedule_id: str | None = None,
) -> None:
    for row in rows:
        values = row
        schedule_id = str(values.get("recurring_schedule_id", "") or "")
        if filter_schedule_id is not None and schedule_id.strip() != filter_schedule_id:
            continue
        _validate_recurring_provenance(values, label)
        if not schedule_id:
            continue
        if values.get("kind") != "Expense":
            raise StorageValidationError(f"{label} recurring rows must be an Expense")
        if schedule_id not in schedule_values:
            raise StorageValidationError(
                f"{label} references an unknown recurring schedule"
            )
        _iso_date(values.get("recurring_scheduled_date"))
        expected_source_kind = (
            "mixed_use"
            if mixed_source
            else (
                "mixed_use"
                if values.get("source_type") == MIXED_USE_SOURCE_TYPE
                and values.get("source_id")
                else "transaction"
            )
        )
        if (
            values.get("recurring_source_kind") != expected_source_kind
            or schedule_values[schedule_id].get("source_kind") != expected_source_kind
        ):
            raise StorageValidationError(f"{label} recurring source kind is invalid")
        if values.get("recurring_occurrence_type") not in {"initial", "generated"}:
            raise StorageValidationError(
                f"{label} recurring occurrence type is invalid"
            )


def validate_mixed_use_projection_parity(
    source: Mapping[str, Any], projection: Mapping[str, Any]
) -> None:
    for field in (
        "recurring_schedule_id",
        "recurring_scheduled_date",
        "recurring_source_kind",
        "recurring_occurrence_type",
    ):
        if str(source.get(field, "") or "") != str(projection.get(field, "") or ""):
            raise StorageValidationError(
                "Mixed-use source and projection recurring provenance does not match"
            )


def valid_mixed_use_projection(
    source: Mapping[str, Any], projection: Mapping[str, Any] | None
) -> bool:
    if projection is None:
        raise StorageValidationError("Mixed-use source has no linked projection")
    if projection.get("source_type") != MIXED_USE_SOURCE_TYPE or str(
        projection.get("source_id", "")
    ) != str(source.get("id", "")):
        raise StorageValidationError(
            "Mixed-use source projection does not point back to its source"
        )
    return True


def reject_existing_recurring_metadata(record: Mapping[str, Any], label: str) -> None:
    """Reject partial recurring provenance before converting an occurrence."""
    if any(
        str(record.get(field, "") or "").strip()
        for field in (
            "recurring_schedule_id",
            "recurring_scheduled_date",
            "recurring_source_kind",
            "recurring_occurrence_type",
        )
    ):
        raise StorageValidationError(f"{label} already contains recurring metadata")


def validate_schedule_changes(current, changes, *, transition=None):
    if "source_kind" in changes and _clean_text(
        changes["source_kind"], "Source kind", required=True
    ).casefold() != current.get("source_kind"):
        raise StorageValidationError(
            "A recurring schedule's source kind cannot be changed"
        )
    if (
        "status" in changes
        and current.get("status") == "ended"
        and schedule_status(changes["status"]) != "ended"
    ):
        raise StorageValidationError("Ended schedules cannot be reactivated")
    if transition == "pause" and current.get("status") != "active":
        raise StorageConflictError("Only an active schedule can be paused")
    if transition == "resume" and current.get("status") != "paused":
        raise StorageConflictError("Only a paused schedule can be resumed")
    if transition == "end" and current.get("status") == "ended":
        raise StorageConflictError("Schedule is already ended")


def latest_current_occurrence_date(
    schedule_id, source_kind, *, transactions, mixed_sources, projections
):
    records = mixed_sources if source_kind == "mixed_use" else transactions
    dates = []
    for record in records:
        if record.get("recurring_schedule_id") != schedule_id or not record.get(
            "recurring_scheduled_date"
        ):
            continue
        try:
            _validate_recurring_provenance(record, "Recurring occurrence")
        except StorageValidationError:
            continue
        if (
            record.get("kind") != "Expense"
            or record.get("recurring_source_kind") != source_kind
            or record.get("recurring_occurrence_type") not in {"initial", "generated"}
        ):
            continue
        if source_kind == "mixed_use":
            projection = projections.get(str(record.get("linked_transaction_id", "")))
            valid_mixed_use_projection(record, projection)
            validate_mixed_use_projection_parity(record, projection)
        try:
            dates.append(_as_date(record["recurring_scheduled_date"]))
        except (StorageValidationError, TypeError, ValueError):
            continue
    return max(dates) if dates else None


def existing_recurring_dates(
    schedule_id, source_kind, *, transactions, mixed_sources, projections
):
    records = mixed_sources if source_kind == "mixed_use" else transactions
    dates = set()
    for record in records:
        if record.get("recurring_schedule_id") != schedule_id:
            continue
        if source_kind == "mixed_use":
            valid_mixed_use_projection(
                record, projections.get(str(record.get("linked_transaction_id", "")))
            )
        dates.add(str(record.get("recurring_scheduled_date", "")))
    return dates


def next_due_for_schedule(schedule, **records):
    if schedule["status"] != "active":
        return ""
    current = _as_date(schedule["start_date"])
    latest = latest_current_occurrence_date(
        schedule["id"], schedule.get("source_kind"), **records
    )
    if latest:
        current = next_occurrence(
            _as_date(schedule["anchor_date"]),
            schedule["recurrence_unit"],
            int(schedule["recurrence_interval"]),
            latest,
        )
    if schedule.get("end_date") and current.isoformat() > schedule["end_date"]:
        return ""
    return current.isoformat()


def occurrence_data(schedule, scheduled, *, role):
    data = {
        key: schedule.get(key, "")
        for key in (
            "account_id",
            "category_id",
            "payee_id",
            "description",
            "reference",
            "tag_ids",
        )
    }
    data.update(
        txn_date=scheduled,
        kind="Expense",
        receipt_references="",
        recurring_schedule_id=schedule["id"],
        recurring_scheduled_date=scheduled.isoformat(),
        recurring_source_kind=schedule["source_kind"],
        recurring_occurrence_type=role,
    )
    if schedule.get("source_kind") == "mixed_use":
        data.update(
            source_id=occurrence_id(schedule["id"], scheduled, role + "-source"),
            linked_transaction_id=occurrence_id(
                schedule["id"], scheduled, role + "-projection"
            ),
            total_expense=schedule["total_expense"],
            business_use_percentage=schedule["business_use_percentage"],
            allocation_rationale=schedule.get("allocation_rationale", ""),
        )
    else:
        data.update(
            transaction_id=occurrence_id(schedule["id"], scheduled, role),
            amount=schedule["amount"],
        )
    return data
