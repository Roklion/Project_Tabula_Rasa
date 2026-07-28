from __future__ import annotations

from collections.abc import Mapping
from datetime import date
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
import plotly.express as px
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
from tabula_rasa.ledger_reporting import (
    account_balances,
    balance_sheet,
    expenses_by_category,
    monthly_performance,
    profit_and_loss,
)
from tabula_rasa.local_profile_admin import render_local_profile_admin
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    local_profile_admin_available,
    local_profile_revision,
    merged_profile_secrets,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageError,
    StorageValidationError,
)
from tabula_rasa.submission_guard import is_recent_duplicate, mark_completed
from tabula_rasa.quickbooks_import import (
    REQUIRED_COLUMNS as QUICKBOOKS_REQUIRED_COLUMNS,
    general_ledger_rows,
)
from tabula_rasa.quickbooks_mileage_import import (
    missing_required_columns as missing_quickbooks_mileage_columns,
)


STORAGE_IMPLEMENTATION_VERSION = 7
ACCOUNT_TYPES = ["Bank", "Cash", "Credit card", "Short-term debt", "Equity", "Other"]
ACCOUNT_CLASSIFICATIONS = ["Asset", "Liability", "Equity"]
FIXED_TYPE_CLASSIFICATIONS = {
    "Bank": "Asset",
    "Cash": "Asset",
    "Credit card": "Liability",
    "Short-term debt": "Liability",
    "Equity": "Equity",
}


def money(value: float) -> str:
    return f"${value:,.2f}"


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


def ledger_frame(
    transactions: list[dict],
    accounts: list[dict],
    categories: list[dict],
) -> pd.DataFrame:
    account_names = {account["id"]: account["name"] for account in accounts}
    category_names = {category["id"]: category["name"] for category in categories}
    rows = [
        {
            "ID": transaction["id"],
            "Date": transaction["txn_date"],
            "Type": transaction["kind"],
            "Account": account_names.get(transaction["account_id"], "Unknown"),
            "To account": account_names.get(transaction.get("to_account_id"), ""),
            "Category": category_names.get(transaction.get("category_id"), ""),
            "Payee": transaction.get("payee", ""),
            "Description": transaction.get("description", ""),
            "Reference": transaction.get("reference", ""),
            "Amount": float(transaction["amount"]),
        }
        for transaction in transactions
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "ID",
            "Date",
            "Type",
            "Account",
            "To account",
            "Category",
            "Payee",
            "Description",
            "Reference",
            "Amount",
        ],
    )


def balances_frame(accounts: list[dict], transactions: list[dict]) -> pd.DataFrame:
    rows = account_balances(accounts, transactions)
    return pd.DataFrame(
        [
            {
                "ID": account["id"],
                "Account": account["name"],
                "Type": account["type"],
                "Classification": account["classification"],
                "Active": account["active"],
                "Balance": account["balance"],
            }
            for account in rows
        ]
    )


def mileage_frame(trips: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ID": trip["id"],
                "Date": trip["trip_date"],
                "Miles": float(trip["miles"]),
                "Vehicle": trip.get("vehicle", ""),
                "From": trip.get("start_location", ""),
                "Destination": trip.get("destination", ""),
                "Business purpose": trip.get("business_purpose", ""),
                "Notes": trip.get("notes", ""),
            }
            for trip in trips
        ],
        columns=[
            "ID",
            "Date",
            "Miles",
            "Vehicle",
            "From",
            "Destination",
            "Business purpose",
            "Notes",
        ],
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
    if on_success is not None:
        on_success()
    st.session_state["workbook_data_revision"] = (
        int(st.session_state.get("workbook_data_revision", 0)) + 1
    )
    st.success(success_message(result) if callable(success_message) else success_message)
    st.rerun()


