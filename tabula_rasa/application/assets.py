"""Fixed-asset lifecycle and explicit depreciation posting workflows."""

from datetime import date
from uuid import uuid4

from tabula_rasa.asset import (
    prepare_asset,
    edit_asset,
    override_asset_period,
    remove_asset_period_override,
    _decode_overrides,
)
from tabula_rasa.depreciation_posting import asset_schedule
from tabula_rasa.errors import StorageConflictError
from tabula_rasa.ledger_validation import iso_date
from tabula_rasa.reference_data import clean_text

from .asset_contracts import AssetRepository
from .journals import JournalService


class AssetService:
    def __init__(self, repository: AssetRepository, *, journals: JournalService):
        self._repository = repository
        self._journals = journals

    def list(self, *, fresh=False):
        return self._repository.list(fresh=fresh)

    def create(self, *, asset_id=None, **data):
        identity = (
            clean_text(asset_id, "Asset ID", required=True)
            if asset_id is not None
            else str(uuid4())
        )
        return self._repository.create(prepare_asset(data, asset_id=identity))

    def update(self, asset_id, *, expected=None, **changes):
        return self._repository.update(
            clean_text(asset_id, "Asset ID", required=True),
            expected=expected,
            build=lambda current, postings: edit_asset(current, postings, changes),
        )

    def retire(self, asset_id, retired_date, *, expected=None):
        return self.update(
            asset_id, expected=expected, status="retired", retired_date=retired_date
        )

    def override(
        self, asset_id, sequence, amount, reason, *, as_of_date: date, expected=None
    ):
        as_of = date.fromisoformat(iso_date(as_of_date))
        return self._repository.update(
            clean_text(asset_id, "Asset ID", required=True),
            expected=expected,
            build=lambda current, postings: override_asset_period(
                current, postings, sequence, amount, reason, as_of
            ),
        )

    def remove_override(self, asset_id, sequence, *, expected=None):
        return self._repository.update(
            clean_text(asset_id, "Asset ID", required=True),
            expected=expected,
            build=lambda current, postings: remove_asset_period_override(
                current, postings, sequence
            ),
        )

    def schedule(self, asset):
        return asset_schedule(asset)

    def post_due(self, asset_id, through_date, *, expected=None):
        through = iso_date(through_date)
        return self._repository.post(
            clean_text(asset_id, "Asset ID", required=True),
            expected=expected,
            build=lambda asset, references, transactions: (
                self._journals.prepare_depreciation(
                    asset,
                    references,
                    transactions,
                    through=through,
                )
            ),
        )

    def delete(self, asset_id, *, expected=None):
        def validate(current, postings):
            if postings or _decode_overrides(current.get("schedule_overrides", "")):
                raise StorageConflictError(
                    "Assets with saved depreciation history cannot be deleted"
                )
            return current

        return self._repository.delete(
            clean_text(asset_id, "Asset ID", required=True),
            expected=expected,
            validate=validate,
        )
