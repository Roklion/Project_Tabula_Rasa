from __future__ import annotations

import hashlib

from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


def make_reference(index: int, content: bytes) -> dict[str, object]:
    return {
        "id": f"oldreceipt{index:02d}",
        "name": f"statement ({index}).pdf",
        "receipt_id": hashlib.sha256(f"receipt-{index}".encode("utf-8")).hexdigest()[
            :32
        ],
        "original_filename": f"original-{index}.pdf",
        "mime_type": "application/pdf",
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def make_drive_file(
    reference: dict[str, object],
    *,
    file_id: str | None = None,
    profile_key: str = "north",
) -> dict[str, object]:
    return {
        "id": file_id or reference["id"],
        "name": reference["name"],
        "mimeType": reference["mime_type"],
        "size": str(reference["byte_size"]),
        "appProperties": {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": reference["receipt_id"],
            "tabulaRasaSha256": reference["sha256"],
            "tabulaRasaOriginalName": reference["original_filename"],
            "tabulaRasaOriginalFileId": reference["id"],
        },
    }


def backup_with_receipts(
    references: list[dict[str, object]],
    *,
    unreferenced: list[dict[str, object]] | None = None,
    profile_key: str = "north",
) -> tuple[bytes, GoogleSheetsStorage, str]:
    source = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    account = source.create_account("Checking", "Bank")
    category = source.create_category("Sales", "Income")
    transaction = source.create_transaction(
        txn_date="2026-07-31",
        kind="Income",
        amount=10,
        account_id=account["id"],
        category_id=category["id"],
    )
    for receipt_reference in references:
        source.link_transaction_receipt(
            transaction["id"],
            reference=receipt_reference,
        )
    all_references = [*references, *(unreferenced or [])]
    manifest = build_receipt_manifest(
        profile_key,
        source.list_transactions(_force_refresh=True),
        [
            make_drive_file(receipt_reference, profile_key=profile_key)
            for receipt_reference in all_references
        ],
    )
    backup = source.export_backup_zip(manifest)
    target = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _delay: None)
    target.restore_backup_zip(backup)
    return backup, target, transaction["id"]
