"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Callable
from .errors import StorageConflictError
from .errors import StorageValidationError
from .validation import _clean_text
from .validation import _managed_comparison_text
from .base import _StoredRow

class _ManagedMixin:
    """_ManagedMixin boundary for the Google Sheets facade."""

    @staticmethod
    def _expected_managed_records(
        expected: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
    ) -> dict[str, Mapping[str, Any]]:
        """Normalize an optional caller snapshot used by management actions."""
        if expected is None:
            return {}
        if isinstance(expected, Mapping) and "id" in expected:
            values = [(expected.get("id"), expected)]
        elif isinstance(expected, Mapping):
            values = expected.items()
        else:
            values = ((None, item) for item in expected)
        result: dict[str, Mapping[str, Any]] = {}
        for mapping_id, item in values:
            record_id = _clean_text(
                item.get("id", mapping_id), "Managed record ID", required=True
            )
            result[record_id] = item
        return result

    @staticmethod
    def _assert_expected_managed_records(
        current: Mapping[str, Mapping[str, str]],
        expected: Iterable[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None,
    ) -> None:
        for record_id, expected_record in _ManagedMixin._expected_managed_records(
            expected
        ).items():
            actual = current.get(record_id)
            if actual is None or any(
                _managed_comparison_text(actual.get(key))
                != _managed_comparison_text(value)
                for key, value in expected_record.items()
                if key != "tags"
            ):
                raise StorageConflictError(
                    "A payee or tag changed; refresh the management list and try again."
                )

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

    def _managed_write(
        self,
        *,
        operation: str,
        requests: Sequence[Mapping[str, Any]],
        read_state: Callable[[], Any],
        applied: Callable[[Any], bool],
        unchanged: Callable[[Any], bool],
        before_retry: Callable[[], None] | None = None,
        invalidate: Iterable[str],
    ) -> None:
        """Write one managed batch with one fresh readback and safe retry."""

        def state() -> str:
            current = read_state()
            if applied(current):
                return "applied"
            if unchanged(current):
                return "unchanged"
            return "ambiguous"

        self._write_with_uncertain_readback(
            operation,
            lambda: self._batch_update_spreadsheet(requests),
            state,
            before_retry=before_retry,
            invalidate=invalidate,
        )

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

    def _managed_delete_request(self, title: str, row: _StoredRow) -> dict[str, Any]:
        return {
            "deleteDimension": {
                "range": {
                    "sheetId": self._sheet_id(title),
                    "dimension": "ROWS",
                    "startIndex": row.row_number - 1,
                    "endIndex": row.row_number,
                }
            }
        }

__all__ = ['_ManagedMixin']
