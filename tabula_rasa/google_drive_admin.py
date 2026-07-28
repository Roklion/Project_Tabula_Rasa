"""Authenticated local administration for business-scoped Drive OAuth."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import streamlit as st

from tabula_rasa.google_drive import (
    GoogleDriveAuthorizationError,
    GoogleDriveClient,
    GoogleDriveConfigurationError,
    GoogleDriveError,
    GoogleDriveOAuthConfig,
    authorization_url,
    exchange_authorization_code,
    load_oauth_config,
    select_redirect_uri,
    verify_oauth_state,
)
from tabula_rasa.google_drive_picker import folder_picker
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    load_local_profiles,
    update_local_profile_google_drive,
)


@st.cache_resource
def _cached_drive_client(
    config: GoogleDriveOAuthConfig,
    profile_key: str,
    settings_json: str,
) -> GoogleDriveClient:
    """Reuse a profile's access token while its saved OAuth settings are unchanged."""
    del profile_key
    return GoogleDriveClient(config, json.loads(settings_json))


def _query_value(value: object) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def process_google_drive_oauth_callback(
    app_secrets: Mapping[str, Any],
    *,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> bool:
    """Process a signed Google callback and persist one local refresh token."""
    state = _query_value(st.query_params.get("state"))
    code = _query_value(st.query_params.get("code"))
    error = _query_value(st.query_params.get("error"))
    if not state or (not code and not error):
        return False

    try:
        config = load_oauth_config(app_secrets)
        payload = verify_oauth_state(config, state)
        profile_key = str(payload["profile"])
        if profile_key not in load_local_profiles(store_path):
            raise LocalProfileStoreError(
                "The Google authorization profile is not available locally."
            )
        if error:
            raise GoogleDriveAuthorizationError(
                "Google Drive authorization was cancelled or denied."
            )
        drive_settings = exchange_authorization_code(
            config,
            code,
            str(payload["redirect_uri"]),
        )
        update_local_profile_google_drive(
            profile_key,
            drive_settings,
            path=store_path,
        )
        st.session_state["local_profile_admin_unlocked"] = True
        st.session_state["google_drive_admin_notice"] = (
            f"Google Drive was connected for profile '{profile_key}'. "
            "Choose its receipt and backup folders next."
        )
        st.session_state["navigation_page"] = "Business profiles"
    except (GoogleDriveError, LocalProfileStoreError) as exc:
        st.session_state["google_drive_admin_error"] = str(exc)
        st.session_state["navigation_page"] = "Business profiles"
    finally:
        st.query_params.clear()
    st.cache_resource.clear()
    st.rerun()
    return True


def _save_selected_folder(
    profile_key: str,
    drive_settings: Mapping[str, Any],
    field: str,
    selected: Mapping[str, Any],
    *,
    client: GoogleDriveClient,
    store_path: Path,
) -> bool:
    selected_id = str(selected.get("id", ""))
    existing = drive_settings.get(field)
    if isinstance(existing, Mapping) and existing.get("id") == selected_id:
        return False
    folder = client.folder(selected_id)
    updated = dict(drive_settings)
    updated[field] = {
        "id": str(folder["id"]),
        "name": str(folder["name"]),
    }
    update_local_profile_google_drive(profile_key, updated, path=store_path)
    label = "receipt" if field == "receipt_folder" else "backup"
    st.session_state["google_drive_admin_notice"] = (
        f"Google Drive {label} folder saved for profile '{profile_key}'."
    )
    st.cache_resource.clear()
    st.rerun()
    return True


def render_google_drive_admin(
    app_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]],
    *,
    current_url: str,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Render connection, folder selection, test, and disconnect controls."""
    st.divider()
    st.subheader("Google Drive OAuth")
    st.write(
        "Connect the human Google account that owns each business's Drive files. "
        "The OAuth client is shared, while refresh tokens and selected folders "
        "remain isolated by business profile."
    )

    notice = st.session_state.pop("google_drive_admin_notice", None)
    if notice:
        st.success(notice)
    callback_error = st.session_state.pop("google_drive_admin_error", None)
    if callback_error:
        st.error(callback_error)

    try:
        config = load_oauth_config(app_secrets)
        redirect_uri = select_redirect_uri(config, current_url)
    except GoogleDriveConfigurationError as exc:
        st.warning(str(exc))
        st.code(
            '[google_drive_oauth]\n'
            'client_id = "…apps.googleusercontent.com"\n'
            'client_secret = "…"\n'
            'redirect_uris = [\n'
            '  "http://localhost:8501/",\n'
            '  "http://127.0.0.1:8501/",\n'
            '  "https://tabula-rasa.streamlit.app/",\n'
            "]\n"
            'picker_api_key = "…"\n'
            'project_number = "…"\n',
            language="toml",
        )
        return

    if not local_profiles:
        st.info("Add a local business profile before connecting Google Drive.")
        return

    profile_key = st.selectbox(
        "Business profile to connect",
        list(local_profiles),
        format_func=lambda key: str(local_profiles[key].get("name", key)),
        key="google_drive_profile_key",
    )
    profile = local_profiles[profile_key]
    drive_settings = profile.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        st.info("Google Drive is not connected for this profile.")
        connect_url = authorization_url(
            config,
            profile_key,
            redirect_uri,
        )
        st.link_button(
            "Connect Google Drive",
            connect_url,
            type="primary",
            help=(
                "Google will return to this app after you approve narrow "
                "Drive file access and offline access."
            ),
        )
        st.caption(f"OAuth callback: `{redirect_uri}`")
        return

    authorized_email = str(drive_settings.get("authorized_email", "")).strip()
    authorized_name = str(drive_settings.get("authorized_name", "")).strip()
    identity = authorized_email or authorized_name or "Connected Google account"
    st.success(f"Connected as {identity}.")

    try:
        client = _cached_drive_client(
            config,
            profile_key,
            json.dumps(dict(drive_settings), sort_keys=True),
        )
        access_token = client.access_token()
    except GoogleDriveError as exc:
        st.error(str(exc))
        reconnect_url = authorization_url(
            config,
            profile_key,
            redirect_uri,
            login_hint=authorized_email,
        )
        st.link_button("Reconnect Google Drive", reconnect_url, type="primary")
        remove_invalid = st.checkbox(
            "Remove the saved invalid Google Drive connection",
            key=f"remove-invalid-google-drive-{profile_key}",
        )
        if st.button(
            "Remove saved connection",
            disabled=not remove_invalid,
            key=f"remove-invalid-google-drive-button-{profile_key}",
        ):
            try:
                update_local_profile_google_drive(profile_key, None, path=store_path)
            except LocalProfileStoreError as remove_error:
                st.error(str(remove_error))
            else:
                st.cache_resource.clear()
                st.session_state["google_drive_admin_notice"] = (
                    f"Saved Google Drive connection removed for profile '{profile_key}'."
                )
                st.rerun()
        return

    if not config.picker_ready:
        st.warning(
            "Add picker_api_key and project_number to google_drive_oauth before "
            "choosing folders."
        )
    else:
        receipt_folder = drive_settings.get("receipt_folder")
        backup_folder = drive_settings.get("backup_folder")
        left, right = st.columns(2)
        with left:
            st.markdown("**Receipt folder**")
            if isinstance(receipt_folder, Mapping):
                st.caption(str(receipt_folder.get("name", "")))
            selected_receipt = folder_picker(
                access_token=access_token,
                api_key=config.picker_api_key,
                project_number=config.project_number,
                key=f"receipt-folder-{profile_key}",
            )
            if selected_receipt is not None:
                try:
                    _save_selected_folder(
                        profile_key,
                        drive_settings,
                        "receipt_folder",
                        selected_receipt,
                        client=client,
                        store_path=store_path,
                    )
                except (GoogleDriveError, LocalProfileStoreError) as exc:
                    st.error(str(exc))
        with right:
            st.markdown("**Backup folder**")
            if isinstance(backup_folder, Mapping):
                st.caption(str(backup_folder.get("name", "")))
            selected_backup = folder_picker(
                access_token=access_token,
                api_key=config.picker_api_key,
                project_number=config.project_number,
                key=f"backup-folder-{profile_key}",
            )
            if selected_backup is not None:
                try:
                    _save_selected_folder(
                        profile_key,
                        drive_settings,
                        "backup_folder",
                        selected_backup,
                        client=client,
                        store_path=store_path,
                    )
                except (GoogleDriveError, LocalProfileStoreError) as exc:
                    st.error(str(exc))

    st.divider()
    reconnect_url = authorization_url(
        config,
        profile_key,
        redirect_uri,
        login_hint=authorized_email,
    )
    st.link_button("Reconnect Google Drive", reconnect_url)
    confirm_disconnect = st.checkbox(
        "Remove this profile's Google Drive authorization and folder selections",
        key=f"disconnect-google-drive-{profile_key}",
    )
    if st.button(
        "Disconnect Google Drive",
        disabled=not confirm_disconnect,
        key=f"disconnect-google-drive-button-{profile_key}",
    ):
        try:
            client.revoke()
            update_local_profile_google_drive(profile_key, None, path=store_path)
        except (GoogleDriveError, LocalProfileStoreError) as exc:
            st.error(str(exc))
        else:
            st.cache_resource.clear()
            st.session_state["google_drive_admin_notice"] = (
                f"Google Drive was disconnected for profile '{profile_key}'."
            )
            st.rerun()
