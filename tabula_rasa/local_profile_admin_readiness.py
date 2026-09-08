"""Readiness validation and presentation for local business profiles."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import streamlit as st

from tabula_rasa.google_drive import GoogleDriveError
from tabula_rasa.google_drive_admin import validate_google_drive_profile
from tabula_rasa.local_profile_store import LocalProfileStoreError
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


def safe_readiness_error(stage: str, error: Exception) -> str:
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


def fresh_profile_readiness(
    profile_key: str,
    settings: Mapping[str, Any],
    *,
    app_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]] | None = None,
    drive_validator: Any = None,
) -> ProfileReadiness:
    """Run fresh Sheets and configured Drive checks for one profile."""
    validation_errors: list[str] = []
    profiles_for_isolation = local_profiles or {profile_key: settings}
    try:
        GoogleSheetsStorage.from_secrets_read_only(settings)
    except StorageError as error:
        validation_errors.append(safe_readiness_error("Sheets", error))

    drive = settings.get("google_drive")
    storage_root = drive.get("storage_root") if isinstance(drive, Mapping) else None
    if (
        isinstance(drive, Mapping)
        and isinstance(storage_root, Mapping)
        and storage_root.get("id")
    ):
        try:
            (drive_validator or validate_google_drive_profile)(
                app_secrets,
                profile_key,
                drive,
                local_profiles=profiles_for_isolation,
            )
        except (GoogleDriveError, LocalProfileStoreError) as error:
            validation_errors.append(safe_readiness_error("Drive", error))

    return profile_configuration_readiness(
        profile_key,
        settings,
        validation_errors=tuple(validation_errors),
    )


def readiness_for_display(
    profile_key: str,
    settings: Mapping[str, Any],
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


def render_profile_readiness(
    profile_key: str,
    settings: Mapping[str, Any],
    *,
    app_secrets: Mapping[str, Any],
    local_profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    st.subheader("Profile readiness")
    report = readiness_for_display(profile_key, settings)
    labels = {
        "incomplete": "Incomplete",
        "ready-local": "Ready locally",
    }
    status_key = f"profile_readiness_status_{report.status.replace('-', '_')}"
    with st.container(key=status_key):
        st.metric("Status", labels[report.status])
    for step in report.missing_steps:
        st.warning(step)
    for error in report.validation_errors:
        st.error(error)
    if report.status == "ready-local":
        st.info(
            "Local profile settings are ready. To publish them to Streamlit "
            "Community Cloud, run `python scripts/export_streamlit_secrets.py` "
            "from the repository root, paste the complete generated TOML into "
            "Streamlit App settings > Secrets, and save it. This local page "
            "cannot verify the separate hosted Secrets store; confirm the "
            "deployed app after saving. Local backup and Synology changes do not "
            "require a new export."
        )
    if st.button(
        "Run readiness check",
        type="primary",
        key=f"profile-readiness-check-{profile_key}",
    ):
        report = fresh_profile_readiness(
            profile_key,
            settings,
            app_secrets=app_secrets,
            local_profiles=local_profiles,
        )
        st.session_state[f"profile-readiness:{profile_key}"] = (
            profile_settings_fingerprint(settings),
            report,
        )
        st.rerun()
