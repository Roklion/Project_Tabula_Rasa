"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from typing import Any
from tabula_rasa.receipt_manifest import ReceiptManifestError
from tabula_rasa.receipt_manifest import validate_receipt_manifest
from .schema import (
    BACKUP_FORMAT_VERSION,
    WORKSHEET_HEADERS,
)
from .errors import (
    StorageConflictError,
    StorageUnavailableError,
    StorageValidationError,
)
from .validation import (
    _as_bool,
    _clean_text,
    _encode_tag_ids,
    _normalize_tag_ids,
    _parse_backup_zip,
    _utc_now,
    _validate_hierarchy_records,
    _validate_mixed_use_tables,
    _validate_tag_records,
)
from tabula_rasa.mixed_use import validate_mixed_use_allocation

class BackupMixin:
    """Mixin for the backup storage boundary."""

    def export_backup_zip(self, receipt_manifest: Mapping[str, Any]) -> bytes:
        """Return a fresh, checksummed backup of every ledger worksheet."""
        generated_at = _utc_now()
        row_counts: dict[str, int] = {}
        worksheet_headers: dict[str, list[str]] = {}
        csv_files: dict[str, bytes] = {}
        archive_buffer = io.BytesIO()
        snapshot = self._snapshot(WORKSHEET_HEADERS, force_refresh=True)
        _validate_mixed_use_tables(
            {
                title: (WORKSHEET_HEADERS[title], [dict(row.values) for row in rows])
                for title, rows in snapshot.items()
            }
        )
        self._validate_recurring_references()
        self.list_assets(_force_refresh=True)
        accounts = self._account_lookup(force_refresh=True)
        categories = self._category_lookup(force_refresh=True)
        from .depreciation_posting import validate_depreciation_history
        validate_depreciation_history(
            [row.values for row in snapshot["Assets"]],
            [row.values for row in snapshot["Transactions"]], accounts, categories,
        )
        payees = self._payee_lookup(force_refresh=True)
        for row in snapshot["MixedUseExpenses"]:
            self._validate_mixed_use_references(
                row.values,
                accounts=accounts,
                categories=categories,
                payees=payees,
            )
        _validate_hierarchy_records(
            [row.values for row in snapshot["Accounts"]],
            compatibility_field="classification",
            item_label="Account",
        )
        _validate_hierarchy_records(
            [row.values for row in snapshot["Categories"]],
            compatibility_field="kind",
            item_label="Category",
        )
        tag_records = [dict(row.values) for row in snapshot["Tags"]]
        for tag in tag_records:
            tag["id"] = _clean_text(tag.get("id"), "Tag ID", required=True)
            tag["name"] = _clean_text(tag.get("name"), "Tag name", required=True)
            tag["active"] = (
                "TRUE" if _as_bool(tag.get("active"), "Tag active") else "FALSE"
            )
        _validate_tag_records(tag_records)
        known_tag_ids = {tag["id"] for tag in tag_records}
        for title in WORKSHEET_HEADERS:
            headers = self._headers(title)
            rows = snapshot[title]
            row_counts[title] = len(rows)
            worksheet_headers[title] = headers
            csv_buffer = io.StringIO(newline="")
            writer = csv.writer(csv_buffer, lineterminator="\n")
            writer.writerow(headers)
            for row in rows:
                values = dict(row.values)
                if title in {"Transactions", "Mileage", "MixedUseExpenses", "Assets"}:
                    normalized_tag_ids = _normalize_tag_ids(values.get("tag_ids", ""))
                    if any(tag_id not in known_tag_ids for tag_id in normalized_tag_ids):
                        item_label = {
                            "Transactions": "transaction",
                            "Mileage": "mileage",
                            "MixedUseExpenses": "mixed-use source",
                            "Assets": "asset",
                        }[title]
                        raise StorageValidationError(
                            "Backup contains an unknown "
                            f"{item_label} tag"
                        )
                    values["tag_ids"] = _encode_tag_ids(normalized_tag_ids)
                elif title == "Tags":
                    record_id = _clean_text(values.get("id"), "Tag ID", required=True)
                    tag = next(item for item in tag_records if item["id"] == record_id)
                    values = tag
                elif title == "RecurringSchedules":
                    values = {**values, **self._decode_schedule(values)}
                    if values.get("source_kind") == "mixed_use":
                        allocation = validate_mixed_use_allocation(
                            values.get("total_expense"),
                            values.get("business_use_percentage"),
                        )
                        values["amount"] = allocation.allocated_amount
                        values["total_expense"] = allocation.total_expense
                        values["business_use_percentage"] = (
                            allocation.business_use_percentage
                        )
                    for field in ("account_id", "category_id", "payee_id"):
                        values[field] = str(values.get(field, "") or "").strip()
                writer.writerow([values.get(header, "") for header in headers])
            csv_files[f"{title}.csv"] = csv_buffer.getvalue().encode("utf-8")

        try:
            validated_receipts = validate_receipt_manifest(
                receipt_manifest,
                transaction_ids={
                    row.values["id"] for row in snapshot["Transactions"]
                },
            )
        except ReceiptManifestError as exc:
            raise StorageValidationError(str(exc)) from exc
        receipts_bytes = (
            json.dumps(validated_receipts, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")

        manifest = {
            "backup_time": generated_at,
            "format_version": BACKUP_FORMAT_VERSION,
            "row_counts": row_counts,
            "sha256": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in {
                    **csv_files,
                    "receipts.json": receipts_bytes,
                }.items()
            },
            "workbook_title": self.workbook_title,
            "worksheet_headers": worksheet_headers,
        }
        with zipfile.ZipFile(
            archive_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, content in csv_files.items():
                archive.writestr(name, content)
            archive.writestr("receipts.json", receipts_bytes)
            archive.writestr(
                "manifest.json",
                (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                ),
            )
        return archive_buffer.getvalue()

    @staticmethod
    def validate_backup_zip(backup: bytes) -> dict[str, Any]:
        """Return a validated manifest or raise a safe validation error."""
        manifest, _, receipt_manifest = _parse_backup_zip(backup)
        result = dict(manifest)
        result["receipt_inventory"] = receipt_manifest is not None
        if receipt_manifest is not None:
            result["receipt_count"] = len(receipt_manifest["receipts"])
            result["business_profile_key"] = receipt_manifest[
                "business_profile_key"
            ]
        return result

    @staticmethod
    def receipt_manifest_from_backup(backup: bytes) -> dict[str, Any] | None:
        """Return a validated receipt inventory, or None for ledger-only backups."""
        _, _, receipt_manifest = _parse_backup_zip(backup)
        return receipt_manifest

    def restore_backup_zip(self, backup: bytes) -> dict[str, int]:
        """Restore a validated backup into a blank initialized workbook."""
        manifest, tables, _ = _parse_backup_zip(backup)
        for title in WORKSHEET_HEADERS:
            target_headers = self._headers(title)
            if set(target_headers) != set(tables[title][0]):
                raise StorageValidationError(
                    f"{title} target headers do not match the backup"
                )
            if self._rows(title, force_refresh=True):
                raise StorageConflictError(
                    "Restore target must have empty ledger worksheets"
                )

        counts: dict[str, int] = {}
        for title in WORKSHEET_HEADERS:
            if title not in tables:
                continue
            _, records = tables[title]
            if title == "MixedUseExpenses" and not records:
                continue
            self._append_many(title, records)
            restored = self._rows(title, force_refresh=True)
            expected_by_id = {record["id"]: record for record in records}
            actual_by_id = {row.values.get("id", ""): row.values for row in restored}
            headers = tables[title][0]
            if len(restored) != len(records) or any(
                [actual_by_id.get(record_id, {}).get(header, "") for header in headers]
                != [record.get(header, "") for header in headers]
                for record_id, record in expected_by_id.items()
            ):
                raise StorageUnavailableError(
                    "Restore verification failed; the target may contain partial data"
                )
            counts[title] = len(records)
        return counts

__all__ = ["BackupMixin"]
