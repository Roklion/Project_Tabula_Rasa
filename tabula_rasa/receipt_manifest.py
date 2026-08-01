"""Validated receipt integrity metadata shared by backup and recovery flows."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any


RECEIPT_MANIFEST_SCHEMA_VERSION = 1
PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
DRIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
RECEIPT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
RICH_REFERENCE_FIELDS = {
    "id",
    "name",
    "receipt_id",
    "original_filename",
    "mime_type",
    "byte_size",
    "sha256",
}


class ReceiptManifestError(ValueError):
    """Raised when receipt integrity metadata is absent, unsafe, or inconsistent."""


def _text(
    value: object,
    label: str,
    *,
    maximum: int,
    required: bool = True,
) -> str:
    text = str(value or "").strip()
    if (
        (required and not text)
        or len(text) > maximum
        or any(ord(character) < 32 for character in text)
    ):
        raise ReceiptManifestError(f"{label} is invalid")
    return text


def _filename(value: object, label: str, *, required: bool = True) -> str:
    filename = _text(value, label, maximum=255, required=required)
    if filename and (
        filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or filename != filename.strip(" .")
    ):
        raise ReceiptManifestError(f"{label} is unsafe")
    return filename


def _byte_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ReceiptManifestError("Receipt byte size is invalid")
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise ReceiptManifestError("Receipt byte size is invalid") from exc
    if size <= 0 or str(value).strip() != str(size):
        raise ReceiptManifestError("Receipt byte size is invalid")
    return size


def _timestamp(value: object, label: str) -> str:
    timestamp = _text(value, label, maximum=64, required=False)
    if not timestamp:
        return ""
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptManifestError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ReceiptManifestError(f"{label} is invalid")
    return timestamp


def validate_receipt_reference(
    value: object,
    *,
    allow_legacy: bool = True,
) -> dict[str, Any]:
    """Return one validated legacy or integrity-rich transaction reference."""
    if not isinstance(value, Mapping):
        raise ReceiptManifestError("Transaction receipt reference is invalid")
    fields = set(value)
    if fields == {"id", "name"} and allow_legacy:
        file_id = _text(value.get("id"), "Receipt file ID", maximum=256)
        if not DRIVE_ID_PATTERN.fullmatch(file_id):
            raise ReceiptManifestError("Receipt file ID is invalid")
        return {
            "id": file_id,
            "name": _filename(value.get("name"), "Receipt stored filename"),
        }
    if fields != RICH_REFERENCE_FIELDS:
        raise ReceiptManifestError("Transaction receipt reference is invalid")
    file_id = _text(value.get("id"), "Receipt file ID", maximum=256)
    receipt_id = _text(value.get("receipt_id"), "Receipt identity", maximum=32)
    sha256 = _text(value.get("sha256"), "Receipt SHA-256", maximum=64)
    if not DRIVE_ID_PATTERN.fullmatch(file_id):
        raise ReceiptManifestError("Receipt file ID is invalid")
    if not RECEIPT_ID_PATTERN.fullmatch(receipt_id):
        raise ReceiptManifestError("Receipt identity is invalid")
    if not SHA256_PATTERN.fullmatch(sha256):
        raise ReceiptManifestError("Receipt SHA-256 is invalid")
    return {
        "id": file_id,
        "name": _filename(value.get("name"), "Receipt stored filename"),
        "receipt_id": receipt_id,
        "original_filename": _filename(
            value.get("original_filename"),
            "Receipt original filename",
        ),
        "mime_type": _text(
            value.get("mime_type"),
            "Receipt MIME type",
            maximum=255,
        ),
        "byte_size": _byte_size(value.get("byte_size")),
        "sha256": sha256,
    }


def decode_receipt_reference_list(value: object) -> list[dict[str, Any]]:
    """Decode and validate a transaction cell containing receipt references."""
    if value is None or value == "":
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise ReceiptManifestError(
            "Transaction receipt references are unreadable"
        ) from exc
    if not isinstance(parsed, list) or len(parsed) > 100:
        raise ReceiptManifestError("Transaction receipt references are invalid")
    references = [validate_receipt_reference(item) for item in parsed]
    file_ids = [str(item["id"]) for item in references]
    if len(file_ids) != len(set(file_ids)):
        raise ReceiptManifestError("Transaction receipt references are duplicated")
    rich_identities = [
        (str(item["receipt_id"]), str(item["sha256"]))
        for item in references
        if "receipt_id" in item
    ]
    if len(rich_identities) != len(set(rich_identities)):
        raise ReceiptManifestError("Transaction receipt references are duplicated")
    return references


def receipt_reference_from_drive_file(file: Mapping[str, Any]) -> dict[str, Any]:
    """Build an integrity-rich transaction reference from one Drive file."""
    properties = file.get("appProperties")
    if not isinstance(properties, Mapping):
        raise ReceiptManifestError("Receipt is missing private integrity metadata")
    return validate_receipt_reference(
        {
            "id": file.get("id"),
            "name": file.get("name"),
            "receipt_id": properties.get("tabulaRasaReceiptId"),
            "original_filename": properties.get("tabulaRasaOriginalName")
            or file.get("name"),
            "mime_type": file.get("mimeType") or "application/octet-stream",
            "byte_size": file.get("size"),
            "sha256": properties.get("tabulaRasaSha256"),
        },
        allow_legacy=False,
    )


def _manifest_entry(
    reference: Mapping[str, Any],
    file: Mapping[str, Any],
    *,
    transaction_id: str | None,
) -> dict[str, Any]:
    state = "referenced" if transaction_id is not None else "unreferenced"
    return {
        "schema_version": RECEIPT_MANIFEST_SCHEMA_VERSION,
        "receipt_id": reference["receipt_id"],
        "reference_state": state,
        "transaction_id": transaction_id,
        "stored_filename": reference["name"],
        "original_filename": reference["original_filename"],
        "mime_type": reference["mime_type"],
        "byte_size": reference["byte_size"],
        "sha256": reference["sha256"],
        "old_drive_file_id": reference["id"],
        "drive_created_time": str(file.get("createdTime") or ""),
        "drive_modified_time": str(file.get("modifiedTime") or ""),
    }


def build_receipt_manifest(
    profile_key: str,
    transactions: Iterable[Mapping[str, Any]],
    drive_files: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a complete profile-scoped inventory from Sheets and Drive data."""
    if not PROFILE_KEY_PATTERN.fullmatch(str(profile_key)):
        raise ReceiptManifestError("Business profile key is invalid")
    files_by_id: dict[str, Mapping[str, Any]] = {}
    for file in drive_files:
        properties = file.get("appProperties")
        if (
            not isinstance(properties, Mapping)
            or properties.get("tabulaRasaKind") != "receipt"
            or properties.get("tabulaRasaProfile") != profile_key
        ):
            raise ReceiptManifestError(
                "Receipt inventory contains a file from another profile"
            )
        reference = receipt_reference_from_drive_file(file)
        file_id = str(reference["id"])
        if file_id in files_by_id:
            raise ReceiptManifestError("Receipt inventory contains duplicate files")
        files_by_id[file_id] = file

    entries: list[dict[str, Any]] = []
    referenced_ids: set[str] = set()
    for transaction in transactions:
        transaction_id = _text(
            transaction.get("id"),
            "Receipt transaction ID",
            maximum=256,
        )
        references = decode_receipt_reference_list(
            transaction.get("receipt_references", "")
        )
        for stored_reference in references:
            if "receipt_id" not in stored_reference:
                raise ReceiptManifestError(
                    "Receipt references need checksum backfill before backup"
                )
            file_id = str(stored_reference["id"])
            if file_id in referenced_ids:
                raise ReceiptManifestError(
                    "A receipt is referenced by more than one transaction"
                )
            file = files_by_id.get(file_id)
            if file is None:
                raise ReceiptManifestError(
                    "A referenced receipt is outside the selected profile folder"
                )
            drive_reference = receipt_reference_from_drive_file(file)
            if stored_reference != drive_reference:
                raise ReceiptManifestError(
                    "Receipt reference integrity metadata does not match Google Drive"
                )
            referenced_ids.add(file_id)
            entries.append(
                _manifest_entry(
                    drive_reference,
                    file,
                    transaction_id=transaction_id,
                )
            )

    for file_id, file in files_by_id.items():
        if file_id in referenced_ids:
            continue
        entries.append(
            _manifest_entry(
                receipt_reference_from_drive_file(file),
                file,
                transaction_id=None,
            )
        )
    manifest = {
        "schema_version": RECEIPT_MANIFEST_SCHEMA_VERSION,
        "business_profile_key": profile_key,
        "receipts": sorted(
            entries,
            key=lambda entry: (
                str(entry["stored_filename"]).casefold(),
                str(entry["receipt_id"]),
            ),
        ),
    }
    return validate_receipt_manifest(manifest)


