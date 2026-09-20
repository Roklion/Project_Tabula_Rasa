"""Simple Ledger depreciation semantics and durable period provenance.

Expense Categories are the Simple Ledger debit accounts. An Expense credits
its account_id; using an Other/Asset account therefore records non-cash
accumulated depreciation without changing the ledger's accounting model.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import json
from uuid import NAMESPACE_URL, uuid5

from tabula_rasa.depreciation import straight_line_schedule

from .errors import StorageValidationError


DEPRECIATION_SOURCE_TYPE = "depreciation"


def depreciation_entry_id(asset_id: str, sequence: int) -> str:
    """Stable identity for one asset quarter, independent of posting date."""
    return str(uuid5(NAMESPACE_URL, f"tabula-rasa:depreciation:{asset_id}:{sequence}"))


def asset_schedule(asset):
    try:
        return straight_line_schedule(
            asset["cost_basis"],
            asset["salvage_value"],
            date.fromisoformat(asset["depreciation_start_date"]),
            int(asset["useful_life_quarters"]),
            retired_date=date.fromisoformat(asset["retired_date"])
            if asset.get("retired_date")
            else None,
            overrides={
                int(key): value
                for key, value in json.loads(
                    asset.get("schedule_overrides") or "{}"
                ).items()
            },
        )
    except (ValueError, KeyError, TypeError, ArithmeticError):
        raise StorageValidationError(
            "Asset schedule is invalid; inspect Assets before posting"
        ) from None


def validate_depreciation_accounts(
    asset, accounts, categories, *, required=False, active=False
):
    expense_id = asset.get("depreciation_expense_account_id", "")
    offset_id = asset.get("accumulated_depreciation_account_id", "")
    if required and (not expense_id or not offset_id):
        raise StorageValidationError(
            "Both depreciation accounts are required before posting"
        )
    if not expense_id and not offset_id:
        return
    if expense_id and (
        expense_id not in categories or categories[expense_id]["kind"] != "Expense"
    ):
        raise StorageValidationError(
            "Select a Depreciation expense account (Expense category)"
        )
    if offset_id:
        offset = accounts.get(offset_id, {})
        if offset.get("type") != "Other" or offset.get("classification") != "Asset":
            raise StorageValidationError(
                "Accumulated depreciation must use an Other account classified as Asset"
            )
        if active and str(offset.get("active")).lower() not in {"true", "1"}:
            raise StorageValidationError("Accumulated depreciation account is inactive")


def validate_depreciation_history(assets, transactions, accounts, categories):
    """Validate links once for live reads and backup/restore alike."""
    assets = list(assets)
    by_id = {asset["id"]: asset for asset in assets}
    for asset in assets:
        validate_depreciation_accounts(asset, accounts, categories)
    periods = {}
    seen = set()
    for transaction in transactions:
        source_type = str(transaction.get("source_type") or "").strip().lower()
        if source_type != DEPRECIATION_SOURCE_TYPE:
            continue
        asset_id = transaction.get("source_id")
        asset = by_id.get(asset_id)
        if asset is None:
            raise StorageValidationError("Depreciation entry has no asset source")
        if asset_id not in periods:
            validate_depreciation_accounts(asset, accounts, categories, required=True)
            periods[asset_id] = {
                depreciation_entry_id(asset_id, period.sequence): period
                for period in asset_schedule(asset)
            }
        entry_id = transaction.get("id")
        period = periods[asset_id].get(entry_id)
        if period is None or entry_id in seen:
            raise StorageValidationError(
                "Depreciation period identity is invalid or duplicated"
            )
        seen.add(entry_id)
        try:
            amount = Decimal(str(transaction.get("amount")))
        except InvalidOperation:
            raise StorageValidationError("Depreciation amount is invalid") from None
        if (
            not amount.is_finite()
            or transaction.get("kind") != "Expense"
            or transaction.get("account_id")
            != asset.get("accumulated_depreciation_account_id")
            or transaction.get("category_id")
            != asset.get("depreciation_expense_account_id")
            or transaction.get("to_account_id")
            or transaction.get("txn_date") != period.scheduled_date.isoformat()
            or amount != period.depreciation_amount
            or transaction.get("recurring_schedule_id")
        ):
            raise StorageValidationError(
                "Depreciation entry conflicts with its asset schedule; inspect it before posting"
            )
