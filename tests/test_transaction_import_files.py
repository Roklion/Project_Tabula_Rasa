"""Source preparation keeps precision, conversion diagnostics and safe bounds."""

import csv
import io
import zipfile

from openpyxl import Workbook
import pytest

from tabula_rasa.application.import_files import (
    CSV_REQUIRED_COLUMNS, MAX_IMPORT_ROWS, prepare_csv_import, prepare_quickbooks_import, read_csv_upload,
)
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.quickbooks_import import GENERAL_LEDGER_COLUMNS


def csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def general_ledger_bytes(*, broken=False):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "General Ledger"
    sheet.append(list(GENERAL_LEDGER_COLUMNS))
    sheet.append(["10/05/2026", "Expense", "INV-1", "Vendor", "Supplies", "cash", "", "12.50", ""])
    if not broken:
        sheet.append(["10/05/2026", "Expense", "INV-1", "Vendor", "Supplies", "office", "12.50", "", ""])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def test_csv_preparation_retains_decimal_and_reference_text_without_domain_preview():
    content = csv_bytes([dict(Date="2026-10-05", Type="Expense", Amount="12.50000001", Account="cash", Category="office", Reference="0001")])
    prepared = prepare_csv_import(content)
    assert prepared.rows[0]["Amount"] == "12.50000001"
    assert prepared.rows[0]["Reference"] == "0001"
    assert prepared.conversion_errors == []
    # Header-only imports still check all required fields.
    assert read_csv_upload(b"Date,Type,Amount,Account,Category\n", required_columns=CSV_REQUIRED_COLUMNS) == []


@pytest.mark.parametrize("content", [b"Date,Type\n", b"Date,Date\n", b"\xff\xfe", b"Date\n\"broken", b"Date\nvalue,extra"])
def test_malformed_csv_and_missing_headers_fail_with_safe_guidance(content):
    with pytest.raises(StorageValidationError) as raised:
        read_csv_upload(content, required_columns=CSV_REQUIRED_COLUMNS)
    assert "broken" not in str(raised.value) and "extra" not in str(raised.value)


def test_csv_source_batches_are_bounded_without_silent_prefix_import():
    with pytest.raises(StorageValidationError, match="1,000"):
        read_csv_upload(b"Date\n" + b"2026-10-05\n" * (MAX_IMPORT_ROWS + 1))


def test_supported_xlsx_and_zip_use_existing_general_ledger_conversion():
    workbook = general_ledger_bytes()
    prepared = prepare_quickbooks_import("General_ledger.xlsx", workbook)
    assert prepared.conversion_errors == []
    assert prepared.rows == [{"Date": "2026-10-05", "Transaction Type": "Expense", "Num": "INV-1", "Name": "Vendor",
                             "Memo/Description": "Supplies", "Account": "cash", "Split": "office", "Amount": "-12.50"}]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("export/General_ledger.xlsx", workbook)
        archive.writestr("__MACOSX/General_ledger.xlsx", b"ignored")
    assert prepare_quickbooks_import("export.zip", output.getvalue()) == prepared
    broken = prepare_quickbooks_import("General_ledger.xlsx", general_ledger_bytes(broken=True))
    assert broken.rows == []
    assert "General Ledger row(s) 2" in broken.conversion_errors[0]


def test_unsupported_or_ambiguous_workbooks_fail_without_raw_provider_errors():
    with pytest.raises(StorageValidationError, match="file integrity"):
        prepare_quickbooks_import("private-file.xlsx", b"private-file-content")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("one.xlsx", b"private-one")
        archive.writestr("two.xlsx", b"private-two")
    with pytest.raises(StorageValidationError, match="exactly one"):
        prepare_quickbooks_import("export.zip", output.getvalue())
