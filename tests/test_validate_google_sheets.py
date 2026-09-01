from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.validate_google_sheets import validate
from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


PROFILE_DOCUMENT = {
    "business_profiles": {
        "test-business": {
            "name": "Test Business",
            "spreadsheet_id": "configured-live-workbook",
            "gcp_service_account": {"client_email": "test@example.invalid"},
        }
    }
}


def populated_workbook() -> FakeWorkbook:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = storage.create_account("Checking", "Bank")
    category = storage.create_category("Software", "Expense")
    payee = storage.create_payee("Vendor")
    storage.create_transaction(
        txn_date="2026-07-29",
        kind="Expense",
        amount="12.50",
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
    )
    storage.create_mileage_trip(
        trip_date="2026-07-29",
        miles="5",
        start_location="Office",
        destination="Client",
        business_purpose="Meeting",
    )
    return workbook


def legacy_hierarchy_workbook() -> FakeWorkbook:
    workbook = populated_workbook()
    for title in ("Accounts", "Categories"):
        worksheet = workbook.sheets[title]
        parent_index = worksheet.rows[0].index("parent_id")
        for row in worksheet.rows:
            del row[parent_index]
    return workbook


@patch(
    "scripts.validate_google_sheets.load_business_profile_document",
    return_value=PROFILE_DOCUMENT,
)
@patch("scripts.validate_google_sheets.Credentials.from_service_account_info")
@patch("scripts.validate_google_sheets.gspread.authorize")
def test_explicit_workbook_override_is_read_only_and_reports_counts(
    authorize: Mock,
    from_service_account_info: Mock,
    _load_document: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workbook = populated_workbook()
    client = authorize.return_value
    client.open_by_key.return_value = workbook

    validate(
        Path("unused.toml"),
        profile_key="test-business",
        spreadsheet_id=" recovery-workbook ",
    )

    client.open_by_key.assert_called_once_with("recovery-workbook")
    scopes = from_service_account_info.call_args.kwargs["scopes"]
    assert scopes == ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    output = capsys.readouterr().out
    assert "Ledger rows readable: Accounts=1, Categories=1" in output
    assert "Transactions=1, Mileage=1" in output
    assert "Explicit workbook override verified; business profile unchanged" in output
    assert "recovery-workbook" not in output
    assert "configured-live-workbook" not in output


def test_explicit_workbook_override_rejects_write_test() -> None:
    with pytest.raises(
        ValueError,
        match="--spreadsheet-id cannot be combined with --write-test",
    ):
        validate(
            Path("unused.toml"),
            write_test=True,
            spreadsheet_id="recovery-workbook",
        )


@patch(
    "scripts.validate_google_sheets.load_business_profile_document",
    return_value=PROFILE_DOCUMENT,
)
@patch("scripts.validate_google_sheets.Credentials.from_service_account_info")
@patch("scripts.validate_google_sheets.gspread.authorize")
def test_configured_profile_still_uses_configured_workbook(
    authorize: Mock,
    _from_service_account_info: Mock,
    _load_document: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authorize.return_value.open_by_key.return_value = FakeWorkbook()

    validate(Path("unused.toml"), profile_key="test-business")

    authorize.return_value.open_by_key.assert_called_once_with(
        "configured-live-workbook"
    )
    output = capsys.readouterr().out
    assert "Ledger rows readable: Accounts=0, Categories=0" in output
    assert "Explicit workbook override" not in output


@patch(
    "scripts.validate_google_sheets.load_business_profile_document",
    return_value=PROFILE_DOCUMENT,
)
@patch("scripts.validate_google_sheets.Credentials.from_service_account_info")
@patch("scripts.validate_google_sheets.gspread.authorize")
def test_read_only_validation_accepts_legacy_hierarchy_headers_without_migration(
    authorize: Mock,
    _from_service_account_info: Mock,
    _load_document: Mock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workbook = legacy_hierarchy_workbook()
    original_rows = {
        title: [list(row) for row in workbook.sheets[title].rows]
        for title in ("Accounts", "Categories")
    }
    authorize.return_value.open_by_key.return_value = workbook

    validate(Path("unused.toml"), profile_key="test-business")

    output = capsys.readouterr().out
    assert "Ledger rows readable: Accounts=1, Categories=1" in output
    for title in ("Accounts", "Categories"):
        assert workbook.sheets[title].rows == original_rows[title]
