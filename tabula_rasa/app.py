from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import io
from pathlib import Path
import sys
import zipfile

# Streamlit Community Cloud adds this file's directory, rather than the
# repository root, to sys.path when the entry point lives in a subdirectory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
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
    GoogleDriveError,
    backup_filename_and_hash,
    load_oauth_config,
)
from tabula_rasa.google_drive_admin import process_google_drive_oauth_callback
from tabula_rasa.ledger_presentation import balances_frame, ledger_frame
from tabula_rasa.ledger_reporting import (
    rollup_account_values,
)
from tabula_rasa.hierarchy import (
    eligible_parent_ids,
    has_hierarchy_children,
    hierarchy_paths,
    ordered_hierarchy,
)
from tabula_rasa.local_profile_admin import render_local_profile_admin
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    local_profile_admin_available,
    local_profile_revision,
    merged_profile_secrets,
)
from tabula_rasa.page_renderers.dashboard import DashboardContext, render_dashboard
from tabula_rasa.page_renderers.mileage import MileageContext, render_mileage
from tabula_rasa.page_renderers.reports import ReportsContext, render_reports
from tabula_rasa.page_renderers.transactions import (
    TransactionsContext,
    render_transactions,
)
from tabula_rasa.presentation import (
    apply_global_styles,
    render_page_header,
    reset_profile_presentation_state,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageError,
    StorageValidationError,
)
from tabula_rasa.synology_recovery import (
    DESTINATION_DELETIONS,
    SYNC_DIRECTION,
    SynologyRecoveryConfigurationError,
    validate_synology_recovery_settings,
)
from tabula_rasa.submission_guard import is_recent_duplicate, mark_completed
from tabula_rasa.quickbooks_import import (
    REQUIRED_COLUMNS as QUICKBOOKS_REQUIRED_COLUMNS,
    general_ledger_rows,
)
from tabula_rasa.quickbooks_mileage_import import (
    missing_required_columns as missing_quickbooks_mileage_columns,
)
from tabula_rasa.receipt_manifest import (
    ReceiptManifestError,
)
from tabula_rasa.receipt_backfill import (
    ReceiptPreparationError,
    prepare_backup_receipt_manifest,
)


STORAGE_IMPLEMENTATION_VERSION = 10
ACCOUNT_TYPES = ["Bank", "Cash", "Credit card", "Short-term debt", "Equity", "Other"]
ACCOUNT_CLASSIFICATIONS = ["Asset", "Liability", "Equity"]
FIXED_TYPE_CLASSIFICATIONS = {
    "Bank": "Asset",
    "Cash": "Asset",
    "Credit card": "Liability",
    "Short-term debt": "Liability",
    "Equity": "Equity",
}


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
    profile_secrets: Mapping[str, object],
    configuration_revision: str,
) -> dict[str, object]:
    """Build a fresh profile-scoped receipt inventory for one ledger backup."""
    drive_settings = profile_secrets.get("google_drive")
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

    pages = [
        "Dashboard",
        "Transactions",
        "Mileage",
        "Accounts",
        "Categories",
        "Reports",
        "Data & backup",
    ]
    if profile_admin_enabled:
        pages.append("Business profiles")
    if not profiles:
        pages = ["Business profiles"]
    if st.session_state.get("navigation_page") not in pages:
        st.session_state["navigation_page"] = pages[0]
    page = st.radio("Navigate", pages, key="navigation_page")
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

if page == "Business profiles":
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

