"""Business-profile creation and edit forms for local administration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.local_profile_admin_support import (
    configured_profiles_or_empty,
    initialize_candidate_storage,
    profile_setup_error_message,
    validate_profile_edit_action,
)
from tabula_rasa.local_profile_store import (
    LocalProfileStoreError,
    build_profile_edit_settings,
    build_profile_settings,
    save_local_profile,
    suggest_profile_key,
    update_local_profile,
    validate_profile_key,
)
from tabula_rasa.storage import StorageError


def sync_profile_key_suggestion() -> None:
    """Update the editable key while it still matches the prior suggestion."""
    name = str(st.session_state.get("local_profile_name", ""))
    suggestion = suggest_profile_key(name)
    current = str(st.session_state.get("local_profile_key", ""))
    previous = str(st.session_state.get("local_profile_key_suggestion", ""))
    if not current or current == previous:
        st.session_state["local_profile_key"] = suggestion
    st.session_state["local_profile_key_suggestion"] = suggestion


def render_local_profile_edits(
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
        {selected_profile_key: local_profiles[selected_profile_key]}
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
                edit_error = st.empty()
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
                validate_profile_edit_action(
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
                initialize_candidate_storage(settings)
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
                edit_error.error(str(error))
                continue
            except StorageError as error:
                edit_error.error(profile_setup_error_message(error, settings))
                continue

            st.cache_resource.clear()
            action = "rotated and saved" if rotate_credential else "saved"
            st.session_state["local_profile_admin_notice"] = (
                f"Business profile '{profile_key}' was validated and {action}."
            )
            st.rerun()


def render_add_profile_form(
    effective_secrets: Mapping[str, Any],
    *,
    store_path: Path,
    prominent: bool,
) -> None:
    heading = (
        "Create your first business profile"
        if prominent
        else "Add another local profile"
    )
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
            "saving. Validation initializes a genuinely blank workbook, but populated "
            "workbooks with missing or incompatible worksheets must be migrated first "
            "with the explicit workbook migration command."
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
            on_change=sync_profile_key_suggestion,
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
            save_error = st.empty()
            submitted = st.form_submit_button("Validate and save", type="primary")

        if not submitted:
            return

        try:
            key = validate_profile_key(profile_key)
            if key in {
                profile.key for profile in configured_profiles_or_empty(effective_secrets)
            }:
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
                for profile in configured_profiles_or_empty(effective_secrets)
            ):
                raise LocalProfileStoreError(
                    "Business display names must be unique."
                )
            initialize_candidate_storage(settings)
            save_local_profile(
                key,
                settings,
                path=store_path,
            )
        except LocalProfileStoreError as error:
            save_error.error(str(error))
            return
        except StorageError as error:
            save_error.error(profile_setup_error_message(error, settings))
            return

        st.cache_resource.clear()
        st.session_state["reset_local_profile_form"] = True
        st.session_state["local_profile_admin_notice"] = (
            f"Business profile '{key}' was validated and saved locally."
        )
        st.rerun()
