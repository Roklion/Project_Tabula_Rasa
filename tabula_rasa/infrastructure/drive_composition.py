"""Shared profile-owned Drive byte-store composition, without ledger/UI imports."""

from collections.abc import Mapping

from .google_drive_documents import GoogleDriveDocumentStore


def create_drive_document_store(profile_key, selected_secrets, secrets, *, client_factory=None):
    drive_settings = selected_secrets.get("google_drive")
    receipt_folder = drive_settings.get("receipt_folder") if isinstance(drive_settings, Mapping) else None
    folder_id = str(receipt_folder.get("id", "")) if isinstance(receipt_folder, Mapping) else ""

    def create_client():
        from tabula_rasa.google_drive import GoogleDriveClient, GoogleDriveConfigurationError, load_oauth_config
        if not isinstance(drive_settings, Mapping):
            raise GoogleDriveConfigurationError("Google Drive is not connected for this business profile.")
        return GoogleDriveClient(load_oauth_config(secrets), drive_settings)

    return GoogleDriveDocumentStore(profile_key, folder_id,
                                    client_factory if client_factory is not None else create_client)
