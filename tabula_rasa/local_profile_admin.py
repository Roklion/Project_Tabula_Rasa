"""Authenticated Streamlit UI for local-only business-profile onboarding."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from scripts.export_streamlit_secrets import (
    SecretsExportError,
    build_streamlit_secrets_toml,
    write_secure_export,
)
from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.google_drive_admin import render_google_drive_admin
from tabula_rasa.google_drive_admin import validate_google_drive_profile
from tabula_rasa.ledger_auth import verify_password
from tabula_rasa.local_profile_admin_forms import (
    render_add_profile_form,
    render_local_profile_edits,
    sync_profile_key_suggestion,
)
from tabula_rasa.local_profile_admin_readiness import (
    fresh_profile_readiness,
    readiness_for_display,
    render_profile_readiness,
    safe_readiness_error,
)
from tabula_rasa.local_profile_admin_security import (
    render_security_deployment_info as _render_security_deployment_info_impl,
)
from tabula_rasa.local_profile_admin_support import (
    configured_profiles_or_empty,
    initialize_candidate_storage,
    masked_spreadsheet_id,
    profile_setup_error_message,
    validate_profile_edit_action,
)
from tabula_rasa.local_profile_admin_synology import render_synology_recovery_admin
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    load_local_profiles,
)
from tabula_rasa.presentation import render_page_header
from tabula_rasa.storage import GoogleSheetsStorage

__all__ = [
    "GoogleDriveError",
    "GoogleSheetsStorage",
    "SecretsExportError",
    "_export_hosted_secrets_file",
    "_fresh_profile_readiness",
    "_initialize_candidate_storage",
    "_configured_profiles_or_empty",
    "_masked_spreadsheet_id",
    "_profile_rows",
    "_profile_setup_error_message",
    "_readiness_for_display",
    "_render_add_profile_form",
    "_render_local_profile_edits",
    "_render_profile_readiness",
    "_render_security_deployment_info",
    "_render_synology_recovery_admin",
    "_safe_readiness_error",
    "_sync_profile_key_suggestion",
    "_validate_profile_edit_action",
    "render_local_profile_admin",
]


# These compatibility names preserve the focused test seams and private helper
# imports used by the existing administration tests while the implementation is
# owned by the cohesive modules above.
_initialize_candidate_storage = initialize_candidate_storage
_profile_setup_error_message = profile_setup_error_message
_validate_profile_edit_action = validate_profile_edit_action
_readiness_for_display = readiness_for_display
_configured_profiles_or_empty = configured_profiles_or_empty
_masked_spreadsheet_id = masked_spreadsheet_id
_render_add_profile_form = render_add_profile_form
_render_local_profile_edits = render_local_profile_edits
_render_profile_readiness = render_profile_readiness
_render_synology_recovery_admin = render_synology_recovery_admin
_safe_readiness_error = safe_readiness_error
_sync_profile_key_suggestion = sync_profile_key_suggestion


def _fresh_profile_readiness(*args: Any, **kwargs: Any) -> Any:
    return fresh_profile_readiness(
        *args,
        drive_validator=validate_google_drive_profile,
        **kwargs,
    )


def _export_hosted_secrets_file(
    app_secrets: Mapping[str, object],
    *,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> Path:
    """Compatibility facade for the hosted Secrets export workflow."""
    local_profiles = load_local_profiles(store_path)
    if not local_profiles:
        raise LocalProfileStoreError(
            "At least one local business profile is required for hosted export."
        )
    document = build_streamlit_secrets_toml(app_secrets, local_profiles)
    return write_secure_export(document)


def _render_security_deployment_info(
    app_secrets: Mapping[str, Any] | None = None,
    *,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    _render_security_deployment_info_impl(
        app_secrets,
        store_path=store_path,
        export_function=_export_hosted_secrets_file,
    )


def _profile_rows(
    effective_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Any],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for profile in configured_profiles_or_empty(effective_secrets):
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
                "Spreadsheet": masked_spreadsheet_id(
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


def render_local_profile_admin(
    base_secrets: Mapping[str, Any],
    effective_secrets: Mapping[str, Any],
    *,
    current_url: str = "",
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Render the reauthenticated local profile-administration page."""
    render_page_header(
        "Account settings",
        "Manage isolated business profiles, storage, recovery, and deployment "
        "settings locally. Private keys are never displayed after upload.",
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
            unlock_error = st.empty()
            unlock = st.form_submit_button("Unlock profile administration")
        if unlock:
            encoded_hash = base_secrets.get("app_password_hash")
            if encoded_hash and verify_password(password, str(encoded_hash)):
                st.session_state["local_profile_admin_unlocked"] = True
                st.session_state["account_settings_route_pending"] = True
                st.rerun()
            unlock_error.error("Incorrect password.")
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
        st.subheader("Business profiles")
        render_add_profile_form(
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
    (
        business_profiles_tab,
        google_drive_tab,
        recovery_tab,
        security_tab,
    ) = st.tabs(
        [
            "Business profiles",
            "Google Drive storage",
            "Recovery",
            "Security & deployment information",
        ]
    )
    with business_profiles_tab:
        render_local_profile_edits(
            effective_secrets,
            local_profiles,
            selected_profile_key=selected_profile_key,
            store_path=store_path,
        )
        render_add_profile_form(
            effective_secrets,
            store_path=store_path,
            prominent=False,
        )

    with google_drive_tab:
        render_google_drive_admin(
            base_secrets,
            local_profiles,
            current_url=current_url,
            selected_profile_key=selected_profile_key,
            store_path=store_path,
        )

    with recovery_tab:
        render_synology_recovery_admin(
            local_profiles,
            app_secrets=base_secrets,
            app_defaults=base_secrets.get("synology_recovery_defaults"),
            selected_profile_key=selected_profile_key,
            store_path=store_path,
        )
        selected_settings = local_profiles[selected_profile_key]
        render_profile_readiness(
            selected_profile_key,
            selected_settings,
            app_secrets=base_secrets,
            local_profiles=local_profiles,
        )

    with security_tab:
        _render_security_deployment_info(
            base_secrets,
            store_path=store_path,
        )
