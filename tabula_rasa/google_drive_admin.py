"""Authenticated local administration for business-scoped Drive OAuth."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import streamlit as st

from tabula_rasa.google_drive import (
    GoogleDriveAccessError,
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
    ensure_google_drive_disconnect_allowed,
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


def _folder_display_name(
    folder: Mapping[str, Any],
    fallback: str = "",
) -> str:
    return str(folder.get("name") or fallback)


def _ensure_storage_root_is_not_directly_nested(
    profile_key: str,
    selected_root: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    """Reject known root reuse or direct nesting using visible folder IDs only."""
    selected_id = str(selected_root.get("id", ""))
    parents = selected_root.get("parents")
    parent_ids = (
        {str(parent_id) for parent_id in parents}
        if isinstance(parents, list)
        else set()
    )
    for other_key, profile in local_profiles.items():
        if other_key == profile_key:
            continue
        drive = profile.get("google_drive")
        other_root = drive.get("storage_root") if isinstance(drive, Mapping) else None
        if not isinstance(other_root, Mapping):
            continue
        other_id = str(other_root.get("id", ""))
        if other_id and (other_id == selected_id or other_id in parent_ids):
            raise GoogleDriveConfigurationError(
                "Google Drive storage roots cannot be nested between business "
                "profiles."
            )


def _revalidated_storage_settings(
    client: GoogleDriveClient,
    profile_key: str,
    previous: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep only destinations confirmed under the newly authorized account."""
    preserved: dict[str, Any] = {}
    storage_root = previous.get("storage_root")
    if isinstance(storage_root, Mapping):
        root_id = str(storage_root.get("id", ""))
        try:
            root = client.folder(root_id)
        except GoogleDriveError:
            return preserved
        root_properties = root.get("appProperties")
        if (
            not isinstance(root_properties, Mapping)
            or root_properties.get("tabulaRasaKind") != "storage-root"
            or root_properties.get("tabulaRasaProfile") != profile_key
        ):
            return preserved
        root_id = str(root["id"])
        preserved["storage_root"] = {
            "id": root_id,
            "name": str(root["name"]),
        }
        for field, storage_kind in (
            ("receipt_folder", "receipts"),
            ("backup_folder", "ledger-backups"),
        ):
            child = previous.get(field)
            if not isinstance(child, Mapping):
                continue
            try:
                confirmed = client.folder(str(child.get("id", "")))
            except GoogleDriveError:
                continue
            parents = confirmed.get("parents")
            if not isinstance(parents, list):
                parents = []
            properties = confirmed.get("appProperties")
            if (
                root_id in parents
                and isinstance(properties, Mapping)
                and properties.get("tabulaRasaKind") == storage_kind
                and properties.get("tabulaRasaProfile") == profile_key
                and properties.get("tabulaRasaStorageRoot") == root_id
            ):
                preserved[field] = {
                    "id": str(confirmed["id"]),
                    "name": str(confirmed["name"]),
                }
        return preserved

    return preserved


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
        local_profiles = load_local_profiles(store_path)
        if profile_key not in local_profiles:
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
        previous_drive = local_profiles[profile_key].get("google_drive")
        if isinstance(previous_drive, Mapping):
            client = GoogleDriveClient(config, drive_settings)
            drive_settings.update(
                _revalidated_storage_settings(
                    client,
                    profile_key,
                    previous_drive,
                )
            )
            storage_root = drive_settings.get("storage_root")
            if isinstance(storage_root, Mapping):
                # Re-fetch the root after revalidation so direct-parent metadata
                # is available for the minimal cross-profile check; persisted
                # settings intentionally retain only the validated ID and name.
                storage_root = client.folder(str(storage_root.get("id", "")))
                _ensure_storage_root_is_not_directly_nested(
                    profile_key,
                    storage_root,
                    local_profiles,
                )
        update_local_profile_google_drive(
            profile_key,
            drive_settings,
            path=store_path,
        )
        st.session_state["local_profile_admin_unlocked"] = True
        st.session_state["google_drive_admin_notice"] = (
            f"Google Drive was connected for profile '{profile_key}'. "
            "Choose or provision its profile storage folders next."
        )
        st.session_state["navigation_page"] = "Account settings"
        st.session_state["active_page"] = "Account settings"
    except (GoogleDriveError, LocalProfileStoreError) as exc:
        st.session_state["google_drive_admin_error"] = str(exc)
        st.session_state["navigation_page"] = "Account settings"
        st.session_state["active_page"] = "Account settings"
    finally:
        st.query_params.clear()
    st.cache_resource.clear()
    st.rerun()
    return True