def validate_receipt_manifest(
    value: object,
    *,
    expected_profile_key: str | None = None,
    transaction_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Return a normalized strict receipt manifest."""
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "business_profile_key",
        "receipts",
    }:
        raise ReceiptManifestError("Receipt manifest fields are invalid")
    if value.get("schema_version") != RECEIPT_MANIFEST_SCHEMA_VERSION:
        raise ReceiptManifestError("Receipt manifest schema version is unsupported")
    profile_key = str(value.get("business_profile_key") or "")
    if not PROFILE_KEY_PATTERN.fullmatch(profile_key):
        raise ReceiptManifestError("Receipt manifest business profile is invalid")
    if expected_profile_key is not None and profile_key != expected_profile_key:
        raise ReceiptManifestError(
            "Receipt manifest belongs to a different business profile"
        )
    raw_entries = value.get("receipts")
    if not isinstance(raw_entries, list) or len(raw_entries) > 100_000:
        raise ReceiptManifestError("Receipt manifest entries are invalid")

    entries: list[dict[str, Any]] = []
    expected_fields = {
        "schema_version",
        "receipt_id",
        "reference_state",
        "transaction_id",
        "stored_filename",
        "original_filename",
        "mime_type",
        "byte_size",
        "sha256",
        "old_drive_file_id",
        "drive_created_time",
        "drive_modified_time",
    }
    for raw in raw_entries:
        if not isinstance(raw, Mapping) or set(raw) != expected_fields:
            raise ReceiptManifestError("Receipt manifest entry fields are invalid")
        if raw.get("schema_version") != RECEIPT_MANIFEST_SCHEMA_VERSION:
            raise ReceiptManifestError("Receipt manifest entry version is invalid")
        state = str(raw.get("reference_state") or "")
        transaction_id_value = raw.get("transaction_id")
        if state == "referenced":
            transaction_id = _text(
                transaction_id_value,
                "Receipt transaction ID",
                maximum=256,
            )
            if transaction_ids is not None and transaction_id not in transaction_ids:
                raise ReceiptManifestError(
                    "Receipt manifest references an unknown transaction"
                )
        elif state == "unreferenced" and transaction_id_value is None:
            transaction_id = None
        else:
            raise ReceiptManifestError("Receipt reference state is invalid")
        receipt_id = _text(raw.get("receipt_id"), "Receipt identity", maximum=32)
        sha256 = _text(raw.get("sha256"), "Receipt SHA-256", maximum=64)
        old_file_id = _text(
            raw.get("old_drive_file_id"),
            "Old Google Drive file ID",
            maximum=256,
        )
        if not RECEIPT_ID_PATTERN.fullmatch(receipt_id):
            raise ReceiptManifestError("Receipt identity is invalid")
        if not SHA256_PATTERN.fullmatch(sha256):
            raise ReceiptManifestError("Receipt SHA-256 is invalid")
        if not DRIVE_ID_PATTERN.fullmatch(old_file_id):
            raise ReceiptManifestError("Old Google Drive file ID is invalid")
        entry = {
            "schema_version": RECEIPT_MANIFEST_SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "reference_state": state,
            "transaction_id": transaction_id,
            "stored_filename": _filename(
                raw.get("stored_filename"),
                "Receipt stored filename",
            ),
            "original_filename": _filename(
                raw.get("original_filename"),
                "Receipt original filename",
            ),
            "mime_type": _text(
                raw.get("mime_type"),
                "Receipt MIME type",
                maximum=255,
            ),
            "byte_size": _byte_size(raw.get("byte_size")),
            "sha256": sha256,
            "old_drive_file_id": old_file_id,
            "drive_created_time": _timestamp(
                raw.get("drive_created_time"),
                "Receipt created timestamp",
            ),
            "drive_modified_time": _timestamp(
                raw.get("drive_modified_time"),
                "Receipt modified timestamp",
            ),
        }
        entries.append(entry)

    identities = [(item["receipt_id"], item["sha256"]) for item in entries]
    old_ids = [item["old_drive_file_id"] for item in entries]
    stored_names = [str(item["stored_filename"]).casefold() for item in entries]
    if (
        len(identities) != len(set(identities))
        or len(old_ids) != len(set(old_ids))
        or len(stored_names) != len(set(stored_names))
    ):
        raise ReceiptManifestError("Receipt manifest contains duplicate entries")
    return {
        "schema_version": RECEIPT_MANIFEST_SCHEMA_VERSION,
        "business_profile_key": profile_key,
        "receipts": entries,
    }
