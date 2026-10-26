"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from .errors import StorageValidationError
from .validation import _clean_text
from .base import _StoredRow

class _ManagedMixin:
    """_ManagedMixin boundary for the Google Sheets facade."""


    @staticmethod
    def _managed_rows_by_id(
        rows: Iterable[_StoredRow], title: str
    ) -> dict[str, _StoredRow]:
        result: dict[str, _StoredRow] = {}
        for row in rows:
            record_id = _clean_text(row.values.get("id"), f"{title} ID", required=True)
            if record_id in result:
                raise StorageValidationError(f"Duplicate ID detected in {title}")
            result[record_id] = row
        return result


    def _managed_update_request(
        self, title: str, row: _StoredRow, column: str, value: str
    ) -> dict[str, Any]:
        headers = self._headers(title)
        column_index = self._sheet_column_index(headers, column)
        return {
            "updateCells": {
                "range": {
                    "sheetId": self._sheet_id(title),
                    "startRowIndex": row.row_number - 1,
                    "endRowIndex": row.row_number,
                    "startColumnIndex": column_index,
                    "endColumnIndex": column_index + 1,
                },
                "rows": [{"values": [{"userEnteredValue": {"stringValue": value}}]}],
                "fields": "userEnteredValue",
            }
        }


__all__ = ['_ManagedMixin']
