"""Authenticated Streamlit UI for local-only business-profile onboarding."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from business_profiles import load_business_profiles
from ledger_auth import verify_password
from local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    build_profile_settings,
    load_local_profiles,
    save_local_profile,
    validate_profile_key,
)
from storage import GoogleSheetsStorage, StorageError


def _masked_spreadsheet_id(spreadsheet_id: object) -> str:
    value = str(spreadsheet_id)
    return f"…{value[-8:]}" if len(value) > 8 else value


def _profile_rows(
    effective_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for profile in load_business_profiles(effective_secrets):
        credential = profile.secrets.get("gcp_service_account", {})
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
                "Backup folder": str(
                    profile.secrets.get("backup_folder_path", "")
                ),
                "Service account": str(credential.get("client_email", "")),
                "Source": source,
            }
        )
    return rows


def render_local_profile_admin(
    base_secrets: Mapping[str, Any],
    effective_secrets: Mapping[str, Any],
    *,
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

    st.subheader("Add or replace a local profile")
    st.write(
        "Share the spreadsheet with the uploaded service account as Editor before "
        "saving. Validation opens the workbook and checks the required worksheets."
    )
    profile_form_keys = (
        "local_profile_name",
        "local_profile_key",
        "local_profile_spreadsheet",
        "local_profile_backup_path",
        "local_profile_credential",
        "local_profile_replace",
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
            "Google Drive Desktop backup folder path",
            help=(
                "Backups are ZIP files written by the local backup process, not "
                "uploaded through the Drive API. Enter the absolute folder path "
                "provided by Google Drive Desktop, for example "
                r"G:\My Drive\Tabula Rosa Backups\business. Google Drive Desktop "
                "must be installed, signed in, and running when backups execute."
            ),
            key="local_profile_backup_path",
        )
        credential_file = st.file_uploader(
            "Google service-account JSON",
            type=["json"],
            accept_multiple_files=False,
            key="local_profile_credential",
        )
        replace = st.checkbox(
            "Replace an existing profile with this key",
            help=(
                "This replaces the profile with this key in business_profiles.json."
            ),
            key="local_profile_replace",
        )
        submitted = st.form_submit_button("Validate and save", type="primary")

    if not submitted:
        return

    try:
        key = validate_profile_key(profile_key)
        if key in {profile.key for profile in load_business_profiles(effective_secrets)}:
            if not replace:
                raise LocalProfileStoreError(
                    "That profile key already exists. Select the replacement "
                    "confirmation to update it locally."
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
        )
        folded_name = settings["name"].casefold()
        if any(
            profile.key != key and profile.name.casefold() == folded_name
            for profile in load_business_profiles(effective_secrets)
        ):
            raise LocalProfileStoreError(
                "Business display names must be unique."
            )
        candidate_storage = GoogleSheetsStorage.from_secrets(settings)
        candidate_storage.ensure_defaults()
        save_local_profile(
            key,
            settings,
            replace=replace,
            path=store_path,
        )
    except LocalProfileStoreError as error:
        st.error(str(error))
        return
    except StorageError:
        st.error(
            "Google Sheets authentication, workbook access, or initialization "
            "failed. No profile was saved."
        )
        return

    st.cache_resource.clear()
    st.session_state["reset_local_profile_form"] = True
    st.session_state["local_profile_admin_notice"] = (
        f"Business profile '{key}' was validated and saved locally."
    )
    st.rerun()
