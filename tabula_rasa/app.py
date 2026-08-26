from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import sys

# Streamlit Community Cloud adds this file's directory, rather than the
# repository root, to sys.path when the entry point lives in a subdirectory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from tabula_rasa.business_profiles import (
    BusinessProfileConfigurationError,
    load_business_profiles,
    select_profile_secrets,
)
from tabula_rasa.ledger_auth import logout, require_authentication
from tabula_rasa.google_drive import (
    GoogleDriveClient,
    GoogleDriveConfigurationError,
    load_oauth_config,
)
from tabula_rasa.google_drive_admin import process_google_drive_oauth_callback
from tabula_rasa.local_profile_admin import render_local_profile_admin
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    local_profile_admin_available,
    local_profile_revision,
    merged_profile_secrets,
)
from tabula_rasa.page_renderers.accounts import AccountsContext, render_accounts
from tabula_rasa.page_renderers.categories import (
    CategoriesContext,
    render_categories,
)
from tabula_rasa.page_renderers.data_backup import (
    DataBackupContext,
    render_data_backup,
)
from tabula_rasa.page_renderers.dashboard import DashboardContext, render_dashboard
from tabula_rasa.page_renderers.mileage import (
    MileageContext,
    render_mileage,
)
from tabula_rasa.page_renderers.reports import ReportsContext, render_reports
from tabula_rasa.page_renderers.transactions import (
    TransactionsContext,
    render_transactions,
)
from tabula_rasa.presentation import (
    apply_global_styles,
    reset_profile_presentation_state,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageError,
)
from tabula_rasa.submission_guard import is_recent_duplicate, mark_completed
from tabula_rasa.receipt_backfill import (
    prepare_backup_receipt_manifest,
)


STORAGE_IMPLEMENTATION_VERSION = 11
def alert_list(title: str, messages: list[str]) -> str:
    """Format multiple alert messages as a readable Markdown list."""
    return f"**{title}**\n\n- " + "\n- ".join(messages)


@st.cache_resource
def get_storage(
    profile_key: str,
    implementation_version: int,
    configuration_revision: str,
) -> GoogleSheetsStorage:
    # Include the implementation version in Streamlit's cache key. Otherwise a
    # storage instance created before a deployment can survive with an older
    # class definition that does not contain newly added methods.
    del implementation_version, configuration_revision
    secrets = merged_profile_secrets(
        st.secrets,
        path=LOCAL_PROFILE_STORE_PATH,
    )
    return GoogleSheetsStorage.from_secrets(
        select_profile_secrets(secrets, profile_key)
    )


def report_storage_error(error: StorageError) -> None:
    st.error(str(error))


def current_app_url() -> str:
    """Return Streamlit's current URL without assuming context in tests."""
    context = getattr(st, "context", None)
    return str(getattr(context, "url", "") or "")


@st.cache_resource
def get_drive_client(
    profile_key: str,
    configuration_revision: str,
) -> GoogleDriveClient:
    """Build a Drive client only when the selected profile is connected."""
    del configuration_revision
    app_secrets = merged_profile_secrets(
        st.secrets,
        path=LOCAL_PROFILE_STORE_PATH,
    )
    profile_secrets = select_profile_secrets(app_secrets, profile_key)
    config = load_oauth_config(app_secrets)
    drive_settings = profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        raise GoogleDriveConfigurationError(
            "Google Drive is not connected for this business profile."
        )
    return GoogleDriveClient(config, drive_settings)


def receipt_manifest_for_backup(
    storage: GoogleSheetsStorage,
    *,
    profile_key: str,
    drive_settings: Mapping[str, object] | None,
    configuration_revision: str,
) -> dict[str, object]:
    """Build a fresh profile-scoped receipt inventory for one ledger backup."""
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    if not isinstance(receipt_folder, Mapping):
        raise GoogleDriveConfigurationError(
            "A current-format backup requires a selected Google Drive receipt "
            "folder so its receipt inventory is complete."
        )
    drive = get_drive_client(profile_key, configuration_revision)
    return prepare_backup_receipt_manifest(
        storage,
        drive,
        profile_key=profile_key,
        folder_id=str(receipt_folder["id"]),
    )


def reset_widget_state_if_requested(
    flag: str,
    *,
    keys: tuple[str, ...],
    prefixes: tuple[str, ...] = (),
) -> None:
    """Clear create-form widgets only on the rerun after a successful write."""
    if not st.session_state.pop(flag, False):
        return
    for key in list(st.session_state):
        if key in keys or any(key.startswith(prefix) for prefix in prefixes):
            st.session_state.pop(key, None)


