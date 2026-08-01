"""Verified, idempotent receipt recovery from a Synology recovery copy."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tabula_rasa.google_drive import (
    GoogleDriveClient,
    GoogleDriveConflictError,
    GoogleDriveError,
)
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
    receipt_reference_from_drive_file,
    validate_receipt_manifest,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageError,
    decode_receipt_references,
)


class ReceiptRecoveryError(RuntimeError):
    """Raised when receipt recovery cannot safely begin."""


def _preflight_transactions(
    manifest: Mapping[str, Any],
    transactions: list[dict[str, str]],
) -> None:
    transactions_by_id = {transaction["id"]: transaction for transaction in transactions}
    if len(transactions_by_id) != len(transactions):
        raise ReceiptRecoveryError(
            "Receipt recovery found duplicate live transaction IDs."
        )
    for entry in manifest["receipts"]:
        if entry["reference_state"] != "referenced":
            continue
        transaction = transactions_by_id.get(str(entry["transaction_id"]))
        if transaction is None:
            raise ReceiptRecoveryError(
                "Receipt recovery requires every referenced transaction to exist."
            )
        references = decode_receipt_references(
            transaction.get("receipt_references", "")
        )
        if not any(
            reference["id"] == entry["old_drive_file_id"]
            or (
                reference.get("receipt_id") == entry["receipt_id"]
                and reference.get("sha256") == entry["sha256"]
            )
            for reference in references
        ):
            raise ReceiptRecoveryError(
                "A referenced transaction does not contain the manifest receipt."
            )


def _reference_matches_entry(
    reference: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> bool:
    return all(
        reference[reference_field] == entry[entry_field]
        for reference_field, entry_field in (
            ("name", "stored_filename"),
            ("receipt_id", "receipt_id"),
            ("original_filename", "original_filename"),
            ("mime_type", "mime_type"),
            ("byte_size", "byte_size"),
            ("sha256", "sha256"),
        )
    )


def _issue(report: dict[str, Any], entry: Mapping[str, Any], status: str) -> None:
    report[status] += 1
    report["skipped"] += 1
    report["issues"].append(
        {"receipt_id": str(entry["receipt_id"]), "status": status}
    )


def recover_receipts_from_synology(
    backup: bytes,
    receipt_directory: Path,
    *,
    profile_key: str,
    folder_id: str,
    storage: GoogleSheetsStorage,
    drive: GoogleDriveClient,
) -> dict[str, Any]:
    """Recover verified receipt bytes and remap transaction references."""
    manifest = storage.receipt_manifest_from_backup(backup)
    if manifest is None:
        raise ReceiptRecoveryError(
            "This is a ledger-only backup without a recoverable receipt inventory."
        )
    try:
        manifest = validate_receipt_manifest(
            manifest,
            expected_profile_key=profile_key,
        )
    except ReceiptManifestError as exc:
        raise ReceiptRecoveryError(str(exc)) from exc
    transactions = storage.list_transactions(_force_refresh=True)
    _preflight_transactions(manifest, transactions)
    try:
        recovery_root = receipt_directory.resolve(strict=True)
    except OSError as exc:
        raise ReceiptRecoveryError(
            "The Synology receipt recovery directory is unavailable."
        ) from exc
    if not recovery_root.is_dir():
        raise ReceiptRecoveryError(
            "The Synology receipt recovery path is not a directory."
        )

    report: dict[str, Any] = {
        "total": len(manifest["receipts"]),
        "restored": 0,
        "reused": 0,
        "references_remapped": 0,
        "unreferenced_preserved": 0,
        "missing": 0,
        "corrupt": 0,
        "conflicts": 0,
        "errors": 0,
        "skipped": 0,
        "issues": [],
    }
    for entry in manifest["receipts"]:
        candidate = recovery_root / str(entry["stored_filename"])
        try:
            resolved_candidate = candidate.resolve(strict=True)
            if resolved_candidate.parent != recovery_root or not resolved_candidate.is_file():
                raise OSError
            if resolved_candidate.stat().st_size != entry["byte_size"]:
                _issue(report, entry, "corrupt")
                continue
            content = resolved_candidate.read_bytes()
        except FileNotFoundError:
            _issue(report, entry, "missing")
            continue
        except OSError:
            _issue(report, entry, "corrupt")
            continue
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            _issue(report, entry, "corrupt")
            continue
        try:
            restored_file, reused = drive.restore_receipt(
                profile_key=profile_key,
                folder_id=folder_id,
                stored_filename=str(entry["stored_filename"]),
                original_filename=str(entry["original_filename"]),
                content=content,
                mime_type=str(entry["mime_type"]),
                receipt_id=str(entry["receipt_id"]),
                sha256=str(entry["sha256"]),
                old_file_id=str(entry["old_drive_file_id"]),
            )
            reference = receipt_reference_from_drive_file(restored_file)
            if not _reference_matches_entry(reference, entry):
                raise ReceiptManifestError(
                    "Recovered receipt metadata does not match the manifest"
                )
            if entry["reference_state"] == "referenced":
                storage.remap_transaction_receipt(
                    str(entry["transaction_id"]),
                    old_file_id=str(entry["old_drive_file_id"]),
                    reference=reference,
                )
                report["references_remapped"] += 1
            else:
                report["unreferenced_preserved"] += 1
        except GoogleDriveConflictError:
            _issue(report, entry, "conflicts")
            continue
        except (GoogleDriveError, ReceiptManifestError, StorageError):
            _issue(report, entry, "errors")
            continue
        report["reused" if reused else "restored"] += 1
    return report
