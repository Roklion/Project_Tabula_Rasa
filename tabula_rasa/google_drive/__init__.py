"""Profile-scoped Google Drive client compatibility facade."""

from .backups import _BackupOperationsMixin, backup_filename_and_hash, backup_is_in_local_week
from .client import PathName, _DriveClientCore
from .errors import (
    DRIVE_SCOPE, GoogleDriveAccessError, GoogleDriveAuthorizationError,
    GoogleDriveConfigurationError, GoogleDriveConflictError, GoogleDriveError,
)
from .folders import _FolderOperationsMixin
from .oauth import (
    GoogleDriveOAuthConfig, authorization_url, create_oauth_state,
    exchange_authorization_code, load_oauth_config, select_redirect_uri,
    validate_drive_profile_settings, verify_oauth_state,
)
from .receipts import (
    safe_receipt_filename, suffixed_receipt_filename,
    validate_receipt_upload, _ReceiptOperationsMixin,
)


class GoogleDriveClient(
    _DriveClientCore,
    _FolderOperationsMixin,
    _ReceiptOperationsMixin,
    _BackupOperationsMixin,
):
    """Stable facade composed from flat responsibility-specific operations."""


__all__ = [
    "DRIVE_SCOPE", "GoogleDriveAccessError", "GoogleDriveAuthorizationError",
    "GoogleDriveClient", "GoogleDriveConfigurationError", "GoogleDriveConflictError",
    "GoogleDriveError", "GoogleDriveOAuthConfig", "PathName",
    "authorization_url", "backup_filename_and_hash", "backup_is_in_local_week",
    "create_oauth_state", "exchange_authorization_code", "load_oauth_config",
    "safe_receipt_filename", "select_redirect_uri", "suffixed_receipt_filename",
    "validate_drive_profile_settings", "validate_receipt_upload",
    "verify_oauth_state",
]
