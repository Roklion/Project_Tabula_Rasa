"""Local administration entry point and retired bookkeeping boundary."""
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.local_profile_store import save_local_profile
from tabula_rasa.storage import GoogleSheetsStorage

PASSWORD = "synthetic-admin-password"


def app_test():
    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(PASSWORD)
    return app


@pytest.mark.parametrize("address,enabled", [("127.0.0.1", ""), ("0.0.0.0", "1")])
def test_non_operator_environment_cannot_initialize_ledger(monkeypatch, address, enabled):
    monkeypatch.setenv("TABULA_LOCAL_PROFILE_ADMIN", enabled)
    with patch.object(st, "get_option", return_value=address), patch.object(GoogleSheetsStorage, "from_secrets") as opening:
        app = app_test().run()
        assert not app.tabs
        app.text_input[0].input(PASSWORD)
        app.button[0].click().run()
        assert not app.exception
        assert any("restricted loopback" in error.value for error in app.error)
        assert not app.tabs and not app.radio
    opening.assert_not_called()


def test_operator_requires_login_and_reauthentication_without_startup_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("TABULA_LOCAL_PROFILE_ADMIN", "1")
    path = tmp_path / "profiles.json"
    for key in ("north", "south"):
        save_local_profile(key, {"name": key.title(), "spreadsheet_id": key + "-sheet-12345"}, path=path)
    before = path.read_bytes()
    with (
        patch.object(st, "get_option", return_value="127.0.0.1"),
        patch("tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH", path),
        patch.object(GoogleSheetsStorage, "from_secrets") as opening,
    ):
        app = app_test()
        app.session_state["active_page"] = "Transactions"
        app.session_state["navigation_page"] = "Dashboard"
        app.run()
        assert app.text_input[0].label == "Password"
        app.text_input[0].input("wrong")
        app.button[0].click().run()
        assert any("Incorrect password" in item.value for item in app.error)
        app.text_input[0].input(PASSWORD)
        app.button[0].click().run()
        assert not app.exception
        assert any(item.label == "Application password" for item in app.text_input)
        assert not app.tabs and not app.radio
        next(item for item in app.text_input if item.label == "Application password").input(PASSWORD)
        next(item for item in app.button if item.label == "Unlock profile administration").click().run()
        assert not app.exception
        assert [tab.label for tab in app.tabs] == ["Business profiles", "Google setup", "Recovery", "Security & deployment information"]
        selector = next(item for item in app.selectbox if item.label == "Business profile to configure")
        selector.select("south").run()
        assert app.session_state["local_profile_selected"] == "south"
        assert not app.radio
        next(item for item in app.button if item.label == "Log out").click().run()
        assert app.text_input[0].label == "Password"
        assert not app.tabs
    opening.assert_not_called()
    assert path.read_bytes() == before
