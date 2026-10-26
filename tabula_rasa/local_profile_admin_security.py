"""Local security information without credential export controls."""

import streamlit as st


def render_security_deployment_info() -> None:
    """Explain local and commercial custody without reading or exporting secrets."""
    st.subheader("Security & deployment information")
    st.write(
        "Account settings is local administration for every configured business "
        "profile. It is not per-user identity or permission management."
    )
    st.info(
        "The application password currently unlocks every local profile. Profile "
        "keys identify configuration and are not user accounts. Credentials are "
        "never displayed here."
    )
    st.write(
        "Local profile settings are stored in the ignored plaintext profile file "
        "and depend on operating-system protections. Commercial provider grants use "
        "separate encrypted server provisioning. Streamlit Cloud Secrets export "
        "is retired; local settings do not configure the commercial deployment."
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
