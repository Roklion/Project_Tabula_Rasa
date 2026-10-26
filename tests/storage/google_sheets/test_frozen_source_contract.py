"""Supported format-13 source and recovery boundary, without historical converters."""
from tests.sheets_fixtures import account as fixture_account, category as fixture_category, transaction as fixture_transaction

from copy import deepcopy
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch
import zipfile

import pytest

import scripts.restore_google_sheets_backup as restore_script
from scripts.restore_google_sheets_backup import (
    initialize_blank_ledger_sheets,
    validate_restore_backup,
)
from tabula_rasa.business_profiles import select_profile_secrets
from tabula_rasa.receipt_manifest import build_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage, StorageValidationError
from tabula_rasa.storage.google_sheets.schema import WORKSHEET_HEADERS
from tests.fakes import FakeWorkbook
from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant
from ._support import rewrite_backup_tables


def rewrite_manifest(backup, change):
    output = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(backup)) as source,
        zipfile.ZipFile(output, "w") as target,
    ):
        manifest = json.loads(source.read("manifest.json"))
        change(manifest)
        for name in source.namelist():
            target.writestr(
                name,
                json.dumps(manifest) if name == "manifest.json" else source.read(name),
            )
    return output.getvalue()


def profile_config():
    return {
        "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        "business_profiles": {
            key: {
                "name": key.title(),
                "spreadsheet_id": f"{key}-sheet",
                "google_drive": google_grant(f"{key}@example.test"),
            }
            for key in ("north", "south")
        },
    }


@pytest.fixture
def current_backup():
    storage = GoogleSheetsStorage(FakeWorkbook())
    fixture_account(storage, "Checking", "Bank", opening_balance="123.45")
    return storage.export_backup_zip(build_receipt_manifest("north", [], []))


@pytest.mark.parametrize("version", [*range(1, 13), 14, "13", 13.0, None])
def test_unsupported_archive_versions_are_rejected_without_restore_writes(
    current_backup, version
):
    backup = rewrite_manifest(
        current_backup, lambda manifest: manifest.update(format_version=version)
    )
    target = GoogleSheetsStorage(FakeWorkbook())
    target._append_many = Mock()
    with pytest.raises(StorageValidationError, match="Only backup format 13") as raised:
        target.restore_backup_zip(backup)
    assert "scripts/" not in str(raised.value)
    target._append_many.assert_not_called()
    assert all(len(sheet.rows) == 1 for sheet in target._workbook.worksheets())


@pytest.mark.parametrize(
    "layout", ["pre-payee", "pre-journal", "missing-tags", "extra-field"]
)
@pytest.mark.parametrize("read_only", [False, True])
def test_unsupported_populated_workbooks_fail_without_writes(layout, read_only):
    headers = dict(WORKSHEET_HEADERS)
    if layout == "pre-payee":
        headers["Transactions"] = tuple(
            "payee" if field == "payee_id" else field
            for field in headers["Transactions"]
        )
    elif layout == "pre-journal":
        del headers["JournalEntries"]
        del headers["JournalPostings"]
    elif layout == "missing-tags":
        headers["MixedUseExpenses"] = tuple(
            field for field in headers["MixedUseExpenses"] if field != "tag_ids"
        )
    else:
        headers["Transactions"] += ("tag_ids__migration_pending",)
    workbook = FakeWorkbook(headers)
    workbook.sheets["Accounts"].rows.append(["account-1", "Preserved history"])
    before = deepcopy({title: sheet.rows for title, sheet in workbook.sheets.items()})
    workbook.add_worksheet = Mock(wraps=workbook.add_worksheet)
    for sheet in workbook.worksheets():
        sheet.update = Mock(wraps=sheet.update)
    factory = (
        GoogleSheetsStorage.from_secrets_read_only
        if read_only
        else GoogleSheetsStorage.from_secrets
    )
    with patch.object(
        GoogleSheetsStorage, "_open_workbook_from_secrets", return_value=workbook
    ):
        with pytest.raises(StorageValidationError, match="format-13") as raised:
            factory({"spreadsheet_id": "north-sheet"})
    assert "scripts/" not in str(raised.value)
    assert before == {title: sheet.rows for title, sheet in workbook.sheets.items()}
    workbook.add_worksheet.assert_not_called()
    for sheet in workbook.worksheets():
        sheet.update.assert_not_called()


