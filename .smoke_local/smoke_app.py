from __future__ import annotations

import runpy
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from tests.fakes import FakeWorkbook  # noqa: E402
from tabula_rasa.google_drive import GoogleDriveClient  # noqa: E402
from tabula_rasa.storage import GoogleSheetsStorage  # noqa: E402
import tabula_rasa.local_profile_store as local_profile_store  # noqa: E402


local_profile_store.LOCAL_PROFILE_STORE_PATH = (
    Path(__file__).resolve().parent / ".streamlit" / "business_profiles.json"
)
fake_storage = GoogleSheetsStorage(FakeWorkbook())
fake_storage.ensure_defaults()
smoke_account = fake_storage.list_accounts()[0]
smoke_category = fake_storage.list_categories(kind="Expense")[0]
smoke_payee = fake_storage.create_payee("Viewport smoke vendor")
fake_storage.create_transaction(
    txn_date=date.today().isoformat(),
    kind="Expense",
    amount="25.00",
    account_id=smoke_account["id"],
    category_id=smoke_category["id"],
    payee_id=smoke_payee["id"],
)
fake_storage.create_mixed_use_expense(
    txn_date=(date.today() - timedelta(days=1)).isoformat(),
    total_expense="40.00",
    business_use_percentage="50",
    account_id=smoke_account["id"],
    category_id=smoke_category["id"],
    allocation_rationale="Viewport smoke allocation",
)
if os.environ.get("TABULA_RASA_SMOKE_JOURNALS") == "1":
    journal_category = fake_storage.list_categories(kind="Expense")[1]
    fake_storage.create_journal_entry(
        entry_id="viewport-journal", txn_date=date.today().isoformat(),
        description="Viewport journal", postings=[
            {"id": "viewport-line-1", "target_type": "category", "target_id": smoke_category["id"],
             "side": "Debit", "amount": "100", "payee_id": smoke_payee["id"], "description": "First posting"},
            {"id": "viewport-line-2", "target_type": "category", "target_id": journal_category["id"],
             "side": "Debit", "amount": "50", "description": "Second posting"},
            {"id": "viewport-line-3", "target_type": "account", "target_id": smoke_account["id"],
             "side": "Credit", "amount": "150", "description": "Offset posting"},
        ],
    )
fake_storage.create_asset(
    name="Viewport smoke laptop",
    asset_type="Computers & office equipment",
    acquisition_date=date.today().isoformat(),
    depreciation_start_date=date.today().isoformat(),
    cost_basis="1200.00",
    salvage_value="0.00",
    useful_life_quarters=20,
    depreciation_method="Straight-line",
    payee_id=smoke_payee["id"],
)


def fake_from_secrets(cls, secrets):
    del cls, secrets
    return fake_storage


GoogleSheetsStorage.from_secrets = classmethod(fake_from_secrets)
GoogleDriveClient.list_receipts = lambda self, **kwargs: []
GoogleDriveClient.list_profile_receipts = lambda self, **kwargs: []
st.session_state.setdefault("active_page", "Dashboard")
st.session_state.setdefault("navigation_page", "Dashboard")
runpy.run_path(str(REPOSITORY / "tabula_rasa" / "app.py"), run_name="__main__")
