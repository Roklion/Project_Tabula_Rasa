from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from .errors import (
    DRIVE_API_ROOT, FOLDER_MIME_TYPE, PROFILE_KEY_PATTERN, STORAGE_CHILD_NAMES,
    GoogleDriveAccessError, GoogleDriveConfigurationError, GoogleDriveConflictError,
)
from .client import _escape_query_value, _json_response
from .oauth import _clean_text


class _FolderOperationsMixin:
    """Profile-owned storage-root and managed-child operations."""

    def validate_storage_configuration(
        self,
        profile_key: str,
        *,
        root_folder: Mapping[str, Any] | None = None,
    ) -> dict[str, dict[str, str]]:
        """Freshly validate the saved root and managed child folders."""
        storage_root = self.profile_settings.get("storage_root")
        if not isinstance(storage_root, Mapping) or not storage_root.get("id"):
            raise GoogleDriveConfigurationError(
                "Select or create the Google Drive storage root."
            )
        root = root_folder or self.folder(str(storage_root.get("id") or ""))
        validated_root = {
            "id": self._valid_folder_id(str(root.get("id") or "")),
            "name": str(root.get("name") or ""),
        }
        if not validated_root["name"].strip():
            raise GoogleDriveAccessError(
                "The selected Google Drive storage root is not an available folder."
            )
        validated: dict[str, dict[str, str]] = {"storage_root": validated_root}
        for field, storage_kind in (
            ("receipt_folder", "receipts"),
            ("backup_folder", "ledger-backups"),
        ):
            child = self.profile_settings.get(field)
            if not isinstance(child, Mapping) or not child.get("id"):
                raise GoogleDriveConfigurationError(
                    "Provision the Receipts and Ledger Backups folders under "
                    "the root."
                )
            validated[field] = self._validate_managed_folder(
                self.folder(str(child.get("id") or "")),
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=validated_root["id"],
            )
        return validated


    def _managed_folder_query(
        self,
        *,
        profile_key: str,
        storage_kind: str,
        root_id: str | None = None,
    ) -> str:
        if not PROFILE_KEY_PATTERN.fullmatch(profile_key):
            raise GoogleDriveConfigurationError("The business profile key is invalid.")
        if storage_kind not in {"storage-root", *STORAGE_CHILD_NAMES}:
            raise GoogleDriveConfigurationError("The storage folder kind is invalid.")
        properties = [
            "appProperties has { key='tabulaRasaKind' and "
            f"value='{_escape_query_value(storage_kind)}' }}",
            "appProperties has { key='tabulaRasaProfile' and "
            f"value='{_escape_query_value(profile_key)}' }}",
        ]
        if root_id is not None:
            root_id = self._valid_folder_id(root_id)
            properties.append(
                "appProperties has { key='tabulaRasaStorageRoot' and "
                f"value='{_escape_query_value(root_id)}' }}"
            )
            properties.append(
                "'{0}' in parents".format(_escape_query_value(root_id))
            )
        return " and ".join(
            [
                "trashed = false",
                f"mimeType = '{FOLDER_MIME_TYPE}'",
                *properties,
            ]
        )


    def _list_managed_folders(
        self,
        *,
        profile_key: str,
        storage_kind: str,
        root_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._list(
            self._managed_folder_query(
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=root_id,
            ),
            page_size=1000,
            fetch_all=True,
        )


    def _validate_managed_folder(
        self,
        folder: Mapping[str, Any],
        *,
        profile_key: str,
        storage_kind: str,
        root_id: str | None = None,
    ) -> dict[str, str]:
        folder_id = self._valid_folder_id(str(folder.get("id", "")))
        if (
            folder.get("mimeType") != FOLDER_MIME_TYPE
            or folder.get("trashed")
            or not str(folder.get("name") or "").strip()
        ):
            raise GoogleDriveAccessError(
                "The managed Google Drive folder is not available."
            )
        parents = folder.get("parents")
        if not isinstance(parents, list):
            parents = []
        if root_id is not None and root_id not in parents:
            raise GoogleDriveAccessError(
                "The managed Google Drive folder is outside its profile storage root."
            )
        properties = folder.get("appProperties")
        if not isinstance(properties, Mapping):
            raise GoogleDriveAccessError(
                "The managed Google Drive folder is missing its identity metadata."
            )
        if (
            properties.get("tabulaRasaKind") != storage_kind
            or properties.get("tabulaRasaProfile") != profile_key
            or (
                root_id is not None
                and properties.get("tabulaRasaStorageRoot") != root_id
            )
        ):
            raise GoogleDriveAccessError(
                "The managed Google Drive folder identity does not match this profile."
            )
        return {"id": folder_id, "name": str(folder["name"])}


    def _metadata_create(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        self._invalidate_list_cache()
        response = self._request(
            "POST",
            f"{DRIVE_API_ROOT}/files",
            expected=(200, 201),
            retry_transient=False,
            params={
                "fields": "id,name,mimeType,trashed,parents,appProperties",
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": "application/json"},
            data=json.dumps(metadata, separators=(",", ":")).encode("utf-8"),
        )
        return dict(_json_response(response))


    def _ensure_managed_folder(
        self,
        *,
        profile_key: str,
        storage_kind: str,
        name: str,
        root_id: str | None = None,
    ) -> dict[str, str]:
        matches = self._list_managed_folders(
            profile_key=profile_key,
            storage_kind=storage_kind,
            root_id=root_id,
        )
        if len(matches) > 1:
            raise GoogleDriveConflictError(
                "Google Drive contains duplicate managed storage folders."
            )
        if matches:
            return self._validate_managed_folder(
                matches[0],
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=root_id,
            )

        metadata: dict[str, Any] = {
            "name": name,
            "mimeType": FOLDER_MIME_TYPE,
            "appProperties": {
                "tabulaRasaKind": storage_kind,
                "tabulaRasaProfile": profile_key,
            },
        }
        if root_id is not None:
            metadata["parents"] = [self._valid_folder_id(root_id)]
            metadata["appProperties"]["tabulaRasaStorageRoot"] = root_id

        for attempt in range(2):
            try:
                created = self._metadata_create(metadata)
            except GoogleDriveAccessError:
                reconciled = self._list_managed_folders(
                    profile_key=profile_key,
                    storage_kind=storage_kind,
                    root_id=root_id,
                )
                if len(reconciled) > 1:
                    raise GoogleDriveConflictError(
                        "Google Drive contains duplicate managed storage folders."
                    )
                if reconciled:
                    return self._validate_managed_folder(
                        reconciled[0],
                        profile_key=profile_key,
                        storage_kind=storage_kind,
                        root_id=root_id,
                    )
                if attempt == 1:
                    raise
                self.sleeper(1.0)
                continue
            created_id = str(created.get("id", ""))
            if not created_id:
                raise GoogleDriveAccessError(
                    "Google Drive did not return the managed folder identity."
                )
            return self._validate_managed_folder(
                created,
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=root_id,
            )


    def create_storage_root(self, profile_key: str, name: str) -> dict[str, str]:
        """Create or reuse one app-managed storage root for a profile."""
        clean_name = _clean_text(name, maximum=255)
        if not clean_name:
            raise GoogleDriveConfigurationError("Storage root name is required.")
        return self._ensure_managed_folder(
            profile_key=profile_key,
            storage_kind="storage-root",
            name=clean_name,
        )


    def provision_storage_children(
        self,
        profile_key: str,
        root_id: str,
    ) -> dict[str, dict[str, str]]:
        """Create or reuse the receipt and ledger-backup children under a root."""
        root = self.folder(root_id)
        self._valid_folder_id(str(root.get("id", "")))
        children: dict[str, dict[str, str]] = {}
        for storage_kind, name in STORAGE_CHILD_NAMES.items():
            children[storage_kind] = self._ensure_managed_folder(
                profile_key=profile_key,
                storage_kind=storage_kind,
                name=name,
                root_id=root_id,
            )
        return children
