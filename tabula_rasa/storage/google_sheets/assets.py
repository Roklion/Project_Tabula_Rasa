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

from .depreciation_posting import (
    asset_schedule,
    depreciation_entry_id,
    validate_depreciation_accounts,
    validate_depreciation_history,
)
from .errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from .validation import (
    _clean_text,
    _encode_tag_ids,
    _iso_date,
    _normalize_tag_ids,
    _utc_now,
)


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


class AssetsMixin:
    """CRUD boundary for individually tracked depreciable assets."""

    @staticmethod
    def _prepare_asset(
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
            "useful_life_quarters": str(
                _whole_quarters(data.get("useful_life_quarters"))
            ),
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
            "schedule_overrides": _normalize_overrides(
                data.get("schedule_overrides", "")
            ),
            "created_at": created_at or _utc_now(),
            "updated_at": _utc_now(),
        }
        try:
            straight_line_schedule(
                cost_basis,
                salvage_value,
                date.fromisoformat(start_date),
                int(record["useful_life_quarters"]),
                retired_date=(
                    date.fromisoformat(retired_date) if retired_date else None
                ),
                overrides=_decode_overrides(record["schedule_overrides"]),
            )
        except DepreciationError as exc:
            raise StorageValidationError(str(exc)) from exc
        return record

    def _validate_asset_references(
        self,
        record: Mapping[str, str],
        *,
        allowed_missing_source_id: str = "",
    ) -> None:
        validate_depreciation_accounts(
            record,
            self._account_lookup(force_refresh=True),
            self._category_lookup(force_refresh=True),
        )
        payee_id = record.get("payee_id", "")
        if payee_id and payee_id not in self._payee_lookup(force_refresh=True):
            raise StorageValidationError("Payee does not exist")
        tags = self._tag_lookup(force_refresh=True)
        if any(
            tag_id not in tags
            for tag_id in _normalize_tag_ids(record.get("tag_ids", ""))
        ):
            raise StorageValidationError("Tag does not exist")
        source_id = record.get("source_transaction_id", "")
        if source_id:
            try:
                self._find_row("Transactions", source_id)
            except StorageNotFoundError:
                if source_id == allowed_missing_source_id:
                    return
                raise StorageValidationError(
                    "Source acquisition transaction does not exist"
                ) from None

    def list_assets(self, *, _force_refresh: bool = False) -> list[dict[str, Any]]:
        payees = self._payee_lookup(force_refresh=_force_refresh)
        tags = self._tag_lookup(force_refresh=_force_refresh)
        assets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._rows("Assets", force_refresh=_force_refresh):
            record = self._prepare_asset(
                row.values,
                asset_id=_clean_text(row.values.get("id"), "Asset ID", required=True),
                created_at=_clean_text(
                    row.values.get("created_at"), "Asset created time", required=True
                ),
            )
            record["updated_at"] = _clean_text(
                row.values.get("updated_at"), "Asset updated time", required=True
            )
            if record["id"] in seen:
                raise StorageValidationError("Asset IDs must be unique")
            seen.add(record["id"])
            if record["payee_id"] and record["payee_id"] not in payees:
                raise StorageValidationError("Asset payee does not exist")
            normalized_tags = _normalize_tag_ids(record["tag_ids"])
            if any(tag_id not in tags for tag_id in normalized_tags):
                raise StorageValidationError("Asset tag does not exist")
            record["tag_ids"] = normalized_tags
            record["tags"] = [tags[tag_id]["name"] for tag_id in normalized_tags]
            record["payee"] = payees.get(record["payee_id"], {}).get("name", "")
            assets.append(record)
        return sorted(
            assets,
            key=lambda item: (item["status"] != "active", item["name"].casefold()),
        )

    def create_asset(self, **data: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            record = self._prepare_asset(data)
            self._validate_asset_references(record)
            self._append("Assets", record)
            return record

    def override_asset_period(
        self,
        asset_id: str,
        sequence: int,
        amount: Any,
        reason: str,
        *,
        as_of_date: date,
        expected_asset: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Persist one due/past-quarter override and rebalance later quarters."""
        with self._workbook_locks.ledger:
            current = self._find_row("Assets", asset_id)
            self._assert_expected_asset(current.values, expected_asset)
            if self._asset_postings(asset_id):
                raise StorageConflictError(
                    "Overrides are locked after depreciation is posted"
                )
            normalized = self._prepare_asset(
                current.values,
                asset_id=asset_id,
                created_at=current.values.get("created_at"),
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
                raise StorageValidationError(
                    "Override period is outside the asset life"
                )
            if full_schedule[sequence - 1].scheduled_date > as_of_date:
                raise StorageValidationError(
                    "Only due or past quarters can be overridden"
                )
            overrides = _decode_overrides(normalized["schedule_overrides"])
            if overrides and sequence < max(overrides):
                raise StorageConflictError(
                    "Earlier quarters are locked by the latest historical override"
                )
            overrides[sequence] = {
                "amount": _currency(amount, "Override amount"),
                "reason": _clean_text(reason, "Override reason", required=True),
            }
            merged = dict(current.values)
            merged["schedule_overrides"] = _normalize_overrides(overrides)
            updated = self._prepare_asset(
                merged,
                asset_id=asset_id,
                created_at=current.values.get("created_at"),
            )
            self._replace_row("Assets", current, updated)
            return updated

    @staticmethod
    def _assert_expected_asset(
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

    def edit_asset(
        self,
        asset_id: str,
        *,
        expected_asset: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        with self._workbook_locks.ledger:
            current = self._find_row("Assets", asset_id)
            self._assert_expected_asset(current.values, expected_asset)
            normalized_current = self._prepare_asset(
                current.values,
                asset_id=_clean_text(
                    current.values.get("id"), "Asset ID", required=True
                ),
                created_at=_clean_text(
                    current.values.get("created_at"),
                    "Asset created time",
                    required=True,
                ),
            )
            merged = dict(current.values)
            merged.update(changes)
            updated = self._prepare_asset(
                merged,
                asset_id=_clean_text(
                    current.values.get("id"), "Asset ID", required=True
                ),
                created_at=_clean_text(
                    current.values.get("created_at"),
                    "Asset created time",
                    required=True,
                ),
            )
            postings = self._asset_postings(asset_id)
            if postings or _decode_overrides(
                current.values.get("schedule_overrides", "")
            ):
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
                _iso_date(row.get("txn_date")) > updated["retired_date"]
                for row in postings
            ):
                raise StorageConflictError(
                    "Retirement cannot precede posted depreciation"
                )
            self._validate_asset_references(
                updated,
                allowed_missing_source_id=_clean_text(
                    current.values.get("source_transaction_id"),
                    "Source transaction",
                ),
            )
            self._replace_row("Assets", current, updated)
            return updated

    def remove_asset_period_override(
        self,
        asset_id: str,
        sequence: int,
        *,
        expected_asset: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        with self._workbook_locks.ledger:
            current = self._find_row("Assets", asset_id)
            self._assert_expected_asset(current.values, expected_asset)
            if self._asset_postings(asset_id):
                raise StorageConflictError(
                    "Overrides are locked after depreciation is posted"
                )
            overrides = _decode_overrides(current.values.get("schedule_overrides", ""))
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
            merged = dict(current.values)
            merged["schedule_overrides"] = _normalize_overrides(overrides)
            updated = self._prepare_asset(
                merged,
                asset_id=asset_id,
                created_at=current.values.get("created_at"),
            )
            self._replace_row("Assets", current, updated)
            return updated

    def retire_asset(
        self,
        asset_id: str,
        retired_date: date | str,
        *,
        expected_asset: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        return self.edit_asset(
            asset_id,
            expected_asset=expected_asset,
            status="retired",
            retired_date=retired_date,
        )

    def _asset_postings(self, asset_id: str) -> list[dict[str, str]]:
        asset_id = _clean_text(asset_id, "Asset ID", required=True)
        return [
            dict(row.values)
            for row in self._rows("Transactions", force_refresh=True)
            if row.values.get("source_type") == "depreciation"
            and row.values.get("source_id") == asset_id
        ]

    def post_due_depreciation(
        self,
        asset_id: str,
        through_date: date | str,
        *,
        expected_asset: Mapping[str, Any] | None = None,
    ) -> list[dict[str, str]]:
        """Explicitly post each pending quarter using one durable ledger row.

        The workbook ledger lock serializes application sessions. The existing
        append boundary reconciles uncertain responses by stable entry ID.
        Each successful row is independently durable if a later period fails.
        """
        through = _iso_date(through_date)
        with self._workbook_locks.ledger:
            current = self._find_row("Assets", asset_id)
            asset_id = _clean_text(current.values.get("id"), "Asset ID", required=True)
            self._assert_expected_asset(current.values, expected_asset)
            asset = self._prepare_asset(
                current.values,
                asset_id=asset_id,
                created_at=current.values.get("created_at"),
            )
            accounts = self._account_lookup(force_refresh=True)
            categories = self._category_lookup(force_refresh=True)
            validate_depreciation_accounts(
                asset, accounts, categories, required=True, active=True
            )
            transactions = [
                dict(row.values)
                for row in self._rows("Transactions", force_refresh=True)
            ]
            postings = [
                row
                for row in transactions
                if row.get("source_type") == "depreciation"
                and row.get("source_id") == asset_id
            ]
            validate_depreciation_history([asset], postings, accounts, categories)
            existing = {row["id"]: row for row in transactions}
            posted = []
            for period in asset_schedule(asset):
                if period.scheduled_date.isoformat() > through:
                    break
                entry_id = depreciation_entry_id(asset_id, period.sequence)
                if entry_id in existing:
                    existing_entry = existing[entry_id]
                    if (
                        existing_entry.get("source_type") != "depreciation"
                        or existing_entry.get("source_id") != asset_id
                    ):
                        raise StorageConflictError(
                            "Depreciation entry ID is already in use"
                        )
                    continue
                record = self._prepare_transaction(
                    dict(
                        txn_date=period.scheduled_date,
                        kind="Expense",
                        amount=period.depreciation_amount,
                        account_id=asset["accumulated_depreciation_account_id"],
                        category_id=asset["depreciation_expense_account_id"],
                        description=f"Asset depreciation · {asset['name']} · Quarter {period.sequence}",
                        reference=asset["reference"],
                    ),
                    transaction_id=entry_id,
                    _allow_zero_amount=True,
                )
                record.update(source_type="depreciation", source_id=asset_id)
                self._append("Transactions", record)
                posted.append(record)
            return posted

    def delete_asset(
        self,
        asset_id: str,
        *,
        expected_asset: Mapping[str, Any] | None = None,
    ) -> None:
        """Delete only assets without saved or posted depreciation history."""
        with self._workbook_locks.ledger:
            current = self._find_row("Assets", asset_id)
            self._assert_expected_asset(current.values, expected_asset)
            if self._asset_postings(asset_id) or _decode_overrides(
                current.values.get("schedule_overrides", "")
            ):
                raise StorageConflictError(
                    "Assets with saved depreciation history cannot be deleted"
                )
            original = dict(current.values)
            current_row = current
            worksheet = self._worksheet("Assets")

            def write() -> None:
                self._api(
                    lambda: worksheet.delete_rows(current_row.row_number),
                    retry_safe=False,
                )

            def state() -> str:
                try:
                    latest = self._find_row("Assets", asset_id)
                except StorageNotFoundError:
                    return "applied"
                return "unchanged" if latest.values == original else "ambiguous"

            def refresh() -> None:
                nonlocal current_row
                current_row = self._find_row("Assets", asset_id)
                if current_row.values != original:
                    raise StorageConflictError(
                        "The asset changed while deletion was being retried."
                    )

            self._write_with_uncertain_readback(
                "asset deletion",
                write,
                state,
                before_retry=refresh,
                invalidate=("Assets",),
            )


__all__ = ["ASSET_TYPES", "AssetsMixin"]
