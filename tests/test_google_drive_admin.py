from __future__ import annotations

from typing import Any

from tabula_rasa.google_drive import GoogleDriveAccessError
from tabula_rasa.google_drive_admin import _revalidated_storage_settings


class FolderClient:
    def __init__(self, folders: dict[str, dict[str, Any]]) -> None:
        self.folders = folders

    def folder(self, folder_id: str) -> dict[str, Any]:
        if folder_id not in self.folders:
            raise GoogleDriveAccessError("folder unavailable")
        return self.folders[folder_id]


def managed_folder(
    folder_id: str,
    name: str,
    *,
    kind: str,
    profile_key: str = "north",
    root_id: str | None = None,
) -> dict[str, Any]:
    properties = {
        "tabulaRasaKind": kind,
        "tabulaRasaProfile": profile_key,
    }
    folder: dict[str, Any] = {
        "id": folder_id,
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "trashed": False,
        "appProperties": properties,
    }
    if root_id is not None:
        properties["tabulaRasaStorageRoot"] = root_id
        folder["parents"] = [root_id]
    return folder


def test_reconnect_preserves_only_valid_managed_root_and_children() -> None:
    root_id = "rootfolder123"
    folders = {
        root_id: managed_folder(root_id, "North Storage", kind="storage-root"),
        "receiptchild123": managed_folder(
            "receiptchild123",
            "Receipts",
            kind="receipts",
            root_id=root_id,
        ),
    }
    client = FolderClient(folders)
    previous = {
        "storage_root": {"id": root_id, "name": "Old Root Name"},
        "receipt_folder": {"id": "receiptchild123", "name": "Old Receipts"},
        "backup_folder": {"id": "missingchild123", "name": "Old Backups"},
    }

    preserved = _revalidated_storage_settings(client, "north", previous)

    assert preserved == {
        "storage_root": {"id": root_id, "name": "North Storage"},
        "receipt_folder": {"id": "receiptchild123", "name": "Receipts"},
    }


def test_reconnect_keeps_legacy_independent_folders() -> None:
    client = FolderClient(
        {
            "receiptchild123": {
                "id": "receiptchild123",
                "name": "Receipts",
                "mimeType": "application/vnd.google-apps.folder",
                "trashed": False,
            },
            "backupchild123": {
                "id": "backupchild123",
                "name": "Backups",
                "mimeType": "application/vnd.google-apps.folder",
                "trashed": False,
            },
        }
    )

    preserved = _revalidated_storage_settings(
        client,
        "north",
        {
            "receipt_folder": {"id": "receiptchild123", "name": "Old Receipts"},
            "backup_folder": {"id": "backupchild123", "name": "Old Backups"},
        },
    )

    assert preserved == {
        "receipt_folder": {"id": "receiptchild123", "name": "Receipts"},
        "backup_folder": {"id": "backupchild123", "name": "Backups"},
    }
