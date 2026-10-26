"""Read and validate frozen asset history for format-13 recovery."""
from typing import Any
from tabula_rasa.asset import ASSET_TYPES, prepare_asset
from tabula_rasa.asset import _decode_overrides as _decode_overrides, _whole_quarters as _whole_quarters
from tabula_rasa.errors import StorageValidationError
from .validation import _clean_text, _normalize_tag_ids

class AssetsMixin:
    """Read boundary for retained depreciable asset history."""

    _prepare_asset = staticmethod(prepare_asset)


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


__all__ = ["ASSET_TYPES", "AssetsMixin"]
