# Import from QuickBooks

Project Tabula Rasa supports:

- QuickBooks Online **Transaction Detail by Account** CSV exports;
- QuickBooks Self-Employed **General ledger** XLSX or ZIP exports; and
- QuickBooks Online **Download Trips** mileage CSV exports.

Every import is previewed and validated before any ledger rows are written.

## Transaction Detail by Account CSV

In QuickBooks Online:

1. Open **Reports > Transaction Detail by Account**.
2. Choose the intended date range.
3. Export the report to CSV.
4. Remove report title, subtotal, and footer rows.
5. Confirm the first CSV row contains the headers.
6. Upload the file under **Data & backup > Import QuickBooks transactions**.

Keep this uploader separate from the Tabula Rasa CSV and QuickBooks mileage
uploaders. Review conversion diagnostics, duplicate summaries, validation
results, and proposed auto-created references before selecting **Import
validated rows**; previewing never writes to the workbook.

The importer supports these English-language column names:

```text
Date
Transaction Type
Num
Name
Memo/Description
Account
Split
Amount
```

## QuickBooks Self-Employed General ledger

In QuickBooks Self-Employed:

1. Open **Settings > Export data**.
2. Enable **General ledger**.
3. Select **Export to Excel**.
4. Upload either the exported ZIP or its `General_ledger.xlsx` file directly.

The importer pairs debit and credit entries so each accounting event becomes
one Project Tabula Rasa transaction. A separate chart-of-accounts export is not
required.

## Transaction field mapping

Account and category names must already exist in Project Tabula Rasa unless automatic
creation is enabled. Matching is case-insensitive.

| QuickBooks field | Project Tabula Rasa field or behavior |
| --- | --- |
| `Account` | Source ledger account |
| `Split` on income or expense | Category |
| `Split` on transfer | Destination account |
| Positive `Amount` | Income |
| Negative or parenthesized `Amount` | Expense |
| `Name` | Payee |
| `Memo/Description` | Description |
| `Num` | Reference |

Rows with transaction type `Transfer` or `Funds Transfer` use `Split` as the
destination account and leave category blank.

## Preview, validation, and duplicates

The upload screen validates every row and reports:

- income;
- expenses;
- transfers;
- duplicates; and
- actionable row errors.

A transaction is considered a duplicate when it has the same:

- date;
- type;
- amount;
- source and destination accounts;
- category;
- payee;
- description; and
- reference

as an existing transaction or an earlier row in the same upload.

Duplicates are skipped. Fix every reported row error and preview again before
committing. All validated rows are written in one batch.

## Automatically create missing references

Optionally enable **Automatically create missing accounts and categories** in
the preview. Review every proposed addition before importing.

Imported accounts:

- use a zero opening balance;
- infer classification and subtype from the name;
- recognize Bank, Cash, Credit card, Short-term debt, and common equity-style
  names; and
- use the flexible Other subtype classified as Asset when no stronger inference
  is available.

Imported categories infer their kind from transaction amount:

- positive amounts create Income categories; and
- negative amounts create Expense categories.

Existing account and category names are matched case-insensitively.
Matching uses the stored item name rather than its displayed hierarchy path, so
existing Layer 2 accounts and categories are valid matches. Automatically
created accounts and categories are always created at Layer 1.

## Import QuickBooks mileage

In QuickBooks Online:

1. Open **Expenses & Bills > Mileage**.
2. Open the dropdown next to **Add trip**.
3. Choose **Download Trips**.
4. Upload the CSV under **Data & backup > Import QuickBooks mileage**.

This uploader has its own staged file and preview state. Review the ready,
duplicate, personal, and unreviewed counts before selecting **Import validated
mileage**; only valid unique Business trips are written.

The export may contain:

- trip date;
- classification;
- purpose;
- vehicle;
- start address;
- end address; and
- distance.

Only rows classified as `Business` are imported. `Personal` and `Unreviewed`
rows are counted separately and skipped.

Every business row must have:

- a date;
- trip purpose;
- start address;
- end address; and
- positive distance.

Common QuickBooks header variants are recognized. Distance columns explicitly
labeled in kilometers are converted to miles.

## Mileage preview and duplicates

The mileage preview reports:

- ready;
- duplicate;
- personal; and
- unreviewed rows.

A mileage row is considered a duplicate when it has the same:

- date;
- distance;
- vehicle;
- start address;
- end address; and
- business purpose

as an existing trip or an earlier row in the upload.

Fix every reported business-row error before committing. Valid unique business
trips are written to the `Mileage` worksheet in one batch.

## Safety notes

- Previewing never writes ledger rows.
- Imports are scoped to the currently selected business profile.
- Referenced accounts and categories are validated again before the batch write.
- Duplicate detection includes existing rows and earlier uploaded rows.
- Keep source exports outside the repository because they may contain private
  financial and location data.

## Implementation map

| Responsibility | Implementation |
| --- | --- |
| Transaction CSV/XLSX normalization | [`tabula_rasa/quickbooks_import.py`](../../tabula_rasa/quickbooks_import.py) |
| Mileage CSV normalization | [`tabula_rasa/quickbooks_mileage_import.py`](../../tabula_rasa/quickbooks_mileage_import.py) |
| Import validation and batch persistence | [`tabula_rasa/storage/google_sheets.py`](../../tabula_rasa/storage/google_sheets.py) |
| Upload and preview UI | [`tabula_rasa/page_renderers/data_backup/imports.py`](../../tabula_rasa/page_renderers/data_backup/imports.py) |
