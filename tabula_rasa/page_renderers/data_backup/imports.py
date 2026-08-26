"""CSV and QuickBooks import workflows for the Data & backup page."""

from __future__ import annotations

import io
import zipfile

import pandas as pd
import streamlit as st

from tabula_rasa.page_renderers.data_backup.context import DataBackupContext
from tabula_rasa.quickbooks_import import (
    REQUIRED_COLUMNS as QUICKBOOKS_REQUIRED_COLUMNS,
    general_ledger_rows,
)
from tabula_rasa.quickbooks_mileage_import import (
    missing_required_columns as missing_quickbooks_mileage_columns,
)
from tabula_rasa.storage import StorageValidationError


def alert_list(title: str, messages: list[str]) -> str:
    """Format multiple alert messages as a readable Markdown list."""
    return f"**{title}**\n\n- " + "\n- ".join(messages)


def render_imports(context: DataBackupContext) -> None:
    """Render the three profile-scoped import workflows."""
    st.subheader("Imports")
    with st.expander("Import Project Tabula Rasa CSV"):
        st.write(
            "Upload a CSV with: Date, Type, Amount, Account, Category, Payee, "
            "Description, Reference. Type must be Income or Expense."
        )
        plain_upload = st.file_uploader(
            "CSV file",
            type="csv",
            key=f"transaction_csv_upload_{context.profile_key}",
        )
        if plain_upload:
            try:
                plain_incoming = pd.read_csv(plain_upload).where(
                    lambda frame: frame.notna(), ""
                )
                plain_required = {"Date", "Type", "Amount", "Account", "Category"}
                plain_missing = plain_required - set(plain_incoming.columns)
                if plain_missing:
                    st.error(f"Missing columns: {', '.join(sorted(plain_missing))}")
                else:
                    st.dataframe(plain_incoming.head(20), hide_index=True, width="stretch")
                    if st.button("Import rows", type="primary"):
                        plain_records = plain_incoming.to_dict(orient="records")
                        with st.spinner("Importing Tabula Rasa transactions..."):
                            context.confirmed_write(
                                "import_csv_transactions",
                                {"rows": plain_records},
                                lambda: context.storage.import_csv_transactions(
                                    plain_records
                                ),
                                lambda imported: f"Imported {len(imported)} transactions.",
                            )
            except StorageValidationError as error:
                context.report_storage_error(error)
            except (ValueError, pd.errors.ParserError, UnicodeError):
                st.error("Could not read this CSV file. Check its format and encoding.")
    st.subheader("Import QuickBooks transactions")
    st.write(
        "Upload a QuickBooks Online **Transaction Detail by Account** CSV, "
        "or a QuickBooks Self-Employed **General ledger** XLSX or ZIP export. "
        "Review the validation results and summary before committing."
    )
    upload = st.file_uploader(
        "QuickBooks export",
        type=["csv", "xlsx", "zip"],
        key=f"quickbooks_transaction_upload_{context.profile_key}",
    )
    if upload:
        try:
            upload_bytes = upload.getvalue()
            upload_name = upload.name.casefold()
            conversion_errors: list[str] = []
            if upload_name.endswith(".csv"):
                incoming = pd.read_csv(io.BytesIO(upload_bytes)).where(
                    lambda frame: frame.notna(), ""
                )
            else:
                if upload_name.endswith(".zip"):
                    with zipfile.ZipFile(io.BytesIO(upload_bytes)) as archive:
                        workbooks = [
                            name
                            for name in archive.namelist()
                            if name.casefold().endswith(".xlsx")
                            and not name.startswith("__MACOSX/")
                        ]
                        if len(workbooks) != 1:
                            raise ValueError(
                                "The ZIP must contain exactly one QuickBooks .xlsx workbook"
                            )
                        if archive.getinfo(workbooks[0]).file_size > 25 * 1024 * 1024:
                            raise ValueError(
                                "The QuickBooks workbook is larger than 25 MB"
                            )
                        workbook_bytes = archive.read(workbooks[0])
                else:
                    workbook_bytes = upload_bytes
                ledger = pd.read_excel(
                    io.BytesIO(workbook_bytes),
                    sheet_name="General Ledger",
                    header=None,
                ).where(lambda frame: frame.notna(), "")
                records, conversion_errors = general_ledger_rows(ledger.values.tolist())
                incoming = pd.DataFrame(
                    records,
                    columns=sorted(QUICKBOOKS_REQUIRED_COLUMNS),
                )
            missing = QUICKBOOKS_REQUIRED_COLUMNS - set(incoming.columns)
            if missing:
                st.error(f"Missing columns: {', '.join(sorted(missing))}")
            else:
                records = incoming.to_dict(orient="records")
                auto_create = st.checkbox(
                    "Automatically create missing accounts and categories",
                    help="New accounts use an inferred type and zero opening balance. Category type is inferred from the amount.",
                )
                preview = context.storage.preview_quickbooks_transactions(
                    records,
                    auto_create=auto_create,
                )
                summary = preview["summary"]
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Ready", summary["ready"])
                c2.metric("Duplicates", summary["duplicates"])
                c3.metric("Income", summary["Income"])
                c4.metric("Expenses", summary["Expense"])
                c5.metric("Transfers", summary["Transfer"])
                if preview["errors"]:
                    st.error(
                        alert_list(
                            "Fix these import errors before continuing:",
                            preview["errors"],
                        )
                    )
                if conversion_errors:
                    st.error(
                        alert_list(
                            "Some QuickBooks rows could not be converted:",
                            conversion_errors,
                        )
                    )
                if auto_create and (preview["new_accounts"] or preview["new_categories"]):
                    additions = [
                        (
                            f"Account name: {name} — Classification: "
                            f"{preview['new_account_classifications'][name]} — "
                            f"Type: {preview['new_account_types'][name]}"
                        )
                        for name in preview["new_accounts"]
                    ]
                    additions += [
                        f"{kind} category: {name}"
                        for name, kind in preview["new_categories"]
                    ]
                    st.info("Will create:\n\n- " + "\n- ".join(additions))
                if preview["duplicate_rows"]:
                    st.warning(
                        "Already imported or repeated rows will be skipped: "
                        + ", ".join(map(str, preview["duplicate_rows"]))
                    )
                st.dataframe(incoming.head(50), hide_index=True, width="stretch")
                if st.button(
                    "Import validated rows",
                    type="primary",
                    disabled=bool(preview["errors"] or conversion_errors)
                    or not summary["ready"],
                ):
                    with st.spinner("Importing validated QuickBooks transactions..."):
                        context.confirmed_write(
                            "import_quickbooks_transactions",
                            {"rows": records, "auto_create": auto_create},
                            lambda: context.storage.import_quickbooks_transactions(
                                records,
                                auto_create=auto_create,
                            ),
                            lambda imported: f"Imported {len(imported)} transactions.",
                        )
        except StorageValidationError as error:
            context.report_storage_error(error)
        except ValueError as error:
            st.error(str(error))
        except (
            KeyError,
            zipfile.BadZipFile,
            pd.errors.ParserError,
            UnicodeError,
        ):
            st.error("Could not read this QuickBooks export. Check its format and file integrity.")
    st.subheader("Import QuickBooks mileage")
    st.write(
        "In QuickBooks Online, open **Expenses & Bills > Mileage**, use the "
        "dropdown next to **Add trip**, and select **Download Trips**. Upload "
        "that CSV here. Business trips are imported; Personal and Unreviewed "
        "trips are skipped."
    )
    mileage_upload = st.file_uploader(
        "QuickBooks mileage CSV",
        type="csv",
        key=f"quickbooks_mileage_upload_{context.profile_key}",
    )
    if mileage_upload:
        try:
            mileage_incoming = pd.read_csv(mileage_upload).where(
                lambda frame: frame.notna(), ""
            )
            mileage_missing = missing_quickbooks_mileage_columns(
                mileage_incoming.columns
            )
            if mileage_missing:
                st.error(
                    "Missing QuickBooks mileage columns: "
                    + ", ".join(mileage_missing)
                )
            else:
                mileage_records = mileage_incoming.to_dict(orient="records")
                mileage_preview = context.storage.preview_quickbooks_mileage(
                    mileage_records
                )
                mileage_summary = mileage_preview["summary"]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Mileage ready", mileage_summary["ready"])
                c2.metric("Mileage duplicates", mileage_summary["duplicates"])
                c3.metric(
                    "Personal skipped",
                    mileage_summary["personal_skipped"],
                )
                c4.metric(
                    "Unreviewed skipped",
                    mileage_summary["unreviewed_skipped"],
                )
                if mileage_preview["errors"]:
                    st.error(
                        alert_list(
                            "Fix these mileage import errors before continuing:",
                            mileage_preview["errors"],
                        )
                    )
                if mileage_preview["duplicate_rows"]:
                    st.warning(
                        "Already imported or repeated mileage rows will be skipped: "
                        + ", ".join(map(str, mileage_preview["duplicate_rows"]))
                    )
                if mileage_preview["personal_rows"]:
                    st.info(
                        "Personal mileage rows will be skipped: "
                        + ", ".join(map(str, mileage_preview["personal_rows"]))
                    )
                if mileage_preview["unreviewed_rows"]:
                    st.info(
                        "Unreviewed mileage rows will be skipped: "
                        + ", ".join(map(str, mileage_preview["unreviewed_rows"]))
                    )
                st.dataframe(
                    mileage_incoming.head(50),
                    hide_index=True,
                    width="stretch",
                )
                if st.button(
                    "Import validated mileage",
                    type="primary",
                    disabled=bool(mileage_preview["errors"])
                    or not mileage_summary["ready"],
                ):
                    with st.spinner("Importing validated QuickBooks mileage..."):
                        context.confirmed_write(
                            "import_quickbooks_mileage",
                            {"rows": mileage_records},
                            lambda: context.storage.import_quickbooks_mileage(
                                mileage_records
                            ),
                            lambda imported: f"Imported {len(imported)} mileage trips.",
                        )
        except StorageValidationError as error:
            context.report_storage_error(error)
        except (ValueError, pd.errors.ParserError, UnicodeError):
            st.error(
                "Could not read this QuickBooks mileage CSV. "
                "Check its format and encoding."
            )
