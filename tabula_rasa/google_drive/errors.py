from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

import requests


def _clean_text(value: object, *, maximum: int = 4096) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(ord(character) < 32 for character in text):
        return ""
    return text


def _json_response(
    response: requests.Response,
    *,
    retryable: bool = False,
) -> Mapping[str, Any]:
    """Decode a Drive response without coupling OAuth to the client mixin."""
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleDriveAccessError(
            "Google Drive returned an unreadable response. Retry the request.",
            retryable=retryable,
        ) from exc
    if not isinstance(payload, Mapping):
        raise GoogleDriveAccessError(
            "Google Drive returned an unreadable response. Retry the request.",
            retryable=retryable,
        )
    return payload

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
DRIVE_API_ROOT = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_ROOT = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
STATE_MAX_AGE_SECONDS = 10 * 60
HTTP_TIMEOUT_SECONDS = 30
MAX_RECEIPT_BYTES = 20 * 1024 * 1024
RECEIPT_FILE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".heic")
PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
DRIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
SAFE_RECEIPT_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._() -]+")
STORAGE_CHILD_NAMES = {"receipts": "Receipts", "ledger-backups": "Ledger Backups"}


class GoogleDriveError(RuntimeError):
    """Base class for safe Google Drive failures."""


class GoogleDriveConfigurationError(GoogleDriveError):
    """Raised when application or profile Drive settings are incomplete."""


class GoogleDriveAuthorizationError(GoogleDriveError):
    """Raised when Google authorization is rejected, invalid, or revoked."""


class GoogleDriveAccessError(GoogleDriveError):
    """Raised when a Drive API operation cannot be completed."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        upload_attempted: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.upload_attempted = upload_attempted


class GoogleDriveConflictError(GoogleDriveAccessError):
    """Raised when recovery would overwrite or ambiguously reuse a Drive file."""