def schedule_widget_reset(flag: str) -> None:
    st.session_state[flag] = True


def _select_operational_page() -> None:
    """Leave the shared route state aligned with the operational radio."""
    st.session_state["active_page"] = st.session_state["navigation_page"]


def _open_account_settings() -> None:
    """Open settings with no operational route selected."""
    st.session_state["active_page"] = "Account settings"
    st.session_state["navigation_page"] = None


def confirmed_write(
    action: str,
    payload: dict,
    operation,
    success_message,
    *,
    on_success=None,
    on_confirmed=None,
) -> None:
    profile_action = f"{st.session_state.get('business_profile', 'default')}:{action}"
    if is_recent_duplicate(st.session_state, profile_action, payload):
        st.warning("This submission was already completed. No duplicate was created.")
        return
    try:
        result = operation()
    except StorageError as error:
        report_storage_error(error)
        return
    mark_completed(st.session_state, profile_action, payload)
    if on_confirmed is not None:
        on_confirmed(result)
    if on_success is not None:
        on_success()
    st.session_state["workbook_data_revision"] = (
        int(st.session_state.get("workbook_data_revision", 0)) + 1
    )
    st.session_state["write_success_notice"] = (
        success_message(result) if callable(success_message) else success_message
    )
    st.rerun()


st.set_page_config(page_title="Project Tabula Rasa", page_icon="📒", layout="wide")
apply_global_styles()

require_authentication()

profile_admin_enabled = local_profile_admin_available(
    st.get_option("server.address")
)
try:
    effective_secrets = merged_profile_secrets(
        st.secrets,
        path=LOCAL_PROFILE_STORE_PATH,
    )
    profiles = load_business_profiles(effective_secrets)
except LocalProfileStoreError:
    st.error(
        "The local business-profile file is malformed or unavailable. "
        "Repair or move .streamlit/business_profiles.json and restart."
    )
    st.stop()
except BusinessProfileConfigurationError as error:
    if not profile_admin_enabled:
        st.error(str(error))
        st.stop()
    profiles = []

if profile_admin_enabled and (
    st.query_params.get("code")
    or st.query_params.get("error")
    or st.query_params.get("state")
):
    process_google_drive_oauth_callback(
        st.secrets,
        store_path=LOCAL_PROFILE_STORE_PATH,
    )

profile_by_key = {profile.key: profile for profile in profiles}
with st.sidebar:
    st.title("Project Tabula Rasa")
    if profiles:
        selected_profile_key = st.selectbox(
            "Business",
            list(profile_by_key),
            key="business_profile",
            format_func=lambda key: profile_by_key[key].name,
        )
        st.caption(profile_by_key[selected_profile_key].name)
    else:
        selected_profile_key = None
        st.info("Add the first business profile to continue.")

    reset_profile_presentation_state(
        st.session_state,
        previous_profile_key=st.session_state.get("previous_business_profile"),
        selected_profile_key=selected_profile_key,
    )
    st.session_state["previous_business_profile"] = selected_profile_key

    operational_pages = [
        "Dashboard",
        "Transactions",
        "Mileage",
        "Accounts",
        "Categories",
        "Reports",
        "Data & backup",
    ]
    if profiles:
        available_pages = [*operational_pages]
    else:
        available_pages = []
    available_routes = [*available_pages]
    if profile_admin_enabled:
        available_routes.append("Account settings")

    stored_page = st.session_state.get(
        "active_page",
        st.session_state.get("navigation_page"),
    )
    if stored_page == "Business profiles":
        stored_page = "Account settings"
    if stored_page not in available_routes:
        stored_page = (
            available_pages[0]
            if available_pages
            else available_routes[0]
            if available_routes
            else None
        )
    st.session_state["active_page"] = stored_page

    if available_pages:
        settings_active = st.session_state.get("active_page") == "Account settings"
        if settings_active:
            # Account settings is a separate utility destination. Keep the
            # operational radio unselected so choosing the page the user came
            # from still invokes its callback and returns to that page.
            st.session_state["navigation_page"] = None
        else:
            operational_page = st.session_state.get("navigation_page")
            if operational_page not in available_pages:
                st.session_state["navigation_page"] = available_pages[0]
        page = st.radio(
            "Navigate",
            available_pages,
            key="navigation_page",
            index=None if settings_active else 0,
            on_change=_select_operational_page,
        )
    else:
        page = None

    if profile_admin_enabled:
        st.divider()
        settings_active = st.session_state.get("active_page") == "Account settings"
        st.button(
            "Account settings",
            key="account_settings_navigation",
            type="primary" if settings_active else "secondary",
            on_click=_open_account_settings,
        )
        if settings_active:
            page = "Account settings"

    if page is None:
        st.error("No application page is available in this environment.")
        st.stop()

    previous_page = st.session_state.get("previous_navigation_page")
    if previous_page != page:
        table_generation_by_page = {
            "Transactions": "transaction_ledger_generation",
            "Mileage": "mileage_log_generation",
            "Accounts": "account_table_generation",
            "Categories": "category_table_generation",
        }
        if table_generation := table_generation_by_page.get(page):
            st.session_state[table_generation] = (
                int(st.session_state.get(table_generation, 0)) + 1
            )
    st.session_state["previous_navigation_page"] = page
    st.divider()
    if st.button("Log out", width="stretch"):
        logout()

