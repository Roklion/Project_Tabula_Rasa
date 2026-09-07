"""Move legacy Drive-only receipt associations into the current workbook."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import load_business_profiles, select_profile_secrets
from tabula_rasa.google_drive import GoogleDriveClient, load_oauth_config
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    receipt_reference_from_drive_file,
)
from tabula_rasa.storage import (
    decode_receipt_references,
    GoogleSheetsStorage,
    MIXED_USE_SOURCE_TYPE,
)


def migrate_receipt_associations(
    storage: GoogleSheetsStorage,
    drive: GoogleDriveClient,
    *,
    profile_key: str,
    folder_id: str,
) -> dict[str, int]:
    """Convert blank legacy receipt cells using their old Drive association."""
    transactions = storage.list_transactions(_force_refresh=True)
    transactions_by_id = {
        str(transaction["id"]): transaction for transaction in transactions
    }
    linked_file_ids = {
        str(reference["id"])
        for transaction in transactions
        for reference in decode_receipt_references(
            transaction.get("receipt_references", "")
        )
    }
    pending: dict[str, list[dict[str, Any]]] = {}
    backfilled = 0
    for receipt in drive.list_profile_receipts(
        profile_key=profile_key,
        folder_id=folder_id,
        _force_refresh=True,
    ):
        file_id = str(receipt.get("id") or "")
        if not file_id or file_id in linked_file_ids:
            continue
        properties = receipt.get("appProperties")
        transaction_id = (
            str(properties.get("tabulaRasaTransaction") or "")
            if isinstance(properties, Mapping)
            else ""
        )
        transaction = transactions_by_id.get(transaction_id)
        if transaction is None or str(transaction.get("receipt_references", "")) != "":
            continue
        try:
            reference = receipt_reference_from_drive_file(receipt)
        except ReceiptManifestError:
            receipt = drive.backfill_receipt_checksum(
                profile_key=profile_key,
                folder_id=folder_id,
                file_id=file_id,
            )
            reference = receipt_reference_from_drive_file(receipt)
            backfilled += 1
        pending.setdefault(transaction_id, []).append(reference)

    migrated = 0
    for transaction_id, references in pending.items():
        transaction = next(
            (
                item
                for item in storage.list_transactions(_force_refresh=True)
                if str(item.get("id") or "") == transaction_id
            ),
            None,
        )
        if (
            transaction is None
            or str(transaction.get("receipt_references", "")) != ""
        ):
            continue
        source_id = str(transaction.get("source_id") or "")
        if (
            str(transaction.get("source_type") or "") == MIXED_USE_SOURCE_TYPE
            and source_id
        ):
            source = next(
                (
                    item
                    for item in storage.list_mixed_use_expense_sources(
                        _force_refresh=True
                    )
                    if str(item.get("id") or "") == source_id
                ),
                None,
            )
            if (
                source is None
                or str(source.get("receipt_references", "")) != ""
            ):
                continue
            storage.set_mixed_use_receipt_references(
                source_id,
                references,
                expected_source=source,
            )
        else:
            storage.set_transaction_receipt_references(
                transaction_id,
                references,
            )
        migrated += len(references)
    return {"associations_migrated": migrated, "checksums_backfilled": backfilled}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Move legacy tabulaRasaTransaction Drive associations into one "
            "already-migrated current workbook"
        )
    )
    parser.add_argument(
        "--secrets",
        type=Path,
        default=PROJECT_ROOT / ".streamlit" / "secrets.toml",
    )
    parser.add_argument("--profile", help="Business profile key to migrate")
    args = parser.parse_args()

    all_secrets = load_business_profile_document(args.secrets)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    profile_key = args.profile or profiles[0].key
    profile_secrets = select_profile_secrets(all_secrets, profile_key)
    drive_settings = profile_secrets.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    if not isinstance(receipt_folder, Mapping) or not receipt_folder.get("id"):
        raise SystemExit("The selected profile has no configured receipt folder")

    report = migrate_receipt_associations(
        GoogleSheetsStorage.from_secrets(profile_secrets),
        GoogleDriveClient(load_oauth_config(all_secrets), drive_settings),
        profile_key=profile_key,
        folder_id=str(receipt_folder["id"]),
    )
    print(
        "Legacy receipt migration complete: "
        f"associations={report['associations_migrated']} "
        f"checksums={report['checksums_backfilled']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
