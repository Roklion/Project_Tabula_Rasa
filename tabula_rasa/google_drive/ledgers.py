"""Initial profile-owned spreadsheet provisioning using the existing Drive client."""

from __future__ import annotations

from .client import _escape_query_value
from .errors import (
    GoogleDriveAccessError,
    GoogleDriveConfigurationError,
    GoogleDriveConflictError,
    PROFILE_KEY_PATTERN,
    DRIVE_ID_PATTERN,
)

SPREADSHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"


class _LedgerOperationsMixin:
    def create_ledger_spreadsheet(self, profile_key: str, name: str) -> dict[str, str]:
        """Create or recover the initial ledger; never retry an uncertain create.

        Google Workspace files do not support pre-generated file IDs. Stable
        profile/kind appProperties identify the initial provision instead.
        """
        if not PROFILE_KEY_PATTERN.fullmatch(profile_key) or not name.strip():
            raise GoogleDriveConfigurationError(
                "A valid business profile and ledger name are required."
            )
        query = (
            "trashed = false and mimeType = '" + SPREADSHEET_MIME_TYPE + "' and "
            "appProperties has { key='tabulaRasaKind' and value='ledger' } and "
            "appProperties has { key='tabulaRasaProfile' and value='"
            + _escape_query_value(profile_key)
            + "' }"
        )

        def existing():
            matches = self._list(query, page_size=2, use_cache=False)
            if len(matches) > 1:
                raise GoogleDriveConflictError(
                    "Multiple provisioned ledgers exist. Select the intended workbook through Picker."
                )
            return matches[0] if matches else None

        created = existing()
        if created is None:
            try:
                created = self._metadata_create(
                    {
                        "name": name.strip(),
                        "mimeType": SPREADSHEET_MIME_TYPE,
                        "appProperties": {
                            "tabulaRasaKind": "ledger",
                            "tabulaRasaProfile": profile_key,
                        },
                    }
                )
            except GoogleDriveAccessError as error:
                # One fresh readback; a missing result is not proof that create failed.
                try:
                    created = existing()
                except GoogleDriveAccessError:
                    created = None
                if created is None:
                    raise GoogleDriveAccessError(
                        "Ledger creation could not be confirmed. Inspect Google Drive and select the created ledger through Picker before trying again.",
                        upload_attempted=True,
                    ) from error
        spreadsheet_id = str(created.get("id") or "")
        if not DRIVE_ID_PATTERN.fullmatch(spreadsheet_id):
            raise GoogleDriveAccessError(
                "Ledger creation returned no usable ID. Inspect Google Drive and select the ledger through Picker.",
                upload_attempted=True,
            )
        return {"id": spreadsheet_id, "name": str(created.get("name") or name)}
