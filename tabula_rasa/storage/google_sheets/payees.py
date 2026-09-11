"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from uuid import uuid4
from .schema import WORKSHEET_HEADERS
from .errors import StorageConflictError
from .errors import StorageNotFoundError
from .errors import StorageValidationError
from .validation import _as_bool
from .validation import _clean_text
from .validation import _utc_now
from .validation import _validate_mixed_use_tables
from .validation import normalize_payee_name
from .base import _StoredRow
from .managed import _ManagedMixin

class PayeesMixin(_ManagedMixin):
    """PayeesMixin boundary for the Google Sheets facade."""

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
        with self._workbook_locks.payee:
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
        with self._workbook_locks.payee:
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
        with self._workbook_locks.payee:
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
        with self._workbook_locks.ledger, self._workbook_locks.payee:
            snapshot = self._snapshot(
                ["Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"], force_refresh=True
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
                    for row in (
                        *snapshot["Transactions"],
                        *snapshot["MixedUseExpenses"],
                        *snapshot["RecurringSchedules"],
                    )
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
            schedule_rows = self._managed_rows_by_id(snapshot["RecurringSchedules"], "RecurringSchedules")
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
            schedule_updates = {
                record_id: row
                for record_id, row in schedule_rows.items()
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
            for row in schedule_updates.values():
                requests.append(
                    self._managed_update_request(
                        "RecurringSchedules", row, "payee_id", target_id
                    )
                )
            for source_id in sorted(source_ids, key=lambda item: payee_rows[item].row_number, reverse=True):
                requests.append(self._managed_delete_request("Payees", payee_rows[source_id]))
            if not requests:
                raise StorageValidationError("The selected payees have no mergeable changes")

            def fresh_state() -> tuple[dict[str, dict[str, str]], dict[str, _StoredRow], dict[str, _StoredRow], dict[str, _StoredRow]]:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"], force_refresh=True
                )
                return (
                    {record_id: dict(row.values) for record_id, row in self._managed_rows_by_id(current["Payees"], "Payees").items()},
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["MixedUseExpenses"], "MixedUseExpenses"),
                    self._managed_rows_by_id(current["RecurringSchedules"], "RecurringSchedules"),
                )

            def is_applied(state: Any) -> bool:
                current_payees, current_transactions, current_mixed, current_schedules = state
                return (
                    target_id in current_payees
                    and not any(item in current_payees for item in source_ids)
                    and all(
                        _clean_text(row.values.get("payee_id"), "Payee") != source_id
                        for source_id in source_ids
                        for row in (
                            *current_transactions.values(),
                            *current_mixed.values(),
                            *current_schedules.values(),
                        )
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
                    and all(
                        record_id in current_schedules
                        and _clean_text(current_schedules[record_id].values.get("payee_id"), "Payee") == target_id
                        for record_id in schedule_updates
                    )
                )

            def is_unchanged(state: Any) -> bool:
                current_payees, current_transactions, current_mixed, current_schedules = state
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
                ) and all(
                    record_id in current_schedules and current_schedules[record_id].values == row.values
                    for record_id, row in schedule_updates.items()
                )

            def refresh_requests() -> None:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"],
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
                    self._managed_rows_by_id(
                        current["RecurringSchedules"], "RecurringSchedules"
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
                current_schedules = self._managed_rows_by_id(
                    current["RecurringSchedules"], "RecurringSchedules"
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
                    self._managed_update_request(
                        "RecurringSchedules", current_schedules[record_id], "payee_id", target_id
                    )
                    for record_id in schedule_updates
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
                invalidate=("Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"),
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
        with self._workbook_locks.ledger, self._workbook_locks.payee:
            snapshot = self._snapshot(
                ["Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"], force_refresh=True
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
                for row in (
                    *snapshot["Transactions"],
                    *snapshot["MixedUseExpenses"],
                    *snapshot["RecurringSchedules"],
                )
            )
            if references:
                raise StorageConflictError(
                    f"This payee is referenced by {references} records. Merge it or unassign it first."
                )
            request = self._managed_delete_request("Payees", payee_rows[payee_id])

            def read_state() -> tuple[dict[str, _StoredRow], dict[str, _StoredRow], dict[str, _StoredRow], dict[str, _StoredRow]]:
                current = self._snapshot(
                    ["Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Payees"], "Payees"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["MixedUseExpenses"], "MixedUseExpenses"),
                    self._managed_rows_by_id(current["RecurringSchedules"], "RecurringSchedules"),
                )

            def references_present(state: Any) -> bool:
                _, current_transactions, current_mixed, current_schedules = state
                return any(
                    _clean_text(row.values.get("payee_id"), "Payee") == payee_id
                    for row in (
                        *current_transactions.values(),
                        *current_mixed.values(),
                        *current_schedules.values(),
                    )
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
                invalidate=("Payees", "Transactions", "MixedUseExpenses", "RecurringSchedules"),
            )
            return {"status": "fully_applied"}

    delete_payee = remove_payee

    def _payee_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_payees(_force_refresh=force_refresh)}

__all__ = ['PayeesMixin']
