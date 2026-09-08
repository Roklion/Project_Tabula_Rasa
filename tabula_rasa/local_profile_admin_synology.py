"""Local-only Synology recovery metadata administration."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import streamlit as st

from tabula_rasa.local_profile_store import (
    LocalProfileStoreError,
    update_local_profile_synology_recovery,
)
from tabula_rasa.synology_recovery import (
    PROFILE_ROOT_LAYOUT,
    SynologyRecoveryConfigurationError,
    resolve_synology_recovery_defaults,
)


def render_synology_recovery_admin(
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
        "each business. Project Tabula Rasa does not mount or connect to the NAS."
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
            value=str(existing.get("destination_path", defaults["destination_path"])),
            placeholder=f"/volume1/Backups/TabulaRasa/{profile_key}",
            help="Informational DSM path only. The app never opens or writes to it.",
        )
        schedule = st.text_input(
            "Cloud Sync schedule",
            value=str(existing.get("schedule", defaults["schedule"])),
            help="For example: Continuous, or Daily at 11:00 PM.",
        )
        retention_policy = st.text_area(
            "NAS retention policy",
            value=str(
                existing.get("retention_policy", defaults["retention_policy"])
            ),
            help=(
                "Destination deletions must remain disabled. Describe when an "
                "administrator may manually remove old NAS generations."
            ),
        )
        save_error = st.empty()
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
        update_local_profile_synology_recovery(
            profile_key,
            settings,
            path=store_path,
        )
    except LocalProfileStoreError as error:
        save_error.error(str(error))
        return

    st.cache_resource.clear()
    state = "enabled" if enabled else "disabled"
    st.session_state["local_profile_admin_notice"] = (
        f"Synology recovery was {state} for '{profile_key}'."
    )
    st.rerun()