if page == "Account settings":
    notice = st.session_state.pop("local_profile_admin_notice", None)
    if notice:
        st.success(notice)
    render_local_profile_admin(
        st.secrets,
        effective_secrets,
        current_url=current_app_url(),
        store_path=LOCAL_PROFILE_STORE_PATH,
    )
else:
    try:
        revision = (
            local_profile_revision(LOCAL_PROFILE_STORE_PATH)
        )
        storage = get_storage(
            selected_profile_key,
            STORAGE_IMPLEMENTATION_VERSION,
            revision,
        )
        initialized_profiles = st.session_state.setdefault(
            "defaults_initialized_profiles", set()
        )
        if selected_profile_key not in initialized_profiles:
            storage.ensure_defaults()
            initialized_profiles.add(selected_profile_key)

    except (LocalProfileStoreError, StorageError) as error:
        if isinstance(error, StorageError):
            report_storage_error(error)
        else:
            st.error("The local business-profile file could not be read safely.")
        st.stop()

    with st.sidebar:
        st.caption(f"Workbook: {storage.workbook_title}")

if page != "Account settings":
    notice = st.session_state.pop("write_success_notice", None)
    notice_placeholder = st.empty()
    if notice:
        notice_placeholder.success(str(notice))


if page == "Dashboard":
    render_dashboard(DashboardContext(selected_profile_key, storage))


elif page == "Transactions":
    render_transactions(
        TransactionsContext(
            profile_key=selected_profile_key,
            storage=storage,
            profile_secrets=profile_by_key[selected_profile_key].secrets,
            configuration_revision=revision,
            get_drive_client=get_drive_client,
            confirmed_write=confirmed_write,
            report_storage_error=report_storage_error,
            reset_widget_state_if_requested=reset_widget_state_if_requested,
            schedule_widget_reset=schedule_widget_reset,
        )
    )


elif page == "Mileage":
    render_mileage(
        MileageContext(
            profile_key=selected_profile_key,
            storage=storage,
            confirmed_write=confirmed_write,
            report_storage_error=report_storage_error,
            reset_widget_state_if_requested=reset_widget_state_if_requested,
            schedule_widget_reset=schedule_widget_reset,
        )
    )



elif page == "Accounts":
    render_accounts(
        AccountsContext(
            profile_key=selected_profile_key,
            storage=storage,
            confirmed_write=confirmed_write,
            report_storage_error=report_storage_error,
            reset_widget_state_if_requested=reset_widget_state_if_requested,
            schedule_widget_reset=schedule_widget_reset,
        )
    )


elif page == "Categories":
    render_categories(
        CategoriesContext(
            profile_key=selected_profile_key,
            storage=storage,
            confirmed_write=confirmed_write,
            report_storage_error=report_storage_error,
            reset_widget_state_if_requested=reset_widget_state_if_requested,
            schedule_widget_reset=schedule_widget_reset,
        )
    )
elif page == "Reports":
    render_reports(
        ReportsContext(
            profile_key=selected_profile_key,
            storage=storage,
            report_storage_error=report_storage_error,
        )
    )


elif page == "Data & backup":
    render_data_backup(
        DataBackupContext(
            profile_key=selected_profile_key,
            storage=storage,
            drive_settings=(
                profile_by_key[selected_profile_key].secrets.get("google_drive")
                if isinstance(
                    profile_by_key[selected_profile_key].secrets.get("google_drive"),
                    Mapping,
                )
                else None
            ),
            synology_recovery_settings=profile_by_key[
                selected_profile_key
            ].secrets.get("synology_recovery"),
            configuration_revision=revision,
            get_drive_client=get_drive_client,
            receipt_manifest_for_backup=receipt_manifest_for_backup,
            confirmed_write=confirmed_write,
            report_storage_error=report_storage_error,
        )
    )
