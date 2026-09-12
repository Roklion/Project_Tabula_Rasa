"""Google Sheets persistence for recurring Expense schedules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import uuid4

from tabula_rasa.mixed_use import MIXED_USE_SOURCE_TYPE, validate_mixed_use_allocation
from tabula_rasa.recurrence import (
    next_occurrence,
    occurrence_id,
    occurrences_between,
    normalize_unit,
)
from .errors import StorageConflictError, StorageNotFoundError, StorageValidationError
from .schema import WORKSHEET_HEADERS
from .validation import (
    _as_bool,
    _clean_text,
    decode_receipt_references,
    _encode_tag_ids,
    _iso_date,
    _normalize_tag_ids,
    _positive_amount,
    _positive_integer,
    _validate_recurring_provenance,
    _validate_unique_recurring_occurrences,
    _utc_now,
    normalize_payee_name,
    normalize_tag_name,
)


def _as_date(value: Any) -> date:
    return date.fromisoformat(_iso_date(value))


class RecurringMixin:
    """Schedule reads and bounded recurring Expense mutations."""

    @staticmethod
    def _logical_record_matches(
        existing: Mapping[str, Any] | None,
        expected: Mapping[str, Any],
        *,
        ignored: frozenset[str] = frozenset(),
    ) -> bool:
        if existing is None:
            return False
        return all(
            str(existing.get(field, "") or "") == str(value or "")
            for field, value in expected.items()
            if field not in ignored
        )

    @staticmethod
    def _schedule_status(value: Any) -> str:
        status = _clean_text(value, "Schedule status", required=True).casefold()
        if status not in {"active", "paused", "ended"}:
            raise StorageValidationError("Schedule status must be active, paused, or ended")
        return status

    def _schedule_template(
        self,
        data: Mapping[str, Any],
        *,
        schedule_id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        account_lookup: Mapping[str, Any] | None = None,
        category_lookup: Mapping[str, Any] | None = None,
        payee_lookup: Mapping[str, Any] | None = None,
        tag_lookup: Mapping[str, Any] | None = None,
        require_active_references: bool = False,
    ) -> dict[str, str]:
        schedule_id = _clean_text(schedule_id or data.get("schedule_id") or data.get("id"), "Schedule ID") or str(uuid4())
        name = _clean_text(data.get("name"), "Schedule name", required=True)
        kind = _clean_text(data.get("kind", "Expense"), "Schedule kind", required=True).title()
        if kind != "Expense":
            raise StorageValidationError("Recurring schedules support Expense records only")
        try:
            unit = normalize_unit(data.get("recurrence_unit", data.get("unit", "month"))).value
        except ValueError as exc:
            raise StorageValidationError(str(exc)) from exc
        source_kind = _clean_text(data.get("source_kind", "transaction"), "Source kind").casefold()
        if source_kind not in {"transaction", "mixed_use"}:
            raise StorageValidationError("Source kind must be transaction or mixed_use")
        interval = _positive_integer(
            data.get("recurrence_interval", data.get("interval", 1)),
            "Recurrence interval",
        )
        anchor = _iso_date(data.get("anchor_date", data.get("start_date", data.get("txn_date"))))
        start = _iso_date(data.get("start_date", anchor))
        status = self._schedule_status(data.get("status", "active"))
        end_value = _clean_text(data.get("end_date"), "Schedule end date")
        end = _iso_date(end_value) if end_value else ""
        if end and end < start and status != "ended":
            raise StorageValidationError("Schedule end date must not precede its start date")
        if anchor != start:
            # The first occurrence is the anchor; exposing two dates that differ
            # makes a schedule ambiguous and causes month/year drift.
            raise StorageValidationError("Schedule anchor date must equal its start date")
        account_id = _clean_text(data.get("account_id"), "Account", required=True)
        category_id = _clean_text(data.get("category_id"), "Category", required=True)
        accounts = account_lookup if account_lookup is not None else self._account_lookup(force_refresh=True)
        categories = category_lookup if category_lookup is not None else self._category_lookup(force_refresh=True)
        if account_id not in accounts:
            raise StorageValidationError("Source account does not exist")
        if require_active_references and not _as_bool(
            accounts[account_id].get("active"), "Account active"
        ):
            raise StorageValidationError("Source account is inactive")
        if category_id not in categories or categories[category_id].get("kind") != "Expense":
            raise StorageValidationError("Category kind does not match transaction kind")
        payee_id = _clean_text(data.get("payee_id"), "Payee")
        payees = payee_lookup if payee_lookup is not None else self._payee_lookup(force_refresh=True)
        if payee_id and payee_id not in payees:
            raise StorageValidationError("Payee does not exist")
        if payee_id and require_active_references and not _as_bool(
            payees[payee_id].get("active"), "Payee active"
        ):
            raise StorageValidationError("Payee is inactive")
        tags = _normalize_tag_ids(data.get("tag_ids", ""))
        known_tags = tag_lookup if tag_lookup is not None else self._tag_lookup(force_refresh=True)
        if any(tag not in known_tags for tag in tags):
            raise StorageValidationError("Tag does not exist")
        if require_active_references and any(
            not _as_bool(known_tags[tag].get("active"), "Tag active")
            for tag in tags
        ):
            raise StorageValidationError("Tag is inactive")
        try:
            receipt_references = decode_receipt_references(data.get("receipt_references", ""))
        except StorageValidationError as exc:
            raise StorageValidationError("Receipts cannot be part of a recurring template") from exc
        if receipt_references:
            raise StorageValidationError("Receipts cannot be part of a recurring template")
        timestamp = created_at or _utc_now()
        allocation = None
        if source_kind == "mixed_use":
            try:
                allocation = validate_mixed_use_allocation(
                    data.get("total_expense", data.get("amount")),
                    data.get("business_use_percentage", "100"),
                )
            except Exception as exc:
                raise StorageValidationError(str(exc)) from exc
        allocation_rationale = _clean_text(
            data.get("allocation_rationale"),
            "Allocation rationale",
            required=source_kind == "mixed_use",
        )
        return {
            "id": schedule_id,
            "name": name,
            "kind": "Expense",
            "source_kind": source_kind,
            "recurrence_unit": unit,
            "recurrence_interval": str(interval),
            "anchor_date": start,
            "start_date": start,
            "end_date": end,
            "status": status,
            "amount": _positive_amount(
                data.get("amount") if source_kind == "transaction" else allocation.allocated_amount
            ),
            "total_expense": allocation.total_expense if allocation else "",
            "business_use_percentage": allocation.business_use_percentage if allocation else "",
            "account_id": account_id,
            "category_id": category_id,
            "payee_id": payee_id,
            "description": _clean_text(data.get("description"), "Description"),
            "reference": _clean_text(data.get("reference"), "Reference"),
            "allocation_rationale": allocation_rationale,
            "tag_ids": _encode_tag_ids(tags),
            "created_at": timestamp,
            "updated_at": updated_at or timestamp,
            "attention_code": _clean_text(data.get("attention_code"), "Attention code"),
            "attention_at": _clean_text(data.get("attention_at"), "Attention timestamp"),
        }

    def _resolve_recurring_inline_references(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Resolve Add-form payee/tag values after non-reference validation."""
        resolved = dict(data)
        payee_id = _clean_text(resolved.get("payee_id"), "Payee")
        new_payee_name = _clean_text(resolved.get("new_payee_name"), "New payee")
        if payee_id and new_payee_name:
            raise StorageValidationError("Choose an existing payee or add a new payee")
        if not payee_id and new_payee_name:
            resolved["payee_id"] = self.create_payee(new_payee_name)["id"]
        resolved["new_payee_name"] = ""
        tag_ids = _normalize_tag_ids(resolved.get("tag_ids", ""))
        new_tag_name = _clean_text(resolved.get("new_tag_name"), "New tag")
        if new_tag_name:
            new_tag_id = self.create_tag(new_tag_name)["id"]
            if new_tag_id not in tag_ids:
                tag_ids.append(new_tag_id)
        resolved["tag_ids"] = tag_ids
        resolved["new_tag_name"] = ""
        return resolved

    def _inline_references_match_existing_schedule(
        self, data: Mapping[str, Any], existing: Mapping[str, Any]
    ) -> bool:
        new_payee_name = _clean_text(data.get("new_payee_name"), "New payee")
        if new_payee_name:
            payee = next(
                (
                    item
                    for item in self.list_payees(_force_refresh=True)
                    if normalize_payee_name(item["name"]) == normalize_payee_name(new_payee_name)
                ),
                None,
            )
            if payee is None or str(existing.get("payee_id", "")) != str(payee["id"]):
                return False
        new_tag_name = _clean_text(data.get("new_tag_name"), "New tag")
        if new_tag_name:
            tag = next(
                (
                    item
                    for item in self.list_tags(_force_refresh=True)
                    if normalize_tag_name(item["name"]) == normalize_tag_name(new_tag_name)
                ),
                None,
            )
            if tag is None or str(tag["id"]) not in _normalize_tag_ids(existing.get("tag_ids", "")):
                return False
        return True

    def _prevalidate_recurring_form(self, data: Mapping[str, Any]) -> dict[str, str]:
        """Validate a new schedule before creating inline managed references."""
        preflight = dict(data)
        preflight["payee_id"] = _clean_text(preflight.get("payee_id"), "Payee")
        preflight["tag_ids"] = _normalize_tag_ids(preflight.get("tag_ids", ""))
        preflight["new_payee_name"] = ""
        preflight["new_tag_name"] = ""
        return self._schedule_template(
            preflight,
            require_active_references=True,
        )

    @staticmethod
    def _partial_recurring_record_matches(
        actual: Mapping[str, Any],
        expected: Mapping[str, Any],
        *,
        ignored: frozenset[str],
    ) -> bool:
        return all(
            str(actual.get(field, "") or "") == str(value or "")
            for field, value in expected.items()
            if field not in ignored
        )

    @staticmethod
    def _decode_schedule(values: Mapping[str, Any]) -> dict[str, str]:
        """Normalize stored schedule fields without validating references."""
        schedule = {header: str(values.get(header, "") or "") for header in WORKSHEET_HEADERS["RecurringSchedules"]}
        schedule["id"] = _clean_text(schedule.get("id"), "Schedule ID")
        schedule["kind"] = schedule.get("kind", "Expense").strip().title()
        schedule["source_kind"] = schedule.get("source_kind", "transaction").strip().casefold()
        try:
            schedule["recurrence_unit"] = normalize_unit(schedule.get("recurrence_unit", "month")).value
        except ValueError:
            schedule["recurrence_unit"] = str(schedule.get("recurrence_unit", ""))
        try:
            schedule["status"] = RecurringMixin._schedule_status(schedule.get("status", "active"))
        except StorageValidationError:
            schedule["status"] = str(schedule.get("status", ""))
        attention_messages = {
            "validation": "Invalid template references; edit the schedule.",
            "storage": "Storage unavailable; retry or inspect the workbook.",
        }
        schedule["attention_message"] = attention_messages.get(
            schedule.get("attention_code", ""), ""
        )
        if not schedule["id"]:
            schedule["attention_code"] = "validation"
            schedule["attention_message"] = "Missing schedule ID; edit the workbook."
        try:
            schedule["tag_ids"] = _encode_tag_ids(_normalize_tag_ids(schedule.get("tag_ids", "")))
        except StorageValidationError:
            schedule["tag_ids"] = str(values.get("tag_ids", "") or "")
        return schedule

    @staticmethod
    def _validate_recurring_occurrence_rows(
        rows,
        schedule_values: Mapping[str, Mapping[str, Any]],
        label: str,
        *,
        mixed_source: bool,
        filter_schedule_id: str | None = None,
    ) -> None:
        for row in rows:
            values = row.values
            schedule_id = str(values.get("recurring_schedule_id", "") or "")
            if filter_schedule_id is not None and schedule_id.strip() != filter_schedule_id:
                continue
            _validate_recurring_provenance(values, label)
            if not schedule_id:
                continue
            if values.get("kind") != "Expense":
                raise StorageValidationError(f"{label} recurring rows must be an Expense")
            if schedule_id not in schedule_values:
                raise StorageValidationError(f"{label} references an unknown recurring schedule")
            _iso_date(values.get("recurring_scheduled_date"))
            expected_source_kind = "mixed_use" if mixed_source else (
                "mixed_use"
                if values.get("source_type") == MIXED_USE_SOURCE_TYPE
                and values.get("source_id")
                else "transaction"
            )
            if (
                values.get("recurring_source_kind") != expected_source_kind
                or schedule_values[schedule_id].get("source_kind") != expected_source_kind
            ):
                raise StorageValidationError(f"{label} recurring source kind is invalid")
            if values.get("recurring_occurrence_type") not in {"initial", "generated"}:
                raise StorageValidationError(f"{label} recurring occurrence type is invalid")

    @staticmethod
    def _validate_mixed_use_projection_parity(
        source: Mapping[str, Any], projection: Mapping[str, Any]
    ) -> None:
        for field in (
            "recurring_schedule_id",
            "recurring_scheduled_date",
            "recurring_source_kind",
            "recurring_occurrence_type",
        ):
            if str(source.get(field, "") or "") != str(projection.get(field, "") or ""):
                raise StorageValidationError(
                    "Mixed-use source and projection recurring provenance does not match"
                )

    def _validate_recurring_references(self) -> None:
        schedules = self._snapshot(("RecurringSchedules",), force_refresh=True)["RecurringSchedules"]
        raw_schedule_ids = [str(row.values.get("id", "") or "") for row in schedules]
        schedule_ids = [schedule_id.strip() for schedule_id in raw_schedule_ids]
        if (
            any(
                not schedule_id or raw_schedule_id != schedule_id
                for raw_schedule_id, schedule_id in zip(raw_schedule_ids, schedule_ids)
            )
            or len(schedule_ids) != len(set(schedule_ids))
        ):
            raise StorageValidationError("Recurring schedule IDs are missing or duplicated")
        schedule_values = {str(row.values.get("id", "")): row.values for row in schedules}
        accounts = self._account_lookup(force_refresh=True)
        categories = self._category_lookup(force_refresh=True)
        payees = self._payee_lookup(force_refresh=True)
        tags = self._tag_lookup(force_refresh=True)
        transaction_rows = self._rows("Transactions", force_refresh=True)
        mixed_rows = self._rows("MixedUseExpenses", force_refresh=True)
        self._validate_recurring_occurrence_rows(
            transaction_rows,
            schedule_values,
            "Transaction",
            mixed_source=False,
        )
        self._validate_recurring_occurrence_rows(
            mixed_rows,
            schedule_values,
            "Mixed-use source",
            mixed_source=True,
        )
        _validate_unique_recurring_occurrences(
            [row.values for row in transaction_rows],
            "Transactions",
        )
        _validate_unique_recurring_occurrences(
            [row.values for row in mixed_rows],
            "Mixed-use expenses",
        )
        for row in schedules:
            self._schedule_template(
                row.values,
                schedule_id=row.values.get("id"),
                created_at=row.values.get("created_at"),
                updated_at=row.values.get("updated_at"),
                account_lookup=accounts,
                category_lookup=categories,
                payee_lookup=payees,
                tag_lookup=tags,
            )

    def list_recurring_schedules(
        self,
        *,
        _force_refresh: bool = False,
        transaction_rows: list[Any] | None = None,
        mixed_rows: list[Any] | None = None,
        projections: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        rows = self._rows("RecurringSchedules", force_refresh=_force_refresh)
        transaction_rows = (
            transaction_rows
            if transaction_rows is not None
            else self._rows("Transactions", force_refresh=_force_refresh)
        )
        mixed_rows = (
            mixed_rows
            if mixed_rows is not None
            else self._rows("MixedUseExpenses", force_refresh=_force_refresh)
        )
        projections = projections or {
            str(row.values.get("id", "")): row.values for row in transaction_rows
        }
        result = []
        for row in rows:
            schedule = self._decode_schedule(row.values)
            try:
                schedule["next_due_date"] = self._next_due_for_schedule(
                    schedule,
                    transaction_rows=transaction_rows,
                    mixed_rows=mixed_rows,
                    projections=projections,
                )
            except (StorageValidationError, ValueError, TypeError):
                schedule["next_due_date"] = ""
            try:
                latest = self._latest_current_occurrence_date(
                    schedule["id"], schedule.get("source_kind"),
                    transaction_rows=transaction_rows, mixed_rows=mixed_rows,
                    projections=projections,
                )
            except (StorageValidationError, ValueError, TypeError):
                latest = None
            schedule["latest_current_occurrence_date"] = latest.isoformat() if latest else ""
            result.append(schedule)
        return sorted(result, key=lambda item: (item["start_date"], item["id"]), reverse=True)

    def get_recurring_schedule(self, schedule_id: str, *, _force_refresh: bool = False) -> dict[str, str]:
        schedule_id = _clean_text(schedule_id, "Schedule ID", required=True)
        for item in self.list_recurring_schedules(_force_refresh=_force_refresh):
            if item["id"] == schedule_id:
                return item
        raise StorageNotFoundError("Recurring schedule no longer exists")

    def _next_due_for_schedule(
        self,
        schedule: Mapping[str, str],
        *,
        transaction_rows=None,
        mixed_rows=None,
        projections=None,
    ) -> str:
        if schedule["status"] != "active":
            return ""
        current = _as_date(schedule["start_date"])
        latest = self._latest_current_occurrence_date(
            schedule["id"], schedule.get("source_kind"),
            transaction_rows=transaction_rows,
            mixed_rows=mixed_rows,
            projections=projections,
        )
        if latest:
            current = next_occurrence(_as_date(schedule["anchor_date"]), schedule["recurrence_unit"], int(schedule["recurrence_interval"]), latest)
        if schedule.get("end_date") and current.isoformat() > schedule["end_date"]:
            return ""
        return current.isoformat()

    def _latest_current_occurrence_date(
        self,
        schedule_id: str,
        source_kind: str | None,
        *,
        transaction_rows=None,
        mixed_rows=None,
        projections=None,
    ) -> date | None:
        if source_kind == "mixed_use":
            rows = mixed_rows if mixed_rows is not None else self._rows("MixedUseExpenses", force_refresh=False)
            if projections is None:
                projections = {
                    str(row.values.get("id", "")): row.values
                    for row in (
                        transaction_rows
                        if transaction_rows is not None
                        else self._rows("Transactions", force_refresh=False)
                    )
                }
            field = "recurring_scheduled_date"
        else:
            rows = transaction_rows if transaction_rows is not None else self._rows("Transactions", force_refresh=False)
            field = "recurring_scheduled_date"
        dates = []
        for row in rows:
            if row.values.get("recurring_schedule_id") != schedule_id or not row.values.get(field):
                continue
            if source_kind == "mixed_use":
                projection = projections.get(str(row.values.get("linked_transaction_id", "")))
                self._valid_mixed_use_projection(row.values, projection)
                self._validate_mixed_use_projection_parity(row.values, projection)
            try:
                dates.append(_as_date(row.values[field]))
            except (StorageValidationError, TypeError, ValueError):
                continue
        return max(dates) if dates else None

    def create_recurring_schedule(self, **data: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            schedule = self._schedule_template(data)
            existing = {
                str(row.values.get("id")): row.values
                for row in self._rows("RecurringSchedules", force_refresh=True)
            }
            if schedule["id"] in existing:
                if not self._logical_record_matches(
                    existing[schedule["id"]],
                    schedule,
                    ignored=frozenset({"created_at", "updated_at", "attention_code", "attention_at"}),
                ):
                    raise StorageConflictError("Recurring schedule ID is already in use")
            else:
                self._append("RecurringSchedules", schedule)
            return self.get_recurring_schedule(schedule["id"], _force_refresh=True)

    def edit_recurring_schedule(self, schedule_id: str, *, expected_schedule: Mapping[str, Any] | None = None, **changes: Any) -> dict[str, str]:
        with self._workbook_locks.ledger:
            current = self.get_recurring_schedule(schedule_id, _force_refresh=True)
            if expected_schedule is not None:
                for field in WORKSHEET_HEADERS["RecurringSchedules"]:
                    if field in {"updated_at", "attention_code", "attention_at"}:
                        continue
                    if str(expected_schedule.get(field, "") or "") != str(current.get(field, "") or ""):
                        raise StorageConflictError("The recurring schedule changed; refresh it before editing.")
            if "source_kind" in changes:
                requested_source_kind = _clean_text(
                    changes["source_kind"], "Source kind", required=True
                ).casefold()
                if requested_source_kind != current.get("source_kind"):
                    raise StorageValidationError(
                        "A recurring schedule's source kind cannot be changed"
                    )
            if "status" in changes:
                target_status = self._schedule_status(changes["status"])
                current_status = current.get("status")
                if current_status == "ended" and target_status != "ended":
                    raise StorageValidationError(
                        "Ended schedules cannot be reactivated"
                    )
            merged = {**current, **changes}
            merged.pop("next_due_date", None)
            updated = self._schedule_template(merged, schedule_id=schedule_id,
                                              created_at=current["created_at"], updated_at=_utc_now())
            row = self._find_row("RecurringSchedules", schedule_id)
            self._replace_row("RecurringSchedules", row, updated)
            return self.get_recurring_schedule(schedule_id, _force_refresh=True)

    def pause_recurring_schedule(self, schedule_id: str, *, expected_schedule: Mapping[str, Any] | None = None) -> dict[str, str]:
        current = self.get_recurring_schedule(schedule_id, _force_refresh=True)
        if current.get("status") != "active":
            raise StorageConflictError("Only an active schedule can be paused")
        return self.edit_recurring_schedule(schedule_id, expected_schedule=expected_schedule, status="paused")

    def resume_recurring_schedule(self, schedule_id: str, *, expected_schedule: Mapping[str, Any] | None = None) -> dict[str, str]:
        current = self.get_recurring_schedule(schedule_id, _force_refresh=True)
        if current.get("status") != "paused":
            raise StorageConflictError("Only a paused schedule can be resumed")
        return self.edit_recurring_schedule(schedule_id, expected_schedule=expected_schedule, status="active")

    def end_recurring_schedule(self, schedule_id: str, *, expected_schedule: Mapping[str, Any] | None = None) -> dict[str, str]:
        current = self.get_recurring_schedule(schedule_id, _force_refresh=True)
        if current.get("status") == "ended":
            raise StorageConflictError("Schedule is already ended")
        return self.edit_recurring_schedule(
            schedule_id, expected_schedule=expected_schedule, status="ended", end_date=date.today().isoformat(),
        )

    def _recurring_occurrence(self, schedule: Mapping[str, str], scheduled: date, *, role: str) -> dict[str, str]:
        transaction_id = occurrence_id(schedule["id"], scheduled, role)
        return self._prepare_transaction({
            "id": transaction_id,
            "txn_date": scheduled,
            "kind": "Expense",
            "amount": schedule["amount"],
            "account_id": schedule["account_id"],
            "category_id": schedule["category_id"],
            "payee_id": schedule.get("payee_id", ""),
            "description": schedule.get("description", ""),
            "reference": schedule.get("reference", ""),
            "tag_ids": schedule.get("tag_ids", ""),
            "receipt_references": "",
            "recurring_schedule_id": schedule["id"],
            "recurring_scheduled_date": scheduled.isoformat(),
            "recurring_source_kind": schedule["source_kind"],
            "recurring_occurrence_type": role,
        })

    def _recurring_mixed_occurrence(
        self, schedule: Mapping[str, str], scheduled: date, *, role: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        source_id = occurrence_id(schedule["id"], scheduled, f"{role}-source")
        transaction_id = occurrence_id(schedule["id"], scheduled, f"{role}-projection")
        return self._prepare_mixed_use_expense({
            "source_id": source_id,
            "linked_transaction_id": transaction_id,
            "txn_date": scheduled,
            "total_expense": schedule["total_expense"],
            "business_use_percentage": schedule["business_use_percentage"],
            "account_id": schedule["account_id"],
            "category_id": schedule["category_id"],
            "payee_id": schedule.get("payee_id", ""),
            "description": schedule.get("description", ""),
            "reference": schedule.get("reference", ""),
            "allocation_rationale": schedule.get("allocation_rationale", ""),
            "tag_ids": schedule.get("tag_ids", ""),
            "receipt_references": "",
            "recurring_schedule_id": schedule["id"],
            "recurring_scheduled_date": scheduled.isoformat(),
            "recurring_source_kind": schedule["source_kind"],
            "recurring_occurrence_type": role,
        })

    @staticmethod
    def _valid_mixed_use_projection(
        source: Mapping[str, Any], projection: Mapping[str, Any] | None
    ) -> bool:
        if projection is None:
            raise StorageValidationError(
                "Mixed-use source has no linked projection"
            )
        if (
            projection.get("source_type") != MIXED_USE_SOURCE_TYPE
            or str(projection.get("source_id", "")) != str(source.get("id", ""))
        ):
            raise StorageValidationError(
                "Mixed-use source projection does not point back to its source"
            )
        return True

    def _existing_recurring_dates(
        self,
        schedule_id: str,
        source_kind: str = "transaction",
        *,
        transaction_rows=None,
        mixed_rows=None,
        projections=None,
    ) -> set[str]:
        if source_kind == "mixed_use":
            rows = mixed_rows if mixed_rows is not None else self._rows("MixedUseExpenses", force_refresh=False)
            if projections is None:
                projections = {
                    str(row.values.get("id", "")): row.values
                    for row in (
                        transaction_rows
                        if transaction_rows is not None
                        else self._rows("Transactions", force_refresh=False)
                    )
                }
            return {str(row.values.get("recurring_scheduled_date", "")) for row in rows
                    if row.values.get("recurring_schedule_id") == schedule_id
                    and self._valid_mixed_use_projection(
                        row.values,
                        projections.get(str(row.values.get("linked_transaction_id", ""))),
                    )}
        rows = transaction_rows if transaction_rows is not None else self._rows("Transactions", force_refresh=False)
        return {
            str(row.values.get("recurring_scheduled_date", ""))
            for row in rows
            if row.values.get("recurring_schedule_id") == schedule_id
        }

    def reconcile_recurring_schedules(self, *, as_of: date | str | None = None) -> dict[str, Any]:
        with self._workbook_locks.ledger:
            return self._reconcile_recurring_schedules(as_of=as_of)

    def _clear_recurring_attention(self, schedule_id: str) -> None:
        try:
            row = self._find_row("RecurringSchedules", schedule_id)
            if row.values.get("attention_code") or row.values.get("attention_at"):
                updated = dict(row.values)
                updated["attention_code"] = ""
                updated["attention_at"] = ""
                self._replace_row("RecurringSchedules", row, updated)
        except Exception:
            pass

    def _reconcile_recurring_schedules(self, *, as_of: date | str | None = None) -> dict[str, Any]:
        cutoff = _iso_date(as_of or date.today())
        generated: list[dict[str, str]] = []
        attention: dict[str, str] = {}
        transaction_rows = self._rows("Transactions", force_refresh=True)
        mixed_rows = self._rows("MixedUseExpenses", force_refresh=True)
        transaction_rows_by_schedule: dict[str, list[Any]] = {}
        mixed_rows_by_schedule: dict[str, list[Any]] = {}
        for row in transaction_rows:
            transaction_rows_by_schedule.setdefault(
                str(row.values.get("recurring_schedule_id", "") or "").strip(), []
            ).append(row)
        for row in mixed_rows:
            mixed_rows_by_schedule.setdefault(
                str(row.values.get("recurring_schedule_id", "") or "").strip(), []
            ).append(row)
        projections = {
            str(row.values.get("id", "")): row.values for row in transaction_rows
        }
        accounts = self._account_lookup(force_refresh=True)
        categories = self._category_lookup(force_refresh=True)
        payees = self._payee_lookup(force_refresh=True)
        tags = self._tag_lookup(force_refresh=True)
        schedules = self.list_recurring_schedules(
            _force_refresh=True,
            transaction_rows=transaction_rows,
            mixed_rows=mixed_rows,
            projections=projections,
        )
        schedule_values = {schedule["id"]: schedule for schedule in schedules if schedule["id"]}
        schedule_ids = [schedule["id"] for schedule in schedules if schedule["id"]]
        if len(schedule_ids) != len(set(schedule_ids)):
            raise StorageValidationError("Recurring schedule IDs are duplicated")
        for row in (*transaction_rows, *mixed_rows):
            if str(row.values.get("recurring_schedule_id", "") or "").strip() not in schedule_ids:
                _validate_recurring_provenance(row.values, "Recurring occurrence")
        mixed_sources_by_id = {
            str(row.values.get("id", "")): row.values for row in mixed_rows
        }
        for schedule in schedules:
            try:
                if not schedule["id"]:
                    raise StorageValidationError("Schedule ID is missing")
                _validate_unique_recurring_occurrences(
                    [
                        row.values
                        for row in transaction_rows_by_schedule.get(schedule["id"], [])
                    ],
                    "Transactions",
                )
                _validate_unique_recurring_occurrences(
                    [
                        row.values
                        for row in mixed_rows_by_schedule.get(schedule["id"], [])
                    ],
                    "Mixed-use expenses",
                )
                self._validate_recurring_occurrence_rows(
                    transaction_rows_by_schedule.get(schedule["id"], []),
                    schedule_values,
                    "Transaction",
                    mixed_source=False,
                    filter_schedule_id=schedule["id"],
                )
                self._validate_recurring_occurrence_rows(
                    mixed_rows_by_schedule.get(schedule["id"], []),
                    schedule_values,
                    "Mixed-use source",
                    mixed_source=True,
                    filter_schedule_id=schedule["id"],
                )
                for source_row in mixed_rows_by_schedule.get(schedule["id"], []):
                    source = source_row.values
                    projection = projections.get(str(source.get("linked_transaction_id", "") or ""))
                    self._valid_mixed_use_projection(source, projection)
                    self._validate_mixed_use_projection_parity(source, projection)
                for projection_row in transaction_rows_by_schedule.get(schedule["id"], []):
                    projection = projection_row.values
                    if projection.get("source_type") != MIXED_USE_SOURCE_TYPE:
                        continue
                    source = mixed_sources_by_id.get(str(projection.get("source_id", "") or ""))
                    self._valid_mixed_use_projection(source or {}, projection)
                    self._validate_mixed_use_projection_parity(source or {}, projection)
                schedule = self._schedule_template(
                    schedule,
                    schedule_id=schedule["id"],
                    created_at=schedule.get("created_at"),
                    updated_at=schedule.get("updated_at"),
                    account_lookup=accounts,
                    category_lookup=categories,
                    payee_lookup=payees,
                    tag_lookup=tags,
                )
                if schedule["status"] != "active":
                    self._clear_recurring_attention(schedule["id"])
                    continue
                end = min(cutoff, schedule["end_date"]) if schedule.get("end_date") else cutoff
                existing = self._existing_recurring_dates(
                    schedule["id"], schedule.get("source_kind", "transaction"),
                    transaction_rows=transaction_rows,
                    mixed_rows=mixed_rows,
                    projections=projections,
                )
                latest = self._latest_current_occurrence_date(
                    schedule["id"], schedule.get("source_kind"),
                    transaction_rows=transaction_rows,
                    mixed_rows=mixed_rows,
                    projections=projections,
                )
                candidate_start = _as_date(schedule["start_date"])
                if latest is not None:
                    candidate_start = next_occurrence(
                        _as_date(schedule["anchor_date"]), schedule["recurrence_unit"],
                        int(schedule["recurrence_interval"]), latest,
                    )
                for scheduled in occurrences_between(_as_date(schedule["anchor_date"]), schedule["recurrence_unit"], int(schedule["recurrence_interval"]), candidate_start, _as_date(end)):
                    key = scheduled.isoformat()
                    if key in existing:
                        continue
                    if schedule.get("source_kind") == "mixed_use":
                        source, record = self._recurring_mixed_occurrence(schedule, scheduled, role="generated")
                        persisted_source = self.create_mixed_use_expense(
                            _allow_recurring_provenance=True, **source
                        )
                        generated.append(persisted_source)
                    else:
                        record = self._recurring_occurrence(schedule, scheduled, role="generated")
                        self._append("Transactions", record)
                        generated.append(record)
                    existing.add(key)
            except Exception as exc:  # one bad schedule must not block others
                code = "validation" if isinstance(exc, StorageValidationError) else "storage"
                schedule_id = schedule.get("id", "")
                if schedule_id:
                    attention[schedule_id] = code
                try:
                    if not schedule_id:
                        continue
                    row = self._find_row("RecurringSchedules", schedule_id)
                    updated = dict(row.values)
                    updated["attention_code"] = code
                    updated["attention_at"] = _utc_now()
                    self._replace_row("RecurringSchedules", row, updated)
                except Exception:
                    pass
            else:
                self._clear_recurring_attention(schedule["id"])
        return {"generated": generated, "attention": attention}

    # Clear aliases make the public operation discoverable without coupling UI
    # code to the reconciliation wording.
    generate_recurring_expenses = reconcile_recurring_schedules
    reconcile_recurring_expenses = reconcile_recurring_schedules

    def create_recurring_expense(self, **data: Any) -> dict[str, Any]:
        """Create one schedule and its initial Expense occurrence."""
        with self._workbook_locks.ledger:
            preflight = self._prevalidate_recurring_form(data)
            existing_schedules = {
                str(row.values.get("id")): row.values
                for row in self._rows("RecurringSchedules", force_refresh=True)
            }
            if (
                preflight["id"] in existing_schedules
                and (data.get("new_payee_name") or data.get("new_tag_name"))
                and not self._inline_references_match_existing_schedule(
                    data, existing_schedules[preflight["id"]]
                )
            ):
                raise StorageConflictError(
                    "Recurring schedule ID is already in use; inline references were not created"
                )
            data = self._resolve_recurring_inline_references(data)
            schedule = self._schedule_template(data, schedule_id=preflight["id"])
            initial_date = _as_date(schedule["start_date"])
            initial_id = _clean_text(data.get("transaction_id"), "Transaction ID") or occurrence_id(schedule["id"], initial_date, "initial")
            initial = self._recurring_occurrence(schedule, initial_date, role="initial")
            initial["id"] = initial_id
            existing = {
                str(row.values.get("id")): row.values
                for row in self._rows("RecurringSchedules", force_refresh=True)
            }
            if schedule["id"] in existing:
                if not self._logical_record_matches(
                    existing[schedule["id"]], schedule,
                    ignored=frozenset({"created_at", "updated_at", "attention_code", "attention_at"}),
                ):
                    raise StorageConflictError("Recurring schedule ID is already in use")
            else:
                self._append("RecurringSchedules", schedule)
            current = {str(row.values.get("id")): row.values for row in self._rows("Transactions", force_refresh=True)}
            matching_dates = [
                row for row in current.values()
                if row.get("recurring_schedule_id") == schedule["id"]
                and row.get("recurring_scheduled_date") == initial_date.isoformat()
            ]
            if matching_dates:
                if len(matching_dates) != 1 or not self._partial_recurring_record_matches(
                    matching_dates[0], initial,
                    ignored=frozenset({"id", "created_at", "recurring_occurrence_type"}),
                ):
                    raise StorageConflictError(
                        "A recurring occurrence for this schedule and date conflicts with the requested data"
                    )
                self._clear_recurring_attention(schedule["id"])
                return {
                    "schedule": self.get_recurring_schedule(schedule["id"], _force_refresh=True),
                    "transaction": matching_dates[0],
                }
            if initial_id in current:
                if not self._logical_record_matches(
                    current[initial_id], initial,
                    ignored=frozenset({"created_at"}),
                ):
                    raise StorageConflictError("Initial recurring transaction ID is already in use")
            else:
                self._append("Transactions", initial)
            self._clear_recurring_attention(schedule["id"])
            return {"schedule": self.get_recurring_schedule(schedule["id"], _force_refresh=True), "transaction": initial}

    def create_recurring_mixed_use_expense(self, **data: Any) -> dict[str, Any]:
        """Create one mixed-use schedule and its source/projection pair."""
        with self._workbook_locks.ledger:
            data = {**data, "source_kind": "mixed_use"}
            preflight = self._prevalidate_recurring_form(data)
            existing_schedules = {
                str(row.values.get("id")): row.values
                for row in self._rows("RecurringSchedules", force_refresh=True)
            }
            if (
                preflight["id"] in existing_schedules
                and (data.get("new_payee_name") or data.get("new_tag_name"))
                and not self._inline_references_match_existing_schedule(
                    data, existing_schedules[preflight["id"]]
                )
            ):
                raise StorageConflictError(
                    "Recurring schedule ID is already in use; inline references were not created"
                )
            data = self._resolve_recurring_inline_references(data)
            schedule = self._schedule_template(data, schedule_id=preflight["id"])
            scheduled = _as_date(schedule["start_date"])
            source_id = _clean_text(data.get("source_id"), "Mixed-use source ID") or occurrence_id(schedule["id"], scheduled, "initial-source")
            transaction_id = _clean_text(data.get("transaction_id"), "Transaction ID") or occurrence_id(schedule["id"], scheduled, "initial-projection")
            payload = {**data, "source_id": source_id, "linked_transaction_id": transaction_id}
            source, projection = self._prepare_mixed_use_expense(payload)
            for field in ("recurring_schedule_id", "recurring_scheduled_date", "recurring_source_kind", "recurring_occurrence_type"):
                source[field] = projection[field] = {
                    "recurring_schedule_id": schedule["id"],
                    "recurring_scheduled_date": scheduled.isoformat(),
                    "recurring_source_kind": schedule["source_kind"],
                    "recurring_occurrence_type": "initial",
                }[field]
            existing_schedules = {
                str(row.values.get("id")): row.values
                for row in self._rows("RecurringSchedules", force_refresh=True)
            }
            if schedule["id"] in existing_schedules:
                if not self._logical_record_matches(
                    existing_schedules[schedule["id"]], schedule,
                    ignored=frozenset({"created_at", "updated_at", "attention_code", "attention_at"}),
                ):
                    raise StorageConflictError("Recurring schedule ID is already in use")
            else:
                self._append("RecurringSchedules", schedule)
            current_sources = [
                row.values for row in self._rows("MixedUseExpenses", force_refresh=True)
                if row.values.get("recurring_schedule_id") == schedule["id"]
                and row.values.get("recurring_scheduled_date") == scheduled.isoformat()
            ]
            current_transactions = {
                str(row.values.get("id")): row.values
                for row in self._rows("Transactions", force_refresh=True)
            }
            if current_sources:
                if len(current_sources) != 1:
                    raise StorageConflictError(
                        "Multiple mixed-use occurrences exist for this schedule and date"
                    )
                current_source = current_sources[0]
                current_projection = current_transactions.get(
                    str(current_source.get("linked_transaction_id", ""))
                )
                if current_projection is None:
                    raise StorageConflictError(
                        "A mixed-use recurring source exists without its linked projection"
                    )
                if not self._partial_recurring_record_matches(
                    current_source, source,
                    ignored=frozenset({"id", "linked_transaction_id", "created_at", "recurring_occurrence_type"}),
                ) or not self._partial_recurring_record_matches(
                    current_projection, projection,
                    ignored=frozenset({"id", "source_id", "created_at", "recurring_occurrence_type"}),
                ):
                    raise StorageConflictError(
                        "A mixed-use occurrence for this schedule and date conflicts with the requested data"
                    )
                self._clear_recurring_attention(schedule["id"])
                return {
                    "schedule": self.get_recurring_schedule(schedule["id"], _force_refresh=True),
                    "source": current_source,
                    "transaction": current_projection,
                }
            pair = self.create_mixed_use_expense(
                _allow_recurring_provenance=True, **source
            )
            try:
                projection = self._find_row(
                    "Transactions", source["linked_transaction_id"]
                ).values
            except StorageNotFoundError:
                raise StorageConflictError(
                    "Could not find the linked projection for the recurring "
                    "mixed-use expense. The ledger may be inconsistent."
                ) from None
            self._clear_recurring_attention(schedule["id"])
            return {
                "schedule": self.get_recurring_schedule(schedule["id"], _force_refresh=True),
                "source": pair,
                "transaction": projection,
            }


__all__ = ["RecurringMixin"]