def test_partial_current_header_bootstrap_resumes_without_default_tab_changes():
    workbook = FakeWorkbook({"Sheet1": (), "Accounts": WORKSHEET_HEADERS["Accounts"]})
    with patch.object(
        GoogleSheetsStorage, "_open_workbook_from_secrets", return_value=workbook
    ):
        storage = GoogleSheetsStorage.from_secrets({"spreadsheet_id": "new-sheet"})
    assert workbook.sheets["Sheet1"].rows == [[]]
    for title, headers in WORKSHEET_HEADERS.items():
        assert workbook.sheets[title].rows == [list(headers)]
    assert storage.ensure_defaults() == {"accounts": 2, "categories": 16}


@pytest.mark.parametrize(
    "headers", [{"Mileage": ("id", "trip_date")}, {"Sheet1": ("private data",)}]
)
def test_restore_initialization_preflights_all_tabs_before_creating_any(headers):
    workbook = FakeWorkbook(headers)
    workbook.add_worksheet = Mock(wraps=workbook.add_worksheet)
    for sheet in workbook.worksheets():
        sheet.update = Mock(wraps=sheet.update)
    with pytest.raises(
        StorageValidationError, match="populated or incompatible restore target"
    ):
        initialize_blank_ledger_sheets(workbook)
    workbook.add_worksheet.assert_not_called()
    for sheet in workbook.worksheets():
        sheet.update.assert_not_called()


def test_restore_initialization_resumes_supported_partial_blank_target():
    workbook = FakeWorkbook({"Accounts": WORKSHEET_HEADERS["Accounts"], "Mileage": ()})
    initialize_blank_ledger_sheets(workbook)
    assert set(workbook.sheets) == set(WORKSHEET_HEADERS)
    assert all(
        sheet.rows == [list(WORKSHEET_HEADERS[title])]
        for title, sheet in workbook.sheets.items()
    )


@pytest.mark.parametrize("title", ["Accounts", "Transactions", "JournalPostings"])
def test_archive_extra_headers_fail_before_restore_writes(current_backup, title):
    backup = rewrite_backup_tables(
        current_backup, {title: lambda rows: rows[0].append("future_field")}
    )
    target = GoogleSheetsStorage(FakeWorkbook())
    target._append_many = Mock()
    with pytest.raises(StorageValidationError, match="unsupported headers"):
        target.restore_backup_zip(backup)
    target._append_many.assert_not_called()


@pytest.mark.parametrize("field", ["row_counts", "worksheet_headers", "sha256"])
def test_archive_metadata_maps_cannot_claim_extra_tables(current_backup, field):
    backup = rewrite_manifest(
        current_backup, lambda manifest: manifest[field].update(Unknown=0)
    )
    with pytest.raises(StorageValidationError, match="entries are invalid"):
        GoogleSheetsStorage.validate_backup_zip(backup)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backup_time", None),
        ("backup_time", "not-a-date"),
        ("backup_time", "2026-01-01T00:00:00"),
        ("backup_time", "2026-01-01T00:00:00-04:00"),
        ("workbook_title", None),
        ("workbook_title", ""),
    ],
)
def test_required_archive_identity_metadata_is_validated_before_writes(
    current_backup, field, value
):
    backup = rewrite_manifest(
        current_backup, lambda manifest: manifest.update({field: value})
    )
    target = GoogleSheetsStorage(FakeWorkbook())
    target._append_many = Mock()
    with pytest.raises(
        StorageValidationError, match="Backup time|Backup workbook title"
    ):
        target.restore_backup_zip(backup)
    target._append_many.assert_not_called()


def test_archive_row_counts_require_integers(current_backup):
    backup = rewrite_manifest(
        current_backup, lambda manifest: manifest["row_counts"].update(Accounts=1.0)
    )
    with pytest.raises(StorageValidationError, match="row count"):
        GoogleSheetsStorage.validate_backup_zip(backup)


