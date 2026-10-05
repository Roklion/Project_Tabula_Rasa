"""Verified, idempotent receipt recovery from a Synology recovery copy."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
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
    MIXED_USE_SOURCE_TYPE,
    StorageError,
    decode_receipt_references,
)


class ReceiptRecoveryError(RuntimeError):
    """Raised when receipt recovery cannot safely begin."""


_MAX_RECONCILIATION_ATTEMPTS = 3


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
        reference.get(reference_field) == entry[entry_field]
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


def _plan_receipt_reconciliation(
    transactions: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[
    dict[str, list[Mapping[str, Any]]],
    list[bool | None],
]:
    transactions_by_id = {
        str(transaction["id"]): transaction for transaction in transactions
    }
    if len(transactions_by_id) != len(transactions):
        raise StorageError(
            "Receipt recovery found duplicate live transaction IDs."
        )
    references_by_transaction = {
        transaction_id: decode_receipt_references(
            transaction.get("receipt_references") or ""
        )
        for transaction_id, transaction in transactions_by_id.items()
    }
    reference_owners: dict[str, set[str]] = {}
    for transaction_id, references in references_by_transaction.items():
        for current_reference in references:
            reference_owners.setdefault(
                str(current_reference.get("id")), set()
            ).add(transaction_id)
    updates: dict[str, list[Mapping[str, Any]]] = {}
    outcomes: list[bool | None] = []

    for candidate in candidates:
        entry = candidate["entry"]
        reference = candidate["reference"]
        transaction_id = str(entry["transaction_id"])
        old_file_id = str(entry["old_drive_file_id"])
        confirmed_file_id = str(reference["id"])
        current_references = references_by_transaction.get(transaction_id)
        if current_references is None:
            outcomes.append(None)
            continue
        transaction = transactions_by_id[transaction_id]

        confirmed_reference_present = any(
            str(current_reference.get("id")) == confirmed_file_id
            and _reference_matches_entry(current_reference, entry)
            for current_reference in current_references
        )
        confirmed_reference_conflict = bool(
            reference_owners.get(confirmed_file_id, set()) - {transaction_id}
        )
        if confirmed_reference_conflict:
            outcomes.append(None)
            continue
        stale_old_reference_present = (
            old_file_id != confirmed_file_id
            and any(
                str(current_reference.get("id")) == old_file_id
                for current_reference in current_references
            )
        )
        if confirmed_reference_present and not stale_old_reference_present:
            if transaction.get("source_type") == MIXED_USE_SOURCE_TYPE:
                updates[transaction_id] = current_references
            outcomes.append(False)
            continue

        replacement_indexes = [
            index
            for index, current_reference in enumerate(current_references)
            if str(current_reference.get("id"))
            in {old_file_id, confirmed_file_id}
            or (
                current_reference.get("receipt_id")
                == reference["receipt_id"]
                and current_reference.get("sha256") == reference["sha256"]
            )
        ]
        if not replacement_indexes:
            outcomes.append(None)
            continue
        first_index = replacement_indexes[0]
        retained = [
            current_reference
            for index, current_reference in enumerate(current_references)
            if index not in replacement_indexes
        ]
        retained.insert(first_index, reference)
        for current_file_id in {
            str(current_reference.get("id"))
            for current_reference in current_references
        }:
            owners = reference_owners[current_file_id]
            owners.discard(transaction_id)
            if not owners:
                del reference_owners[current_file_id]
        for retained_reference in retained:
            reference_owners.setdefault(
                str(retained_reference.get("id")), set()
            ).add(transaction_id)
        references_by_transaction[transaction_id] = retained
        updates[transaction_id] = retained
        outcomes.append(True)

    return updates, outcomes


def _record_reconciliation_outcomes(
    report: dict[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    outcomes: Sequence[bool | None],
) -> None:
    for candidate, remapped in zip(candidates, outcomes):
        entry = candidate["entry"]
        if remapped is None:
            _issue(report, entry, "errors")
            continue
        if remapped:
            report["references_remapped"] += 1
        report["reused" if candidate["reused"] else "restored"] += 1


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
    reconciliation_candidates: list[dict[str, Any]] = []
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
                reconciliation_candidates.append(
                    {
                        "entry": entry,
                        "reference": reference,
                        "reused": reused,
                    }
                )
                continue
            else:
                report["unreferenced_preserved"] += 1
        except GoogleDriveConflictError:
            _issue(report, entry, "conflicts")
            continue
        except (GoogleDriveError, ReceiptManifestError, StorageError):
            _issue(report, entry, "errors")
            continue
        report["reused" if reused else "restored"] += 1

    if reconciliation_candidates:
        base_transactions = transactions
        for _attempt in range(_MAX_RECONCILIATION_ATTEMPTS):
            try:
                updates, outcomes = _plan_receipt_reconciliation(
                    base_transactions,
                    reconciliation_candidates,
                )
                applied, fresh_transactions = (
                    storage.apply_receipt_recovery_plan(
                        base_transactions,
                        updates,
                    )
                )
            except StorageError:
                outcomes = [None] * len(reconciliation_candidates)
                break
            if applied:
                break
            base_transactions = fresh_transactions
        else:
            outcomes = [None] * len(reconciliation_candidates)
        _record_reconciliation_outcomes(
            report,
            reconciliation_candidates,
            outcomes,
        )
    return report