def validate_google_drive_profile(
    app_secrets: Mapping[str, Any],
    profile_key: str,
    drive_settings: Mapping[str, Any],
    *,
    local_profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    """Re-read one profile's Drive grant and configured destinations."""
    storage_root = drive_settings.get("storage_root")
    if not isinstance(storage_root, Mapping) or not storage_root.get("id"):
        raise GoogleDriveConfigurationError(
            "Select or create the Google Drive storage root."
        )
    root_id = str(storage_root.get("id") or "")
    config = load_oauth_config(app_secrets)
    client = _cached_drive_client(
        config,
        profile_key,
        json.dumps(dict(drive_settings), sort_keys=True),
    )
    root = client.folder(root_id)
    client.validate_storage_configuration(profile_key, root_folder=root)
    _ensure_storage_root_is_not_directly_nested(
        profile_key,
        root,
        local_profiles,
    )


def _save_storage_root(
    profile_key: str,
    drive_settings: Mapping[str, Any],
    selected: Mapping[str, Any],
    *,
    client: GoogleDriveClient,
    store_path: Path,
) -> bool:
    selected_id = str(selected.get("id", ""))
    existing = drive_settings.get("storage_root")
    folder = client.folder(selected_id)
    if not isinstance(folder, Mapping):
        raise GoogleDriveAccessError(
            "Google Drive could not return the selected folder details. Retry."
        )
    folder_id = str(folder.get("id") or "")
    folder_name = str(folder.get("name") or "").strip()
    if not folder_id or not folder_name:
        raise GoogleDriveAccessError(
            "Google Drive could not return the selected folder details. Retry."
        )
    updated = dict(drive_settings)
    updated["storage_root"] = {
        "id": folder_id,
        "name": folder_name,
    }
    same_root = isinstance(existing, Mapping) and existing.get("id") == selected_id
    if same_root and existing.get("name") == folder_name:
        return False
    if not same_root:
        updated.pop("receipt_folder", None)
        updated.pop("backup_folder", None)
    update_local_profile_google_drive(profile_key, updated, path=store_path)
    st.session_state["google_drive_admin_notice"] = (
        (
            f"Google Drive storage root name refreshed for profile '{profile_key}'."
            if same_root
            else (
                f"Google Drive storage root saved for profile '{profile_key}'. "
                "Provision its receipt and ledger-backup folders next."
            )
        )
    )
    st.cache_resource.clear()
    st.rerun()
    return True


def _create_storage_root(
    profile_key: str,
    profile_name: str,
    drive_settings: Mapping[str, Any],
    *,
    client: GoogleDriveClient,
    store_path: Path,
) -> bool:
    root = client.create_storage_root(
        profile_key,
        f"{profile_name} Storage",
    )
    local_profiles = load_local_profiles(store_path)
    full_root = client.folder(str(root.get("id", "")))
    _ensure_storage_root_is_not_directly_nested(
        profile_key,
        full_root,
        local_profiles,
    )
    updated = dict(drive_settings)
    updated["storage_root"] = {
        "id": str(full_root["id"]),
        "name": str(full_root["name"]),
    }
    updated.pop("receipt_folder", None)
    updated.pop("backup_folder", None)
    update_local_profile_google_drive(profile_key, updated, path=store_path)
    st.session_state["google_drive_admin_notice"] = (
        f"Google Drive storage root created for profile '{profile_key}'. "
        "Provision its receipt and ledger-backup folders next."
    )
    st.cache_resource.clear()
    st.rerun()
    return True


def _provision_storage_children(
    profile_key: str,
    drive_settings: Mapping[str, Any],
    *,
    client: GoogleDriveClient,
    store_path: Path,
) -> bool:
    storage_root = drive_settings.get("storage_root")
    if not isinstance(storage_root, Mapping):
        raise GoogleDriveConfigurationError(
            "Select or create a storage root before provisioning its folders."
        )
    storage_root_id = str(storage_root.get("id", ""))
    if not storage_root_id:
        raise GoogleDriveConfigurationError(
            "The configured storage root is missing its Google Drive folder ID."
        )
    children = client.provision_storage_children(profile_key, storage_root_id)
    updated = dict(drive_settings)
    updated["receipt_folder"] = children["receipts"]
    updated["backup_folder"] = children["ledger-backups"]
    update_local_profile_google_drive(profile_key, updated, path=store_path)
    st.session_state["google_drive_admin_notice"] = (
        f"Google Drive receipt and ledger-backup folders are ready for "
        f"'{profile_key}'."
    )
    st.cache_resource.clear()
    st.rerun()
    return True


def render_google_drive_admin(
    app_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]],
    *,
    current_url: str,
    selected_profile_key: str | None = None,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Render connection, folder selection, test, and disconnect controls."""
    st.divider()
    st.subheader("Google Drive OAuth")
    st.write(
        "Connect the human Google account that owns each business's Drive files. "
        "The OAuth client is shared, while refresh tokens, storage roots, and "
        "child folders remain isolated by business profile."
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

    profile_key = selected_profile_key
    if profile_key is None:
        profile_key = st.selectbox(
            "Business profile to connect",
            list(local_profiles),
            format_func=lambda key: str(local_profiles[key].get("name", key)),
            key="google_drive_profile_key",
        )
    if profile_key not in local_profiles:
        st.info("Select a local business profile before configuring Google Drive.")
        return
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
        remove_connection_error = st.empty()
        if st.button(
            "Remove saved connection",
            disabled=not remove_invalid,
            key=f"remove-invalid-google-drive-button-{profile_key}",
        ):
            try:
                update_local_profile_google_drive(profile_key, None, path=store_path)
            except LocalProfileStoreError as remove_error:
                remove_connection_error.error(str(remove_error))
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
        storage_root = drive_settings.get("storage_root")
        receipt_folder = drive_settings.get("receipt_folder")
        backup_folder = drive_settings.get("backup_folder")
        st.markdown("**Profile storage root**")
        if isinstance(storage_root, Mapping):
            st.caption(_folder_display_name(storage_root))
        storage_root_error = st.empty()
        selected_root = folder_picker(
            access_token=access_token,
            api_key=config.picker_api_key,
            project_number=config.project_number,
            key=f"storage-root-{profile_key}",
        )
        if selected_root is not None:
            try:
                local_profiles = load_local_profiles(store_path)
                folder = client.folder(str(selected_root.get("id", "")))
                _ensure_storage_root_is_not_directly_nested(
                    profile_key,
                    folder,
                    local_profiles,
                )
                _save_storage_root(
                    profile_key,
                    drive_settings,
                    selected_root,
                    client=client,
                    store_path=store_path,
                )
            except (GoogleDriveError, LocalProfileStoreError) as exc:
                storage_root_error.error(str(exc))
        if not isinstance(storage_root, Mapping):
            create_root_error = st.empty()
            if st.button(
                "Create storage root",
                key=f"create-storage-root-{profile_key}",
            ):
                try:
                    _create_storage_root(
                        profile_key,
                        str(profile.get("name", profile_key)),
                        drive_settings,
                        client=client,
                        store_path=store_path,
                    )
                except (GoogleDriveError, LocalProfileStoreError) as exc:
                    create_root_error.error(str(exc))
        if isinstance(storage_root, Mapping):
            if isinstance(receipt_folder, Mapping):
                st.caption(
                    f"Receipts: {_folder_display_name(receipt_folder, 'Provisioned')}"
                )
            if isinstance(backup_folder, Mapping):
                st.caption(
                    "Ledger backups: "
                    f"{_folder_display_name(backup_folder, 'Provisioned')}"
                )
            provision_error = st.empty()
            if st.button(
                "Provision storage folders",
                type="primary",
                key=f"provision-storage-folders-{profile_key}",
            ):
                try:
                    _provision_storage_children(
                        profile_key,
                        drive_settings,
                        client=client,
                        store_path=store_path,
                    )
                except (GoogleDriveError, LocalProfileStoreError) as exc:
                    provision_error.error(str(exc))

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
    disconnect_error = st.empty()
    if st.button(
        "Disconnect Google Drive",
        disabled=not confirm_disconnect,
        key=f"disconnect-google-drive-button-{profile_key}",
    ):
        try:
            ensure_google_drive_disconnect_allowed(profile)
            client.revoke()
            update_local_profile_google_drive(profile_key, None, path=store_path)
        except (GoogleDriveError, LocalProfileStoreError) as exc:
            disconnect_error.error(str(exc))
        else:
            st.cache_resource.clear()
            st.session_state["google_drive_admin_notice"] = (
                f"Google Drive was disconnected for profile '{profile_key}'."
            )
            st.rerun()
