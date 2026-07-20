from __future__ import annotations

from datetime import date
import io
import zipfile

import pandas as pd
import plotly.express as px
import streamlit as st

from business_profiles import (
    BusinessProfileConfigurationError,
    load_business_profiles,
    select_profile_secrets,
)
from ledger_auth import logout, require_authentication
from ledger_reporting import (
    account_balances,
    expenses_by_category,
    monthly_performance,
    profit_and_loss,
)
from storage import (
    GoogleSheetsStorage,
    StorageError,
    StorageValidationError,
)
from submission_guard import is_recent_duplicate, mark_completed
from quickbooks_import import (
    REQUIRED_COLUMNS as QUICKBOOKS_REQUIRED_COLUMNS,
    general_ledger_rows,
)


def money(value: float) -> str:
    return f"${value:,.2f}"


@st.cache_resource
def get_storage(profile_key: str) -> GoogleSheetsStorage:
    return GoogleSheetsStorage.from_secrets(
        select_profile_secrets(st.secrets, profile_key)
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
                "Active": account["active"],
                "Balance": account["balance"],
            }
            for account in rows
        ]
    )


def report_storage_error(error: StorageError) -> None:
    st.error(str(error))


def confirmed_write(
    action: str,
    payload: dict,
    operation,
    success_message,
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
    h1,h2,h3 { letter-spacing:-.025em; }
    .muted { color:#67716b; margin-top:-.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

require_authentication()

try:
    profiles = load_business_profiles(st.secrets)
except BusinessProfileConfigurationError as error:
    st.error(str(error))
    st.stop()

profile_by_key = {profile.key: profile for profile in profiles}
with st.sidebar:
    selected_profile_key = st.selectbox(
        "Business",
        list(profile_by_key),
        key="business_profile",
        format_func=lambda key: profile_by_key[key].name,
    )

try:
    storage = get_storage(selected_profile_key)
    initialized_profiles = st.session_state.setdefault(
        "defaults_initialized_profiles", set()
    )
    if selected_profile_key not in initialized_profiles:
        storage.ensure_defaults()
        initialized_profiles.add(selected_profile_key)
except StorageError as error:
    report_storage_error(error)
    st.stop()

with st.sidebar:
    st.title("Tabula Rosa")
    st.caption(profile_by_key[selected_profile_key].name)
    page = st.radio(
        "Navigate",
        ["Dashboard", "Transactions", "Accounts", "Categories", "Reports", "Data & backup"],
    )
    st.divider()
    st.caption(f"Workbook: {storage.workbook_title}")
    if st.button("Log out", width="stretch"):
        logout()


if page == "Dashboard":
    st.title("Your books at a glance")
    st.markdown(
        '<p class="muted">A current view of cash, income, and spending.</p>',
        unsafe_allow_html=True,
    )
    try:
        today = date.today()
        month_start = today.replace(day=1)
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
            balances[["Account", "Type", "Balance"]],
            hide_index=True,
            width="stretch",
            column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
        )


elif page == "Transactions":
    st.title("Transactions")
    tab_add, tab_ledger = st.tabs(["Add transaction", "View & edit ledger"])
    try:
        accounts = storage.list_accounts(active_only=False)
        active_accounts = [account for account in accounts if account["active"]]
        categories = storage.list_categories()
    except StorageError as error:
        report_storage_error(error)
        st.stop()

    account_map = {account["name"]: account["id"] for account in active_accounts}
    with tab_add:
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
                with st.form("add_transaction", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    transaction_date = c1.date_input("Date", date.today())
                    amount = c2.number_input(
                        "Amount", min_value=0.01, step=1.0, format="%.2f"
                    )
                    source = st.selectbox(
                        "Account" if kind != "Transfer" else "From account",
                        list(account_map),
                    )
                    to_account = None
                    category_id = None
                    if kind == "Transfer":
                        choices = [name for name in account_map if name != source]
                        to_account = (
                            st.selectbox("To account", choices) if choices else None
                        )
                    else:
                        category_map = {
                            category["name"]: category["id"]
                            for category in categories_for_kind
                        }
                        category_id = category_map[
                            st.selectbox("Category", list(category_map))
                        ]
                    c1, c2 = st.columns(2)
                    payee = c1.text_input("Payee / customer")
                    reference = c2.text_input("Reference (optional)")
                    description = st.text_input("Description / memo")
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
        try:
            transactions = storage.list_transactions(
                start=start,
                end=end,
                kind=None if filter_type == "All" else filter_type,
            )
        except StorageError as error:
            report_storage_error(error)
            st.stop()
        transaction_frame = ledger_frame(transactions, accounts, categories)
        st.dataframe(
            transaction_frame,
            hide_index=True,
            width="stretch",
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
        )
        if not transaction_frame.empty:
            transaction_ids = transaction_frame["ID"].tolist()

            def transaction_label(transaction_id: str) -> str:
                row = transaction_frame.loc[
                    transaction_frame["ID"] == transaction_id
                ].iloc[0]
                return f"{row['Date']} — {row['Type']} — {money(row['Amount'])} — {transaction_id[:8]}"

            with st.expander("Edit a transaction"):
                edit_id = st.selectbox(
                    "Transaction to edit",
                    transaction_ids,
                    format_func=transaction_label,
                )
                selected = next(
                    transaction for transaction in transactions if transaction["id"] == edit_id
                )
                with st.form("edit_transaction"):
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
                    if st.form_submit_button("Save changes", type="primary"):
                        payload = {
                            "id": edit_id,
                            "txn_date": edited_date,
                            "amount": edited_amount,
                            "payee": edited_payee,
                            "reference": edited_reference,
                            "description": edited_description,
                        }
                        confirmed_write(
                            "edit_transaction",
                            payload,
                            lambda: storage.edit_transaction(
                                edit_id,
                                txn_date=edited_date,
                                amount=edited_amount,
                                payee=edited_payee,
                                reference=edited_reference,
                                description=edited_description,
                            ),
                            "Transaction updated.",
                        )

            with st.expander("Delete a transaction"):
                delete_id = st.selectbox(
                    "Transaction to delete",
                    transaction_ids,
                    format_func=transaction_label,
                )
                confirm = st.checkbox(
                    "I understand this permanently removes the record"
                )
                if st.button("Delete", disabled=not confirm):
                    payload = {"id": delete_id}
                    confirmed_write(
                        "delete_transaction",
                        payload,
                        lambda: storage.delete_transaction(delete_id),
                        "Transaction deleted.",
                    )


elif page == "Accounts":
    st.title("Accounts")
    st.caption("Track bank, cash, credit card, and other manual balances.")
    try:
        accounts = storage.list_accounts(active_only=False)
        transactions = storage.list_transactions()
        balances = balances_frame(accounts, transactions)
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    st.dataframe(
        balances[["Account", "Type", "Active", "Balance"]],
        hide_index=True,
        width="stretch",
        column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")},
    )
    with st.expander("Add account", expanded=True):
        with st.form("add_account"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Account name")
            account_type = c2.selectbox(
                "Type", ["Bank", "Cash", "Credit card", "Loan", "Other"]
            )
            opening = c3.number_input(
                "Opening balance",
                value=0.0,
                format="%.2f",
                help="Use a negative value for money owed.",
            )
            if st.form_submit_button("Add account", type="primary"):
                payload = {
                    "name": name,
                    "account_type": account_type,
                    "opening_balance": opening,
                }
                confirmed_write(
                    "create_account",
                    payload,
                    lambda: storage.create_account(name, account_type, opening),
                    "Account added.",
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
            with st.form("edit_account"):
                edited_name = st.text_input("Edit account name", value=selected["name"])
                edited_type = st.selectbox(
                    "Edit account type",
                    ["Bank", "Cash", "Credit card", "Loan", "Other"],
                    index=["Bank", "Cash", "Credit card", "Loan", "Other"].index(
                        selected["type"]
                    ),
                )
                edited_opening = st.number_input(
                    "Edit opening balance",
                    value=float(selected["opening_balance"]),
                    format="%.2f",
                )
                edited_active = st.checkbox("Active", value=selected["active"])
                if st.form_submit_button("Save account changes", type="primary"):
                    payload = {
                        "id": account_id,
                        "name": edited_name,
                        "type": edited_type,
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
    with st.form("add_category"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Category name")
        kind = c2.selectbox("Type", ["Expense", "Income"])
        if st.form_submit_button("Add category", type="primary"):
            payload = {"name": name, "kind": kind}
            confirmed_write(
                "create_category",
                payload,
                lambda: storage.create_category(name, kind),
                "Category added.",
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
        transactions = storage.list_transactions()
        categories = storage.list_categories()
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


else:
    st.title("Data & backup")
    st.caption("Your live records are stored in the private Google Sheets workbook.")
    try:
        accounts = storage.list_accounts(active_only=False)
        categories = storage.list_categories()
        transactions = storage.list_transactions()
        all_transactions = ledger_frame(transactions, accounts, categories)
        backup_zip = storage.export_backup_zip()
    except StorageError as error:
        report_storage_error(error)
        st.stop()
    st.download_button(
        "Download transactions CSV",
        all_transactions.to_csv(index=False).encode("utf-8"),
        f"tabula-rosa-{date.today()}.csv",
        "text/csv",
        width="stretch",
    )
    st.download_button(
        "Download complete workbook backup",
        backup_zip,
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
        "Upload a QuickBooks Online **Transaction Detail by Account** CSV. "
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
                    st.error("\n".join(preview["errors"]))
                if conversion_errors:
                    st.error("\n".join(conversion_errors))
                if auto_create and (preview["new_accounts"] or preview["new_categories"]):
                    additions = [
                        f"Account: {name} ({preview['new_account_types'][name]})"
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
