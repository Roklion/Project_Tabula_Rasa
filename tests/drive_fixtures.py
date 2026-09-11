"""Semantic Google Drive resource builders shared by Drive-facing tests."""

from __future__ import annotations

from typing import Any


FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def drive_folder(
    folder_id: str,
    name: str,
    *,
    parent_id: str | None = None,
    profile_key: str | None = None,
    kind: str | None = None,
    storage_root_id: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build folder metadata while keeping ownership fields explicit."""

    folder: dict[str, Any] = {
        "id": folder_id,
        "name": name,
        "mimeType": FOLDER_MIME_TYPE,
        "trashed": False,
        "parents": [] if parent_id is None else [parent_id],
    }
    properties: dict[str, str] = {}
    if kind is not None:
        properties["tabulaRasaKind"] = kind
    if profile_key is not None:
        properties["tabulaRasaProfile"] = profile_key
    if storage_root_id is not None:
        properties["tabulaRasaStorageRoot"] = storage_root_id
    if properties:
        folder["appProperties"] = properties
    folder.update(overrides)
    return folder


def drive_file(
    file_id: str,
    name: str,
    *,
    mime_type: str = "application/octet-stream",
    parent_id: str | None = None,
    size: str | None = None,
    app_properties: dict[str, str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build ordinary Drive file metadata for request/response tests."""

    file: dict[str, Any] = {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "trashed": False,
    }
    if parent_id is not None:
        file["parents"] = [parent_id]
    if size is not None:
        file["size"] = size
    if app_properties is not None:
        file["appProperties"] = app_properties
    file.update(overrides)
    return file


def receipt_drive_file(
    file_id: str,
    name: str,
    *,
    profile_key: str = "test",
    receipt_id: str = "a" * 32,
    sha256: str = "b" * 64,
    original_name: str | None = None,
    size: int = 7,
    parent_id: str | None = None,
    original_file_id: str | None = None,
    recovery_attempt: str | None = None,
) -> dict[str, Any]:
    """Build canonical receipt metadata used by Drive and recovery tests."""

    properties = {
        "tabulaRasaKind": "receipt",
        "tabulaRasaProfile": profile_key,
        "tabulaRasaReceiptId": receipt_id,
        "tabulaRasaSha256": sha256,
        "tabulaRasaOriginalName": original_name or name,
    }
    if original_file_id is not None:
        properties["tabulaRasaOriginalFileId"] = original_file_id
    if recovery_attempt is not None:
        properties["tabulaRasaRecoveryAttempt"] = recovery_attempt
    return drive_file(
        file_id,
        name,
        mime_type="application/pdf",
        parent_id=parent_id,
        size=str(size),
        app_properties=properties,
    )
