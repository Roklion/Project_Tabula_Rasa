from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tabula_rasa.google_drive import (
    GoogleDriveAccessError,
    GoogleDriveConfigurationError,
)
from tabula_rasa.google_drive_admin import (
    _folder_display_name,
    _ensure_storage_root_is_profile_isolated,
    _provision_storage_children,
    _revalidated_storage_settings,
)


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


@pytest.mark.parametrize(
    ("root_kind", "root_profile"),
    [("receipts", "north"), ("storage-root", "south")],
)
def test_reconnect_drops_root_with_mismatched_identity(
    root_kind: str, root_profile: str
) -> None:
    root_id = "rootfolder123"
    client = FolderClient(
        {root_id: managed_folder(root_id, "Other Storage", kind=root_kind, profile_key=root_profile)}
    )

    preserved = _revalidated_storage_settings(
        client,
        "north",
        {"storage_root": {"id": root_id, "name": "North Storage"}},
    )

    assert preserved == {}


def test_reconnect_drops_managed_child_with_missing_parents_safely() -> None:
    root_id = "rootfolder123"
    child = managed_folder(
        "receiptchild123",
        "Receipts",
        kind="receipts",
        root_id=root_id,
    )
    child["parents"] = None
    client = FolderClient(
        {
            root_id: managed_folder(root_id, "North Storage", kind="storage-root"),
            "receiptchild123": child,
        }
    )

    preserved = _revalidated_storage_settings(
        client,
        "north",
        {
            "storage_root": {"id": root_id, "name": "North Storage"},
            "receipt_folder": {"id": "receiptchild123", "name": "Receipts"},
        },
    )

    assert preserved == {
        "storage_root": {"id": root_id, "name": "North Storage"}
    }


@pytest.mark.parametrize("selected_key", ("north", "south"))
def test_storage_roots_cannot_be_nested_between_profiles(selected_key: str) -> None:
    north_root = managed_folder("northroot123", "North Storage", kind="storage-root")
    south_root = managed_folder(
        "southroot123",
        "South Storage",
        kind="storage-root",
        root_id="northroot123",
    )
    client = FolderClient(
        {
            "northroot123": north_root,
            "southroot123": south_root,
        }
    )
    profiles = {
        "north": {"google_drive": {"storage_root": {"id": "northroot123"}}},
        "south": {"google_drive": {"storage_root": {"id": "southroot123"}}},
    }
    selected_root = (
        north_root if selected_key == "north" else south_root
    )

    with pytest.raises(GoogleDriveConfigurationError, match="cannot be nested"):
        _ensure_storage_root_is_profile_isolated(
            client,
            selected_key,
            selected_root,
            profiles,
        )


def test_provisioning_rejects_a_storage_root_without_an_id() -> None:
    with pytest.raises(GoogleDriveConfigurationError, match="folder ID"):
        _provision_storage_children(
            "north",
            {"storage_root": {}},
            client=FolderClient({}),
            store_path=Path("unused.json"),
        )


@pytest.mark.parametrize(
    ("folder", "fallback", "expected"),
    (({"name": None}, "", ""), ({"name": None}, "Provisioned", "Provisioned")),
)
def test_folder_display_name_handles_null_names(
    folder: dict[str, Any],
    fallback: str,
    expected: str,
) -> None:
    assert _folder_display_name(folder, fallback) == expected
