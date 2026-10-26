from __future__ import annotations

from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.validate_google_sheets import validate
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tests.fakes import FakeWorkbook
from tests.sheets_fixtures import account as fixture_account, category as fixture_category, payee as fixture_payee, tag as fixture_tag, transaction as fixture_transaction, mileage as fixture_mileage


PROFILE_DOCUMENT = {
    "business_profiles": {
        "test-business": {
            "name": "Test Business",
            "spreadsheet_id": "configured-live-workbook",
            "google_drive": google_grant('test@example.invalid'), "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        }
    }
}


def populated_workbook() -> FakeWorkbook:
    workbook = FakeWorkbook()
    storage = GoogleSheetsStorage(workbook, sleeper=lambda _: None)
    account = fixture_account(storage, "Checking", "Bank")
    category = fixture_category(storage, "Software", "Expense")
    payee = fixture_payee(storage, "Vendor")
    tag = fixture_tag(storage, "Client work")
    fixture_transaction(storage,
        txn_date="2026-07-29",
        kind="Expense",
        amount="12.50",
        account_id=account["id"],
        category_id=category["id"],
        payee_id=payee["id"],
        tag_ids=[tag["id"]],
    )
    fixture_mileage(storage,
        trip_date="2026-07-29",
        miles="5",
        start_location="Office",
        destination="Client",
        business_purpose="Meeting",
        tag_ids=[tag["id"]],
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
@patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials")
@patch("tabula_rasa.storage.google_sheets.client.gspread.authorize")
def test_explicit_workbook_override_is_read_only_and_reports_counts(
    authorize: Mock,
    build_profile_credentials: Mock,
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
    assert build_profile_credentials.call_args.args[0]["google_drive"]["refresh_token"] == "fake-refresh"
    output = capsys.readouterr().out
    assert "Ledger rows readable: Accounts=1, Categories=1" in output
    assert "Payees=1" in output
    assert "Tags=1" in output
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
@patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials")
@patch("tabula_rasa.storage.google_sheets.client.gspread.authorize")
def test_configured_profile_still_uses_configured_workbook(
    authorize: Mock,
    _build_profile_credentials: Mock,
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
@patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials")
@patch("tabula_rasa.storage.google_sheets.client.gspread.authorize")
def test_read_only_validation_rejects_legacy_hierarchy_headers_until_migrated(
    authorize: Mock,
    _build_profile_credentials: Mock,
    _load_document: Mock,
) -> None:
    workbook = legacy_hierarchy_workbook()
    original_rows = {
        title: [list(row) for row in workbook.sheets[title].rows]
        for title in ("Accounts", "Categories")
    }
    authorize.return_value.open_by_key.return_value = workbook

    with pytest.raises(StorageValidationError, match="parent_id"):
        validate(Path("unused.toml"), profile_key="test-business")
    for title in ("Accounts", "Categories"):
        assert workbook.sheets[title].rows == original_rows[title]


@patch(
    "scripts.validate_google_sheets.load_business_profile_document",
    return_value=PROFILE_DOCUMENT,
)
@patch("tabula_rasa.storage.google_sheets.client.profile_google_credentials")
@patch("tabula_rasa.storage.google_sheets.client.gspread.authorize")
def test_validation_rejects_invalid_payee_records(
    authorize: Mock,
    _build_profile_credentials: Mock,
    _load_document: Mock,
) -> None:
    workbook = populated_workbook()
    workbook.sheets["Payees"].rows.append(
        ["another-id", " vendor ", "TRUE", "2026-07-29T00:00:00Z"]
    )
    authorize.return_value.open_by_key.return_value = workbook

    with pytest.raises(StorageValidationError, match="unique"):
        validate(Path("unused.toml"), profile_key="test-business")
