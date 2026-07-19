from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from streamlit.testing.v1 import AppTest

from ledger_auth import hash_password


TEST_PASSWORD = "test-password-123"


def by_label(elements: object, label: str):
    return next(element for element in elements if element.label == label)


def main() -> None:
    database_path = Path(os.environ["LEDGER_DB_PATH"])
    app = AppTest.from_file("app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.run()
    app.text_input[0].input(TEST_PASSWORD)
    app.button[0].click().run()

    app.radio[0].set_value("Accounts").run()
    by_label(app.text_input, "Account name").input("Savings")
    by_label(app.selectbox, "Type").set_value("Bank")
    by_label(app.number_input, "Opening balance").set_value(100)
    by_label(app.button, "Add account").click().run()
    assert len(app.exception) == 0

    app.radio[0].set_value("Categories").run()
    by_label(app.text_input, "Category name").input("Testing expense")
    by_label(app.selectbox, "Type").set_value("Expense")
    by_label(app.button, "Add category").click().run()
    assert len(app.exception) == 0

    app.radio[0].set_value("Transactions").run()
    by_label(app.segmented_control, "Transaction type").set_value("Expense").run()
    by_label(app.number_input, "Amount").set_value(25)
    by_label(app.selectbox, "Account").set_value("Checking")
    by_label(app.selectbox, "Category").set_value("Testing expense")
    by_label(app.text_input, "Payee / customer").input("Test vendor")
    by_label(app.button, "Save transaction").click().run()
    assert len(app.exception) == 0

    by_label(app.segmented_control, "Transaction type").set_value("Income").run()
    by_label(app.number_input, "Amount").set_value(75)
    by_label(app.selectbox, "Account").set_value("Checking")
    by_label(app.selectbox, "Category").set_value("Sales")
    by_label(app.text_input, "Payee / customer").input("Test customer")
    by_label(app.button, "Save transaction").click().run()

    by_label(app.segmented_control, "Transaction type").set_value("Transfer").run()
    by_label(app.number_input, "Amount").set_value(10)
    by_label(app.selectbox, "From account").set_value("Checking")
    by_label(app.selectbox, "To account").set_value("Savings")
    by_label(app.button, "Save transaction").click().run()

    with sqlite3.connect(database_path) as connection:
        kinds = connection.execute(
            "SELECT kind, COUNT(*) FROM transactions GROUP BY kind"
        ).fetchall()
    assert dict(kinds) == {"Expense": 1, "Income": 1, "Transfer": 1}

    by_label(
        app.checkbox, "I understand this permanently removes the record"
    ).check()
    by_label(app.button, "Delete").click().run()
    with sqlite3.connect(database_path) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM transactions"
        ).fetchone()[0]
    assert remaining == 2


if __name__ == "__main__":
    main()
