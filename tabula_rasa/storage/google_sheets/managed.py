"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import Callable
from uuid import uuid4
from .schema import (
    WORKSHEET_HEADERS,
)
from .errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from .validation import (
    _as_bool,
    _clean_text,
    _encode_tag_ids,
    _managed_comparison_text,
    _normalize_tag_ids,
    _raw_tag_ids_may_contain,
    _utc_now,
    _validate_mixed_use_tables,
    normalize_payee_name,
    normalize_tag_name,
)
from .base import (
    _MIXED_USE_CREATE_LOCK,
    _PAYEE_WRITE_LOCK,
    _StoredRow,
    _TAG_WRITE_LOCK,
)

class _ManagedMixin:
    """Mixin for the managed storage boundary."""

    def list_payees(
        self, *, active_only: bool = False, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        payees: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for row in self._rows("Payees", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Payee ID", required=True)
            item["name"] = _clean_text(item.get("name"), "Payee name", required=True)
            item["active"] = "TRUE" if _as_bool(item.get("active"), "Payee active") else "FALSE"
            item["created_at"] = _clean_text(item.get("created_at"), "Payee created at")
            key = normalize_payee_name(item["name"])
            if item["id"] in seen_ids or key in seen_names:
                raise StorageValidationError("Payee IDs and names must be unique")
            seen_ids.add(item["id"])
            seen_names.add(key)
            if not active_only or item["active"] == "TRUE":
                payees.append(item)
        return sorted(payees, key=lambda item: item["name"].casefold())

    def create_payee(self, name: str, *, active: bool = True) -> dict[str, str]:
        name = _clean_text(name, "Payee name", required=True)
        with _PAYEE_WRITE_LOCK:
            existing = self.list_payees(_force_refresh=True)
            key = normalize_payee_name(name)
            match = next(
                (item for item in existing if normalize_payee_name(item["name"]) == key),
                None,
            )
            if match is not None:
                if active and match["active"] != "TRUE":
                    return self.edit_payee(match["id"], active=True)
                return match
            record = {
                "id": str(uuid4()),
                "name": name,
                "active": "TRUE" if active else "FALSE",
                "created_at": _utc_now(),
            }
            self._append("Payees", record)
            return record

    def _ensure_payee_names(
        self, names: Iterable[Any]
    ) -> dict[str, dict[str, str]]:
        with _PAYEE_WRITE_LOCK:
            payees = self.list_payees(_force_refresh=True)
            by_key = {normalize_payee_name(item["name"]): item for item in payees}
            rows_by_id = {
                _clean_text(row.values.get("id"), "Payee ID", required=True): row
                for row in self._rows("Payees")
            }
            additions: list[dict[str, str]] = []
            activations: list[dict[str, str]] = []
            for value in names:
                name = _clean_text(value, "New payee")
                if not name:
                    continue
                key = normalize_payee_name(name)
                match = by_key.get(key)
                if match is None:
                    match = {
                        "id": str(uuid4()),
                        "name": name,
                        "active": "TRUE",
                        "created_at": _utc_now(),
                    }
                    additions.append(match)
                    by_key[key] = match
                elif match["active"] != "TRUE":
                    match = dict(match)
                    match["active"] = "TRUE"
                    activations.append(match)
                    by_key[key] = match
            if activations:
                self._replace_rows(
                    "Payees",
                    [(rows_by_id[item["id"]], item) for item in activations],
                )
            if additions:
                self._append_many("Payees", additions)
            return {item["id"]: item for item in by_key.values()}

    def edit_payee(
        self,
        payee_id: str,
        *,
        expected_payee: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        with _PAYEE_WRITE_LOCK:
            current = self._find_row("Payees", payee_id)
            updated = dict(current.values)
            expected_record = expected_payee or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {str(updated["id"]): updated}, expected_record
                )
            name = _clean_text(
                changes.get("name", updated["name"]),
                "Payee name",
                required=True,
            )
            if "name" in changes and normalize_payee_name(name) != normalize_payee_name(updated["name"]):
                existing = self.list_payees(_force_refresh=True)
                if any(
                    item["id"] != payee_id
                    and normalize_payee_name(item["name"]) == normalize_payee_name(name)
                    for item in existing
                ):
                    raise StorageConflictError("That payee already exists")
            updated.update(
                {
                    "name": name,
                    "active": "TRUE"
                    if _as_bool(
                        changes.get("active", updated["active"]), "Payee active"
                    )
                    else "FALSE",
                }
            )
            self._replace_row("Payees", current, updated)
            return updated

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

    def merge_payees(
        self,
        target_payee_id: str,
        source_payee_ids: Sequence[str],
        *,
        expected_payees: Iterable[Mapping[str, Any]]
        | Mapping[str, Mapping[str, Any]]
        | None = None,
    ) -> dict[str, str]:
        """Merge source payees into one target while preserving all references."""
        target_id = _clean_text(target_payee_id, "Target payee", required=True)
        source_ids = list(dict.fromkeys(
            _clean_text(item, "Source payee", required=True) for item in source_payee_ids
        ))
        if not source_ids:
            raise StorageValidationError("Select at least one source payee")
        if target_id in source_ids:
            raise StorageValidationError("The target payee cannot also be a source")
        with _MIXED_USE_CREATE_LOCK, _PAYEE_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Payees", "Transactions", "MixedUseExpenses"], force_refresh=True
            )
            _validate_mixed_use_tables(
                {
                    "MixedUseExpenses": (
                        WORKSHEET_HEADERS["MixedUseExpenses"],
                        [dict(row.values) for row in snapshot["MixedUseExpenses"]],
                    ),
                    "Transactions": (
                        WORKSHEET_HEADERS["Transactions"],
                        [dict(row.values) for row in snapshot["Transactions"]],
                    ),
                }
            )
            payee_rows = self._managed_rows_by_id(snapshot["Payees"], "Payees")
            payees = {record_id: dict(row.values) for record_id, row in payee_rows.items()}
            if target_id not in payees:
                raise StorageNotFoundError("Payee no longer exists")
            missing = [item for item in source_ids if item not in payees]
            if missing and len(missing) == len(source_ids):
                # A retried merge may have already removed every source. Once
                # the target still exists and no reference survives, this is
                # a safe converged outcome. Do not hide an inconsistent
                # workbook behind a successful retry.
                expected_records = self._expected_managed_records(expected_payees)
                self._assert_expected_managed_records(
                    {target_id: payees[target_id]},
                    {target_id: expected_records[target_id]}
                    if target_id in expected_records
                    else None,
                )
                references = [
                    row
                    for row in (*snapshot["Transactions"], *snapshot["MixedUseExpenses"])
                    if _clean_text(row.values.get("payee_id"), "Payee") in source_ids
                ]
                if not references:
                    return {"status": "fully_applied", "count": str(len(source_ids))}
                raise StorageConflictError(
                    "The selected source payee records are missing but their references remain."
                )
            if missing:
                raise StorageNotFoundError("A source payee no longer exists")
            self._assert_expected_managed_records(payees, expected_payees)

            transaction_rows = self._managed_rows_by_id(snapshot["Transactions"], "Transactions")
            mixed_rows = self._managed_rows_by_id(snapshot["MixedUseExpenses"], "MixedUseExpenses")
            transaction_updates = {
                record_id: row
                for record_id, row in transaction_rows.items()
                if _clean_text(row.values.get("payee_id"), "Payee") in source_ids
            }
            mixed_updates = {
                record_id: row
                for record_id, row in mixed_rows.items()
                if _clean_text(row.values.get("payee_id"), "Payee") in source_ids
            }
            requests: list[dict[str, Any]] = []
            for row in transaction_updates.values():
                requests.append(
                    self._managed_update_request(
                        "Transactions", row, "payee_id", target_id
                    )
                )
            for row in mixed_updates.values():
                requests.append(
                    self._managed_update_request(
                        "MixedUseExpenses", row, "payee_id", target_id
                    )
                )
            for source_id in sorted(source_ids, key=lambda item: payee_rows[item].row_number, reverse=True):
                requests.append(self._managed_delete_request("Payees", payee_rows[source_id]))
            if not requests:
                raise StorageValidationError("The selected payees have no mergeable changes")

            def fresh_state() -> tuple[dict[str, dict[str, str]], dict[str, _StoredRow], dict[str, _StoredRow]]:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses"], force_refresh=True
                )
                return (
                    {record_id: dict(row.values) for record_id, row in self._managed_rows_by_id(current["Payees"], "Payees").items()},
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["MixedUseExpenses"], "MixedUseExpenses"),
                )

            def is_applied(state: Any) -> bool:
                current_payees, current_transactions, current_mixed = state
                return (
                    target_id in current_payees
                    and not any(item in current_payees for item in source_ids)
                    and all(
                        _clean_text(row.values.get("payee_id"), "Payee") != source_id
                        for source_id in source_ids
                        for row in (*current_transactions.values(), *current_mixed.values())
                    )
                    and all(
                        record_id in current_transactions
                        and _clean_text(current_transactions[record_id].values.get("payee_id"), "Payee") == target_id
                        for record_id in transaction_updates
                    )
                    and all(
                        record_id in current_mixed
                        and _clean_text(current_mixed[record_id].values.get("payee_id"), "Payee") == target_id
                        for record_id in mixed_updates
                    )
                )

            def is_unchanged(state: Any) -> bool:
                current_payees, current_transactions, current_mixed = state
                if any(
                    record_id not in current_payees
                    or current_payees[record_id] != row.values
                    for record_id, row in payee_rows.items()
                ):
                    return False
                return all(
                    record_id in current_transactions
                    and current_transactions[record_id].values == row.values
                    for record_id, row in transaction_updates.items()
                ) and all(
                    record_id in current_mixed and current_mixed[record_id].values == row.values
                    for record_id, row in mixed_updates.items()
                )

            def refresh_requests() -> None:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses"],
                    force_refresh=True,
                )
                current_state = (
                    {
                        record_id: dict(row.values)
                        for record_id, row in self._managed_rows_by_id(
                            current["Payees"], "Payees"
                        ).items()
                    },
                    self._managed_rows_by_id(
                        current["Transactions"], "Transactions"
                    ),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                )
                if not is_unchanged(current_state):
                    raise StorageConflictError(
                        "Payee records or references changed while the merge was being retried."
                    )
                current_payees = self._managed_rows_by_id(current["Payees"], "Payees")
                current_transactions = self._managed_rows_by_id(
                    current["Transactions"], "Transactions"
                )
                current_mixed = self._managed_rows_by_id(
                    current["MixedUseExpenses"], "MixedUseExpenses"
                )
                refreshed = [
                    self._managed_update_request(
                        "Transactions", current_transactions[record_id], "payee_id", target_id
                    )
                    for record_id in transaction_updates
                ]
                refreshed.extend(
                    self._managed_update_request(
                        "MixedUseExpenses", current_mixed[record_id], "payee_id", target_id
                    )
                    for record_id in mixed_updates
                )
                refreshed.extend(
                    self._managed_delete_request("Payees", current_payees[source_id])
                    for source_id in sorted(
                        source_ids,
                        key=lambda item: current_payees[item].row_number,
                        reverse=True,
                    )
                )
                requests[:] = refreshed

            self._managed_write(
                operation="payee merge",
                requests=requests,
                read_state=fresh_state,
                applied=is_applied,
                unchanged=is_unchanged,
                before_retry=refresh_requests,
                invalidate=("Payees", "Transactions", "MixedUseExpenses"),
            )
            return {"status": "fully_applied", "count": str(len(source_ids))}

    merge_payee = merge_payees

    def remove_payee(
        self,
        payee_id: str,
        *,
        expected_payee: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Permanently remove one unreferenced payee after a fresh check."""
        payee_id = _clean_text(payee_id, "Payee", required=True)
        with _MIXED_USE_CREATE_LOCK, _PAYEE_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Payees", "Transactions", "MixedUseExpenses"], force_refresh=True
            )
            payee_rows = self._managed_rows_by_id(snapshot["Payees"], "Payees")
            if payee_id not in payee_rows:
                raise StorageNotFoundError("Payee no longer exists")
            expected_record = expected_payee or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {payee_id: dict(payee_rows[payee_id].values)}, expected_record
                )
            references = sum(
                _clean_text(row.values.get("payee_id"), "Payee") == payee_id
                for row in (*snapshot["Transactions"], *snapshot["MixedUseExpenses"])
            )
            if references:
                raise StorageConflictError(
                    f"This payee is referenced by {references} records. Merge it or unassign it first."
                )
            request = self._managed_delete_request("Payees", payee_rows[payee_id])

            def read_state() -> tuple[dict[str, _StoredRow], dict[str, _StoredRow], dict[str, _StoredRow]]:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Payees"], "Payees"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["MixedUseExpenses"], "MixedUseExpenses"),
                )

            def references_present(state: Any) -> bool:
                _, current_transactions, current_mixed = state
                return any(
                    _clean_text(row.values.get("payee_id"), "Payee") == payee_id
                    for row in (*current_transactions.values(), *current_mixed.values())
                )

            def is_applied(state: Any) -> bool:
                current_payees, _, _ = state
                return payee_id not in current_payees and not references_present(state)

            def is_unchanged(state: Any) -> bool:
                current_payees, _, _ = state
                return (
                    payee_id in current_payees
                    and current_payees[payee_id].values == payee_rows[payee_id].values
                    and not references_present(state)
                )

            def refresh_request() -> None:
                state = read_state()
                if not is_unchanged(state):
                    raise StorageConflictError(
                        "The payee changed or became referenced while removal was being retried."
                    )
                current_payees, _, _ = state
                refreshed = self._managed_delete_request(
                    "Payees", current_payees[payee_id]
                )
                requests[:] = [refreshed]

            requests = [request]
            self._managed_write(
                operation="payee removal",
                requests=requests,
                read_state=read_state,
                applied=is_applied,
                unchanged=is_unchanged,
                before_retry=refresh_request,
                invalidate=("Payees", "Transactions", "MixedUseExpenses"),
            )
            return {"status": "fully_applied"}

    delete_payee = remove_payee

    def list_tags(
        self, *, active_only: bool = False, _force_refresh: bool = False
    ) -> list[dict[str, str]]:
        tags: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        seen_names: set[str] = set()
        for row in self._rows("Tags", force_refresh=_force_refresh):
            item = dict(row.values)
            item["id"] = _clean_text(item.get("id"), "Tag ID", required=True)
            item["name"] = _clean_text(item.get("name"), "Tag name", required=True)
            item["active"] = (
                "TRUE" if _as_bool(item.get("active"), "Tag active") else "FALSE"
            )
            item["created_at"] = _clean_text(item.get("created_at"), "Tag created at")
            name_key = normalize_tag_name(item["name"])
            if item["id"] in seen_ids or name_key in seen_names:
                raise StorageValidationError("Tag IDs and names must be unique")
            seen_ids.add(item["id"])
            seen_names.add(name_key)
            if not active_only or item["active"] == "TRUE":
                tags.append(item)
        return sorted(tags, key=lambda item: item["name"].casefold())

    def create_tag(self, name: str, *, active: bool = True) -> dict[str, str]:
        """Create or reactivate a profile-local tag by normalized name."""
        name = _clean_text(name, "Tag name", required=True)
        with _TAG_WRITE_LOCK:
            existing = self.list_tags(_force_refresh=True)
            key = normalize_tag_name(name)
            match = next(
                (item for item in existing if normalize_tag_name(item["name"]) == key),
                None,
            )
            if match is not None:
                if active and match["active"] != "TRUE":
                    current = self._find_row("Tags", match["id"])
                    updated = dict(current.values)
                    updated["active"] = "TRUE"
                    self._replace_row("Tags", current, updated)
                    match = {**match, "active": "TRUE"}
                return match
            record = {
                "id": str(uuid4()),
                "name": name,
                "active": "TRUE" if active else "FALSE",
                "created_at": _utc_now(),
            }
            self._append("Tags", record)
            return record

    def edit_tag(
        self,
        tag_id: str,
        *,
        expected_tag: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
        **changes: Any,
    ) -> dict[str, str]:
        """Rename or activate/deactivate a tag while retaining its stable ID."""
        tag_id = _clean_text(tag_id, "Tag", required=True)
        with _TAG_WRITE_LOCK:
            current = self._find_row("Tags", tag_id)
            updated = dict(current.values)
            expected_record = expected_tag or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {str(updated["id"]): updated}, expected_record
                )
            name = _clean_text(changes.get("name", updated.get("name")), "Tag name", required=True)
            if normalize_tag_name(name) != normalize_tag_name(updated.get("name", "")):
                existing = self.list_tags(_force_refresh=True)
                if any(
                    item["id"] != tag_id
                    and normalize_tag_name(item["name"]) == normalize_tag_name(name)
                    for item in existing
                ):
                    raise StorageConflictError("That tag already exists")
            updated.update({
                "name": name,
                "active": "TRUE"
                if _as_bool(changes.get("active", updated.get("active")), "Tag active")
                else "FALSE",
            })
            self._replace_row("Tags", current, updated)
            return updated

    def merge_tags(
        self,
        target_tag_id: str,
        source_tag_ids: Sequence[str],
        *,
        expected_tags: Iterable[Mapping[str, Any]]
        | Mapping[str, Mapping[str, Any]]
        | None = None,
    ) -> dict[str, str]:
        """Merge source tags into a target across tagged worksheet rows."""
        target_id = _clean_text(target_tag_id, "Target tag", required=True)
        source_ids = list(dict.fromkeys(
            _clean_text(item, "Source tag", required=True) for item in source_tag_ids
        ))
        if not source_ids:
            raise StorageValidationError("Select at least one source tag")
        if target_id in source_ids:
            raise StorageValidationError("The target tag cannot also be a source")
        with _MIXED_USE_CREATE_LOCK, _TAG_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                force_refresh=True,
            )
            tag_rows = self._managed_rows_by_id(snapshot["Tags"], "Tags")
            tags = {record_id: dict(row.values) for record_id, row in tag_rows.items()}
            if target_id not in tags:
                raise StorageNotFoundError("Tag no longer exists")
            missing = [item for item in source_ids if item not in tags]
            if missing and len(missing) == len(source_ids):
                expected_records = self._expected_managed_records(expected_tags)
                self._assert_expected_managed_records(
                    {target_id: tags[target_id]},
                    {target_id: expected_records[target_id]}
                    if target_id in expected_records
                    else None,
                )
                references = []
                for row in (
                    *snapshot["Transactions"],
                    *snapshot["Mileage"],
                    *snapshot["MixedUseExpenses"],
                ):
                    raw_tags = row.values.get("tag_ids", "")
                    if _raw_tag_ids_may_contain(raw_tags, source_ids) and any(
                        item in source_ids for item in _normalize_tag_ids(raw_tags)
                    ):
                        references.append(row)
                if not references:
                    return {"status": "fully_applied", "count": str(len(source_ids))}
                raise StorageConflictError(
                    "The selected source tag records are missing but their references remain."
                )
            if missing:
                raise StorageNotFoundError("A source tag no longer exists")
            self._assert_expected_managed_records(tags, expected_tags)
            update_rows: dict[str, tuple[str, _StoredRow, str]] = {}
            for title in ("Transactions", "Mileage", "MixedUseExpenses"):
                for record_id, row in self._managed_rows_by_id(snapshot[title], title).items():
                    raw_tags = row.values.get("tag_ids", "")
                    if not _raw_tag_ids_may_contain(raw_tags, source_ids):
                        continue
                    tag_ids = _normalize_tag_ids(raw_tags)
                    if not any(item in source_ids for item in tag_ids):
                        continue
                    merged_ids = [target_id if item in source_ids else item for item in tag_ids]
                    merged_ids = list(dict.fromkeys(merged_ids))
                    update_rows[f"{title}:{record_id}"] = (
                        title, row, _encode_tag_ids(merged_ids)
                    )
            requests = [
                self._managed_update_request(title, row, "tag_ids", value)
                for title, row, value in update_rows.values()
            ]
            for source_id in sorted(source_ids, key=lambda item: tag_rows[item].row_number, reverse=True):
                requests.append(self._managed_delete_request("Tags", tag_rows[source_id]))

            def fresh_state() -> tuple[
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
            ]:
                current = self._snapshot(
                    ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Tags"], "Tags"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["Mileage"], "Mileage"),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                )

            def is_applied(state: Any) -> bool:
                (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                ) = state
                if target_id not in current_tags or any(item in current_tags for item in source_ids):
                    return False
                if any(
                    item in _normalize_tag_ids(row.values.get("tag_ids", ""))
                    for item in source_ids
                    for row in (
                        *current_transactions.values(),
                        *current_mileage.values(),
                        *current_sources.values(),
                    )
                ):
                    return False
                for title, row, expected_value in update_rows.values():
                    current_rows = {
                        "Transactions": current_transactions,
                        "Mileage": current_mileage,
                        "MixedUseExpenses": current_sources,
                    }[title]
                    record_id = _clean_text(row.values.get("id"), "ID", required=True)
                    if record_id not in current_rows:
                        return False
                    if str(current_rows[record_id].values.get("tag_ids", "")) != expected_value:
                        return False
                return True

            def is_unchanged(state: Any) -> bool:
                (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                ) = state
                if any(
                    record_id not in current_tags
                    or current_tags[record_id].values != row.values
                    for record_id, row in tag_rows.items()
                ):
                    return False
                for title, row, _ in update_rows.values():
                    current_rows = {
                        "Transactions": current_transactions,
                        "Mileage": current_mileage,
                        "MixedUseExpenses": current_sources,
                    }[title]
                    current = current_rows.get(
                        _clean_text(row.values.get("id"), "ID", required=True)
                    )
                    if current is None or current.values != row.values:
                        return False
                return True

            def refresh_requests() -> None:
                current_tags, current_transactions, current_mileage, current_sources = (
                    fresh_state()
                )
                current_state = (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                )
                if not is_unchanged(current_state):
                    raise StorageConflictError(
                        "Tag records or references changed while the merge was being retried."
                    )
                current_rows_by_title = {
                    "Transactions": current_transactions,
                    "Mileage": current_mileage,
                    "MixedUseExpenses": current_sources,
                }
                refreshed = [
                    self._managed_update_request(
                        title,
                        current_rows_by_title[title][
                            _clean_text(row.values.get("id"), "ID", required=True)
                        ],
                        "tag_ids",
                        expected_value,
                    )
                    for title, row, expected_value in update_rows.values()
                ]
                refreshed.extend(
                    self._managed_delete_request("Tags", current_tags[source_id])
                    for source_id in sorted(
                        source_ids,
                        key=lambda item: current_tags[item].row_number,
                        reverse=True,
                    )
                )
                requests[:] = refreshed

            self._managed_write(
                operation="tag merge",
                requests=requests,
                read_state=fresh_state,
                applied=is_applied,
                unchanged=is_unchanged,
                before_retry=refresh_requests,
                invalidate=("Tags", "Transactions", "Mileage", "MixedUseExpenses"),
            )
            return {"status": "fully_applied", "count": str(len(source_ids))}

    merge_tag = merge_tags

    def remove_tag(
        self,
        tag_id: str,
        *,
        expected_tag: Mapping[str, Any] | None = None,
        expected: Mapping[str, Any] | None = None,
    ) -> dict[str, str]:
        """Permanently remove one tag only when no tagged row uses it."""
        tag_id = _clean_text(tag_id, "Tag", required=True)
        with _MIXED_USE_CREATE_LOCK, _TAG_WRITE_LOCK:
            snapshot = self._snapshot(
                ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                force_refresh=True,
            )
            tag_rows = self._managed_rows_by_id(snapshot["Tags"], "Tags")
            if tag_id not in tag_rows:
                raise StorageNotFoundError("Tag no longer exists")
            expected_record = expected_tag or expected
            if expected_record is not None:
                self._assert_expected_managed_records(
                    {tag_id: dict(tag_rows[tag_id].values)}, expected_record
                )
            references = 0
            for row in (
                *snapshot["Transactions"],
                *snapshot["Mileage"],
                *snapshot["MixedUseExpenses"],
            ):
                raw_tags = row.values.get("tag_ids", "")
                if _raw_tag_ids_may_contain(
                    raw_tags, (tag_id,)
                ) and tag_id in _normalize_tag_ids(raw_tags):
                    references += 1
            if references:
                raise StorageConflictError(
                    f"This tag is referenced by {references} records. Merge it or unassign it first."
                )
            request = self._managed_delete_request("Tags", tag_rows[tag_id])
            def read_state() -> tuple[
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
                dict[str, _StoredRow],
            ]:
                current = self._snapshot(
                    ["Tags", "Transactions", "Mileage", "MixedUseExpenses"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Tags"], "Tags"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["Mileage"], "Mileage"),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                )
            def references_present(state: Any) -> bool:
                _, current_transactions, current_mileage, current_sources = state
                return any(
                    tag_id in _normalize_tag_ids(row.values.get("tag_ids", ""))
                    for row in (
                        *current_transactions.values(),
                        *current_mileage.values(),
                        *current_sources.values(),
                    )
                )
            def is_gone(state: Any) -> bool:
                return tag_id not in state[0] and not references_present(state)
            def is_unchanged(state: Any) -> bool:
                return (
                    tag_id in state[0]
                    and state[0][tag_id].values == tag_rows[tag_id].values
                    and not references_present(state)
                )

            def refresh_request() -> None:
                nonlocal tag_rows, request
                state = read_state()
                if not is_unchanged(state):
                    raise StorageConflictError(
                        "The tag changed or became referenced while removal was being retried."
                    )
                tag_rows = state[0]
                request = self._managed_delete_request("Tags", tag_rows[tag_id])

            requests = [request]
            def refresh_requests() -> None:
                refresh_request()
                requests[:] = [request]

            self._managed_write(
                operation="tag removal",
                requests=requests,
                read_state=read_state,
                applied=is_gone,
                unchanged=is_unchanged,
                before_retry=refresh_requests,
                invalidate=("Tags", "Transactions", "Mileage", "MixedUseExpenses"),
            )
            return {"status": "fully_applied"}

    delete_tag = remove_tag

    def _payee_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_payees(_force_refresh=force_refresh)}

    def _tag_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_tags(_force_refresh=force_refresh)}

__all__ = ["_ManagedMixin"]
