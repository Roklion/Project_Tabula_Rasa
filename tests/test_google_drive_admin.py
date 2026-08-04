from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import tabula_rasa.google_drive_admin as google_drive_admin
from tabula_rasa.google_drive import (
    GoogleDriveAccessError,
    GoogleDriveConfigurationError,
)
from tabula_rasa.google_drive_admin import (
    _folder_display_name,
    _migrate_legacy_storage,
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


class MigrationClient(FolderClient):
    def __init__(
        self,
        folders: dict[str, dict[str, Any]],
        children: dict[str, dict[str, str]],
    ) -> None:
        super().__init__(folders)
        self.children = children
        self.provisioned_root_ids: list[str] = []

    def create_storage_root(self, profile_key: str, name: str) -> dict[str, str]:
        del profile_key, name
        return {"id": "newroot123", "name": "North Storage"}

    def provision_storage_children(
        self, profile_key: str, root_id: str
    ) -> dict[str, dict[str, str]]:
        del profile_key
        self.provisioned_root_ids.append(root_id)
        return self.children


class StreamlitStub:
    def __init__(self) -> None:
        self.session_state: dict[str, str] = {}
        self.cache_resource = self

    def clear(self) -> None:
        pass

    def rerun(self) -> None:
        pass


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


def test_provisioning_rejects_a_storage_root_without_an_id() -> None:
    with pytest.raises(GoogleDriveConfigurationError, match="folder ID"):
        _provision_storage_children(
            "north",
            {"storage_root": {}},
            client=FolderClient({}),
            store_path=Path("unused.json"),
        )


def test_legacy_migration_replaces_settings_after_provisioning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(google_drive_admin, "st", StreamlitStub())
    monkeypatch.setattr(
        google_drive_admin,
        "update_local_profile_google_drive",
        lambda profile_key, settings, *, path: saved.append(dict(settings)),
    )
    client = MigrationClient(
        {"rootfolder123": {"id": "rootfolder123", "name": "North Storage"}},
        {
            "receipts": {"id": "receipts123", "name": "Receipts"},
            "ledger-backups": {"id": "backups123", "name": "Ledger backups"},
        },
    )
    legacy = {
        "receipt_folder": {"id": "legacyreceipts123", "name": "Legacy receipts"},
        "backup_folder": {"id": "legacybackups123", "name": "Legacy backups"},
    }

    assert _migrate_legacy_storage(
        "north",
        "North",
        legacy,
        {"id": "rootfolder123"},
        client=client,
        store_path=tmp_path / "profiles.json",
    )

    assert client.provisioned_root_ids == ["rootfolder123"]
    assert saved == [
        {
            "storage_root": {"id": "rootfolder123", "name": "North Storage"},
            "receipt_folder": {"id": "receipts123", "name": "Receipts"},
            "backup_folder": {"id": "backups123", "name": "Ledger backups"},
        }
    ]
    assert legacy["receipt_folder"]["id"] == "legacyreceipts123"


def test_legacy_migration_keeps_saved_destinations_when_provisioning_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(google_drive_admin, "st", StreamlitStub())
    monkeypatch.setattr(
        google_drive_admin,
        "update_local_profile_google_drive",
        lambda profile_key, settings, *, path: saved.append(dict(settings)),
    )
    client = MigrationClient(
        {"rootfolder123": {"id": "rootfolder123", "name": "North Storage"}},
        {},
    )

    def fail_provision(profile_key: str, root_id: str) -> dict[str, dict[str, str]]:
        del profile_key, root_id
        raise GoogleDriveAccessError("provisioning failed")

    client.provision_storage_children = fail_provision  # type: ignore[method-assign]
    legacy = {"receipt_folder": {"id": "legacyreceipts123", "name": "Legacy"}}

    with pytest.raises(GoogleDriveAccessError, match="provisioning failed"):
        _migrate_legacy_storage(
            "north",
            "North",
            legacy,
            {"id": "rootfolder123"},
            client=client,
            store_path=tmp_path / "profiles.json",
        )

    assert saved == []
    assert legacy == {"receipt_folder": {"id": "legacyreceipts123", "name": "Legacy"}}


def test_legacy_migration_can_create_a_storage_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(google_drive_admin, "st", StreamlitStub())
    monkeypatch.setattr(
        google_drive_admin,
        "update_local_profile_google_drive",
        lambda profile_key, settings, *, path: saved.append(dict(settings)),
    )
    client = MigrationClient(
        {},
        {
            "receipts": {"id": "receipts123", "name": "Receipts"},
            "ledger-backups": {"id": "backups123", "name": "Ledger backups"},
        },
    )

    assert _migrate_legacy_storage(
        "north",
        "North",
        {"receipt_folder": {"id": "legacyreceipts123", "name": "Legacy"}},
        None,
        client=client,
        store_path=tmp_path / "profiles.json",
    )

    assert client.provisioned_root_ids == ["newroot123"]
    assert saved[0]["storage_root"] == {"id": "newroot123", "name": "North Storage"}


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
