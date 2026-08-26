"""Cloud backup and recovery-status workflows for the Data & backup page."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib

import streamlit as st

from tabula_rasa.google_drive import GoogleDriveError, backup_filename_and_hash
from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.storage import GoogleSheetsStorage, StorageError
from tabula_rasa.synology_recovery import (
    DESTINATION_DELETIONS,
    SYNC_DIRECTION,
    SynologyRecoveryConfigurationError,
    validate_synology_recovery_settings,
)


def _drive_setting(
    drive_settings: Mapping[str, object] | None,
    name: str,
) -> object:
    """Return one optional profile-scoped Drive setting."""
    if isinstance(drive_settings, Mapping):
        return drive_settings.get(name)
    return None


def render_cloud_backup(context: DataBackupContext) -> None:
    """Render the profile-scoped Google Drive backup workflow."""
    backup_folder = _drive_setting(context.drive_settings, "backup_folder")
    st.subheader("Cloud backup")
    st.caption("Google Drive backup")
    if not isinstance(backup_folder, Mapping):
        st.info(
            "Connect Google Drive and select a backup folder from the local "
            "Account settings to enable cloud-native backups."
        )
        return

    try:
        backup_drive = context.get_drive_client(
            context.profile_key,
            context.configuration_revision,
        )
        cloud_backups = backup_drive.list_backups(
            profile_key=context.profile_key,
            folder_id=str(backup_folder["id"]),
            limit=30,
        )
    except GoogleDriveError as error:
        st.error(str(error))
        return

    st.caption(f"Destination: {backup_folder.get('name', 'Google Drive folder')}")
    latest_cloud = None
    if cloud_backups:
        latest_cloud = cloud_backups[0]
        st.caption(
            "Latest cloud backup: "
            f"{latest_cloud.get('name', 'Unknown')} "
            f"({latest_cloud.get('createdTime', 'time unavailable')})"
        )
    else:
        st.warning("No cloud backup has been uploaded for this profile.")
    st.caption(
        "Verification downloads the latest backup into the app only to "
        "check its integrity. It does not restore or change the live workbook."
    )
    upload_column, verify_column = st.columns(2)
    if upload_column.button(
        "Upload fresh backup now",
        type="primary",
        width="stretch",
    ):
        try:
            with st.spinner("Preparing and uploading fresh backup..."):
                receipt_manifest = context.receipt_manifest_for_backup(
                    context.storage,
                    profile_key=context.profile_key,
                    drive_settings=context.drive_settings,
                    configuration_revision=context.configuration_revision,
                )
                backup_zip = context.storage.export_backup_zip(receipt_manifest)
                manifest = context.storage.validate_backup_zip(backup_zip)
                cloud_filename, cloud_sha256 = backup_filename_and_hash(
                    backup_zip,
                    manifest,
                )
                uploaded_backup = backup_drive.upload_backup(
                    profile_key=context.profile_key,
                    folder_id=str(backup_folder["id"]),
                    filename=cloud_filename,
                    content=backup_zip,
                    sha256=cloud_sha256,
                    backup_time=str(manifest["backup_time"]),
                    keep=30,
                )
        except (
            StorageError,
            GoogleDriveError,
            ReceiptManifestError,
            RuntimeError,
        ) as error:
            if isinstance(error, StorageError):
                context.report_storage_error(error)
            else:
                st.error(str(error))
        else:
            st.success(
                "Verified backup uploaded to Google Drive: "
                f"{uploaded_backup.get('name', cloud_filename)}"
            )
            st.rerun()
    if verify_column.button(
        "Verify latest cloud backup",
        disabled=latest_cloud is None,
        width="stretch",
    ):
        try:
            with st.spinner("Downloading and validating latest cloud backup..."):
                downloaded_backup = backup_drive.download_file(
                    str(latest_cloud["id"])
                )
                verified_manifest = GoogleSheetsStorage.validate_backup_zip(
                    downloaded_backup
                )
                expected_sha256 = (latest_cloud.get("appProperties") or {}).get(
                    "tabulaRasaSha256",
                    "",
                )
                if (
                    expected_sha256
                    and hashlib.sha256(downloaded_backup).hexdigest()
                    != str(expected_sha256)
                ):
                    raise RuntimeError(
                        "The downloaded cloud backup hash does not match."
                    )
        except (GoogleDriveError, RuntimeError, KeyError) as error:
            st.error(str(error))
        else:
            st.success(
                "Latest cloud backup downloaded and verified: "
                f"{verified_manifest['backup_time']}."
            )
        # Verification is deliberately Drive-only. Do not continue into the
        # live Sheets reads and fresh backup generation below.
        st.stop()


def render_recovery_status(context: DataBackupContext) -> None:
    """Render the configured, profile-scoped Synology recovery expectations."""
    backup_folder = _drive_setting(context.drive_settings, "backup_folder")
    recovery_receipt_folder = _drive_setting(
        context.drive_settings,
        "receipt_folder",
    )
    storage_root = _drive_setting(context.drive_settings, "storage_root")
    st.subheader("Recovery status")
    st.caption("Synology recovery copy")
    raw_synology_recovery = context.synology_recovery_settings
    if raw_synology_recovery is None:
        st.info(
            "No local Synology recovery record is available in this runtime. NAS "
            "settings are intentionally excluded from hosted Secrets; configure "
            "or review them from the loopback-only Account settings page and DSM."
        )
        return

    try:
        synology_recovery = validate_synology_recovery_settings(
            raw_synology_recovery
        )
    except SynologyRecoveryConfigurationError as error:
        st.error(str(error))
        synology_recovery = None
    if synology_recovery is None:
        st.caption(
            "Repair this profile from the loopback-only Account settings page."
        )
        return

    if not isinstance(backup_folder, Mapping):
        st.warning(
            "Synology recovery is enabled, but this profile does not have a "
            "Google Drive backup folder selected."
        )
    if not isinstance(recovery_receipt_folder, Mapping):
        st.warning(
            "Synology recovery is enabled, but this profile does not have a "
            "Google Drive receipt folder selected."
        )
    if not isinstance(storage_root, Mapping):
        st.warning(
            "Synology recovery is enabled, but this profile does "
            "not have a Google Drive storage root selected."
        )
    root_source_name = (
        str(storage_root.get("name", "Google Drive storage root"))
        if isinstance(storage_root, Mapping)
        else "Not configured"
    )
    source_lines = (
        "- **Cloud Sync task:** One recursive profile-root task",
        f"- **Remote source:** {root_source_name}",
        "- **Expected NAS children:** Receipts and Ledger Backups",
    )
    st.markdown(
        "\n".join(
            (
                *source_lines,
                "- **Cloud Sync direction:** " + SYNC_DIRECTION,
                "- **Destination deletions:** " + DESTINATION_DELETIONS,
                "- **NAS destination:** " + synology_recovery["destination_path"],
                "- **Schedule:** " + synology_recovery["schedule"],
                "- **Retention:** " + synology_recovery["retention_policy"],
            )
        )
    )
    st.caption(
        "These are the expected per-business settings. Project Tabula Rasa does not "
        "connect to the NAS; confirm transfers, failures, and retries in DSM "
        "Cloud Sync with destination deletions disabled is the independent "
        "second-layer copy. Optional versioned retention can protect both "
        "synchronized children with another recovery point."
    )
