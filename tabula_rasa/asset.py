"""Profile-local fixed-asset source records."""

from __future__ import annotations

from datetime import date
import json
from typing import Any, Mapping
from uuid import uuid4

from tabula_rasa.depreciation import (
    STRAIGHT_LINE_METHOD,
    DepreciationError,
    currency_decimal,
    straight_line_schedule,
)

from tabula_rasa.errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from tabula_rasa.reference_data import (
    clean_text as _clean_text,
    normalize_tag_ids as _normalize_tag_ids,
)
from tabula_rasa.ledger_validation import (
    iso_date as _iso_date,
    encode_tag_ids as _encode_tag_ids,
)
from tabula_rasa.transaction import utc_now as _utc_now


ASSET_TYPES = (
    "Computers & office equipment",
    "Furniture, fixtures & appliances",
    "Photography, communication & video equipment",
    "Machinery, equipment & tools",
    "Vehicles",
    "Construction equipment",
    "Farm equipment",
    "Residential rental property",
    "Commercial real property",
    "Land improvements",
    "Leasehold improvements",
    "Software & other intangibles",
    "Other depreciable property",
)


def _whole_quarters(value: Any) -> int:
    if isinstance(value, bool):
        raise StorageValidationError("Useful life must be a whole number of quarters")
    try:
        text = str(value).strip()
        result = int(text)
    except (TypeError, ValueError):
        raise StorageValidationError(
            "Useful life must be a whole number of quarters"
        ) from None
    if text not in {str(result), f"+{result}"} or result <= 0:
        raise StorageValidationError(
            "Useful life must be a whole number of quarters greater than zero"
        )
    return result


def _currency(value: Any, field: str) -> str:
    try:
        return format(currency_decimal(value, field), "f")
    except DepreciationError as exc:
        raise StorageValidationError(str(exc)) from exc


def _decode_overrides(value: Any) -> dict[int, dict[str, str]]:
    if value in (None, ""):
        return {}
    if isinstance(value, Mapping):
        raw = value
    else:
        try:
            raw = json.loads(str(value))
        except json.JSONDecodeError:
            raise StorageValidationError(
                "Asset schedule overrides are invalid"
            ) from None
    if not isinstance(raw, Mapping):
        raise StorageValidationError("Asset schedule overrides are invalid")
    result: dict[int, dict[str, str]] = {}
    for key, details in raw.items():
        if not isinstance(details, Mapping):
            raise StorageValidationError("Asset schedule overrides are invalid")
        try:
            sequence = int(key)
        except (TypeError, ValueError):
            raise StorageValidationError("Asset override period is invalid") from None
        if sequence in result:
            raise StorageValidationError("Asset override periods must be unique")
        result[sequence] = {
            "amount": _currency(details.get("amount"), "Override amount"),
            "reason": _clean_text(
                details.get("reason"), "Override reason", required=True
            ),
        }
    return result


def _normalize_overrides(value: Any) -> str:
    overrides = _decode_overrides(value)
    return json.dumps(
        {str(key): details for key, details in sorted(overrides.items())},
        separators=(",", ":"),
    )


def prepare_asset(
    data: Mapping[str, Any],
    *,
    asset_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, str]:
    acquisition_date = _iso_date(data.get("acquisition_date"))
    start_date = _iso_date(data.get("depreciation_start_date"))
    if start_date < acquisition_date:
        raise StorageValidationError(
            "Depreciation start date cannot be earlier than acquisition date"
        )
    cost_basis = _currency(data.get("cost_basis"), "Cost basis")
    salvage_value = _currency(data.get("salvage_value", 0), "Salvage value")
    if currency_decimal(cost_basis, "Cost basis") <= 0:
        raise StorageValidationError("Cost basis must be greater than $0.00")
    if currency_decimal(salvage_value, "Salvage value") < 0 or currency_decimal(
        salvage_value, "Salvage value"
    ) >= currency_decimal(cost_basis, "Cost basis"):
        raise StorageValidationError(
            "Salvage value must be at least $0.00 and less than cost basis"
        )
    asset_type = _clean_text(data.get("asset_type"), "Asset type", required=True)
    if asset_type not in ASSET_TYPES:
        raise StorageValidationError("Unknown asset type")
    method = _clean_text(
        data.get("depreciation_method", STRAIGHT_LINE_METHOD),
        "Depreciation method",
        required=True,
    )
    if method != STRAIGHT_LINE_METHOD:
        raise StorageValidationError(
            "Straight-line is the only supported depreciation method"
        )
    status = _clean_text(data.get("status", "active"), "Asset status").lower()
    if status not in {"active", "retired"}:
        raise StorageValidationError("Asset status must be active or retired")
    retired_date = _clean_text(data.get("retired_date"), "Retired date")
    if retired_date:
        retired_date = _iso_date(retired_date)
        if retired_date < acquisition_date:
            raise StorageValidationError(
                "Retired date cannot be earlier than acquisition date"
            )
    if status == "retired" and not retired_date:
        raise StorageValidationError("A retired asset requires a retired date")
    if status == "active" and retired_date:
        raise StorageValidationError("An active asset cannot have a retired date")

    payee_id = _clean_text(data.get("payee_id"), "Payee")
    tag_ids = _normalize_tag_ids(data.get("tag_ids", ""))
    source_transaction_id = _clean_text(
        data.get("source_transaction_id"), "Source transaction"
    )
    record = {
        "id": asset_id or str(uuid4()),
        "name": _clean_text(data.get("name"), "Asset name", required=True),
        "asset_type": asset_type,
        "notes": _clean_text(data.get("notes"), "Asset notes"),
        "acquisition_date": acquisition_date,
        "depreciation_start_date": start_date,
        "cost_basis": cost_basis,
        "salvage_value": salvage_value,
        "useful_life_quarters": str(_whole_quarters(data.get("useful_life_quarters"))),
        "depreciation_method": method,
        "depreciation_expense_account_id": _clean_text(
            data.get("depreciation_expense_account_id"),
            "Depreciation expense account",
        ),
        "accumulated_depreciation_account_id": _clean_text(
            data.get("accumulated_depreciation_account_id"),
            "Accumulated depreciation account",
        ),
        "payee_id": payee_id,
        "reference": _clean_text(data.get("reference"), "Reference"),
        "tag_ids": _encode_tag_ids(tag_ids),
        "source_transaction_id": source_transaction_id,
        "retired_date": retired_date,
        "status": status,
        "schedule_overrides": _normalize_overrides(data.get("schedule_overrides", "")),
        "created_at": created_at or _utc_now(),
        "updated_at": _utc_now(),
    }
    try:
        straight_line_schedule(
            cost_basis,
            salvage_value,
            date.fromisoformat(start_date),
            int(record["useful_life_quarters"]),
            retired_date=(date.fromisoformat(retired_date) if retired_date else None),
            overrides=_decode_overrides(record["schedule_overrides"]),
        )
    except DepreciationError as exc:
        raise StorageValidationError(str(exc)) from exc
    return record