st.set_page_config(page_title="Tabula Rosa", page_icon="📒", layout="wide")
st.markdown(
    """
    <style>
    :root { color-scheme:light; --ink:#17211b; --green:#206a4b; --cream:#f7f5ef; }
    .stApp { background: var(--cream); color: var(--ink); }
    [data-testid="stMetric"] { background:white; border:1px solid #dedbd2; padding:18px; border-radius:14px; }
    [data-testid="stSidebar"] { background:#173f32; }
    [data-testid="stSidebar"] * { color:#f7f5ef; }
    [data-testid="stWidgetLabel"] {
        width:fit-content !important;
        max-width:100%;
        justify-content:flex-start;
        gap:.3rem;
    }
    [data-testid="stWidgetLabel"] > [data-testid="stMarkdownContainer"] {
        width:fit-content !important;
        flex:0 1 auto;
    }
    [data-testid="stWidgetLabel"] p {
        flex:0 0 auto;
    }
    [data-testid="stWidgetLabel"] [data-testid="stTooltipIcon"] {
        flex:0 0 auto;
    }
    .st-key-edit_transaction [data-testid="stFormSubmitButton"]:has([data-testid="stIconMaterial"]) button {
        background:#b42318;
        border-color:#b42318;
        color:white;
    }
    .st-key-edit_transaction [data-testid="stFormSubmitButton"]:has([data-testid="stIconMaterial"]) button:hover {
        background:#912018;
        border-color:#912018;
        color:white;
    }
    h1,h2,h3 { letter-spacing:-.025em; }
    .muted { color:#67716b; margin-top:-.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

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
    st.title("Tabula Rosa")
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


if page == "Dashboard":
    st.title("Your books at a glance")
    st.markdown(
        '<p class="muted">A current view of cash, income, and spending.</p>',
        unsafe_allow_html=True,
    )
    try:
        today = date.today()
        month_start = today.replace(day=1)
        storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Transactions",
        )
        accounts = storage.list_accounts(active_only=False)
        categories = storage.list_categories()
        transactions = storage.list_transactions()
        monthly_totals = profit_and_loss(
            transactions, start=month_start, end=today
        )
        balances = balances_frame(accounts, transactions)
    except StorageError as error:
        report_storage_error(error)
        st.stop()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total balance", money(float(balances["Balance"].sum())))
    c2.metric("Income this month", money(monthly_totals["income"]))
    c3.metric("Expenses this month", money(monthly_totals["expenses"]))
    c4.metric("Net this month", money(monthly_totals["net"]))
    left, right = st.columns([1.4, 1])
    with left:
        st.subheader("Recent activity")
        recent = ledger_frame(transactions[:8], accounts, categories)
        if recent.empty:
            st.info("No transactions yet. Add your first one from Transactions.")
        else:
            display = recent[
                ["Date", "Type", "Payee", "Category", "Account", "Amount"]
            ].copy()
            display["Amount"] = display.apply(
                lambda row: -row.Amount if row.Type == "Expense" else row.Amount,
                axis=1,
            )
            st.dataframe(
                display,
                hide_index=True,
                width="stretch",
                column_config={
                    "Amount": st.column_config.NumberColumn(format="$%.2f")
                },
            )
    with right:
        st.subheader("Account balances")
        st.dataframe(
            balances[["Account", "Classification", "Type", "Balance"]],
            hide_index=True,
            width="stretch",
            column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
        )


elif page == "Transactions":
    st.title("Transactions")
    tab_add, tab_ledger = st.tabs(["Add transaction", "View & edit ledger"])
    try:
        storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Transactions",
        )
        accounts = storage.list_accounts(active_only=False)
        active_accounts = [account for account in accounts if account["active"]]
        categories = storage.list_categories()
    except StorageError as error:
        report_storage_error(error)
        st.stop()

    account_map = {account["name"]: account["id"] for account in active_accounts}
    with tab_add:
        transaction_form_keys = (
            "add_transaction_date",
            "add_transaction_amount",
            "add_transaction_account_income",
            "add_transaction_account_expense",
            "add_transaction_account_transfer",
            "add_transaction_to_account",
            "add_transaction_category_income",
            "add_transaction_category_expense",
            "add_transaction_payee",
            "add_transaction_reference",
            "add_transaction_description",
        )
        reset_widget_state_if_requested(
            "reset_add_transaction_form",
            keys=transaction_form_keys,
        )
        kind = st.segmented_control(
            "Transaction type",
            ["Income", "Expense", "Transfer"],
            default="Expense",
        )
        if not account_map:
            st.warning("Create an active account before recording transactions.")
        else:
            categories_for_kind = [
                category for category in categories if category["kind"] == kind
            ]
            if kind != "Transfer" and not categories_for_kind:
                st.warning(f"Create a {kind.lower()} category first.")
            else:
                with st.form("add_transaction", clear_on_submit=False):
                    c1, c2 = st.columns(2)
                    transaction_date = c1.date_input(
                        "Date",
                        date.today(),
                        key="add_transaction_date",
                    )
                    amount = c2.number_input(
                        "Amount",
                        min_value=0.01,
                        step=1.0,
                        format="%.2f",
                        key="add_transaction_amount",
                    )
                    source = st.selectbox(
                        "Account" if kind != "Transfer" else "From account",
                        list(account_map),
                        key=f"add_transaction_account_{kind.casefold()}",
                    )
                    to_account = None
                    category_id = None
                    if kind == "Transfer":
                        choices = [name for name in account_map if name != source]
                        to_account = (
                            st.selectbox(
                                "To account",
                                choices,
                                key="add_transaction_to_account",
                            )
                            if choices
                            else None
                        )
                    else:
                        category_map = {
                            category["name"]: category["id"]
                            for category in categories_for_kind
                        }
                        category_id = category_map[
                            st.selectbox(
                                "Category",
                                list(category_map),
                                key=(
                                    "add_transaction_category_"
                                    f"{kind.casefold()}"
                                ),
                            )
                        ]
                    c1, c2 = st.columns(2)
                    payee = c1.text_input(
                        "Payee / customer",
                        key="add_transaction_payee",
                    )
                    reference = c2.text_input(
                        "Reference (optional)",
                        key="add_transaction_reference",
                    )
                    description = st.text_input(
                        "Description / memo",
                        key="add_transaction_description",
                    )
                    submitted = st.form_submit_button(
                        "Save transaction", type="primary", width="stretch"
                    )
                    if submitted:
                        if kind == "Transfer" and not to_account:
                            st.error(
                                "Create a second active account before recording a transfer."
                            )
                        else:
                            payload = {
                                "txn_date": transaction_date,
                                "kind": kind,
                                "amount": amount,
                                "account_id": account_map[source],
                                "to_account_id": account_map.get(to_account, ""),
                                "category_id": category_id or "",
                                "payee": payee,
                                "description": description,
                                "reference": reference,
                            }
                            confirmed_write(
                                "create_transaction",
                                payload,
                                lambda: storage.create_transaction(**payload),
                                "Transaction saved.",
                                on_success=lambda: schedule_widget_reset(
                                    "reset_add_transaction_form"
                                ),
                            )

    with tab_ledger:
        c1, c2, c3 = st.columns(3)
        start = c1.date_input(
            "From", date(date.today().year, 1, 1), key="ledger_start"
        )
        end = c2.date_input("To", date.today(), key="ledger_end")
        filter_type = c3.selectbox(
            "Type", ["All", "Income", "Expense", "Transfer"]
        )
        ledger_account_map = {
            account["name"]: account["id"] for account in accounts
        }
        selected_account_names = st.multiselect(
            "Accounts",
            list(ledger_account_map),
            placeholder="All accounts",
            help=(
                "Includes transactions where a selected account is either side "
                "of a transfer."
            ),
        )
        selected_account_ids = [
            ledger_account_map[name] for name in selected_account_names
        ]
        try:
            transactions = storage.list_transactions(
                start=start,
                end=end,
                kind=None if filter_type == "All" else filter_type,
                account_ids=selected_account_ids or None,
            )
        except StorageError as error:
            report_storage_error(error)
            st.stop()
        transaction_frame = ledger_frame(transactions, accounts, categories)
        transaction_ids = transaction_frame["ID"].tolist()

        def select_ledger_transaction() -> None:
            selected_rows = st.session_state["transaction_ledger"].selection.rows
            if selected_rows:
                st.session_state["edit_transaction_id"] = transaction_ids[
                    selected_rows[0]
                ]

        ledger_event = st.dataframe(
            transaction_frame,
            hide_index=True,
            width="stretch",
            key="transaction_ledger",
            on_select=select_ledger_transaction,
            selection_mode="single-row",
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
        )
        if not transaction_frame.empty:
            selected_rows = ledger_event.selection.rows
            if st.session_state.get("edit_transaction_id") not in transaction_ids:
                st.session_state["edit_transaction_id"] = transaction_ids[0]

            def transaction_label(transaction_id: str) -> str:
                row = transaction_frame.loc[
                    transaction_frame["ID"] == transaction_id
                ].iloc[0]
                return f"{row['Date']} — {row['Type']} — {money(row['Amount'])} — {transaction_id[:8]}"

            st.caption("Select a ledger row (or double-click it) to edit it.")
            with st.expander("Edit transaction", expanded=bool(selected_rows)):
                edit_id = st.selectbox(
                    "Transaction to edit",
                    transaction_ids,
                    format_func=transaction_label,
                    key="edit_transaction_id",
                )
                selected = next(
                    transaction for transaction in transactions if transaction["id"] == edit_id
                )
                with st.form("edit_transaction"):
                    active_account_ids = [account["id"] for account in active_accounts]
                    current_account_ids = [
                        selected["account_id"],
                        selected.get("to_account_id", ""),
                    ]
                    editable_account_ids = active_account_ids + [
                        account_id
                        for account_id in current_account_ids
                        if account_id and account_id not in active_account_ids
                    ]
                    account_names_by_id = {
                        account["id"]: account["name"] for account in accounts
                    }
                    edited_account_id = st.selectbox(
                        (
                            "Edit from account"
                            if selected["kind"] == "Transfer"
                            else "Edit account"
                        ),
                        editable_account_ids,
                        index=editable_account_ids.index(selected["account_id"]),
                        format_func=account_names_by_id.get,
                    )
                    edited_to_account_id = ""
                    edited_category_id = ""
                    if selected["kind"] == "Transfer":
                        edited_to_account_id = st.selectbox(
                            "Edit to account",
                            editable_account_ids,
                            index=editable_account_ids.index(
                                selected["to_account_id"]
                            ),
                            format_func=account_names_by_id.get,
                        )
                    else:
                        category_ids = [
                            category["id"]
                            for category in categories
                            if category["kind"] == selected["kind"]
                        ]
                        category_names_by_id = {
                            category["id"]: category["name"]
                            for category in categories
                        }
                        edited_category_id = st.selectbox(
                            "Edit category",
                            category_ids,
                            index=category_ids.index(selected["category_id"]),
                            format_func=category_names_by_id.get,
                        )
                    c1, c2 = st.columns(2)
                    edited_date = c1.date_input(
                        "Edit date", date.fromisoformat(selected["txn_date"])
                    )
                    edited_amount = c2.number_input(
                        "Edit amount",
                        min_value=0.01,
                        value=float(selected["amount"]),
                        format="%.2f",
                    )
                    edited_payee = st.text_input(
                        "Edit payee / customer", value=selected.get("payee", "")
                    )
                    edited_reference = st.text_input(
                        "Edit reference", value=selected.get("reference", "")
                    )
                    edited_description = st.text_input(
                        "Edit description", value=selected.get("description", "")
                    )
                    st.warning(
                        "Deleting this transaction is permanent and cannot be undone.",
                        icon="⚠️",
                    )
                    confirm_delete = st.checkbox(
                        "I understand this transaction will be permanently deleted"
                    )
                    save_column, delete_column = st.columns(2)
                    save_requested = save_column.form_submit_button(
                        "Save changes", type="primary", width="stretch"
                    )
                    delete_requested = delete_column.form_submit_button(
                        "Permanently delete",
                        icon=":material/delete_forever:",
                        help="Permanently delete this transaction",
                        width="stretch",
                    )
                    if save_requested:
                        payload = {
                            "id": edit_id,
                            "txn_date": edited_date,
                            "amount": edited_amount,
                            "account_id": edited_account_id,
                            "to_account_id": edited_to_account_id,
                            "category_id": edited_category_id,
                            "payee": edited_payee,
                            "reference": edited_reference,
                            "description": edited_description,
                        }
                        if (
                            selected["kind"] == "Transfer"
                            and edited_account_id == edited_to_account_id
                        ):
                            st.error("Transfer accounts must be different.")
                        else:
                            confirmed_write(
                                "edit_transaction",
                                payload,
                                lambda: storage.edit_transaction(
                                    edit_id,
                                    txn_date=edited_date,
                                    amount=edited_amount,
                                    account_id=edited_account_id,
                                    to_account_id=edited_to_account_id,
                                    category_id=edited_category_id,
                                    payee=edited_payee,
                                    reference=edited_reference,
                                    description=edited_description,
                                ),
                                "Transaction updated.",
                            )
                    if delete_requested:
                        if not confirm_delete:
                            st.error(
                                "Confirm that you understand deletion is permanent."
                            )
                        else:
                            payload = {"id": edit_id}
                            confirmed_write(
                                "delete_transaction",
                                payload,
                                lambda: storage.delete_transaction(edit_id),
                                "Transaction deleted.",
                            )
                st.divider()
                st.subheader("Receipt")
                selected_profile = profile_by_key[selected_profile_key].secrets
                drive_settings = selected_profile.get("google_drive")
                receipt_folder = (
                    drive_settings.get("receipt_folder")
                    if isinstance(drive_settings, Mapping)
                    else None
                )
                if not isinstance(receipt_folder, Mapping):
                    st.info(
                        "Connect Google Drive and select a receipt folder from "
                        "the local Business profiles page. Until then, store the "
                        f"receipt manually as `{edit_id}-original-file-name`."
                    )
                else:
                    try:
                        receipt_drive = get_drive_client(
                            selected_profile_key,
                            revision,
                        )
                        receipts = receipt_drive.list_receipts(
                            profile_key=selected_profile_key,
                            transaction_id=edit_id,
                            folder_id=str(receipt_folder["id"]),
                        )
                    except GoogleDriveError as error:
                        st.error(str(error))
                    else:
                        if receipts:
                            for receipt in receipts:
                                name = str(receipt.get("name", "Receipt"))
                                link = str(receipt.get("webViewLink", ""))
                                if link:
                                    st.link_button(name, link)
                                else:
                                    st.caption(name)
                        receipt_upload = st.file_uploader(
                            "Upload receipt",
                            type=["pdf", "png", "jpg", "jpeg", "webp", "heic"],
                            accept_multiple_files=False,
                            key=f"receipt-upload-{edit_id}",
                        )
                        if receipt_upload is not None:
                            receipt_bytes = receipt_upload.getvalue()
                            st.caption(
                                "The file will be stored as "
                                f"`{edit_id}-{receipt_upload.name}`."
                            )
                            if st.button(
                                "Upload receipt to Google Drive",
                                type="primary",
                                key=f"receipt-upload-button-{edit_id}",
                            ):
                                try:
                                    uploaded_receipt = receipt_drive.upload_receipt(
                                        profile_key=selected_profile_key,
                                        transaction_id=edit_id,
                                        folder_id=str(receipt_folder["id"]),
                                        original_name=receipt_upload.name,
                                        content=receipt_bytes,
                                        mime_type=(
                                            receipt_upload.type
                                            or "application/octet-stream"
                                        ),
                                    )
                                except GoogleDriveError as error:
                                    st.error(str(error))
                                else:
                                    st.success(
                                        "Receipt uploaded to Google Drive: "
                                        f"{uploaded_receipt.get('name', receipt_upload.name)}"
                                    )
                                    st.rerun()


elif page == "Mileage":
    st.title("Mileage")
    st.caption(
        "Keep a dated business-mileage log with the route, purpose, and vehicle."
    )
    tab_add, tab_log = st.tabs(["Add trip", "View & edit mileage log"])

    with tab_add:
        mileage_form_keys = (
            "add_mileage_trip_date",
            "add_mileage_miles",
            "add_mileage_vehicle",
            "add_mileage_start",
            "add_mileage_destination",
            "add_mileage_round_trip",
            "add_mileage_purpose",
            "add_mileage_notes",
        )
        reset_widget_state_if_requested(
            "reset_add_mileage_form",
            keys=mileage_form_keys,
        )

        with st.form("add_mileage_trip", clear_on_submit=False):
            c1, c2 = st.columns(2)
            trip_date = c1.date_input(
                "Trip date",
                date.today(),
                key="add_mileage_trip_date",
            )
            miles = c2.number_input(
                "Business miles",
                min_value=0.1,
                step=0.1,
                format="%.1f",
                key="add_mileage_miles",
            )
            vehicle = st.text_input(
                "Vehicle (optional)",
                help="For example: 2022 Honda Civic or Company van.",
                key="add_mileage_vehicle",
            )
            c1, c2 = st.columns(2)
            start_location = c1.text_input(
                "Starting location",
                key="add_mileage_start",
            )
            destination = c2.text_input(
                "Destination",
                key="add_mileage_destination",
            )
            round_trip = st.checkbox(
                "Round trip",
                help=(
                    "Creates an outbound entry and a second entry with the "
                    "starting and ending locations reversed. Each entry uses "
                    "the mileage entered above."
                ),
                key="add_mileage_round_trip",
            )
            business_purpose = st.text_input(
                "Business purpose",
                key="add_mileage_purpose",
            )
            notes = st.text_area(
                "Notes (optional)",
                key="add_mileage_notes",
            )
            submitted = st.form_submit_button(
                "Save mileage trip", type="primary", width="stretch"
            )
            if submitted:
                payload = {
                    "trip_date": trip_date,
                    "miles": miles,
                    "vehicle": vehicle,
                    "start_location": start_location,
                    "destination": destination,
                    "business_purpose": business_purpose,
                    "notes": notes,
                    "round_trip": round_trip,
                }
                confirmed_write(
                    "create_mileage_round_trip"
                    if round_trip
                    else "create_mileage_trip",
                    payload,
                    (
                        lambda: storage.create_mileage_round_trip(
                            trip_date=trip_date,
                            miles=miles,
                            vehicle=vehicle,
                            start_location=start_location,
                            destination=destination,
                            business_purpose=business_purpose,
                            notes=notes,
                        )
                    )
                    if round_trip
                    else lambda: storage.create_mileage_trip(
                        trip_date=trip_date,
                        miles=miles,
                        vehicle=vehicle,
                        start_location=start_location,
                        destination=destination,
                        business_purpose=business_purpose,
                        notes=notes,
                    ),
                    (
                        "Round trip saved as two mileage entries."
                        if round_trip
                        else "Mileage trip saved."
                    ),
                    on_success=lambda: schedule_widget_reset(
                        "reset_add_mileage_form"
                    ),
                )

    with tab_log:
        c1, c2 = st.columns(2)
        start = c1.date_input(
            "From", date(date.today().year, 1, 1), key="mileage_start"
        )
        end = c2.date_input("To", date.today(), key="mileage_end")
        try:
            trips = storage.list_mileage_trips(start=start, end=end)
        except StorageError as error:
            report_storage_error(error)
            st.stop()

        trip_frame = mileage_frame(trips)
        metric_trips, metric_miles = st.columns(2)
        metric_trips.metric("Trips", len(trips))
        metric_miles.metric(
            "Business miles",
            f"{trip_frame['Miles'].sum():,.1f}" if not trip_frame.empty else "0.0",
        )
        st.download_button(
            "Download filtered mileage CSV",
            trip_frame.to_csv(index=False).encode("utf-8"),
            f"tabula-rosa-mileage-{start}-to-{end}.csv",
            "text/csv",
        )

        trip_ids = trip_frame["ID"].tolist()

        def select_mileage_trip() -> None:
            selected_rows = st.session_state["mileage_log"].selection.rows
            if selected_rows:
                st.session_state["edit_mileage_trip_id"] = trip_ids[
                    selected_rows[0]
                ]

        mileage_event = st.dataframe(
            trip_frame,
            hide_index=True,
            width="stretch",
            key="mileage_log",
            on_select=select_mileage_trip,
            selection_mode="single-row",
            column_config={
                "Miles": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        if trip_frame.empty:
            st.info("No mileage trips in this period.")
        else:
            selected_rows = mileage_event.selection.rows
            if st.session_state.get("edit_mileage_trip_id") not in trip_ids:
                st.session_state["edit_mileage_trip_id"] = trip_ids[0]

            def mileage_trip_label(trip_id: str) -> str:
                row = trip_frame.loc[trip_frame["ID"] == trip_id].iloc[0]
                return (
                    f"{row['Date']} - {row['Miles']:,.1f} mi - "
                    f"{row['Destination']} - {trip_id[:8]}"
                )

            st.caption("Select a mileage row (or double-click it) to edit it.")
            with st.expander("Edit mileage trip", expanded=bool(selected_rows)):
                edit_id = st.selectbox(
                    "Mileage trip to edit",
                    trip_ids,
                    format_func=mileage_trip_label,
                    key="edit_mileage_trip_id",
                )
                selected = next(trip for trip in trips if trip["id"] == edit_id)
                with st.form("edit_mileage_trip"):
                    c1, c2 = st.columns(2)
                    edited_date = c1.date_input(
                        "Edit trip date",
                        date.fromisoformat(selected["trip_date"]),
                    )
                    edited_miles = c2.number_input(
                        "Edit business miles",
                        min_value=0.1,
                        step=0.1,
                        value=float(selected["miles"]),
                        format="%.1f",
                    )
                    edited_vehicle = st.text_input(
                        "Edit vehicle", value=selected.get("vehicle", "")
                    )
                    c1, c2 = st.columns(2)
                    edited_start = c1.text_input(
                        "Edit starting location",
                        value=selected.get("start_location", ""),
                    )
                    edited_destination = c2.text_input(
                        "Edit destination",
                        value=selected.get("destination", ""),
                    )
                    edited_purpose = st.text_input(
                        "Edit business purpose",
                        value=selected.get("business_purpose", ""),
                    )
                    edited_notes = st.text_area(
                        "Edit notes", value=selected.get("notes", "")
                    )
                    st.warning(
                        "Deleting this mileage trip is permanent and cannot be undone."
                    )
                    confirm_delete = st.checkbox(
                        "I understand this mileage trip will be permanently deleted"
                    )
                    save_column, delete_column = st.columns(2)
                    save_requested = save_column.form_submit_button(
                        "Save mileage changes",
                        type="primary",
                        width="stretch",
                    )
                    delete_requested = delete_column.form_submit_button(
                        "Permanently delete mileage trip",
                        icon=":material/delete_forever:",
                        width="stretch",
                    )
                    if save_requested:
                        payload = {
                            "id": edit_id,
                            "trip_date": edited_date,
                            "miles": edited_miles,
                            "vehicle": edited_vehicle,
                            "start_location": edited_start,
                            "destination": edited_destination,
                            "business_purpose": edited_purpose,
                            "notes": edited_notes,
                        }
                        confirmed_write(
                            "edit_mileage_trip",
                            payload,
                            lambda: storage.edit_mileage_trip(
                                edit_id,
                                trip_date=edited_date,
                                miles=edited_miles,
                                vehicle=edited_vehicle,
                                start_location=edited_start,
                                destination=edited_destination,
                                business_purpose=edited_purpose,
                                notes=edited_notes,
                            ),
                            "Mileage trip updated.",
                        )
                    if delete_requested:
                        if not confirm_delete:
                            st.error(
                                "Confirm that you understand deletion is permanent."
                            )
                        else:
                            confirmed_write(
                                "delete_mileage_trip",
                                {"id": edit_id},
                                lambda: storage.delete_mileage_trip(edit_id),
                                "Mileage trip deleted.",
                            )


elif page == "Accounts":
    st.title("Accounts")
    st.caption("Track bank, cash, credit card, and other manual balances.")
    try:
        storage.prefetch_worksheets("Accounts", "Transactions")
        accounts = storage.list_accounts(active_only=False)
        transactions = storage.list_transactions()
        balances = balances_frame(accounts, transactions)
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    st.dataframe(
        balances[["Account", "Classification", "Type", "Active", "Balance"]],
        hide_index=True,
        width="stretch",
        column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
    )
    reset_widget_state_if_requested(
        "reset_add_account_form",
        keys=(
            "new_account_name",
            "new_account_type",
            "new_account_opening",
        ),
        prefixes=("new_account_classification_",),
    )
    with st.expander("Add account", expanded=True):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            name = c1.text_input("Account name", key="new_account_name")
            account_type = c2.selectbox(
                "Type",
                ACCOUNT_TYPES,
                key="new_account_type",
            )
            classification_options = [
                FIXED_TYPE_CLASSIFICATIONS[account_type]
            ] if account_type in FIXED_TYPE_CLASSIFICATIONS else ACCOUNT_CLASSIFICATIONS
            classification = c3.selectbox(
                "Balance-sheet classification",
                classification_options,
                key=f"new_account_classification_{account_type}",
            )
            opening = c4.number_input(
                "Opening balance",
                value=0.0,
                format="%.2f",
                key="new_account_opening",
                help=(
                    "Use positive balances for assets and negative balances for "
                    "liabilities and equity."
                ),
            )
            if st.button("Add account", type="primary"):
                payload = {
                    "name": name,
                    "account_type": account_type,
                    "classification": classification,
                    "opening_balance": opening,
                }
                confirmed_write(
                    "create_account",
                    payload,
                    lambda: storage.create_account(
                        name,
                        account_type,
                        opening,
                        classification=classification,
                    ),
                    "Account added.",
                    on_success=lambda: schedule_widget_reset(
                        "reset_add_account_form"
                    ),
                )

    if accounts:
        with st.expander("Edit or deactivate account"):
            account_by_id = {account["id"]: account for account in accounts}
            account_id = st.selectbox(
                "Account to manage",
                list(account_by_id),
                format_func=lambda value: account_by_id[value]["name"],
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
                        ),
                        "Account updated.",
                    )
            st.caption(
                "Accounts are deactivated rather than deleted so transaction references remain valid."
            )


elif page == "Categories":
    st.title("Categories")
    try:
        categories = storage.list_categories()
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    category_frame = pd.DataFrame(
        [
            {"ID": category["id"], "Category": category["name"], "Type": category["kind"]}
            for category in categories
        ]
    )
    st.dataframe(category_frame, hide_index=True, width="stretch")
    reset_widget_state_if_requested(
        "reset_add_category_form",
        keys=("new_category_name", "new_category_kind"),
    )
    with st.form("add_category", clear_on_submit=False):
        c1, c2 = st.columns(2)
        name = c1.text_input("Category name", key="new_category_name")
        kind = c2.selectbox(
            "Type",
            ["Expense", "Income"],
            key="new_category_kind",
        )
        if st.form_submit_button("Add category", type="primary"):
            payload = {"name": name, "kind": kind}
            confirmed_write(
                "create_category",
                payload,
                lambda: storage.create_category(name, kind),
                "Category added.",
                on_success=lambda: schedule_widget_reset(
                    "reset_add_category_form"
                ),
            )
    if categories:
        with st.expander("Edit category"):
            category_by_id = {category["id"]: category for category in categories}
            category_id = st.selectbox(
                "Category to edit",
                list(category_by_id),
                format_func=lambda value: (
                    f'{category_by_id[value]["name"]} '
                    f'({category_by_id[value]["kind"]})'
                ),
            )
            selected = category_by_id[category_id]
            with st.form("edit_category"):
                edited_name = st.text_input(
                    "Edit category name", value=selected["name"]
                )
                edited_kind = st.selectbox(
                    "Edit category type",
                    ["Expense", "Income"],
                    index=["Expense", "Income"].index(selected["kind"]),
                )
                if st.form_submit_button("Save category changes", type="primary"):
                    payload = {
                        "id": category_id,
                        "name": edited_name,
                        "kind": edited_kind,
                    }
                    confirmed_write(
                        "edit_category",
                        payload,
                        lambda: storage.edit_category(
                            category_id, name=edited_name, kind=edited_kind
                        ),
                        "Category updated.",
                    )
    st.caption(
        "Categories are not deleted so existing transaction references remain valid."
    )


elif page == "Reports":
    st.title("Reports")
    c1, c2 = st.columns(2)
    start = c1.date_input(
        "From", date(date.today().year, 1, 1), key="report_start"
    )
    end = c2.date_input("To", date.today(), key="report_end")
    try:
        storage.prefetch_worksheets(
            "Accounts",
            "Categories",
            "Transactions",
        )
        transactions = storage.list_transactions()
        categories = storage.list_categories()
        accounts = storage.list_accounts(active_only=False)
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    summary = profit_and_loss(transactions, start=start, end=end)
    a, b, c = st.columns(3)
    a.metric("Income", money(summary["income"]))
    b.metric("Expenses", money(summary["expenses"]))
    c.metric("Net", money(summary["net"]))
    monthly = pd.DataFrame(
        monthly_performance(transactions, start=start, end=end)
    ).rename(columns={"month": "Month", "income": "Income", "expenses": "Expenses"})
    by_category = pd.DataFrame(
        expenses_by_category(transactions, categories, start=start, end=end)
    ).rename(columns={"category": "Category", "total": "Total"})
    left, right = st.columns(2)
    with left:
        st.subheader("Monthly performance")
        if not monthly.empty:
            st.plotly_chart(
                px.bar(
                    monthly,
                    x="Month",
                    y=["Income", "Expenses"],
                    barmode="group",
                    color_discrete_sequence=["#206a4b", "#d47b55"],
                ),
                width="stretch",
            )
        else:
            st.info("No activity in this period.")
    with right:
        st.subheader("Expenses by category")
        if not by_category.empty:
            st.plotly_chart(
                px.bar(
                    by_category,
                    x="Total",
                    y="Category",
                    orientation="h",
                    color_discrete_sequence=["#d47b55"],
                ),
                width="stretch",
            )
        else:
            st.info("No expenses in this period.")

    st.divider()
    st.subheader("Balance sheet")
    as_of = st.date_input("As of", date.today(), key="balance_sheet_date")
    statement = balance_sheet(accounts, transactions, as_of=as_of)
    asset_metric, liability_metric, equity_metric = st.columns(3)
    asset_metric.metric("Total assets", money(statement["total_assets"]))
    liability_metric.metric(
        "Total liabilities", money(statement["total_liabilities"])
    )
    equity_metric.metric("Total equity", money(statement["total_equity"]))

    def statement_frame(
        rows: list[dict],
        *,
        current_earnings: float | None = None,
    ) -> pd.DataFrame:
        display_rows = [
            {
                "Account": row["name"],
                "Type": row["type"],
                "Balance": row["balance"],
            }
            for row in rows
        ]
        if current_earnings is not None:
            display_rows.append(
                {
                    "Account": "Current earnings",
                    "Type": "Calculated",
                    "Balance": current_earnings,
                }
            )
        return pd.DataFrame(
            display_rows,
            columns=["Account", "Type", "Balance"],
        )

    asset_column, liability_column, equity_column = st.columns(3)
    for column, title, frame in (
        (asset_column, "Assets", statement_frame(statement["assets"])),
        (
            liability_column,
            "Liabilities",
            statement_frame(statement["liabilities"]),
        ),
        (
            equity_column,
            "Equity",
            statement_frame(
                statement["equity"],
                current_earnings=statement["current_earnings"],
            ),
        ),
    ):
        with column:
            st.markdown(f"**{title}**")
            if frame.empty:
                st.caption("No accounts")
            else:
                st.dataframe(
                    frame,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Balance": st.column_config.NumberColumn(format="$%.2f")
                    },
                )
    if abs(statement["difference"]) < 0.005:
        st.success("Balance sheet is balanced.")
    else:
        st.warning(
            "Balance sheet is out of balance by "
            f"{money(statement['difference'])}. Review opening balances and "
            "account classifications."
        )
    st.caption(
        "Liabilities and equity are presented with conventional positive "
        "balances. Enter their opening ledger balances as negative amounts."
    )


elif page == "Data & backup":
    st.title("Data & backup")
    st.caption("Your live records are stored in the private Google Sheets workbook.")
    selected_profile = profile_by_key[selected_profile_key].secrets
    drive_settings = selected_profile.get("google_drive")
    backup_folder = (
        drive_settings.get("backup_folder")
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
                    backup_zip = storage.export_backup_zip()
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
                except (StorageError, GoogleDriveError, RuntimeError) as error:
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
            backup_zip = storage.export_backup_zip()
            manifest = storage.validate_backup_zip(backup_zip)
            accounts = storage.list_accounts(active_only=False)
            categories = storage.list_categories()
            transactions = storage.list_transactions()
            mileage_trips = storage.list_mileage_trips()
            all_transactions = ledger_frame(transactions, accounts, categories)
            all_mileage = mileage_frame(mileage_trips)
        except StorageError as error:
            report_storage_error(error)
        else:
            prepared_exports = {
                "backup": backup_zip,
                "backup_time": str(manifest["backup_time"]),
                "transactions": all_transactions.to_csv(index=False).encode(
                    "utf-8"
                ),
                "mileage": all_mileage.to_csv(index=False).encode("utf-8"),
            }
            st.session_state[prepared_exports_key] = prepared_exports
            st.success("Fresh downloadable exports are ready.")
    if isinstance(prepared_exports, Mapping):
        st.caption(f"Prepared from workbook data at {prepared_exports['backup_time']}.")
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
        st.download_button(
            "Download complete workbook backup",
            prepared_exports["backup"],
            f"tabula-rosa-backup-{date.today()}.zip",
            "application/zip",
            width="stretch",
        )
    with st.expander("Import Tabula Rosa CSV"):
        st.write(
            "Upload a CSV with: Date, Type, Amount, Account, Category, Payee, "
            "Description, Reference. Type must be Income or Expense."
        )
        plain_upload = st.file_uploader("CSV file", type="csv")
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
    upload = st.file_uploader("QuickBooks export", type=["csv", "xlsx", "zip"])
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
