"""Security/deployment information and hosted Secrets export UI."""

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
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    load_local_profiles,
)


def export_hosted_secrets_file(
    app_secrets: Mapping[str, object],
    *,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> Path:
    """Validate all local profiles and create a new hosted Secrets file."""
    local_profiles = load_local_profiles(store_path)
    if not local_profiles:
        raise LocalProfileStoreError(
            "At least one local business profile is required for hosted export."
        )
    document = build_streamlit_secrets_toml(app_secrets, local_profiles)
    return write_secure_export(document)


def render_security_deployment_info(
    app_secrets: Mapping[str, Any] | None = None,
    *,
    store_path: Path = LOCAL_PROFILE_STORE_PATH,
    export_function: Any = export_hosted_secrets_file,
) -> None:
    """Explain local/hosted boundaries without adding administration controls."""
    st.subheader("Security & deployment information")
    st.write(
        "Account settings is local administration for every configured business "
        "profile. It is not per-user identity or permission management."
    )
    st.info(
        "The application password currently unlocks every local profile. Profile "
        "keys identify configuration and are not user accounts. Private keys are "
        "never displayed after upload."
    )
    st.write(
        "Local profile settings are stored in the ignored plaintext profile file "
        "and depend on operating-system protections. Hosted changes require the "
        "documented Streamlit Secrets export and replacement process. Local backup "
        "paths and Synology metadata are excluded from that hosted projection."
    )
    st.subheader("Hosted Streamlit Secrets export")
    st.write(
        "Generate one combined Secrets document from every included local profile "
        "after its hosted settings are ready. The generated file is written only "
        "to the ignored local .streamlit directory and is never shown in this UI."
    )
    if app_secrets is not None and st.button(
        "Generate hosted Secrets file",
        key="generate-hosted-secrets-file",
    ):
        try:
            destination = export_function(
                app_secrets,
                store_path=store_path,
            )
        except (LocalProfileStoreError, SecretsExportError, OSError):
            st.error(
                "Hosted Streamlit Secrets export failed. Review every included "
                "local profile's Sheets and Google Drive settings, verify that "
                ".streamlit is writable, and retry. No hosted deployment was "
                "changed."
            )
        except Exception:
            st.error(
                "Hosted Streamlit Secrets export failed unexpectedly. Verify the "
                "local profile configuration and retry; no hosted deployment was "
                "changed."
            )
        else:
            st.success(f"Generated hosted Secrets file: {destination}")
            st.info(
                "Paste the complete file into Streamlit App settings > Secrets, "
                "save it, then delete the generated local file. Re-run profile "
                "readiness locally afterward; this page cannot verify hosted "
                "Secrets acceptance."
            )
    st.markdown(
        "See the [Account settings and profile setup guide]("
        "https://github.com/Roklion/Project_Tabula_Rasa/blob/main/docs/SETUP.md), "
        "[backup and recovery guide]("
        "https://github.com/Roklion/Project_Tabula_Rasa/blob/main/docs/"
        "BACKUP_RECOVERY.md), and [Synology recovery guide]("
        "https://github.com/Roklion/Project_Tabula_Rasa/blob/main/docs/"
        "BACKUP_RECOVERY.md#optional-synology-recovery-copy) for operational "
        "procedures."
    )
