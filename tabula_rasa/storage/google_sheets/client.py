"""Google Sheets connection, cache, and bounded mutation primitives."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Callable
from uuid import uuid4
import gspread
from google.auth.exceptions import GoogleAuthError
from google.oauth2.service_account import Credentials
from tabula_rasa.quickbooks_import import suggested_account_classification
from .schema import (
    DEFAULT_ACCOUNTS,
    DEFAULT_CATEGORIES,
    SHEETS_READONLY_SCOPE,
    SHEETS_SCOPE,
    WORKSHEET_HEADERS,
)
from .errors import (
    StorageAuthenticationError,
    StorageConflictError,
    StorageError,
    StorageInitializationError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    StorageWorkbookAccessError,
    _mutation_guidance,
)
from .validation import (
    _clean_text,
    _looks_like_historical_workbook,
    _looks_like_partial_blank_workbook,
    _utc_now,
    _validate_hierarchy_records,
)
from .base import (
    _StoredRow,
)
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from . import GoogleSheetsStorage

T = TypeVar("T")


class _GoogleSheetsStorageClient:
    """Shared API/session mechanics for the public storage facade."""

    def __init__(
        self,
        workbook: Any,
        *,
        cache_ttl_seconds: float = 10.0,
        retry_attempts: int = 4,
        retry_base_delay_seconds: float = 0.25,
        sleeper: Callable[[float], None] = time.sleep,
        _allow_legacy_hierarchy_headers: bool = False,
        _initial_worksheets: Mapping[str, Any] | None = None,
        _initial_values: Mapping[str, list[list[Any]]] | None = None,
    ):
        self._workbook = workbook
        self._cache_ttl_seconds = cache_ttl_seconds
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleeper = sleeper
        self._allow_legacy_hierarchy_headers = (
            _allow_legacy_hierarchy_headers
        )
        self._worksheet_cache = dict(_initial_worksheets or {})
        self._header_cache: dict[str, list[str]] = {}
        self._row_cache: dict[str, tuple[float, list[_StoredRow]]] = {}
        self._cache_lock = threading.RLock()
        if _initial_values is None:
            self.validate_headers()
        else:
            missing = sorted(set(WORKSHEET_HEADERS) - set(_initial_values))
            if missing:
                raise StorageValidationError(
                    "Workbook is missing worksheets: " + ", ".join(missing)
                )
            for title in WORKSHEET_HEADERS:
                self._cache_values(title, _initial_values[title])

    @staticmethod
    def _open_workbook_from_secrets(
        secrets: Mapping[str, Any],
        *,
        scopes: Sequence[str],
    ) -> Any:
        """Open a configured workbook without changing its contents."""
        try:
            credential_info = dict(secrets["gcp_service_account"])
            spreadsheet_id = str(secrets["spreadsheet_id"]).strip()
            if not spreadsheet_id:
                raise ValueError("spreadsheet_id is empty")
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageAuthenticationError(
                "Profile Google settings are incomplete or malformed"
            ) from exc

        try:
            credentials = Credentials.from_service_account_info(
                credential_info, scopes=list(scopes)
            )
            client = gspread.authorize(credentials)
        except (
            TypeError,
            ValueError,
            GoogleAuthError,
            gspread.GSpreadException,
            OSError,
        ) as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc

        try:
            workbook = client.open_by_key(spreadsheet_id)
        except GoogleAuthError as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc
        except (
            gspread.SpreadsheetNotFound,
            PermissionError,
        ) as exc:
            raise StorageWorkbookAccessError(
                "The spreadsheet could not be opened with this service account"
            ) from exc
        except (gspread.GSpreadException, OSError) as exc:
            raise StorageWorkbookAccessError(
                "Google Sheets could not open the configured spreadsheet"
            ) from exc

        return workbook

    @classmethod
    def from_secrets_read_only(
        cls,
        secrets: Mapping[str, Any],
    ) -> "GoogleSheetsStorage":
        """Create storage using only read access to the configured workbook."""
        workbook = cls._open_workbook_from_secrets(
            secrets,
            scopes=[SHEETS_READONLY_SCOPE],
        )
        try:
            return cls(workbook)
        except StorageValidationError:
            raise
        except StorageUnavailableError as exc:
            raise StorageInitializationError(
                "The workbook opened, but worksheet validation could not finish"
            ) from exc

    @classmethod
    def from_secrets(cls, secrets: Mapping[str, Any]) -> "GoogleSheetsStorage":
        """Open a workbook, bootstrapping only a genuinely blank workbook.

        Populated workbooks are intentionally validation-only. Historical
        schema conversion is performed by ``scripts/migrate_workbook.py`` so
        an ordinary application startup cannot mutate ledger data.
        """
        workbook = cls._open_workbook_from_secrets(
            secrets,
            scopes=[SHEETS_SCOPE],
        )
        try:
            worksheets = {
                worksheet.title: worksheet for worksheet in workbook.worksheets()
            }
            values = {
                title: worksheet.get_all_values()
                for title, worksheet in worksheets.items()
            }
            is_blank = not any(
                str(value).strip()
                for rows in values.values()
                for row in rows
                for value in row
            )
            if is_blank or _looks_like_partial_blank_workbook(values):
                for title, headers in WORKSHEET_HEADERS.items():
                    worksheet = worksheets.get(title)
                    if worksheet is None:
                        worksheet = workbook.add_worksheet(
                            title=title,
                            rows=1000,
                            cols=len(headers),
                        )
                        worksheets[title] = worksheet
                    worksheet.update([list(headers)], range_name="A1", raw=True)
                return cls(
                    workbook,
                    _initial_worksheets=worksheets,
                    _initial_values={
                        title: [list(headers)]
                        for title, headers in WORKSHEET_HEADERS.items()
                    },
                )

            try:
                return cls(
                    workbook,
                    _initial_worksheets=worksheets,
                    _initial_values=values,
                )
            except StorageValidationError as exc:
                if _looks_like_historical_workbook(values):
                    raise StorageInitializationError(
                        "This workbook uses an older Tabula Rasa schema. "
                        "Run `python scripts/migrate_workbook.py --profile "
                        "PROFILE_KEY` for the selected workbook, replacing "
                        "PROFILE_KEY with its business-profile key, then "
                        "restart the application."
                    ) from exc
                raise
        except GoogleAuthError as exc:
            raise StorageAuthenticationError(
                "Google rejected the uploaded service-account credential"
            ) from exc
        except (PermissionError, gspread.GSpreadException, OSError) as exc:
            raise StorageInitializationError(
                "The workbook opened, but worksheet validation could not finish"
            ) from exc

    @property
    def workbook_title(self) -> str:
        return str(self._workbook.title)

    def _api(self, operation: Callable[[], T], *, retry_safe: bool = True) -> T:
        attempts = self._retry_attempts if retry_safe else 1
        for attempt in range(attempts):
            try:
                return operation()
            except (GoogleAuthError, gspread.GSpreadException, OSError) as exc:
                response = getattr(exc, "response", None)
                status_code = getattr(response, "status_code", None)
                temporary = isinstance(exc, OSError) or status_code in {
                    408,
                    429,
                    500,
                    502,
                    503,
                    504,
                }
                if not temporary or attempt + 1 >= attempts:
                    raise StorageUnavailableError(
                        "Google Sheets is temporarily unavailable; no success was reported",
                        retryable=temporary,
                    ) from exc
                self._sleeper(self._retry_base_delay_seconds * (2**attempt))
        raise AssertionError("Retry loop exited unexpectedly")

    def _worksheet(self, title: str) -> Any:
        with self._cache_lock:
            worksheet = self._worksheet_cache.get(title)
        if worksheet is not None:
            return worksheet
        worksheet = self._api(lambda: self._workbook.worksheet(title))
        with self._cache_lock:
            self._worksheet_cache[title] = worksheet
        return worksheet

    def _headers(self, title: str) -> list[str]:
        with self._cache_lock:
            cached = self._header_cache.get(title)
        if cached is not None:
            return list(cached)
        headers = [
            str(value).strip()
            for value in self._api(lambda: self._worksheet(title).row_values(1))
        ]
        self._validate_header_values(title, headers)
        with self._cache_lock:
            self._header_cache[title] = headers
        return list(headers)

    def _validate_header_values(self, title: str, headers: list[str]) -> None:
        required = set(WORKSHEET_HEADERS[title])
        if (
            self._allow_legacy_hierarchy_headers
            and title in {"Accounts", "Categories"}
        ):
            required.discard("parent_id")
        if not headers:
            raise StorageValidationError(f"{title} header row is empty")
        if any(not header for header in headers):
            raise StorageValidationError(f"{title} has a blank header")
        if len(headers) != len(set(headers)):
            raise StorageValidationError(f"{title} has duplicate headers")
        missing = sorted(required - set(headers))
        if missing:
            raise StorageValidationError(
                f"{title} is missing headers: {', '.join(missing)}"
            )

    def validate_headers(self) -> None:
        """Validate required worksheets and headers without relying on positions."""
        try:
            worksheets = {
                worksheet.title: worksheet
                for worksheet in self._api(self._workbook.worksheets)
            }
        except AttributeError as exc:
            raise StorageValidationError("Invalid workbook object") from exc
        missing = sorted(set(WORKSHEET_HEADERS) - set(worksheets))
        if missing:
            raise StorageValidationError(
                "Workbook is missing worksheets: " + ", ".join(missing)
            )
        with self._cache_lock:
            self._worksheet_cache.update(worksheets)
        for title in WORKSHEET_HEADERS:
            self._headers(title)

    def ensure_defaults(self) -> dict[str, int]:
        """Seed default accounts/categories once for a blank workbook."""
        self._snapshot(["Accounts", "Categories"], force_refresh=True)
        existing_accounts = self.list_accounts(active_only=False)
        existing_categories = self.list_categories()
        if existing_accounts or existing_categories:
            _validate_hierarchy_records(
                existing_accounts,
                compatibility_field="classification",
                item_label="Account",
            )
            _validate_hierarchy_records(
                existing_categories,
                compatibility_field="kind",
                item_label="Category",
            )
            return {"accounts": 0, "categories": 0}

        account_names = {account["name"].casefold() for account in existing_accounts}
        timestamp = _utc_now()
        new_accounts = [
            {
                "id": str(uuid4()),
                "name": name,
                "type": account_type,
                "classification": suggested_account_classification(
                    name, account_type
                ),
                "opening_balance": "0.00",
                "active": "TRUE",
                "created_at": timestamp,
                "parent_id": "",
            }
            for name, account_type in DEFAULT_ACCOUNTS
            if name.casefold() not in account_names
        ]

        category_keys = {
            (category["name"].casefold(), category["kind"])
            for category in existing_categories
        }
        new_categories = [
            {"id": str(uuid4()), "name": name, "kind": kind, "parent_id": ""}
            for kind, names in DEFAULT_CATEGORIES.items()
            for name in names
            if (name.casefold(), kind) not in category_keys
        ]

        _validate_hierarchy_records(
            [*existing_accounts, *new_accounts],
            compatibility_field="classification",
            item_label="Account",
        )
        _validate_hierarchy_records(
            [*existing_categories, *new_categories],
            compatibility_field="kind",
            item_label="Category",
        )
        self._append_many("Accounts", new_accounts)
        self._append_many("Categories", new_categories)
        return {"accounts": len(new_accounts), "categories": len(new_categories)}

    def _cache_values(
        self,
        title: str,
        values: list[list[Any]],
    ) -> list[_StoredRow]:
        """Validate one worksheet response and populate its local caches."""
        if not values:
            raise StorageValidationError(f"{title} header row is empty")
        headers = [str(value).strip() for value in values[0]]
        self._validate_header_values(title, headers)
        rows: list[_StoredRow] = []
        for row_number, raw_row in enumerate(values[1:], start=2):
            padded = [str(value) for value in raw_row] + [""] * (
                len(headers) - len(raw_row)
            )
            record = dict(zip(headers, padded[: len(headers)]))
            if any(value.strip() for value in record.values()):
                rows.append(_StoredRow(row_number, record))
        with self._cache_lock:
            self._header_cache[title] = headers
            self._row_cache[title] = (time.monotonic(), rows)
        return list(rows)

    def _refresh_rows(self, titles: list[str]) -> None:
        """Refresh multiple worksheets with one values batch request when available."""
        if not titles:
            return
        batch_get = getattr(self._workbook, "values_batch_get", None)
        if callable(batch_get) and len(titles) > 1:
            ranges = ["'{}'".format(title.replace("'", "''")) for title in titles]
            response = self._api(lambda: batch_get(ranges))
            value_ranges = response.get("valueRanges", [])
            if not isinstance(value_ranges, list) or len(value_ranges) != len(titles):
                raise StorageValidationError(
                    "Google Sheets returned an incomplete workbook snapshot"
                )
            for title, value_range in zip(titles, value_ranges):
                if not isinstance(value_range, Mapping):
                    raise StorageValidationError(
                        "Google Sheets returned an unreadable workbook snapshot"
                    )
                values = value_range.get("values", [])
                if not isinstance(values, list):
                    raise StorageValidationError(
                        "Google Sheets returned an unreadable worksheet"
                    )
                self._cache_values(title, values)
            return
        for title in titles:
            worksheet = self._worksheet(title)
            values = self._api(worksheet.get_all_values)
            self._cache_values(title, values)

    def _snapshot(
        self,
        titles: Iterable[str],
        *,
        force_refresh: bool = False,
    ) -> dict[str, list[_StoredRow]]:
        """Return a consistent cached or freshly batched worksheet snapshot."""
        requested = list(dict.fromkeys(titles))
        now = time.monotonic()
        refresh: list[str] = []
        with self._cache_lock:
            for title in requested:
                cached = self._row_cache.get(title)
                if (
                    force_refresh
                    or self._cache_ttl_seconds <= 0
                    or cached is None
                    or now - cached[0] >= self._cache_ttl_seconds
                ):
                    refresh.append(title)
        if refresh:
            self._refresh_rows(refresh)
        snapshot: dict[str, list[_StoredRow]] = {}
        with self._cache_lock:
            for title in requested:
                cached = self._row_cache.get(title)
                if cached is None:
                    raise StorageValidationError(
                        f"{title} could not be loaded from Google Sheets"
                    )
                snapshot[title] = list(cached[1])
        return snapshot

    def _rows(self, title: str, *, force_refresh: bool = False) -> list[_StoredRow]:
        return self._snapshot([title], force_refresh=force_refresh)[title]

    def prefetch_worksheets(
        self,
        *titles: str,
        force_refresh: bool = False,
    ) -> None:
        """Warm several worksheet caches through one multi-range values request."""
        unknown = sorted(set(titles) - set(WORKSHEET_HEADERS))
        if unknown:
            raise StorageValidationError(
                "Unknown worksheets requested: " + ", ".join(unknown)
            )
        self._snapshot(titles, force_refresh=force_refresh)

    def _invalidate(self, title: str) -> None:
        with self._cache_lock:
            self._row_cache.pop(title, None)

    def _find_row(self, title: str, record_id: str) -> _StoredRow:
        record_id = _clean_text(record_id, "ID", required=True)
        matches = [
            row
            for row in self._rows(title, force_refresh=True)
            if _clean_text(row.values.get("id"), "ID") == record_id
        ]
        if not matches:
            raise StorageNotFoundError(f"{title[:-1]} no longer exists")
        if len(matches) > 1:
            raise StorageValidationError(f"Duplicate ID detected in {title}")
        return matches[0]

    def _write_with_uncertain_readback(
        self,
        operation: str,
        write: Callable[[], None],
        readback: Callable[[], str],
        *,
        before_retry: Callable[[], None] | None = None,
        invalidate: Iterable[str] = (),
    ) -> None:
        """Perform one mutation, confirming uncertain responses before retrying.

        ``readback`` returns ``"applied"`` when the requested postcondition is
        present, ``"unchanged"`` when the complete precondition is still
        present, and ``"ambiguous"`` for every partial or conflicting state.
        A write is never retried more than once and only an unchanged state is
        safe to retry.  Cache invalidation happens before every failure leaves
        this method so callers cannot continue using a stale snapshot.
        """
        retried = False
        while True:
            try:
                write()
            except StorageUnavailableError as error:
                if not error.retryable:
                    for title in invalidate:
                        self._invalidate(title)
                    if retried:
                        raise StorageUnavailableError(
                            _mutation_guidance(operation), retryable=False
                        ) from error
                    raise
                try:
                    state = readback()
                except (StorageError, OSError) as read_error:
                    for title in invalidate:
                        self._invalidate(title)
                    raise StorageUnavailableError(
                        _mutation_guidance(operation), retryable=False
                    ) from read_error
                except Exception:
                    for title in invalidate:
                        self._invalidate(title)
                    raise
                if state == "applied":
                    for title in invalidate:
                        self._invalidate(title)
                    return
                if state == "unchanged" and not retried:
                    retried = True
                    self._sleeper(self._retry_base_delay_seconds)
                    if before_retry is not None:
                        try:
                            before_retry()
                        except (StorageUnavailableError, OSError) as refresh_error:
                            for title in invalidate:
                                self._invalidate(title)
                            raise StorageUnavailableError(
                                _mutation_guidance(operation), retryable=False
                            ) from refresh_error
                        except Exception:
                            for title in invalidate:
                                self._invalidate(title)
                            raise
                    continue
                for title in invalidate:
                    self._invalidate(title)
                raise StorageUnavailableError(
                    _mutation_guidance(operation), retryable=False
                ) from error
            else:
                for title in invalidate:
                    self._invalidate(title)
                return

    def _append(self, title: str, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        record_id = _clean_text(record.get("id"), "ID", required=True)

        def state() -> str:
            rows = self._rows(title, force_refresh=True)
            matches = [
                row for row in rows
                if _clean_text(row.values.get("id"), "ID") == record_id
            ]
            if not matches:
                return "unchanged"
            if len(matches) != 1:
                return "ambiguous"
            expected = {header: str(record.get(header, "")) for header in headers}
            return "applied" if matches[0].values == expected else "ambiguous"

        self._write_with_uncertain_readback(
            f"{title} append",
            lambda: self._api(
                lambda: worksheet.append_row(values, value_input_option="RAW"),
                retry_safe=False,
            ),
            state,
            invalidate=(title,),
        )

    def _append_many(self, title: str, records: Iterable[Mapping[str, Any]]) -> None:
        records = list(records)
        if not records:
            return
        headers = self._headers(title)
        record_ids = [
            _clean_text(record.get("id"), "ID", required=True)
            for record in records
        ]
        if len(record_ids) != len(set(record_ids)):
            raise StorageValidationError(f"Duplicate ID detected in {title}")
        values = [
            [str(record.get(header, "")) for header in headers] for record in records
        ]
        worksheet = self._worksheet(title)
        record_id_set = set(record_ids)

        def state() -> str:
            rows = self._rows(title, force_refresh=True)
            by_id: dict[str, dict[str, str]] = {}
            for row in rows:
                record_id = _clean_text(row.values.get("id"), "ID")
                if record_id in by_id:
                    return "ambiguous"
                by_id[record_id] = row.values
            expected = {
                _clean_text(record.get("id"), "ID"): {
                    header: str(record.get(header, "")) for header in headers
                }
                for record in records
            }
            if all(by_id.get(record_id) == item for record_id, item in expected.items()):
                return "applied"
            if not any(record_id in by_id for record_id in record_id_set):
                return "unchanged"
            return "ambiguous"

        self._write_with_uncertain_readback(
            f"{title} batch append",
            lambda: self._api(
                lambda: worksheet.append_rows(values, value_input_option="RAW"),
                retry_safe=False,
            ),
            state,
            invalidate=(title,),
        )

    def _replace_row(self, title: str, row: _StoredRow, record: Mapping[str, Any]) -> None:
        headers = self._headers(title)
        values = [str(record.get(header, "")) for header in headers]
        worksheet = self._worksheet(title)
        record_id = _clean_text(record.get("id"), "ID", required=True)
        original = dict(row.values)
        current_row = row

        def write() -> None:
            self._api(
                lambda: worksheet.update(
                    [values], range_name=f"A{current_row.row_number}", raw=True
                ),
                retry_safe=False,
            )

        def state() -> str:
            latest = self._find_row(title, record_id)
            if latest.values == {header: str(record.get(header, "")) for header in headers}:
                return "applied"
            return "unchanged" if latest.values == original else "ambiguous"

        def refresh() -> None:
            nonlocal current_row
            latest = self._find_row(title, record_id)
            if latest.values != original:
                raise StorageConflictError(
                    f"The {title} row changed while the write was being retried."
                )
            current_row = latest

        self._write_with_uncertain_readback(
            f"{title} update", write, state, before_retry=refresh, invalidate=(title,)
        )

    def _replace_rows(
        self,
        title: str,
        updates: Sequence[tuple[_StoredRow, Mapping[str, Any]]],
        *,
        before_retry: Callable[[], None] | None = None,
    ) -> None:
        if not updates:
            return
        headers = self._headers(title)
        worksheet = self._worksheet(title)
        current_updates = list(updates)
        originals = {
            _clean_text(record.get("id"), "ID", required=True): dict(row.values)
            for row, record in updates
        }
        if len(originals) != len(updates):
            raise StorageValidationError(f"Duplicate ID detected in {title}")
        updates_by_id = {
            _clean_text(record.get("id"), "ID", required=True): record
            for _, record in updates
        }

        def write() -> None:
            batch = [
                {
                    "range": f"A{row.row_number}",
                    "values": [[str(record.get(header, "")) for header in headers]],
                }
                for row, record in current_updates
            ]
            self._api(
                lambda: worksheet.batch_update(batch, raw=True),
                retry_safe=False,
            )

        intended_by_id = {
            _clean_text(record.get("id"), "ID", required=True): {
                header: str(record.get(header, "")) for header in headers
            }
            for _, record in updates
        }
        if len(intended_by_id) != len(updates):
            raise StorageValidationError(f"Duplicate ID detected in {title}")

        def state() -> str:
            current_rows = self._rows(title, force_refresh=True)
            current_by_id: dict[str, _StoredRow] = {}
            for item in current_rows:
                row_id = _clean_text(item.values.get("id"), "ID", required=True)
                if row_id in current_by_id:
                    return "ambiguous"
                current_by_id[row_id] = item
            if all(
                current_by_id.get(record_id, _StoredRow(0, {})).values == intended
                for record_id, intended in intended_by_id.items()
            ):
                return "applied"
            if all(
                current_by_id.get(record_id, _StoredRow(0, {})).values
                == originals[record_id]
                for record_id in originals
            ):
                return "unchanged"
            return "ambiguous"

        def refresh() -> None:
            nonlocal current_updates
            if before_retry is not None:
                before_retry()
            retry_rows = self._rows(title, force_refresh=True)
            retry_by_id: dict[str, _StoredRow] = {}
            for item in retry_rows:
                row_id = _clean_text(item.values.get("id"), "ID", required=True)
                if row_id in retry_by_id:
                    raise StorageValidationError(f"Duplicate ID detected in {title}")
                retry_by_id[row_id] = item
            if any(
                retry_by_id.get(record_id, _StoredRow(0, {})).values
                != originals[record_id]
                for record_id in originals
            ):
                raise StorageConflictError(
                    f"A row in {title} changed unexpectedly during a write retry."
                )
            current_updates = [
                (retry_by_id[record_id], updates_by_id[record_id])
                for record_id in originals
            ]

        self._write_with_uncertain_readback(
            f"{title} batch update",
            write,
            state,
            before_retry=refresh,
            invalidate=(title,),
        )

    def _replace_rows_atomically(
        self,
        updates: Sequence[tuple[str, _StoredRow, Mapping[str, Any]]],
    ) -> None:
        """Replace rows across worksheets in one spreadsheet-level batch."""
        if not updates:
            return
        requests: list[dict[str, Any]] = []
        titles: set[str] = set()
        for title, row, record in updates:
            headers = self._headers(title)
            titles.add(title)
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": self._sheet_id(title),
                            "startRowIndex": row.row_number - 1,
                            "endRowIndex": row.row_number,
                            "startColumnIndex": 0,
                            "endColumnIndex": len(headers),
                        },
                        "rows": [
                            {
                                "values": [
                                    {
                                        "userEnteredValue": {
                                            "stringValue": str(record.get(header, ""))
                                        }
                                    }
                                    for header in headers
                                ]
                            }
                        ],
                        "fields": "userEnteredValue",
                    }
                }
            )
        self._batch_update_spreadsheet(requests)
        for title in titles:
            self._invalidate(title)

    def _batch_update_spreadsheet(self, requests: Sequence[Mapping[str, Any]]) -> None:
        if not requests:
            return
        self._api(
            lambda: self._workbook.batch_update({"requests": list(requests)}),
            retry_safe=False,
        )
