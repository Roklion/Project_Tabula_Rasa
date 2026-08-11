"""Authenticated Streamlit UI for local-only business-profile onboarding."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.google_drive_admin import (
    render_google_drive_admin,
    validate_google_drive_profile,
)
from tabula_rasa.ledger_auth import verify_password
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    build_profile_edit_settings,
    build_profile_settings,
    load_local_profiles,
    save_local_profile,
    suggest_profile_key,
    update_local_profile,
    update_local_profile_synology_recovery,
    validate_profile_key,
)
from tabula_rasa.profile_readiness import (
    ProfileReadiness,
    profile_configuration_readiness,
    profile_settings_fingerprint,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageAuthenticationError,
    StorageError,
    StorageInitializationError,
    StorageValidationError,
    StorageWorkbookAccessError,
)
from tabula_rasa.synology_recovery import (
    PROFILE_ROOT_LAYOUT,
    SynologyRecoveryConfigurationError,
    resolve_synology_recovery_defaults,
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


def _sync_profile_key_suggestion() -> None:
    """Update the editable key while it still matches the prior suggestion."""
    name = str(st.session_state.get("local_profile_name", ""))
    suggestion = suggest_profile_key(name)
    current = str(st.session_state.get("local_profile_key", ""))
    previous = str(st.session_state.get("local_profile_key_suggestion", ""))
    if not current or current == previous:
        st.session_state["local_profile_key"] = suggestion
    st.session_state["local_profile_key_suggestion"] = suggestion


def _safe_readiness_error(stage: str, error: Exception) -> str:
    """Return an actionable readiness message without echoing secrets."""
    if stage == "Sheets" and isinstance(error, StorageAuthenticationError):
        return "Sheets credential validation failed. Confirm the service-account key."
    if stage == "Sheets" and isinstance(error, StorageWorkbookAccessError):
        return "Sheets workbook validation failed. Confirm sharing and the workbook ID."
    if stage == "Sheets" and isinstance(error, StorageInitializationError):
        return "Sheets workbook initialization failed. Confirm Editor access."
    if stage == "Sheets" and isinstance(error, StorageValidationError):
        return "Sheets workbook structure validation failed. Repair the required tabs."
    if stage == "Drive" and isinstance(error, GoogleDriveError):
        return f"Google Drive validation failed: {error}"
    return f"{stage} validation failed. Retry the readiness check."


def _fresh_profile_readiness(
    profile_key: str,
    settings: Mapping[str, Any],
    *,
    app_secrets: Mapping[str, Any],
    hosted_profiles: Mapping[str, Any] | None,
    local_profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> ProfileReadiness:
    """Run fresh Sheets and configured Drive checks for one profile."""
    validation_errors: list[str] = []
    profiles_for_isolation = local_profiles or {profile_key: settings}
    try:
        _initialize_candidate_storage(settings)
    except StorageError as error:
        validation_errors.append(_safe_readiness_error("Sheets", error))

    drive = settings.get("google_drive")
    if isinstance(drive, Mapping):
        try:
            validate_google_drive_profile(
                app_secrets,
                profile_key,
                drive,
                local_profiles=profiles_for_isolation,
            )
        except (GoogleDriveError, LocalProfileStoreError) as error:
            validation_errors.append(_safe_readiness_error("Drive", error))

    return profile_configuration_readiness(
        profile_key,
        settings,
        hosted_profiles=hosted_profiles,
        validation_errors=tuple(validation_errors),
    )


def _readiness_for_display(
    profile_key: str,
    settings: Mapping[str, Any],
    *,
    hosted_profiles: Mapping[str, Any] | None,
) -> ProfileReadiness:
    stored = st.session_state.get(f"profile-readiness:{profile_key}")
    if (
        isinstance(stored, tuple)
        and len(stored) == 2
        and stored[0] == profile_settings_fingerprint(settings)
        and isinstance(stored[1], ProfileReadiness)
    ):
        return stored[1]
    return ProfileReadiness(
        status="incomplete",
        missing_steps=(
            "Run the readiness check to verify current Sheets and Drive settings.",
        ),
    )


def _render_profile_readiness(
    profile_key: str,
    settings: Mapping[str, Any],
    *,
    app_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    st.subheader("Profile readiness")
    hosted_profiles = app_secrets.get("business_profiles")
    hosted_profiles = hosted_profiles if isinstance(hosted_profiles, Mapping) else None
    report = _readiness_for_display(
        profile_key,
        settings,
        hosted_profiles=hosted_profiles,
    )
    labels = {
        "incomplete": "Incomplete",
        "ready-local": "Ready locally",
        "ready-hosted": "Ready for hosted Secrets",
    }
    st.metric("Status", labels[report.status])
    for step in report.missing_steps:
        st.warning(step)
    for error in report.validation_errors:
        st.error(error)
    if report.status == "ready-local" and report.hosted_export_needed:
        st.info(
            "Local profile settings are ready. Export hosted Secrets once after "
            "all hosted-runtime settings are complete; local backup and Synology "
            "changes do not require a new export."
        )
    elif report.status == "ready-hosted":
        st.success("The current hosted profile projection matches this local profile.")
    if st.button(
        "Run readiness check",
        type="primary",
        key=f"profile-readiness-check-{profile_key}",
    ):
        report = _fresh_profile_readiness(
            profile_key,
            settings,
            app_secrets=app_secrets,
            hosted_profiles=hosted_profiles,
            local_profiles=local_profiles,
        )
        st.session_state[f"profile-readiness:{profile_key}"] = (
            profile_settings_fingerprint(settings),
            report,
        )
        st.rerun()


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
    app_secrets: Mapping[str, Any],
    app_defaults: object = None,
    selected_profile_key: str | None = None,
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

    profile_key = selected_profile_key
    if profile_key is None:
        profile_key = st.selectbox(
            "Business profile for Synology recovery",
            list(local_profiles),
            format_func=lambda key: str(local_profiles[key].get("name", key)),
        )
    if profile_key not in local_profiles:
        st.info("Select a local business profile before configuring Synology recovery.")
        return
    existing = local_profiles[profile_key].get("synology_recovery")
    existing = existing if isinstance(existing, Mapping) else {}
    try:
        defaults = resolve_synology_recovery_defaults(app_defaults, profile_key)
    except SynologyRecoveryConfigurationError as error:
        st.error(str(error))
        defaults = {
            "layout": PROFILE_ROOT_LAYOUT,
            "destination_path": "",
            "schedule": "",
            "retention_policy": "",
        }
    with st.form("synology_recovery_form"):
        enabled = st.checkbox(
            "Maintain an optional Synology recovery copy for this business",
            value=bool(existing),
        )
        destination_path = st.text_input(
            "NAS destination path",
            value=str(
                existing.get(
                    "destination_path",
                    defaults["destination_path"],
                )
            ),
            placeholder=f"/volume1/Backups/TabulaRasa/{profile_key}",
            help=(
                "Informational DSM path only. The app never opens or writes to it."
            ),
        )
        schedule = st.text_input(
            "Cloud Sync schedule",
            value=str(existing.get("schedule", defaults["schedule"])),
            help="For example: Continuous, or Daily at 11:00 PM.",
        )
        retention_policy = st.text_area(
            "NAS retention policy",
            value=str(
                existing.get(
                    "retention_policy",
                    defaults["retention_policy"],
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
        "deletions disabled. One-task mode uses the profile storage root as its "
        "remote source. Confirm the actual task and its logs in Cloud Sync."
    )
    if not save:
        return

    settings = (
        {
            "layout": PROFILE_ROOT_LAYOUT,
            "destination_path": destination_path,
            "schedule": schedule,
            "retention_policy": retention_policy,
        }
        if enabled
        else None
    )
    try:
        # The Drive root and its managed children are validated when the
        # profile's Drive settings are selected or provisioned. Saving this
        # record only changes local NAS metadata; do not re-walk Drive
        # ancestry here, because the narrow drive.file grant may not expose
        # unrelated parent folders.
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
    selected_profile_key: str | None = None,
    store_path: Path,
) -> None:
    st.subheader("Edit local profile settings")
    st.write(
        "Change ordinary profile settings without re-uploading the stored Sheets "
        "credential. Profile keys are immutable. Use the separate rotation button "
        "only when replacing that credential."
    )
    profiles = (
        {
            selected_profile_key: local_profiles[selected_profile_key]
        }
        if selected_profile_key in local_profiles
        else local_profiles
    )
    for profile_key, existing in profiles.items():
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


def _render_add_profile_form(
    effective_secrets: Mapping[str, Any],
    *,
    store_path: Path,
    prominent: bool,
) -> None:
    heading = "Create your first business profile" if prominent else "Add another local profile"
    if prominent:
        st.subheader(heading)
        st.write(
            "Start with the Sheets ledger. Optional Drive, local backup, and "
            "Synology steps appear after the profile is saved."
        )
        render_form = st.container()
    else:
        render_form = st.expander(heading, expanded=False)
    with render_form:
        st.write(
            "Share the spreadsheet with the uploaded service account as Editor before "
            "saving. Validation opens the workbook, creates missing ledger worksheets "
            "and headers, and seeds the default accounts and categories."
        )
        profile_form_keys = (
            "local_profile_name",
            "local_profile_key",
            "local_profile_key_suggestion",
            "local_profile_spreadsheet",
            "local_profile_backup_path",
            "local_profile_credential",
        )
        if st.session_state.pop("reset_local_profile_form", False):
            for form_key in profile_form_keys:
                st.session_state.pop(form_key, None)

        name = st.text_input(
            "Business name",
            max_chars=100,
            key="local_profile_name",
            on_change=_sync_profile_key_suggestion,
        )
        profile_key = st.text_input(
            "Profile key",
            max_chars=48,
            help="Derived from the business name. Lowercase letters, numbers, underscores, and hyphens.",
            key="local_profile_key",
        )
        with st.form("local_profile_form", clear_on_submit=False):
            spreadsheet = st.text_input(
                "Google Sheets URL or spreadsheet ID",
                key="local_profile_spreadsheet",
            )
            backup_folder_path = st.text_input(
                "Optional local backup folder path",
                help=(
                    "Leave blank for a profile-scoped repository fallback. "
                    "Google Drive Desktop is not needed for cloud-native backups."
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

    notice = st.session_state.pop("local_profile_admin_notice", None)
    if notice:
        st.success(notice)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")

    if not local_profiles:
        _render_add_profile_form(
            effective_secrets,
            store_path=store_path,
            prominent=True,
        )
        return

    selected_profile_key = st.selectbox(
        "Business profile to configure",
        list(local_profiles),
        format_func=lambda key: str(local_profiles[key].get("name", key)),
        key="local_profile_selected",
    )
    _render_local_profile_edits(
        effective_secrets,
        local_profiles,
        selected_profile_key=selected_profile_key,
        store_path=store_path,
    )
    render_google_drive_admin(
        base_secrets,
        local_profiles,
        current_url=current_url,
        selected_profile_key=selected_profile_key,
        store_path=store_path,
    )
    _render_synology_recovery_admin(
        local_profiles,
        app_secrets=base_secrets,
        app_defaults=base_secrets.get("synology_recovery_defaults"),
        selected_profile_key=selected_profile_key,
        store_path=store_path,
    )
    current_profiles = load_local_profiles(store_path)
    if selected_profile_key not in current_profiles:
        st.warning(
            "The selected profile was removed or changed externally. "
            "Reload the page before continuing."
        )
        return
    selected_settings = current_profiles[selected_profile_key]
    _render_profile_readiness(
        selected_profile_key,
        selected_settings,
        app_secrets=base_secrets,
        local_profiles=current_profiles,
    )
    _render_add_profile_form(
        effective_secrets,
        store_path=store_path,
        prominent=False,
    )
    return
