"""Authenticated Streamlit UI for local-only business-profile onboarding."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.google_drive_admin import render_google_drive_admin
from tabula_rasa.ledger_auth import verify_password
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    build_profile_edit_settings,
    build_profile_settings,
    load_local_profiles,
    save_local_profile,
    update_local_profile,
    update_local_profile_synology_recovery,
    validate_profile_key,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageAuthenticationError,
    StorageError,
    StorageInitializationError,
    StorageValidationError,
    StorageWorkbookAccessError,
)


def _masked_spreadsheet_id(spreadsheet_id: object) -> str:
    value = str(spreadsheet_id)
    return f"…{value[-8:]}" if len(value) > 8 else value


def _profile_setup_error_message(
    error: StorageError,
    settings: Mapping[str, Any],
) -> str:
    spreadsheet = _masked_spreadsheet_id(settings.get("spreadsheet_id", ""))
    credential = settings.get("gcp_service_account", {})
    service_account = str(credential.get("client_email", "unknown"))

    if isinstance(error, StorageAuthenticationError):
        detail = (
            "Service-account authentication failed. The uploaded key may be "
            "invalid, disabled, revoked, or no longer active."
        )
    elif isinstance(error, StorageWorkbookAccessError):
        detail = (
            "Workbook access failed. Verify the spreadsheet ID, enable the "
            "Google Sheets API in the service-account project, and share the "
            "spreadsheet with this service account."
        )
    elif isinstance(error, StorageInitializationError):
        detail = (
            "The workbook opened, but initialization failed. Confirm the "
            "service account has Editor access and the ledger tabs are not "
            "protected."
        )
    elif isinstance(error, StorageValidationError):
        detail = f"Workbook structure validation failed: {error}."
    else:
        detail = "Google Sheets setup failed unexpectedly. Retry the request."

    return (
        f"{detail} Spreadsheet: {spreadsheet}. "
        f"Service account: {service_account}. No profile was saved."
    )


def _validate_profile_edit_action(
    save_settings: bool,
    rotate_credential: bool,
    credential_file: Any,
) -> None:
    if save_settings and credential_file is not None:
        raise LocalProfileStoreError(
            "To replace the credential, use the 'Validate and rotate credential' button."
        )
    if rotate_credential and credential_file is None:
        raise LocalProfileStoreError(
            "Upload a replacement Google service-account JSON for rotation."
        )


def _initialize_candidate_storage(
    settings: Mapping[str, Any],
) -> GoogleSheetsStorage:
    candidate_storage = GoogleSheetsStorage.from_secrets(settings)
    try:
        candidate_storage.ensure_defaults()
    except (
        StorageAuthenticationError,
        StorageWorkbookAccessError,
        StorageInitializationError,
        StorageValidationError,
    ):
        raise
    except StorageError as error:
        raise StorageInitializationError(
            "The workbook opened, but default accounts and categories "
            "could not be initialized"
        ) from error
    return candidate_storage


def _profile_rows(
    effective_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for profile in load_business_profiles(effective_secrets):
        credential = profile.secrets.get("gcp_service_account", {})
        synology_recovery = profile.secrets.get("synology_recovery")
        source = (
            "Business profiles JSON"
            if profile.key in local_profiles
            else "Streamlit Secrets (read-only here)"
        )
        rows.append(
            {
                "Profile key": profile.key,
                "Business": profile.name,
                "Spreadsheet": _masked_spreadsheet_id(
                    profile.secrets.get("spreadsheet_id", "")
                ),
                "Local backup folder": str(
                    profile.secrets.get("backup_folder_path") or "Not configured"
                ),
                "Service account": str(credential.get("client_email", "")),
                "Drive OAuth": (
                    str(
                        profile.secrets.get("google_drive", {}).get(
                            "authorized_email",
                            "Connected",
                        )
                    )
                    if profile.secrets.get("google_drive")
                    else "Not connected"
                ),
                "Synology recovery": (
                    str(synology_recovery.get("destination_path", "Configured"))
                    if isinstance(synology_recovery, Mapping)
                    else "Not enabled"
                ),
                "Source": source,
            }
        )
    return rows


def _render_synology_recovery_admin(
    local_profiles: Mapping[str, Mapping[str, Any]],
    *,
    store_path: Path,
) -> None:
    st.subheader("Synology recovery copy")
    st.write(
        "Optionally record the expected Google Drive-to-NAS Cloud Sync setup for "
        "each business. Tabula Rosa does not mount or connect to the NAS."
    )
    if not local_profiles:
        st.info("Add a local business profile before configuring Synology recovery.")
        return

    profile_key = st.selectbox(
        "Business profile for Synology recovery",
        list(local_profiles),
        format_func=lambda key: str(local_profiles[key].get("name", key)),
    )
    existing = local_profiles[profile_key].get("synology_recovery")
    existing = existing if isinstance(existing, Mapping) else {}
    with st.form("synology_recovery_form"):
        enabled = st.checkbox(
            "Maintain an optional Synology recovery copy for this business",
            value=bool(existing),
        )
        destination_path = st.text_input(
            "NAS destination path",
            value=str(existing.get("destination_path", "")),
            placeholder=f"/volume1/Backups/TabulaRasa/{profile_key}",
            help=(
                "Informational DSM path only. The app never opens or writes to it."
            ),
        )
        schedule = st.text_input(
            "Cloud Sync schedule",
            value=str(existing.get("schedule", "Continuous")),
            help="For example: Continuous, or Daily at 11:00 PM.",
        )
        retention_policy = st.text_area(
            "NAS retention policy",
            value=str(
                existing.get(
                    "retention_policy",
                    "Retain all synchronized generations until manual review.",
                )
            ),
            help=(
                "Destination deletions must remain disabled. Describe when an "
                "administrator may manually remove old NAS generations."
            ),
        )
        save = st.form_submit_button("Save Synology recovery choice")

    st.caption(
        "Required DSM settings: Download remote changes only; destination "
        "deletions disabled. Confirm the actual task and its logs in Cloud Sync."
    )
    if not save:
        return

    settings = (
        {
            "destination_path": destination_path,
            "schedule": schedule,
            "retention_policy": retention_policy,
        }
        if enabled
        else None
    )
    try:
        update_local_profile_synology_recovery(
            profile_key,
            settings,
            path=store_path,
        )
    except LocalProfileStoreError as error:
        st.error(str(error))
        return

    st.cache_resource.clear()
    state = "enabled" if enabled else "disabled"
    st.session_state["local_profile_admin_notice"] = (
        f"Synology recovery was {state} for '{profile_key}'."
    )
    st.rerun()


def _render_local_profile_edits(
    effective_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]],
    *,
    store_path: Path,
) -> None:
    st.subheader("Edit local profile settings")
    st.write(
        "Change ordinary profile settings without re-uploading the stored Sheets "
        "credential. Profile keys are immutable. Use the separate rotation button "
        "only when replacing that credential."
    )
    for profile_key, existing in local_profiles.items():
        business_name = str(existing.get("name", profile_key))
        with st.expander(f"{business_name} ({profile_key})"):
            with st.form(f"local_profile_edit_{profile_key}"):
                name = st.text_input(
                    "Business name",
                    value=business_name,
                    max_chars=100,
                    key=f"local_profile_edit_name_{profile_key}",
                )
                spreadsheet = st.text_input(
                    "Google Sheets URL or spreadsheet ID",
                    value=str(existing.get("spreadsheet_id") or ""),
                    key=f"local_profile_edit_spreadsheet_{profile_key}",
                )
                backup_folder_path = st.text_input(
                    "Optional local backup folder path",
                    value=str(existing.get("backup_folder_path") or ""),
                    help=(
                        "Leave blank for the profile-scoped repository fallback. "
                        "This setting is independent from Google Drive backups."
                    ),
                    key=f"local_profile_edit_backup_path_{profile_key}",
                )
                credential_file = st.file_uploader(
                    "Replacement Google service-account JSON (rotation only)",
                    type=["json"],
                    accept_multiple_files=False,
                    key=f"local_profile_edit_credential_{profile_key}",
                )
                save_settings = st.form_submit_button(
                    "Validate and save settings",
                    key=f"local_profile_edit_save_{profile_key}",
                )
                rotate_credential = st.form_submit_button(
                    "Validate and rotate credential",
                    key=f"local_profile_edit_rotate_{profile_key}",
                )

            if not (save_settings or rotate_credential):
                continue
            settings: Mapping[str, Any] = existing
            try:
                _validate_profile_edit_action(
                    save_settings,
                    rotate_credential,
                    credential_file,
                )
                settings = build_profile_edit_settings(
                    existing,
                    name,
                    spreadsheet,
                    backup_folder_path,
                    credential_file.getvalue()
                    if rotate_credential and credential_file is not None
                    else None,
                )
                folded_name = settings["name"].casefold()
                if any(
                    profile.key != profile_key
                    and profile.name.casefold() == folded_name
                    for profile in load_business_profiles(effective_secrets)
                ):
                    raise LocalProfileStoreError(
                        "Business display names must be unique."
                    )
                _initialize_candidate_storage(settings)
                update_local_profile(
                    profile_key,
                    name=name,
                    spreadsheet=spreadsheet,
                    backup_folder_path=backup_folder_path,
                    credential_upload=(
                        credential_file.getvalue()
                        if rotate_credential and credential_file is not None
                        else None
                    ),
                    path=store_path,
                )
            except LocalProfileStoreError as error:
                st.error(str(error))
                continue
            except StorageError as error:
                st.error(_profile_setup_error_message(error, settings))
                continue

            st.cache_resource.clear()
            action = "rotated and saved" if rotate_credential else "saved"
            st.session_state["local_profile_admin_notice"] = (
                f"Business profile '{profile_key}' was validated and {action}."
            )
            st.rerun()


def render_local_profile_admin(
    base_secrets: Mapping[str, Any],
    effective_secrets: Mapping[str, Any],
    *,
    current_url: str = "",
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Render the reauthenticated local profile-administration page."""
    st.title("Business profiles")
    st.caption(
        "Profile onboarding. Private keys are written to the ignored "
        "business profile JSON file and are never displayed after upload."
    )

    if not st.session_state.get("local_profile_admin_unlocked"):
        st.warning(
            "Re-enter the application password to unlock local configuration changes."
        )
        with st.form("local_profile_admin_unlock", clear_on_submit=True):
            password = st.text_input(
                "Application password",
                type="password",
                autocomplete="current-password",
            )
            unlock = st.form_submit_button("Unlock profile administration")
        if unlock:
            encoded_hash = base_secrets.get("app_password_hash")
            if encoded_hash and verify_password(password, str(encoded_hash)):
                st.session_state["local_profile_admin_unlocked"] = True
                st.rerun()
            st.error("Incorrect password.")
        return

    try:
        local_profiles = load_local_profiles(store_path)
        rows = _profile_rows(effective_secrets, local_profiles)
    except (LocalProfileStoreError, ValueError):
        st.error(
            "The local profile file is malformed. Repair or move it manually "
            "before using profile administration."
        )
        return

    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.info("No business profiles are configured yet.")

    render_google_drive_admin(
        base_secrets,
        local_profiles,
        current_url=current_url,
        store_path=store_path,
    )
    _render_synology_recovery_admin(
        local_profiles,
        store_path=store_path,
    )

    st.divider()
    st.subheader("Add a local profile")
    st.write(
        "Share the spreadsheet with the uploaded service account as Editor before "
        "saving. Validation opens the workbook, creates missing ledger worksheets "
        "and headers, and seeds the default accounts and categories."
    )
    profile_form_keys = (
        "local_profile_name",
        "local_profile_key",
        "local_profile_spreadsheet",
        "local_profile_backup_path",
        "local_profile_credential",
    )
    if st.session_state.pop("reset_local_profile_form", False):
        for form_key in profile_form_keys:
            st.session_state.pop(form_key, None)

    with st.form("local_profile_form", clear_on_submit=False):
        name = st.text_input(
            "Business name",
            max_chars=100,
            key="local_profile_name",
        )
        profile_key = st.text_input(
            "Profile key",
            max_chars=48,
            help="Lowercase letters, numbers, underscores, and hyphens.",
            key="local_profile_key",
        )
        spreadsheet = st.text_input(
            "Google Sheets URL or spreadsheet ID",
            key="local_profile_spreadsheet",
        )
        backup_folder_path = st.text_input(
            "Optional local backup folder path",
            help=(
                "Backups are ZIP files written by the local backup process, not "
                "uploaded through the Google Drive API. Leave this blank for a "
                "profile-scoped repository fallback, or enter the absolute folder "
                "path provided by Google Drive Desktop, for example "
                r"G:\My Drive\Tabula Rosa Backups\business. Google Drive Desktop "
                "is only required when this optional local copy uses a mounted path."
            ),
            key="local_profile_backup_path",
        )
        credential_file = st.file_uploader(
            "Google service-account JSON",
            type=["json"],
            accept_multiple_files=False,
            key="local_profile_credential",
        )
        submitted = st.form_submit_button("Validate and save", type="primary")

    if not submitted:
        _render_local_profile_edits(
            effective_secrets,
            local_profiles,
            store_path=store_path,
        )
        return

    try:
        key = validate_profile_key(profile_key)
        if key in {profile.key for profile in load_business_profiles(effective_secrets)}:
            raise LocalProfileStoreError(
                "That profile key already exists. Use its edit or credential "
                "rotation controls instead."
            )
        if credential_file is None:
            raise LocalProfileStoreError(
                "Upload the Google service-account JSON file."
            )
        settings = build_profile_settings(
            name,
            spreadsheet,
            credential_file.getvalue(),
            backup_folder_path,
            None,
            None,
        )
        folded_name = settings["name"].casefold()
        if any(
            profile.key != key and profile.name.casefold() == folded_name
            for profile in load_business_profiles(effective_secrets)
        ):
            raise LocalProfileStoreError(
                "Business display names must be unique."
            )
        _initialize_candidate_storage(settings)
        save_local_profile(
            key,
            settings,
            path=store_path,
        )
    except LocalProfileStoreError as error:
        st.error(str(error))
        return
    except StorageError as error:
        st.error(_profile_setup_error_message(error, settings))
        return

    st.cache_resource.clear()
    st.session_state["reset_local_profile_form"] = True
    st.session_state["local_profile_admin_notice"] = (
        f"Business profile '{key}' was validated and saved locally."
    )
    st.rerun()
