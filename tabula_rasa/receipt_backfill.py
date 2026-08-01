"""Idempotent integrity-metadata migration for legacy receipt files."""

from __future__ import annotations

from typing import Any

from tabula_rasa.google_drive import GoogleDriveClient
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    StorageError,
)


def backfill_profile_receipts(
    storage: GoogleSheetsStorage,
    drive: GoogleDriveClient,
    *,
    profile_key: str,
    folder_id: str,
) -> dict[str, Any]:
    """Backfill legacy Drive metadata and refresh active Sheets references.

    Receipts that already contain valid integrity metadata are never downloaded.
    Failures are reported per file so a later startup or command-line run can
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
            storage.link_transaction_receipt(
                transaction_id,
                reference=reference,
            )
        except StorageError as error:
            report["errors"].append(
                {"file_id": file_id, "error": str(error)}
            )
            continue
        report["references_updated"] += 1
    return report
