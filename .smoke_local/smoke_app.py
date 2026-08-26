from __future__ import annotations

import runpy
import sys
from pathlib import Path

import streamlit as st


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from tests.fakes import FakeWorkbook  # noqa: E402
from tabula_rasa.storage import GoogleSheetsStorage  # noqa: E402
import tabula_rasa.local_profile_store as local_profile_store  # noqa: E402


local_profile_store.LOCAL_PROFILE_STORE_PATH = (
    Path(__file__).resolve().parent / ".streamlit" / "business_profiles.json"
)
fake_storage = GoogleSheetsStorage(FakeWorkbook())


def fake_from_secrets(cls, secrets):
    del cls, secrets
    return fake_storage


GoogleSheetsStorage.from_secrets = classmethod(fake_from_secrets)
st.session_state.setdefault("active_page", "Transactions")
st.session_state.setdefault("navigation_page", "Transactions")
runpy.run_path(str(REPOSITORY / "tabula_rasa" / "app.py"), run_name="__main__")
