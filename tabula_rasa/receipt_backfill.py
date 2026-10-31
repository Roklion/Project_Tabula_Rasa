"""Fresh, profile-scoped receipt preparation for backup creation."""

from __future__ import annotations

from typing import Any

from tabula_rasa.google_drive import GoogleDriveClient
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    build_receipt_manifest,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    MIXED_USE_SOURCE_TYPE,
    StorageError,
)


class ReceiptPreparationError(RuntimeError):
    """Raised when receipt preparation cannot safely precede a backup."""


def prepare_profile_receipts(
    storage: GoogleSheetsStorage,
    drive: GoogleDriveClient,
    *,
    profile_key: str,
    folder_id: str,
) -> dict[str, Any]:
    """Refresh receipt metadata and active Sheets references before backup.

    Receipts that already contain valid integrity metadata are never downloaded.
    Failures are reported per file so a later command-line run can
    safely resume the remaining work.
    """
    transactions = storage.list_transactions(_force_refresh=True)
    transactions_by_id = {
        str(transaction["id"]): transaction for transaction in transactions
    }
    associations: dict[str, str] = {}
    for transaction in transactions:
        for reference in decode_receipt_references(
            transaction.get("receipt_references", "")
        ):
            associations[str(reference["id"])] = str(transaction["id"])

    receipts = drive.list_profile_receipts(
        profile_key=profile_key,
        folder_id=folder_id,
        _force_refresh=True,
    )
    report: dict[str, Any] = {
        "examined": len(receipts),
        "drive_backfilled": 0,
        "references_updated": 0,
        "errors": [],
    }
    for receipt in receipts:
        file_id = str(receipt.get("id") or "")
        try:
            reference = receipt_reference_from_drive_file(receipt)
        except ReceiptManifestError:
            try:
                updated = drive.backfill_receipt_checksum(
                    profile_key=profile_key,
                    folder_id=folder_id,
                    file_id=file_id,
                )
                reference = receipt_reference_from_drive_file(updated)
            except (RuntimeError, ReceiptManifestError) as error:
                report["errors"].append(
                    {"file_id": file_id, "error": str(error)}
                )
                continue
            report["drive_backfilled"] += 1
        transaction_id = associations.get(file_id)
        if transaction_id is None:
            continue
        current_transaction = transactions_by_id[transaction_id]
        current_reference = next(
            item
            for item in decode_receipt_references(
                current_transaction.get("receipt_references", "")
            )
            if item["id"] == file_id
        )
        if current_reference == reference:
            continue
        try:
            source_type = str(current_transaction.get("source_type") or "")
            source_id = str(current_transaction.get("source_id") or "")
            if source_type == MIXED_USE_SOURCE_TYPE and source_id:
                storage.remap_mixed_use_receipt(
                    source_id,
                    old_file_id=file_id,
                    reference=reference,
                )
            else:
                storage.remap_transaction_receipt(
                    transaction_id,
                    old_file_id=file_id,
                    reference=reference,
                )
        except StorageError as error:
            report["errors"].append(
                {"file_id": file_id, "error": str(error)}
            )
            continue
        report["references_updated"] += 1
    return report


def prepare_backup_receipt_manifest(
    storage: GoogleSheetsStorage,
    drive: GoogleDriveClient,
    *,
    profile_key: str,
    folder_id: str,
) -> dict[str, Any]:
    """Prepare receipts and return a newly read, validated backup inventory.

    Confirmed Drive and Sheets migrations are deliberately retained on a
    partial failure: they are idempotent and make the next backup attempt
    smaller. The backup itself is not created until every receipt is ready.
    """
    report = prepare_profile_receipts(
        storage,
        drive,
        profile_key=profile_key,
        folder_id=folder_id,
    )
    if report["errors"]:
        raise ReceiptPreparationError(
            "Receipt preparation is incomplete; no backup was created. "
            "Retry the backup after resolving the reported receipt errors."
        )
    # Writes above can change both sources. Re-read them before constructing
    # the manifest so it represents the confirmed current state.
    transactions = storage.list_transactions(_force_refresh=True)
    receipts = drive.list_profile_receipts(
        profile_key=profile_key,
        folder_id=folder_id,
        _force_refresh=True,
    )
    return build_receipt_manifest(profile_key, transactions, receipts)
