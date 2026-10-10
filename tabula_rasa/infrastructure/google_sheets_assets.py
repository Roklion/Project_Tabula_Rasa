"""Sheet mapping, workbook coordination, and recovery for asset mutations."""

from tabula_rasa.asset import assert_expected_asset
from tabula_rasa.errors import StorageConflictError, StorageNotFoundError
from tabula_rasa.transaction import TransactionReferences


class GoogleSheetsAssetRepository:
    def __init__(self, storage):
        self._storage = storage

    def list(self, *, fresh=False):
        return self._storage.list_assets(_force_refresh=fresh)

    def read(self, asset_id, *, fresh=False):
        with self._storage._workbook_locks.ledger:
            for asset in self.list(fresh=fresh):
                if asset['id'] == asset_id:
                    return asset, self._storage._asset_postings(asset_id)
        raise StorageNotFoundError('Asset no longer exists')

    def create(self, record):
        storage = self._storage
        with storage._workbook_locks.ledger:
            if any(
                row.values.get("id") == record["id"]
                for row in storage._rows("Assets", force_refresh=True)
            ):
                raise StorageConflictError("Asset ID is already in use")
            storage._validate_asset_references(record)
            storage._append("Assets", record)
            return record

    def update(self, asset_id, *, expected, build):
        storage = self._storage
        with storage._workbook_locks.ledger:
            current = storage._find_row("Assets", asset_id)
            assert_expected_asset(current.values, expected)
            record = dict(
                build(dict(current.values), storage._asset_postings(asset_id))
            )
            storage._validate_asset_references(
                record,
                allowed_missing_source_id=current.values.get(
                    "source_transaction_id", ""
                ),
            )
            storage._replace_row("Assets", current, record)
            return record

    def post(self, asset_id, *, expected, build):
        storage = self._storage
        with storage._workbook_locks.ledger:
            current = storage._find_row("Assets", asset_id)
            assert_expected_asset(current.values, expected)
            references = TransactionReferences(
                storage._account_lookup(force_refresh=True),
                storage._category_lookup(force_refresh=True),
                storage._payee_lookup(force_refresh=True),
                storage._tag_lookup(force_refresh=True),
            )
            transactions = [
                dict(row.values)
                for row in storage._rows("Transactions", force_refresh=True)
            ]
            records = [
                storage._serialize_transaction(record)
                for record in build(dict(current.values), references, transactions)
            ]
            storage._append_many("Transactions", records)
            return records

    def delete(self, asset_id, *, expected, validate):
        storage = self._storage
        with storage._workbook_locks.ledger:
            current = storage._find_row("Assets", asset_id)
            assert_expected_asset(current.values, expected)
            validate(dict(current.values), storage._asset_postings(asset_id))
            original = dict(current.values)
            worksheet = storage._worksheet("Assets")

            def write():
                storage._api(
                    lambda: worksheet.delete_rows(current.row_number), retry_safe=False
                )

            def state():
                try:
                    latest = storage._find_row("Assets", asset_id)
                except StorageNotFoundError:
                    return "applied"
                return "unchanged" if latest.values == original else "ambiguous"

            def refresh():
                nonlocal current
                current = storage._find_row("Assets", asset_id)
                if current.values != original:
                    raise StorageConflictError(
                        "The asset changed while deletion was being retried."
                    )

            storage._write_with_uncertain_readback(
                "asset deletion",
                write,
                state,
                before_retry=refresh,
                invalidate=("Assets",),
            )
