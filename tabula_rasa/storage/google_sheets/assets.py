"""Sheets asset reads and compatibility facade for the asset service."""
from typing import Any, Mapping
from datetime import date
from tabula_rasa.asset import ASSET_TYPES, prepare_asset, assert_expected_asset
from tabula_rasa.asset import _decode_overrides as _decode_overrides, _whole_quarters as _whole_quarters
from tabula_rasa.errors import StorageValidationError, StorageNotFoundError
from .validation import _clean_text, _normalize_tag_ids
from tabula_rasa.depreciation_posting import validate_depreciation_accounts

class AssetsMixin:
    """CRUD boundary for individually tracked depreciable assets."""

    _prepare_asset = staticmethod(prepare_asset)

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

    def _asset_service(self):
        from tabula_rasa.application.assets import AssetService
        from tabula_rasa.application.journals import JournalService
        from tabula_rasa.infrastructure.google_sheets_assets import GoogleSheetsAssetRepository
        from tabula_rasa.infrastructure.google_sheets import GoogleSheetsJournalRepository
        return AssetService(GoogleSheetsAssetRepository(self), journals=JournalService(GoogleSheetsJournalRepository(self)))

    def create_asset(self, **data):
        return self._asset_service().create(**data)

    def override_asset_period(self, asset_id, sequence, amount, reason, *, as_of_date, expected_asset=None):
        return self._asset_service().override(asset_id, sequence, amount, reason, as_of_date=as_of_date, expected=expected_asset)

    _assert_expected_asset = staticmethod(assert_expected_asset)

    def edit_asset(self, asset_id, *, expected_asset=None, **changes):
        return self._asset_service().update(asset_id, expected=expected_asset, **changes)

    def remove_asset_period_override(self, asset_id, sequence, *, expected_asset=None):
        return self._asset_service().remove_override(asset_id, sequence, expected=expected_asset)

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
            if str(row.values.get("source_type") or "").strip().lower()
            == "depreciation"
            and str(row.values.get("source_id") or "").strip() == asset_id
        ]

    def post_due_depreciation(self, asset_id, through_date, *, expected_asset=None):
        return self._asset_service().post_due(asset_id, through_date, expected=expected_asset)

    def delete_asset(self, asset_id, *, expected_asset=None):
        return self._asset_service().delete(asset_id, expected=expected_asset)


__all__ = ["ASSET_TYPES", "AssetsMixin"]
