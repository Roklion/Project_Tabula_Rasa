from __future__ import annotations

import io
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from ledger_auth import logout, require_authentication


APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("LEDGER_DB_PATH", APP_DIR / "data" / "ledger.db"))


def money(value: float) -> str:
    return f"${value:,.2f}"


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                opening_balance REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('Income','Expense')),
                UNIQUE(name, kind)
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY,
                txn_date TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('Income','Expense','Transfer')),
                amount REAL NOT NULL CHECK(amount > 0),
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                to_account_id INTEGER REFERENCES accounts(id),
                category_id INTEGER REFERENCES categories(id),
                payee TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                reference TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(kind != 'Transfer' OR to_account_id IS NOT NULL),
                CHECK(kind = 'Transfer' OR to_account_id IS NULL)
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(txn_date);
            CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id);
            """
        )
        if not conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
            conn.executemany(
                "INSERT INTO accounts(name,type,opening_balance) VALUES(?,?,?)",
                [("Checking", "Bank", 0), ("Cash", "Cash", 0)],
            )
        defaults = {
            "Income": ["Sales", "Services", "Interest", "Other income"],
            "Expense": ["Advertising", "Bank fees", "Insurance", "Meals", "Office", "Professional fees", "Rent", "Software", "Supplies", "Travel", "Utilities", "Other expense"],
        }
        for kind, names in defaults.items():
            conn.executemany(
                "INSERT OR IGNORE INTO categories(name,kind) VALUES(?,?)",
                [(name, kind) for name in names],
            )


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with db() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def execute(sql: str, params: tuple = ()) -> None:
    with db() as conn:
        conn.execute(sql, params)


def account_rows(active_only: bool = True):
    where = "WHERE active=1" if active_only else ""
    with db() as conn:
        return conn.execute(f"SELECT * FROM accounts {where} ORDER BY name").fetchall()


def category_rows(kind: str | None = None):
    with db() as conn:
        if kind:
            return conn.execute("SELECT * FROM categories WHERE kind=? ORDER BY name", (kind,)).fetchall()
        return conn.execute("SELECT * FROM categories ORDER BY kind,name").fetchall()


def balances() -> pd.DataFrame:
    return query(
        """
        SELECT a.id, a.name AS Account, a.type AS Type,
          a.opening_balance
          + COALESCE(SUM(CASE
              WHEN t.kind='Income' AND t.account_id=a.id THEN t.amount
              WHEN t.kind='Expense' AND t.account_id=a.id THEN -t.amount
              WHEN t.kind='Transfer' AND t.account_id=a.id THEN -t.amount
              WHEN t.kind='Transfer' AND t.to_account_id=a.id THEN t.amount
              ELSE 0 END),0) AS Balance
        FROM accounts a LEFT JOIN transactions t
          ON a.id=t.account_id OR a.id=t.to_account_id
        GROUP BY a.id ORDER BY a.active DESC,a.name
        """
    )


def ledger(where: str = "", params: tuple = ()) -> pd.DataFrame:
    return query(
        f"""
        SELECT t.id AS ID,t.txn_date AS Date,t.kind AS Type,a.name AS Account,
          ta.name AS "To account",c.name AS Category,t.payee AS Payee,
          t.description AS Description,t.reference AS Reference,t.amount AS Amount
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        LEFT JOIN accounts ta ON ta.id=t.to_account_id
        LEFT JOIN categories c ON c.id=t.category_id
        {where} ORDER BY t.txn_date DESC,t.id DESC
        """,
        params,
    )


st.set_page_config(page_title="Plain Ledger", page_icon="📒", layout="wide")
st.markdown(
    """
    <style>
    :root { --ink:#17211b; --green:#206a4b; --cream:#f7f5ef; }
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
init_db()

with st.sidebar:
    st.title("Plain Ledger")
    st.caption("Simple books. Clear numbers.")
    page = st.radio("Navigate", ["Dashboard", "Transactions", "Accounts", "Categories", "Reports", "Data & backup"])
    st.divider()
    st.caption(f"Database: {DB_PATH.name}")
    if st.button("Log out", use_container_width=True):
        logout()


if page == "Dashboard":
    st.title("Your books at a glance")
    st.markdown('<p class="muted">A current view of cash, income, and spending.</p>', unsafe_allow_html=True)
    today = date.today()
    month_start = today.replace(day=1).isoformat()
    totals = query(
        """SELECT
        COALESCE(SUM(CASE WHEN kind='Income' THEN amount ELSE 0 END),0) income,
        COALESCE(SUM(CASE WHEN kind='Expense' THEN amount ELSE 0 END),0) expense
        FROM transactions WHERE txn_date>=? AND txn_date<=?""",
        (month_start, today.isoformat()),
    ).iloc[0]
    bals = balances()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total balance", money(bals.Balance.sum()))
    c2.metric("Income this month", money(totals.income))
    c3.metric("Expenses this month", money(totals.expense))
    c4.metric("Net this month", money(totals.income - totals.expense))
    left, right = st.columns([1.4, 1])
    with left:
        st.subheader("Recent activity")
        recent = ledger().head(8)
        if recent.empty:
            st.info("No transactions yet. Add your first one from Transactions.")
        else:
            display = recent[["Date", "Type", "Payee", "Category", "Account", "Amount"]].copy()
            display["Amount"] = display.apply(lambda r: (-r.Amount if r.Type == "Expense" else r.Amount), axis=1)
            st.dataframe(display, hide_index=True, use_container_width=True, column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
    with right:
        st.subheader("Account balances")
        st.dataframe(bals[["Account", "Type", "Balance"]], hide_index=True, use_container_width=True, column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")})


elif page == "Transactions":
    st.title("Transactions")
    tab_add, tab_ledger = st.tabs(["Add transaction", "View & edit ledger"])
    accounts = account_rows()
    account_map = {r["name"]: r["id"] for r in accounts}
    with tab_add:
        kind = st.segmented_control("Transaction type", ["Income", "Expense", "Transfer"], default="Expense")
        with st.form("add_transaction", clear_on_submit=True):
            c1, c2 = st.columns(2)
            txn_date = c1.date_input("Date", date.today())
            amount = c2.number_input("Amount", min_value=0.01, step=1.0, format="%.2f")
            source = st.selectbox("Account" if kind != "Transfer" else "From account", list(account_map))
            to_account = None
            category_id = None
            if kind == "Transfer":
                choices = [n for n in account_map if n != source]
                to_account = st.selectbox("To account", choices) if choices else None
            else:
                cats = category_rows(kind)
                cat_map = {r["name"]: r["id"] for r in cats}
                category_id = cat_map[st.selectbox("Category", list(cat_map))]
            c1, c2 = st.columns(2)
            payee = c1.text_input("Payee / customer")
            reference = c2.text_input("Reference (optional)")
            description = st.text_input("Description / memo")
            submitted = st.form_submit_button("Save transaction", type="primary", use_container_width=True)
            if submitted:
                if kind == "Transfer" and not to_account:
                    st.error("Create a second account before recording a transfer.")
                else:
                    execute(
                        "INSERT INTO transactions(txn_date,kind,amount,account_id,to_account_id,category_id,payee,description,reference) VALUES(?,?,?,?,?,?,?,?,?)",
                        (txn_date.isoformat(), kind, amount, account_map[source], account_map.get(to_account), category_id, payee.strip(), description.strip(), reference.strip()),
                    )
                    st.success("Transaction saved.")
    with tab_ledger:
        c1, c2, c3 = st.columns(3)
        start = c1.date_input("From", date(date.today().year, 1, 1), key="ledger_start")
        end = c2.date_input("To", date.today(), key="ledger_end")
        filter_type = c3.selectbox("Type", ["All", "Income", "Expense", "Transfer"])
        sql = "WHERE t.txn_date BETWEEN ? AND ?"
        params: tuple = (start.isoformat(), end.isoformat())
        if filter_type != "All":
            sql += " AND t.kind=?"
            params += (filter_type,)
        txns = ledger(sql, params)
        st.dataframe(txns, hide_index=True, use_container_width=True, column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")})
        if not txns.empty:
            with st.expander("Delete a transaction"):
                delete_id = st.selectbox("Transaction", txns.ID.tolist(), format_func=lambda i: f"#{i} — {txns.loc[txns.ID==i, 'Date'].iloc[0]} — {money(txns.loc[txns.ID==i, 'Amount'].iloc[0])}")
                confirm = st.checkbox("I understand this permanently removes the record")
                if st.button("Delete", disabled=not confirm):
                    execute("DELETE FROM transactions WHERE id=?", (int(delete_id),))
                    st.success("Transaction deleted.")
                    st.rerun()


elif page == "Accounts":
    st.title("Accounts")
    st.caption("Track bank, cash, credit card, and other manual balances.")
    bals = balances()
    st.dataframe(bals[["Account", "Type", "Balance"]], hide_index=True, use_container_width=True, column_config={"Balance": st.column_config.NumberColumn(format="$%.2f")})
    with st.expander("Add account", expanded=True):
        with st.form("add_account"):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Account name")
            account_type = c2.selectbox("Type", ["Bank", "Cash", "Credit card", "Loan", "Other"])
            opening = c3.number_input("Opening balance", value=0.0, format="%.2f", help="Use a negative value for money owed.")
            if st.form_submit_button("Add account", type="primary"):
                try:
                    execute("INSERT INTO accounts(name,type,opening_balance) VALUES(?,?,?)", (name.strip(), account_type, opening))
                    st.success("Account added.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Account names must be unique and cannot be blank.")


elif page == "Categories":
    st.title("Categories")
    cats = query("SELECT id AS ID,name AS Category,kind AS Type FROM categories ORDER BY kind,name")
    st.dataframe(cats, hide_index=True, use_container_width=True)
    with st.form("add_category"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Category name")
        kind = c2.selectbox("Type", ["Expense", "Income"])
        if st.form_submit_button("Add category", type="primary"):
            try:
                execute("INSERT INTO categories(name,kind) VALUES(?,?)", (name.strip(), kind))
                st.success("Category added.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("That category already exists or the name is blank.")


elif page == "Reports":
    st.title("Reports")
    c1, c2 = st.columns(2)
    start = c1.date_input("From", date(date.today().year, 1, 1), key="report_start")
    end = c2.date_input("To", date.today(), key="report_end")
    summary = query(
        """SELECT kind AS Type,COALESCE(SUM(amount),0) AS Total FROM transactions
        WHERE txn_date BETWEEN ? AND ? AND kind IN ('Income','Expense') GROUP BY kind""",
        (start.isoformat(), end.isoformat()),
    )
    inc = float(summary.loc[summary.Type == "Income", "Total"].sum())
    exp = float(summary.loc[summary.Type == "Expense", "Total"].sum())
    a, b, c = st.columns(3)
    a.metric("Income", money(inc)); b.metric("Expenses", money(exp)); c.metric("Net", money(inc-exp))
    monthly = query(
        """SELECT substr(txn_date,1,7) Month,
        SUM(CASE WHEN kind='Income' THEN amount ELSE 0 END) Income,
        SUM(CASE WHEN kind='Expense' THEN amount ELSE 0 END) Expenses
        FROM transactions WHERE txn_date BETWEEN ? AND ? GROUP BY Month ORDER BY Month""",
        (start.isoformat(), end.isoformat()),
    )
    by_cat = query(
        """SELECT COALESCE(c.name,'Uncategorized') Category,SUM(t.amount) Total
        FROM transactions t LEFT JOIN categories c ON c.id=t.category_id
        WHERE t.kind='Expense' AND t.txn_date BETWEEN ? AND ? GROUP BY c.name ORDER BY Total DESC""",
        (start.isoformat(), end.isoformat()),
    )
    left, right = st.columns(2)
    with left:
        st.subheader("Monthly performance")
        if not monthly.empty:
            st.plotly_chart(px.bar(monthly, x="Month", y=["Income", "Expenses"], barmode="group", color_discrete_sequence=["#206a4b", "#d47b55"]), use_container_width=True)
        else: st.info("No activity in this period.")
    with right:
        st.subheader("Expenses by category")
        if not by_cat.empty:
            st.plotly_chart(px.bar(by_cat, x="Total", y="Category", orientation="h", color_discrete_sequence=["#d47b55"]), use_container_width=True)
        else: st.info("No expenses in this period.")


else:
    st.title("Data & backup")
    st.caption("Your records stay in a single SQLite file. Back it up regularly.")
    all_txns = ledger()
    st.download_button("Download transactions CSV", all_txns.to_csv(index=False).encode(), f"plain-ledger-{date.today()}.csv", "text/csv", use_container_width=True)
    if DB_PATH.exists():
        st.download_button("Download full database backup", DB_PATH.read_bytes(), f"plain-ledger-backup-{date.today()}.db", "application/octet-stream", use_container_width=True)
    st.subheader("Import transactions")
    st.write("Upload a CSV with: Date, Type, Amount, Account, Category, Payee, Description, Reference. Type must be Income or Expense; account and category names must already exist.")
    upload = st.file_uploader("CSV file", type="csv")
    if upload:
        try:
            incoming = pd.read_csv(upload)
            required = {"Date", "Type", "Amount", "Account", "Category"}
            missing = required - set(incoming.columns)
            if missing:
                st.error(f"Missing columns: {', '.join(sorted(missing))}")
            else:
                st.dataframe(incoming.head(20), hide_index=True, use_container_width=True)
                if st.button("Import rows", type="primary"):
                    accounts = {r["name"]: r["id"] for r in account_rows(False)}
                    categories = {(r["name"], r["kind"]): r["id"] for r in category_rows()}
                    rows = []
                    for n, r in incoming.iterrows():
                        kind = str(r.Type).title()
                        if kind not in ("Income", "Expense") or r.Account not in accounts or (r.Category, kind) not in categories:
                            raise ValueError(f"Row {n+2} has an unknown type, account, or category")
                        txn_date = pd.to_datetime(r.Date).date().isoformat()
                        rows.append((txn_date, kind, abs(float(r.Amount)), accounts[r.Account], categories[(r.Category, kind)], str(r.get("Payee", "")), str(r.get("Description", "")), str(r.get("Reference", ""))))
                    with db() as conn:
                        conn.executemany("INSERT INTO transactions(txn_date,kind,amount,account_id,category_id,payee,description,reference) VALUES(?,?,?,?,?,?,?,?)", rows)
                    st.success(f"Imported {len(rows)} transactions.")
                    st.rerun()
        except Exception as exc:
            st.error(f"Could not read this file: {exc}")