if page != "Business profiles":
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
    render_page_header(
        "Accounts", "Track bank, cash, credit card, and other manual balances."
    )
    try:
        storage.prefetch_worksheets("Accounts", "Transactions")
        accounts = storage.list_accounts(active_only=False)
        transactions = storage.list_transactions()
        balances = balances_frame(accounts, transactions)
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    account_paths = hierarchy_paths(accounts)
    account_by_id = {
        account_id: account
        for account in accounts
        if (account_id := str(account.get("id") or "").strip())
    }
    account_option_ids = [
        account["id"] for account in ordered_hierarchy(accounts)
    ]
    direct_balance_by_id = balances.set_index("ID")["Balance"].to_dict()
    balance_by_id = rollup_account_values(accounts, direct_balance_by_id)
    transaction_count_by_account: dict[str, int] = {}
    for transaction in transactions:
        involved_account_ids = {
            str(transaction.get("account_id") or "").strip(),
            str(transaction.get("to_account_id") or "").strip(),
        }
        for account_id in involved_account_ids - {""}:
            transaction_count_by_account[account_id] = (
                transaction_count_by_account.get(account_id, 0) + 1
            )
    transaction_count_by_account = rollup_account_values(
        accounts, transaction_count_by_account
    )
    account_rows = []
    account_ids = []
    for account in ordered_hierarchy(accounts):
        account_ids.append(account["id"])
        parent_id = str(account.get("parent_id") or "").strip()
        parent = account_by_id.get(parent_id) if parent_id else None
        account_rows.append(
            {
                "Account": (
                    f'↳ {account["name"]}' if parent else account["name"]
                ),
                "Layer": "Layer 2" if parent else "Layer 1",
                "Parent": parent.get("name") or "" if parent else "",
                "Classification": account["classification"],
                "Type": account["type"],
                "Active": account["active"],
                "Balance": balance_by_id.get(account["id"], 0.0),
                "Transaction count": transaction_count_by_account.get(
                    account["id"], 0
                ),
            }
        )
    account_table_key = (
        "account_table_"
        f"{selected_profile_key}_"
        f"{st.session_state.get('account_table_generation', 0)}"
    )

    def select_account() -> None:
        selected_rows = st.session_state[account_table_key].selection.rows
        if selected_rows:
            st.session_state["edit_account_id"] = account_ids[selected_rows[0]]

    account_event = st.dataframe(
        pd.DataFrame(account_rows),
        hide_index=True,
        width="stretch",
        key=account_table_key,
        on_select=select_account,
        selection_mode="single-row",
        column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
    )
    reset_widget_state_if_requested(
        "reset_add_account_form",
        keys=(
            f"new_account_name_{selected_profile_key}",
            f"new_account_type_{selected_profile_key}",
            f"new_account_opening_{selected_profile_key}",
        ),
        prefixes=(
            f"new_account_classification_{selected_profile_key}_",
            f"new_account_parent_{selected_profile_key}_",
        ),
    )
    with st.expander("Add account", expanded=True):
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns(5)
            name = c1.text_input(
                "Account name", key=f"new_account_name_{selected_profile_key}"
            )
            account_type = c2.selectbox(
                "Type",
                ACCOUNT_TYPES,
                key=f"new_account_type_{selected_profile_key}",
            )
            classification_options = [
                FIXED_TYPE_CLASSIFICATIONS[account_type]
            ] if account_type in FIXED_TYPE_CLASSIFICATIONS else ACCOUNT_CLASSIFICATIONS
            classification = c3.selectbox(
                "Balance-sheet classification",
                classification_options,
                key=(
                    f"new_account_classification_{selected_profile_key}_"
                    f"{account_type}"
                ),
            )
            opening = c4.number_input(
                "Opening balance",
                value=0.0,
                format="%.2f",
                key=f"new_account_opening_{selected_profile_key}",
                help=(
                    "Use positive balances for assets and negative balances for "
                    "liabilities and equity."
                ),
            )
            parent_options = [""] + eligible_parent_ids(
                accounts,
                compatibility_field="classification",
                compatibility_value=classification,
            )
            parent_id = c5.selectbox(
                "Parent account (optional)",
                parent_options,
                key=(
                    f"new_account_parent_{selected_profile_key}_"
                    f"{classification}"
                ),
                format_func=lambda value: (
                    "None (Layer 1)" if not value else account_paths[value]
                ),
            )
            if st.button("Add account", type="primary"):
                payload = {
                    "name": name,
                    "account_type": account_type,
                    "classification": classification,
                    "opening_balance": opening,
                    "parent_id": parent_id,
                }
                confirmed_write(
                    "create_account",
                    payload,
                    lambda: storage.create_account(
                        name,
                        account_type,
                        opening,
                        classification=classification,
                        parent_id=parent_id,
                    ),
                    "Account added.",
                    on_success=lambda: schedule_widget_reset(
                        "reset_add_account_form"
                    ),
                )

    if accounts:
        selected_rows = account_event.selection.rows
        if st.session_state.get("edit_account_id") not in account_by_id:
            st.session_state["edit_account_id"] = account_ids[0]
        st.caption("Select an account row (or double-click it) to edit it.")
        with st.expander(
            "Edit or deactivate account", expanded=bool(selected_rows)
        ):
            account_id = st.selectbox(
                "Account to manage",
                account_option_ids,
                format_func=account_paths.get,
                key="edit_account_id",
            )
            selected = account_by_id[account_id]
            with st.container(border=True):
                edited_name = st.text_input(
                    "Edit account name",
                    value=selected["name"],
                    key=f"edit_account_name_{account_id}",
                )
                edited_type = st.selectbox(
                    "Edit account type",
                    ACCOUNT_TYPES,
                    index=ACCOUNT_TYPES.index(selected["type"]),
                    key=f"edit_account_type_{account_id}",
                )
                edited_classification_options = [
                    FIXED_TYPE_CLASSIFICATIONS[edited_type]
                ] if edited_type in FIXED_TYPE_CLASSIFICATIONS else ACCOUNT_CLASSIFICATIONS
                edited_classification = st.selectbox(
                    "Edit balance-sheet classification",
                    edited_classification_options,
                    index=edited_classification_options.index(
                        FIXED_TYPE_CLASSIFICATIONS.get(
                            edited_type,
                            selected["classification"],
                        )
                    ),
                    key=(
                        f"edit_account_classification_{account_id}_{edited_type}"
                    ),
                )
                edited_opening = st.number_input(
                    "Edit opening balance",
                    value=float(selected["opening_balance"]),
                    format="%.2f",
                    key=f"edit_account_opening_{account_id}",
                )
                edited_active = st.checkbox(
                    "Active",
                    value=selected["active"],
                    key=f"edit_account_active_{account_id}",
                )
                has_children = has_hierarchy_children(accounts, account_id)
                edited_parent_options = [""] + eligible_parent_ids(
                    accounts,
                    compatibility_field="classification",
                    compatibility_value=edited_classification,
                    item_id=account_id,
                )
                current_parent_id = str(selected.get("parent_id") or "").strip()
                edited_parent_id = st.selectbox(
                    "Edit parent account",
                    edited_parent_options,
                    index=(
                        edited_parent_options.index(current_parent_id)
                        if current_parent_id in edited_parent_options
                        else 0
                    ),
                    key=(
                        f"edit_account_parent_{selected_profile_key}_{account_id}_"
                        f"{edited_classification}"
                    ),
                    format_func=lambda value: (
                        "None (Layer 1)" if not value else account_paths[value]
                    ),
                    disabled=has_children,
                )
                if has_children:
                    st.info(
                        "This Layer 1 account has children. Promote or reparent "
                        "those children before moving this account under a parent."
                    )
                if st.button(
                    "Save account changes",
                    type="primary",
                    key=f"save_account_{account_id}",
                ):
                    payload = {
                        "id": account_id,
                        "name": edited_name,
                        "type": edited_type,
                        "classification": edited_classification,
                        "opening_balance": edited_opening,
                        "active": edited_active,
                        "parent_id": edited_parent_id,
                    }
                    confirmed_write(
                        "edit_account",
                        payload,
                        lambda: storage.edit_account(
                            account_id,
                            name=edited_name,
                            type=edited_type,
                            classification=edited_classification,
                            opening_balance=edited_opening,
                            active=edited_active,
                            parent_id=edited_parent_id,
                        ),
                        "Account updated.",
                    )
            st.caption(
                "Accounts are deactivated rather than deleted so transaction references remain valid."
            )


