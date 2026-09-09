from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import re
from typing import Any

from .client import _escape_query_value
from .errors import GoogleDriveAccessError

def backup_filename_and_hash(
    backup: bytes,
    manifest: Mapping[str, Any],
) -> tuple[str, str]:
    """Return the canonical cloud filename and SHA-256 for a verified backup."""
    timestamp = str(manifest["backup_time"]).replace("-", "").replace(":", "")
    timestamp = timestamp.replace("+0000", "Z")
    return (
        f"tabula-rasa-backup-{timestamp}.zip",
        hashlib.sha256(backup).hexdigest(),
    )

def backup_is_in_local_week(
    filename: str,
    *,
    local_date: datetime | None = None,
) -> bool:
    """Return whether a canonical UTC backup filename falls in the local week."""
    match = re.fullmatch(r"tabula-rasa-backup-(\d{8}T\d{6}Z)\.zip", filename)
    if not match:
        return False
    backup_date = (
        datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=timezone.utc)
        .astimezone()
        .date()
    )
    requested = (local_date or datetime.now().astimezone()).date()
    return backup_date.isocalendar()[:2] == requested.isocalendar()[:2]


class _BackupOperationsMixin:
    """Profile-owned backup upload, retention, and download listing."""

    def upload_backup(
        self,
        *,
        profile_key: str,
        folder_id: str,
        filename: str,
        content: bytes,
        sha256: str,
        backup_time: str,
        keep: int = 30,
    ) -> dict[str, Any]:
        """Idempotently upload a verified backup and apply retention."""
        if keep < 2:
            raise ValueError("keep must retain at least two backup generations")
        folder_id = self._valid_folder_id(folder_id)
        name_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                f"name = '{_escape_query_value(filename)}'",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='backup' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
            ]
        )
        generations = self.list_backups(
            profile_key=profile_key,
            folder_id=folder_id,
            limit=1000,
            _force_refresh=True,
        )
        existing = [item for item in generations if item.get("name") == filename]
        if existing:
            uploaded = existing[0]
        else:
            try:
                uploaded = self._multipart_create(
                    {
                        "name": filename,
                        "parents": [folder_id],
                        "appProperties": {
                            "tabulaRasaKind": "backup",
                            "tabulaRasaProfile": profile_key,
                            "tabulaRasaSha256": sha256,
                            "tabulaRasaBackupTime": backup_time,
                        },
                    },
                    content,
                    "application/zip",
                )
            except GoogleDriveAccessError:
                committed = self._list(name_query, page_size=2)
                if not committed:
                    raise
                uploaded = committed[0]
            generations.insert(0, uploaded)
        for expired in generations[keep:]:
            self.delete_file(str(expired["id"]))
        return uploaded


    def list_backups(
        self,
        *,
        profile_key: str,
        folder_id: str,
        limit: int = 100,
        _force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """List app-managed cloud backups newest first."""
        folder_id = self._valid_folder_id(folder_id)
        query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='backup' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
            ]
        )
        return self._list(
            query,
            page_size=limit,
            order_by="createdTime desc",
            use_cache=not _force_refresh,
        )