def assert_expected_asset(
    current: Mapping[str, str], expected: Mapping[str, Any] | None
) -> None:
    if expected is None:
        return
    for key, value in expected.items():
        if key in {"tags", "payee", "posted_entry_ids"}:
            continue
        current_value = current.get(key, "")
        if key == "tag_ids":
            if _normalize_tag_ids(current_value) != _normalize_tag_ids(value):
                break
        elif str(current_value) != str(value):
            break
    else:
        return
    raise StorageConflictError(
        "The asset changed since it was selected. Refresh and try again."
    )


def edit_asset(current, postings, changes):
    normalized_current = prepare_asset(
        current,
        asset_id=_clean_text(current.get("id"), "Asset ID", required=True),
        created_at=_clean_text(
            current.get("created_at"),
            "Asset created time",
            required=True,
        ),
    )
    merged = dict(current)
    merged.update(changes)
    updated = prepare_asset(
        merged,
        asset_id=_clean_text(current.get("id"), "Asset ID", required=True),
        created_at=_clean_text(
            current.get("created_at"),
            "Asset created time",
            required=True,
        ),
    )
    if postings or _decode_overrides(current.get("schedule_overrides", "")):
        locked_fields = {
            "cost_basis",
            "salvage_value",
            "depreciation_start_date",
            "useful_life_quarters",
            "depreciation_method",
            "schedule_overrides",
        }
        if postings:
            locked_fields.update(
                {
                    "depreciation_expense_account_id",
                    "accumulated_depreciation_account_id",
                }
            )
        if any(
            field in changes and updated[field] != normalized_current[field]
            for field in locked_fields
        ):
            raise StorageConflictError(
                "Schedule terms are locked after depreciation is posted or a historical override is saved"
            )
    if updated["retired_date"] and any(
        _iso_date(row.get("txn_date")) > updated["retired_date"] for row in postings
    ):
        raise StorageConflictError("Retirement cannot precede posted depreciation")
    return updated


def override_asset_period(current, postings, sequence, amount, reason, as_of_date):
    asset_id = current["id"]
    if postings:
        raise StorageConflictError("Overrides are locked after depreciation is posted")
    normalized = prepare_asset(
        current,
        asset_id=asset_id,
        created_at=current.get("created_at"),
    )
    try:
        sequence = int(sequence)
    except (TypeError, ValueError):
        raise StorageValidationError("Override period is invalid") from None
    full_schedule = straight_line_schedule(
        normalized["cost_basis"],
        normalized["salvage_value"],
        date.fromisoformat(normalized["depreciation_start_date"]),
        int(normalized["useful_life_quarters"]),
    )
    if sequence < 1 or sequence > len(full_schedule):
        raise StorageValidationError("Override period is outside the asset life")
    if full_schedule[sequence - 1].scheduled_date > as_of_date:
        raise StorageValidationError("Only due or past quarters can be overridden")
    overrides = _decode_overrides(normalized["schedule_overrides"])
    if overrides and sequence < max(overrides):
        raise StorageConflictError(
            "Earlier quarters are locked by the latest historical override"
        )
    overrides[sequence] = {
        "amount": _currency(amount, "Override amount"),
        "reason": _clean_text(reason, "Override reason", required=True),
    }
    merged = dict(current)
    merged["schedule_overrides"] = _normalize_overrides(overrides)
    updated = prepare_asset(
        merged,
        asset_id=asset_id,
        created_at=current.get("created_at"),
    )
    return updated


def remove_asset_period_override(current, postings, sequence):
    asset_id = current["id"]
    if postings:
        raise StorageConflictError("Overrides are locked after depreciation is posted")
    overrides = _decode_overrides(current.get("schedule_overrides", ""))
    try:
        sequence = int(sequence)
    except (TypeError, ValueError):
        raise StorageValidationError("Override period is invalid") from None
    if sequence not in overrides:
        raise StorageNotFoundError("That asset period has no override")
    if sequence < max(overrides):
        raise StorageConflictError(
            "Earlier quarters are locked by the latest historical override"
        )
    del overrides[sequence]
    merged = dict(current)
    merged["schedule_overrides"] = _normalize_overrides(overrides)
    updated = prepare_asset(
        merged,
        asset_id=asset_id,
        created_at=current.get("created_at"),
    )
    return updated