elif page == "Categories":
    render_page_header("Categories")
    try:
        storage.prefetch_worksheets("Categories", "Transactions")
        categories = storage.list_categories()
        transactions = storage.list_transactions()
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    category_paths = hierarchy_paths(categories)
    transaction_count_by_category: dict[str, int] = {}
    for transaction in transactions:
        category_id = str(transaction.get("category_id") or "").strip()
        if category_id:
            transaction_count_by_category[category_id] = (
                transaction_count_by_category.get(category_id, 0) + 1
            )
    category_by_id = {
        category_id: category
        for category in categories
        if (category_id := str(category.get("id") or "").strip())
    }
    category_rows = []
    category_ids = []
    for category in ordered_hierarchy(categories):
        category_ids.append(category["id"])
        parent_id = str(category.get("parent_id") or "").strip()
        parent = category_by_id.get(parent_id) if parent_id else None
        category_rows.append(
            {
                "Category": (
                    f'↳ {category["name"]}' if parent else category["name"]
                ),
                "Layer": "Layer 2" if parent else "Layer 1",
                "Parent": parent.get("name") or "" if parent else "",
                "Type": category["kind"],
                "Transaction count": transaction_count_by_category.get(
                    category["id"], 0
                ),
            }
        )
    category_frame = pd.DataFrame(category_rows)
    category_table_key = (
        "category_table_"
        f"{selected_profile_key}_"
        f"{st.session_state.get('category_table_generation', 0)}"
    )

    def select_category() -> None:
        selected_rows = st.session_state[category_table_key].selection.rows
        if selected_rows:
            st.session_state["edit_category_id"] = category_ids[selected_rows[0]]

    category_event = st.dataframe(
        category_frame,
        hide_index=True,
        width="stretch",
        key=category_table_key,
        on_select=select_category,
        selection_mode="single-row",
    )
    reset_widget_state_if_requested(
        "reset_add_category_form",
        keys=(
            f"new_category_name_{selected_profile_key}",
            f"new_category_kind_{selected_profile_key}",
        ),
        prefixes=(f"new_category_parent_{selected_profile_key}_",),
    )
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input(
            "Category name", key=f"new_category_name_{selected_profile_key}"
        )
        kind = c2.selectbox(
            "Type",
            ["Expense", "Income"],
            key=f"new_category_kind_{selected_profile_key}",
        )
        parent_options = [""] + eligible_parent_ids(
            categories,
            compatibility_field="kind",
            compatibility_value=kind,
        )
        parent_id = c3.selectbox(
            "Parent category (optional)",
            parent_options,
            key=f"new_category_parent_{selected_profile_key}_{kind}",
            format_func=lambda value: (
                "None (Layer 1)" if not value else category_paths[value]
            ),
        )
        if st.button("Add category", type="primary"):
            payload = {"name": name, "kind": kind, "parent_id": parent_id}
            confirmed_write(
                "create_category",
                payload,
                lambda: storage.create_category(name, kind, parent_id=parent_id),
                "Category added.",
                on_success=lambda: schedule_widget_reset(
                    "reset_add_category_form"
                ),
            )
    if categories:
        selected_rows = category_event.selection.rows
        if st.session_state.get("edit_category_id") not in category_by_id:
            st.session_state["edit_category_id"] = category_ids[0]
        st.caption("Select a category row (or double-click it) to edit it.")
        with st.expander("Edit category", expanded=bool(selected_rows)):
            category_id = st.selectbox(
                "Category to edit",
                category_ids,
                format_func=lambda value: (
                    f'{category_paths[value]} '
                    f'({category_by_id[value]["kind"]})'
                ),
                key="edit_category_id",
            )
            selected = category_by_id[category_id]
            with st.container(border=True):
                edited_name = st.text_input(
                    "Edit category name",
                    value=selected["name"],
                    key=f"edit_category_name_{category_id}",
                )
                edited_kind = st.selectbox(
                    "Edit category type",
                    ["Expense", "Income"],
                    index=["Expense", "Income"].index(selected["kind"]),
                    key=f"edit_category_kind_{category_id}",
                )
                has_children = has_hierarchy_children(categories, category_id)
                edited_parent_options = [""] + eligible_parent_ids(
                    categories,
                    compatibility_field="kind",
                    compatibility_value=edited_kind,
                    item_id=category_id,
                )
                current_parent_id = str(selected.get("parent_id") or "").strip()
                edited_parent_id = st.selectbox(
                    "Edit parent category",
                    edited_parent_options,
                    index=(
                        edited_parent_options.index(current_parent_id)
                        if current_parent_id in edited_parent_options
                        else 0
                    ),
                    key=(
                        f"edit_category_parent_{selected_profile_key}_{category_id}_"
                        f"{edited_kind}"
                    ),
                    format_func=lambda value: (
                        "None (Layer 1)" if not value else category_paths[value]
                    ),
                    disabled=has_children,
                )
                if has_children:
                    st.info(
                        "This Layer 1 category has children. Promote or reparent "
                        "those children before moving this category under a parent."
                    )
                if st.button(
                    "Save category changes",
                    type="primary",
                    key=f"save_category_{category_id}",
                ):
                    payload = {
                        "id": category_id,
                        "name": edited_name,
                        "kind": edited_kind,
                        "parent_id": edited_parent_id,
                    }
                    confirmed_write(
                        "edit_category",
                        payload,
                        lambda: storage.edit_category(
                            category_id,
                            name=edited_name,
                            kind=edited_kind,
                            parent_id=edited_parent_id,
                        ),
                        "Category updated.",
                    )
                confirm_delete = st.checkbox(
                    "I understand this category will be permanently deleted",
                    key=f"confirm_delete_category_{category_id}",
                )
                if st.button(
                    "Permanently delete category",
                    icon=":material/delete_forever:",
                    key=f"delete_category_{category_id}",
                ):
                    if not confirm_delete:
                        st.error(
                            "Confirm that you understand deletion is permanent."
                        )
                    else:
                        confirmed_write(
                            "delete_category",
                            {"id": category_id},
                            lambda: storage.delete_category(category_id),
                            "Category deleted.",
                        )
    st.caption(
        "Categories with transactions or child categories cannot be deleted."
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
    render_page_header(
        "Data & backup",
        "Your live records are stored in the private Google Sheets workbook.",
    )
    selected_profile = profile_by_key[selected_profile_key].secrets
    drive_settings = selected_profile.get("google_drive")
    storage_root = (
        drive_settings.get("storage_root")
        if isinstance(drive_settings, Mapping)
        else None
    )
    backup_folder = (
        drive_settings.get("backup_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    recovery_receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    backup_drive = None
    latest_cloud = None
    st.subheader("Google Drive backup")
    if not isinstance(backup_folder, Mapping):
        st.info(
            "Connect Google Drive and select a backup folder from the local "
            "Business profiles page to enable cloud-native backups."
        )
    else:
        try:
            backup_drive = get_drive_client(selected_profile_key, revision)
            cloud_backups = backup_drive.list_backups(
                profile_key=selected_profile_key,
                folder_id=str(backup_folder["id"]),
                limit=30,
            )
        except GoogleDriveError as error:
            st.error(str(error))
        else:
            st.caption(
                f"Destination: {backup_folder.get('name', 'Google Drive folder')}"
            )
            if cloud_backups:
                latest_cloud = cloud_backups[0]
                st.caption(
                    "Latest cloud backup: "
                    f"{latest_cloud.get('name', 'Unknown')} "
                    f"({latest_cloud.get('createdTime', 'time unavailable')})"
                )
            else:
                st.warning("No cloud backup has been uploaded for this profile.")
            st.caption(
                "Verification downloads the latest backup into the app only to "
                "check its integrity. It does not restore or change the live workbook."
            )
            upload_column, verify_column = st.columns(2)
            if upload_column.button(
                "Upload fresh backup now",
                type="primary",
                width="stretch",
            ):
                try:
                    receipt_manifest = receipt_manifest_for_backup(
                        storage,
                        profile_key=selected_profile_key,
                        profile_secrets=selected_profile,
                        configuration_revision=revision,
                    )
                    backup_zip = storage.export_backup_zip(receipt_manifest)
                    manifest = storage.validate_backup_zip(backup_zip)
                    cloud_filename, cloud_sha256 = backup_filename_and_hash(
                        backup_zip,
                        manifest,
                    )
                    uploaded_backup = backup_drive.upload_backup(
                        profile_key=selected_profile_key,
                        folder_id=str(backup_folder["id"]),
                        filename=cloud_filename,
                        content=backup_zip,
                        sha256=cloud_sha256,
                        backup_time=str(manifest["backup_time"]),
                        keep=30,
                    )
                except (
                    StorageError,
                    GoogleDriveError,
                    ReceiptManifestError,
                    RuntimeError,
                ) as error:
                    if isinstance(error, StorageError):
                        report_storage_error(error)
                    else:
                        st.error(str(error))
                else:
                    st.success(
                        "Verified backup uploaded to Google Drive: "
                        f"{uploaded_backup.get('name', cloud_filename)}"
                    )
                    st.rerun()
            if verify_column.button(
                "Verify latest cloud backup",
                disabled=latest_cloud is None,
                width="stretch",
            ):
                try:
                    downloaded_backup = backup_drive.download_file(
                        str(latest_cloud["id"])
                    )
                    verified_manifest = GoogleSheetsStorage.validate_backup_zip(
                        downloaded_backup
                    )
                    expected_sha256 = (
                        latest_cloud.get("appProperties", {}).get(
                            "tabulaRasaSha256",
                            "",
                        )
                    )
                    if (
                        expected_sha256
                        and hashlib.sha256(downloaded_backup).hexdigest()
                        != str(expected_sha256)
                    ):
                        raise RuntimeError(
                            "The downloaded cloud backup hash does not match."
                        )
                except (GoogleDriveError, RuntimeError, KeyError) as error:
                    st.error(str(error))
                else:
                    st.success(
                        "Latest cloud backup downloaded and verified: "
                        f"{verified_manifest['backup_time']}."
                    )
                # Verification is deliberately Drive-only. Do not continue
                # into the live Sheets reads and fresh backup generation below.
                st.stop()

    st.subheader("Synology recovery copy")
    raw_synology_recovery = selected_profile.get("synology_recovery")
    if raw_synology_recovery is None:
        st.info(
            "No local Synology recovery record is available in this runtime. NAS "
            "settings are intentionally excluded from hosted Secrets; configure "
            "or review them from the loopback-only Business profiles page and DSM."
        )
    else:
        try:
            synology_recovery = validate_synology_recovery_settings(
                raw_synology_recovery
            )
        except SynologyRecoveryConfigurationError as error:
            st.error(str(error))
            synology_recovery = None
        if synology_recovery is None:
            st.caption(
                "Repair this profile from the loopback-only Business profiles page."
            )
        else:
            if not isinstance(backup_folder, Mapping):
                st.warning(
                    "Synology recovery is enabled, but this profile does not have a "
                    "Google Drive backup folder selected."
                )
            if not isinstance(recovery_receipt_folder, Mapping):
                st.warning(
                    "Synology recovery is enabled, but this profile does not have a "
                    "Google Drive receipt folder selected."
                )
            if not isinstance(storage_root, Mapping):
                st.warning(
                    "Synology recovery is enabled, but this profile does "
                    "not have a Google Drive storage root selected."
                )
            root_source_name = (
                str(storage_root.get("name", "Google Drive storage root"))
                if isinstance(storage_root, Mapping)
                else "Not configured"
            )
            source_lines = (
                "- **Cloud Sync task:** One recursive profile-root task",
                f"- **Remote source:** {root_source_name}",
                "- **Expected NAS children:** Receipts and Ledger Backups",
            )
            st.markdown(
                "\n".join(
                    (
                        *source_lines,
                        "- **Cloud Sync direction:** " + SYNC_DIRECTION,
                        "- **Destination deletions:** " + DESTINATION_DELETIONS,
                        "- **NAS destination:** "
                        + synology_recovery["destination_path"],
                        "- **Schedule:** " + synology_recovery["schedule"],
                        "- **Retention:** " + synology_recovery["retention_policy"],
                    )
                )
            )
            st.caption(
                "These are the expected per-business settings. Project Tabula Rasa does not "
                "connect to the NAS; confirm transfers, failures, and retries in DSM "
                "Cloud Sync with destination deletions disabled is the independent "
                "second-layer copy. Optional versioned retention can protect both "
                "synchronized children with another recovery point."
            )

    st.subheader("Live workbook exports")
    prepared_exports_key = (
        "prepared-live-exports:"
        f"{selected_profile_key}:{revision}:"
        f"{st.session_state.get('workbook_data_revision', 0)}"
    )
    prepared_exports = st.session_state.get(prepared_exports_key)
    prepare_label = (
        "Refresh downloadable exports"
        if isinstance(prepared_exports, Mapping)
        else "Prepare downloadable exports"
    )
    if st.button(prepare_label, width="stretch"):
        try:
            accounts = storage.list_accounts(active_only=False)
            categories = storage.list_categories()
            transactions = storage.list_transactions()
            mileage_trips = storage.list_mileage_trips()
            all_transactions = ledger_frame(
                transactions,
                accounts,
                categories,
                display_paths=False,
            )
            all_mileage = mileage_frame(mileage_trips)
        except StorageError as error:
            report_storage_error(error)
        else:
            prepared_exports: dict[str, object] = {
                "backup_time": datetime.now(timezone.utc).isoformat(),
                "transactions": all_transactions.to_csv(index=False).encode(
                    "utf-8"
                ),
                "mileage": all_mileage.to_csv(index=False).encode("utf-8"),
            }
            try:
                receipt_manifest = receipt_manifest_for_backup(
                    storage,
                    profile_key=selected_profile_key,
                    profile_secrets=selected_profile,
                    configuration_revision=revision,
                )
                backup_zip = storage.export_backup_zip(receipt_manifest)
                manifest = storage.validate_backup_zip(backup_zip)
            except (
                StorageError,
                GoogleDriveError,
                ReceiptManifestError,
                ReceiptPreparationError,
            ) as error:
                prepared_exports["backup_error"] = str(error)
            else:
                prepared_exports["backup"] = backup_zip
                prepared_exports["backup_time"] = str(manifest["backup_time"])
            st.session_state[prepared_exports_key] = prepared_exports
            if "backup" in prepared_exports:
                st.success("Fresh downloadable exports are ready.")
            else:
                st.success("Fresh CSV exports are ready.")
    if isinstance(prepared_exports, Mapping):
        st.caption(f"Prepared from workbook data at {prepared_exports['backup_time']}.")
        backup_error = prepared_exports.get("backup_error")
        if backup_error:
            st.warning(
                "The complete workbook backup is unavailable: "
                f"{backup_error}"
            )
        st.download_button(
            "Download transactions CSV",
            prepared_exports["transactions"],
            f"tabula-rosa-{date.today()}.csv",
            "text/csv",
            width="stretch",
        )
        st.download_button(
            "Download mileage CSV",
            prepared_exports["mileage"],
            f"tabula-rosa-mileage-{date.today()}.csv",
            "text/csv",
            width="stretch",
        )
        backup_export = prepared_exports.get("backup")
        if isinstance(backup_export, bytes):
            st.download_button(
                "Download complete workbook backup",
                backup_export,
                f"tabula-rosa-backup-{date.today()}.zip",
                "application/zip",
                width="stretch",
            )
    with st.expander("Import Project Tabula Rasa CSV"):
        st.write(
            "Upload a CSV with: Date, Type, Amount, Account, Category, Payee, "
            "Description, Reference. Type must be Income or Expense."
        )
        plain_upload = st.file_uploader(
            "CSV file",
            type="csv",
            key=f"transaction_csv_upload_{selected_profile_key}",
        )
        if plain_upload:
            try:
                plain_incoming = pd.read_csv(plain_upload).where(
                    lambda frame: frame.notna(), ""
                )
                plain_required = {"Date", "Type", "Amount", "Account", "Category"}
                plain_missing = plain_required - set(plain_incoming.columns)
                if plain_missing:
                    st.error(f"Missing columns: {', '.join(sorted(plain_missing))}")
                else:
                    st.dataframe(plain_incoming.head(20), hide_index=True, width="stretch")
                    if st.button("Import rows", type="primary"):
                        plain_records = plain_incoming.to_dict(orient="records")
                        confirmed_write(
                            "import_csv_transactions",
                            {"rows": plain_records},
                            lambda: storage.import_csv_transactions(plain_records),
                            lambda imported: f"Imported {len(imported)} transactions.",
                        )
            except StorageValidationError as error:
                report_storage_error(error)
            except (ValueError, pd.errors.ParserError, UnicodeError):
                st.error("Could not read this CSV file. Check its format and encoding.")
    st.subheader("Import QuickBooks transactions")
    st.write(
        "Upload a QuickBooks Online **Transaction Detail by Account** CSV, "
        "or a QuickBooks Self-Employed **General ledger** XLSX or ZIP export. "
        "Review the validation results and summary before committing."
    )
    upload = st.file_uploader(
        "QuickBooks export",
        type=["csv", "xlsx", "zip"],
        key=f"quickbooks_transaction_upload_{selected_profile_key}",
    )
    if upload:
        try:
            upload_bytes = upload.getvalue()
            upload_name = upload.name.casefold()
            conversion_errors: list[str] = []
            if upload_name.endswith(".csv"):
                incoming = pd.read_csv(io.BytesIO(upload_bytes)).where(lambda frame: frame.notna(), "")
            else:
                if upload_name.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(upload_bytes)) as archive:
                        workbooks = [name for name in archive.namelist() if name.casefold().endswith(".xlsx") and not name.startswith("__MACOSX/")]
                        if len(workbooks) != 1:
                            raise ValueError("The ZIP must contain exactly one QuickBooks .xlsx workbook")
                        if archive.getinfo(workbooks[0]).file_size > 25 * 1024 * 1024:
                            raise ValueError("The QuickBooks workbook is larger than 25 MB")
                        workbook_bytes = archive.read(workbooks[0])
                else:
                    workbook_bytes = upload_bytes
                ledger = pd.read_excel(io.BytesIO(workbook_bytes), sheet_name="General Ledger", header=None).where(lambda frame: frame.notna(), "")
                records, conversion_errors = general_ledger_rows(ledger.values.tolist())
                incoming = pd.DataFrame(records, columns=sorted(QUICKBOOKS_REQUIRED_COLUMNS))
            missing = QUICKBOOKS_REQUIRED_COLUMNS - set(incoming.columns)
            if missing:
                st.error(f"Missing columns: {', '.join(sorted(missing))}")
            else:
                records = incoming.to_dict(orient="records")
                auto_create = st.checkbox(
                    "Automatically create missing accounts and categories",
                    help="New accounts use an inferred type and zero opening balance. Category type is inferred from the amount.",
                )
                preview = storage.preview_quickbooks_transactions(
                    records, auto_create=auto_create
                )
                summary = preview["summary"]
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Ready", summary["ready"])
                c2.metric("Duplicates", summary["duplicates"])
                c3.metric("Income", summary["Income"])
                c4.metric("Expenses", summary["Expense"])
                c5.metric("Transfers", summary["Transfer"])
                if preview["errors"]:
                    st.error(
                        alert_list(
                            "Fix these import errors before continuing:",
                            preview["errors"],
                        )
                    )
                if conversion_errors:
                    st.error(
                        alert_list(
                            "Some QuickBooks rows could not be converted:",
                            conversion_errors,
                        )
                    )
                if auto_create and (preview["new_accounts"] or preview["new_categories"]):
                    additions = [
                        (
                            f"Account name: {name} — Classification: "
                            f"{preview['new_account_classifications'][name]} — "
                            f"Type: {preview['new_account_types'][name]}"
                        )
                        for name in preview["new_accounts"]
                    ]
                    additions += [f"{kind} category: {name}" for name, kind in preview["new_categories"]]
                    st.info("Will create:\n\n- " + "\n- ".join(additions))
                if preview["duplicate_rows"]:
                    st.warning(
                        "Already imported or repeated rows will be skipped: "
                        + ", ".join(map(str, preview["duplicate_rows"]))
                    )
                st.dataframe(incoming.head(50), hide_index=True, width="stretch")
                if st.button(
                    "Import validated rows",
                    type="primary",
                    disabled=bool(preview["errors"] or conversion_errors) or not summary["ready"],
                ):
                    confirmed_write(
                        "import_quickbooks_transactions",
                        {"rows": records, "auto_create": auto_create},
                        lambda: storage.import_quickbooks_transactions(
                            records, auto_create=auto_create
                        ),
                        lambda imported: f"Imported {len(imported)} transactions.",
                    )
        except StorageValidationError as error:
            report_storage_error(error)
        except (ValueError, KeyError, zipfile.BadZipFile, pd.errors.ParserError, UnicodeError):
            st.error("Could not read this QuickBooks export. Check its format and file integrity.")

    st.subheader("Import QuickBooks mileage")
    st.write(
        "In QuickBooks Online, open **Expenses & Bills > Mileage**, use the "
        "dropdown next to **Add trip**, and select **Download Trips**. Upload "
        "that CSV here. Business trips are imported; Personal and Unreviewed "
        "trips are skipped."
    )
    mileage_upload = st.file_uploader(
        "QuickBooks mileage CSV",
        type="csv",
        key="quickbooks_mileage_upload",
    )
    if mileage_upload:
        try:
            mileage_incoming = pd.read_csv(mileage_upload).where(
                lambda frame: frame.notna(), ""
            )
            mileage_missing = missing_quickbooks_mileage_columns(
                mileage_incoming.columns
            )
            if mileage_missing:
                st.error(
                    "Missing QuickBooks mileage columns: "
                    + ", ".join(mileage_missing)
                )
            else:
                mileage_records = mileage_incoming.to_dict(orient="records")
                mileage_preview = storage.preview_quickbooks_mileage(
                    mileage_records
                )
                mileage_summary = mileage_preview["summary"]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Mileage ready", mileage_summary["ready"])
                c2.metric(
                    "Mileage duplicates", mileage_summary["duplicates"]
                )
                c3.metric(
                    "Personal skipped",
                    mileage_summary["personal_skipped"],
                )
                c4.metric(
                    "Unreviewed skipped",
                    mileage_summary["unreviewed_skipped"],
                )
                if mileage_preview["errors"]:
                    st.error(
                        alert_list(
                            "Fix these mileage import errors before continuing:",
                            mileage_preview["errors"],
                        )
                    )
                if mileage_preview["duplicate_rows"]:
                    st.warning(
                        "Already imported or repeated mileage rows will be "
                        "skipped: "
                        + ", ".join(
                            map(str, mileage_preview["duplicate_rows"])
                        )
                    )
                if mileage_preview["personal_rows"]:
                    st.info(
                        "Personal mileage rows will be skipped: "
                        + ", ".join(map(str, mileage_preview["personal_rows"]))
                    )
                if mileage_preview["unreviewed_rows"]:
                    st.info(
                        "Unreviewed mileage rows will be skipped: "
                        + ", ".join(
                            map(str, mileage_preview["unreviewed_rows"])
                        )
                    )
                st.dataframe(
                    mileage_incoming.head(50),
                    hide_index=True,
                    width="stretch",
                )
                if st.button(
                    "Import validated mileage",
                    type="primary",
                    disabled=bool(mileage_preview["errors"])
                    or not mileage_summary["ready"],
                ):
                    confirmed_write(
                        "import_quickbooks_mileage",
                        {"rows": mileage_records},
                        lambda: storage.import_quickbooks_mileage(
                            mileage_records
                        ),
                        lambda imported: (
                            f"Imported {len(imported)} mileage trips."
                        ),
                    )
        except StorageValidationError as error:
            report_storage_error(error)
        except (ValueError, pd.errors.ParserError, UnicodeError):
            st.error(
                "Could not read this QuickBooks mileage CSV. "
                "Check its format and encoding."
            )
