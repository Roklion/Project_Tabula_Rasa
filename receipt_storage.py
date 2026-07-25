"""Google Drive receipt uploads scoped to one business profile."""

from __future__ import annotations

import json
import mimetypes
import re
from pathlib import PurePath
from typing import Any, Mapping
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

from storage import StorageUnavailableError, StorageValidationError


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
MAX_RECEIPT_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"}
DRIVE_FOLDER_URL_PATTERN = re.compile(
    r"https://drive\.google\.com/(?:drive/(?:u/\d+/)?folders|open\?id=)/([A-Za-z0-9_-]+)"
)
DRIVE_FOLDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def parse_drive_folder_id(value: str) -> str:
    """Return a folder ID from a Google Drive folder URL or raw ID."""
    candidate = value.strip()
    match = DRIVE_FOLDER_URL_PATTERN.search(candidate)
    folder_id = match.group(1) if match else candidate
    if not DRIVE_FOLDER_ID_PATTERN.fullmatch(folder_id):
        raise StorageValidationError(
            "Enter a valid Google Drive folder URL or folder ID."
        )
    return folder_id


def receipt_filename(transaction_id: str, original_name: str) -> str:
    """Build a safe Drive filename while retaining the user's basename."""
    identifier = str(transaction_id).strip()
    basename = PurePath(str(original_name).replace("\\", "/")).name.strip()
    basename = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", basename)
    basename = basename.strip(" .")
    if not identifier or not basename:
        raise StorageValidationError("Receipt filename is invalid.")
    return f"{identifier}-{basename}"


class GoogleDriveReceiptStorage:
    """Upload transaction receipts to a configured Drive folder."""

    def __init__(
        self,
        credentials: Credentials,
        folder_id: str,
        *,
        session: AuthorizedSession | None = None,
    ):
        self.folder_id = parse_drive_folder_id(folder_id)
        self._session = session or AuthorizedSession(credentials)

    @classmethod
    def from_secrets(cls, secrets: Mapping[str, Any]) -> "GoogleDriveReceiptStorage":
        folder_id = secrets.get("receipt_folder_id")
        credential_info = secrets.get("gcp_service_account")
        if not folder_id:
            raise StorageValidationError(
                "This business profile does not have a receipt Drive folder configured."
            )
        if not isinstance(credential_info, Mapping):
            raise StorageValidationError("Google service-account settings are missing.")
        try:
            credentials = Credentials.from_service_account_info(
                dict(credential_info), scopes=[DRIVE_SCOPE]
            )
        except (ValueError, GoogleAuthError) as exc:
            raise StorageValidationError(
                "Google service-account settings are invalid."
            ) from exc
        return cls(credentials, str(folder_id))

    def upload(
        self,
        transaction_id: str,
        original_name: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, str]:
        extension = PurePath(original_name).suffix.casefold()
        if extension not in ALLOWED_EXTENSIONS:
            raise StorageValidationError(
                "Receipt must be a JPG, JPEG, PNG, WEBP, HEIC, or PDF file."
            )
        if not content or len(content) > MAX_RECEIPT_BYTES:
            raise StorageValidationError(
                "Receipt must be non-empty and no larger than 20 MB."
            )
        name = receipt_filename(transaction_id, original_name)
        mime = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        boundary = "tabula-rasa-receipt-boundary"
        metadata = json.dumps(
            {"name": name, "parents": [self.folder_id]},
            separators=(",", ":"),
        ).encode("utf-8")
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        ).encode("utf-8") + metadata + (
            f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        try:
            response = self._session.post(
                "https://www.googleapis.com/upload/drive/v3/files"
                "?uploadType=multipart&fields=id,name,webViewLink",
                data=body,
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                timeout=30,
            )
            response.raise_for_status()
            uploaded = response.json()
        except Exception as exc:
            raise StorageUnavailableError(
                "Receipt upload to Google Drive failed. Confirm that the Drive API "
                "is enabled and the configured folder is shared with the service account.",
                retryable=True,
            ) from exc
        return {
            "id": str(uploaded.get("id", "")),
            "name": str(uploaded.get("name", name)),
            "webViewLink": str(uploaded.get("webViewLink", "")),
        }
