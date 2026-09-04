from __future__ import annotations

import runpy
import sys
from datetime import date
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


def fake_from_secrets(cls, secrets):
    del cls, secrets
    return fake_storage


GoogleSheetsStorage.from_secrets = classmethod(fake_from_secrets)
GoogleDriveClient.list_receipts = lambda self, **kwargs: []
GoogleDriveClient.list_profile_receipts = lambda self, **kwargs: []
st.session_state.setdefault("active_page", "Dashboard")
st.session_state.setdefault("navigation_page", "Dashboard")
runpy.run_path(str(REPOSITORY / "tabula_rasa" / "app.py"), run_name="__main__")
