from __future__ import annotations

from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_label, navigate_to, profile_config
from tests.fakes import FakeWorkbook


def test_transaction_payee_selector_is_profile_scoped() -> None:
    storages = {
        "alpha-sheet": GoogleSheetsStorage(FakeWorkbook()),
        "beta-sheet": GoogleSheetsStorage(FakeWorkbook()),
    }
    profiles = {
        "alpha": profile_config(name="Alpha Business", spreadsheet_id="alpha-sheet"),
        "beta": profile_config(name="Beta Business", spreadsheet_id="beta-sheet"),
    }
    alpha = storages["alpha-sheet"]
    alpha.create_account("Alpha Checking", "Bank")
    alpha.create_category("Alpha Office", "Expense")
    alpha.create_payee("Alpha vendor")
    beta = storages["beta-sheet"]
    beta.create_account("Beta Checking", "Bank")
    beta.create_category("Beta Office", "Expense")
    beta.create_payee("Beta vendor")

    with authenticated_app(storages=storages, profiles=profiles) as app:
        navigate_to(app, "Transactions")
        selector = by_label(app.selectbox, "Payee / customer")
        assert "Alpha vendor" in selector.options
        assert "Beta vendor" not in selector.options

        by_label(app.selectbox, "Business").set_value("beta").run()
        selector = by_label(app.selectbox, "Payee / customer")
        assert "Beta vendor" in selector.options
        assert "Alpha vendor" not in selector.options