def test_live_rows_with_unmapped_data_are_not_silently_truncated():
    workbook = FakeWorkbook()
    workbook.sheets["Accounts"].rows.append(
        ["account-1"] + [""] * 7 + ["unmapped history"]
    )
    with patch.object(
        GoogleSheetsStorage, "_open_workbook_from_secrets", return_value=workbook
    ):
        with pytest.raises(
            StorageValidationError, match="data outside the frozen format-13 headers"
        ):
            GoogleSheetsStorage.from_secrets({"spreadsheet_id": "north-sheet"})


def test_format13_reordered_columns_round_trip_history_and_opening_balances():
    headers = {
        title: tuple(reversed(fields)) for title, fields in WORKSHEET_HEADERS.items()
    }
    source = GoogleSheetsStorage(FakeWorkbook(headers))
    account = fixture_account(source, "Checking", "Bank", opening_balance="123.45")
    category = fixture_category(source, "Sales", "Income")
    transaction = fixture_transaction(source,
        txn_date="2026-01-01",
        kind="Income",
        amount="9.87",
        account_id=account["id"],
        category_id=category["id"],
    )
    backup = source.export_backup_zip(
        build_receipt_manifest("north", [transaction], [])
    )
    assert validate_restore_backup(backup, "north")["format_version"] == 13
    target = GoogleSheetsStorage(FakeWorkbook())
    counts = target.restore_backup_zip(backup)
    assert counts["Transactions"] == 1
    assert target.list_accounts(active_only=False) == source.list_accounts(
        active_only=False
    )
    assert target.list_transactions() == source.list_transactions()


def test_selected_profile_rejection_does_not_fall_back_to_another_workbook():
    config = profile_config()
    north = FakeWorkbook({"Transactions": ("id", "payee")})
    south = FakeWorkbook()
    south_storage = GoogleSheetsStorage(south)
    south_account = fixture_account(south_storage, "South Checking", "Bank")
    workbooks = {"north-sheet": north, "south-sheet": south}
    before = deepcopy(
        {
            key: {title: sheet.rows for title, sheet in book.sheets.items()}
            for key, book in workbooks.items()
        }
    )
    with patch.object(
        GoogleSheetsStorage,
        "_open_workbook_from_secrets",
        side_effect=lambda secrets, **_: workbooks[secrets["spreadsheet_id"]],
    ) as open_workbook:
        with pytest.raises(StorageValidationError, match="format-13"):
            GoogleSheetsStorage.from_secrets(select_profile_secrets(config, "north"))
        storage = GoogleSheetsStorage.from_secrets_read_only(
            select_profile_secrets(config, "south")
        )
    assert storage.list_accounts(active_only=False)[0]["id"] == south_account["id"]
    assert [
        call.args[0]["spreadsheet_id"] for call in open_workbook.call_args_list
    ] == ["north-sheet", "south-sheet"]
    assert [
        call.args[0]["google_drive"]["authorized_email"]
        for call in open_workbook.call_args_list
    ] == ["north@example.test", "south@example.test"]
    assert before == {
        key: {title: sheet.rows for title, sheet in book.sheets.items()}
        for key, book in workbooks.items()
    }


@pytest.mark.parametrize("problem", ["retired", "other-profile"])
def test_restore_cli_rejects_archive_before_opening_or_initializing_target(
    current_backup, tmp_path: Path, problem
):
    backup = current_backup
    if problem == "retired":
        backup = rewrite_manifest(
            backup, lambda manifest: manifest.update(format_version=12)
        )
    path = tmp_path / "backup.zip"
    path.write_bytes(backup)
    with (
        patch(
            "sys.argv",
            [
                "restore_google_sheets_backup.py",
                str(path),
                "--profile",
                "south",
                "--target-spreadsheet-id",
                "new-sheet",
                "--initialize",
            ],
        ),
        patch.object(
            restore_script,
            "load_business_profile_document",
            return_value=profile_config(),
        ),
        patch.object(
            GoogleSheetsStorage, "_open_workbook_from_secrets"
        ) as open_workbook,
        patch.object(restore_script, "initialize_blank_ledger_sheets") as initialize,
        pytest.raises(
            SystemExit,
            match="Only backup format 13"
            if problem == "retired"
            else "different business profile",
        ),
    ):
        restore_script.main()
    open_workbook.assert_not_called()
    initialize.assert_not_called()
