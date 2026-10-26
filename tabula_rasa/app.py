"""Local operator administration; bookkeeping runs in the browser application."""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from tabula_rasa.google_drive_admin import process_google_drive_oauth_callback
from tabula_rasa.ledger_auth import logout, require_authentication
from tabula_rasa.legal import render_public_legal_page
from tabula_rasa.local_profile_admin import render_local_profile_admin
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH, LocalProfileStoreError,
    local_profile_admin_available, merged_profile_secrets,
)
from tabula_rasa.presentation import apply_global_styles, render_global_footer

st.set_page_config(page_title="Tabula Rasa administration", page_icon="📒", layout="wide")
apply_global_styles()
if render_public_legal_page():
    render_global_footer()
    st.stop()

require_authentication()
if not local_profile_admin_available(st.get_option("server.address")):
    st.error("Local administration requires the restricted loopback operator environment. "
             "Use the browser application for bookkeeping.")
    render_global_footer()
    st.stop()

try:
    effective_secrets = merged_profile_secrets(st.secrets.to_dict(), path=LOCAL_PROFILE_STORE_PATH)
except LocalProfileStoreError:
    st.error("The local business-profile file is malformed or unavailable. "
             "Repair or move .streamlit/business_profiles.json and restart.")
    render_global_footer()
    st.stop()

if any(st.query_params.get(key) for key in ("code", "error", "state")):
    process_google_drive_oauth_callback(st.secrets, store_path=LOCAL_PROFILE_STORE_PATH)

with st.sidebar:
    st.title("Tabula Rasa administration")
    st.caption("Bookkeeping is available in the browser application.")
    if st.button("Log out", width="stretch"):
        logout()

notice = st.session_state.pop("local_profile_admin_notice", None)
if notice:
    st.success(notice)
context = getattr(st, "context", None)
render_local_profile_admin(
    st.secrets, effective_secrets,
    current_url=str(getattr(context, "url", "") or ""),
    store_path=LOCAL_PROFILE_STORE_PATH,
)
render_global_footer()
