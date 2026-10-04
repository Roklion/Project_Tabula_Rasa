"""Responsibility-focused Google Sheets storage operations."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from uuid import uuid4
from tabula_rasa.reference_data import normalize_merge_ids
from .errors import StorageConflictError
from .errors import StorageNotFoundError
from .errors import StorageValidationError
from .validation import _as_bool
from .validation import _clean_text
from .validation import _encode_tag_ids
from .validation import _normalize_tag_ids
from .validation import _raw_tag_ids_may_contain
from .validation import _utc_now
from .validation import normalize_tag_name
from .base import _StoredRow
from .managed import _ManagedMixin

class TagsMixin(_ManagedMixin):
    """TagsMixin boundary for the Google Sheets facade."""

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
        with self._workbook_locks.tag:
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
        with self._workbook_locks.tag:
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
        target_id, source_ids = normalize_merge_ids(
            target_tag_id, source_tag_ids, "tag"
        )
        with self._workbook_locks.ledger, self._workbook_locks.tag:
            snapshot = self._snapshot(
                ["Tags", "Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"],
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
                    *snapshot["RecurringSchedules"],
                    *snapshot["Assets"],
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
            for title in ("Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"):
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
                dict[str, _StoredRow],
                dict[str, _StoredRow],
            ]:
                current = self._snapshot(
                    ["Tags", "Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Tags"], "Tags"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["Mileage"], "Mileage"),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                    self._managed_rows_by_id(
                        current["RecurringSchedules"], "RecurringSchedules"
                    ),
                    self._managed_rows_by_id(current["Assets"], "Assets"),
                )

            def is_applied(state: Any) -> bool:
                (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                    current_schedules,
                    current_assets,
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
                        *current_schedules.values(),
                        *current_assets.values(),
                    )
                ):
                    return False
                for title, row, expected_value in update_rows.values():
                    current_rows = {
                        "Transactions": current_transactions,
                        "Mileage": current_mileage,
                        "MixedUseExpenses": current_sources,
                        "RecurringSchedules": current_schedules,
                        "Assets": current_assets,
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
                    current_schedules,
                    current_assets,
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
                        "RecurringSchedules": current_schedules,
                        "Assets": current_assets,
                    }[title]
                    current = current_rows.get(
                        _clean_text(row.values.get("id"), "ID", required=True)
                    )
                    if current is None or current.values != row.values:
                        return False
                return True

            def refresh_requests() -> None:
                current_tags, current_transactions, current_mileage, current_sources, current_schedules, current_assets = (
                    fresh_state()
                )
                current_state = (
                    current_tags,
                    current_transactions,
                    current_mileage,
                    current_sources,
                    current_schedules,
                    current_assets,
                )
                if not is_unchanged(current_state):
                    raise StorageConflictError(
                        "Tag records or references changed while the merge was being retried."
                    )
                current_rows_by_title = {
                    "Transactions": current_transactions,
                    "Mileage": current_mileage,
                    "MixedUseExpenses": current_sources,
                    "RecurringSchedules": current_schedules,
                    "Assets": current_assets,
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
                invalidate=("Tags", "Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"),
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
        with self._workbook_locks.ledger, self._workbook_locks.tag:
            snapshot = self._snapshot(
                ["Tags", "Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"],
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
                *snapshot["RecurringSchedules"],
                *snapshot["Assets"],
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
                dict[str, _StoredRow],
                dict[str, _StoredRow],
            ]:
                current = self._snapshot(
                    ["Tags", "Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"],
                    force_refresh=True,
                )
                return (
                    self._managed_rows_by_id(current["Tags"], "Tags"),
                    self._managed_rows_by_id(current["Transactions"], "Transactions"),
                    self._managed_rows_by_id(current["Mileage"], "Mileage"),
                    self._managed_rows_by_id(
                        current["MixedUseExpenses"], "MixedUseExpenses"
                    ),
                    self._managed_rows_by_id(
                        current["RecurringSchedules"], "RecurringSchedules"
                    ),
                    self._managed_rows_by_id(current["Assets"], "Assets"),
                )
            def references_present(state: Any) -> bool:
                _, current_transactions, current_mileage, current_sources, current_schedules, current_assets = state
                return any(
                    tag_id in _normalize_tag_ids(row.values.get("tag_ids", ""))
                    for row in (
                        *current_transactions.values(),
                        *current_mileage.values(),
                        *current_sources.values(),
                        *current_schedules.values(),
                        *current_assets.values(),
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
                invalidate=("Tags", "Transactions", "Mileage", "MixedUseExpenses", "RecurringSchedules", "Assets"),
            )
            return {"status": "fully_applied"}

    delete_tag = remove_tag

    def _tag_lookup(self, *, force_refresh: bool = False) -> dict[str, dict[str, str]]:
        return {item["id"]: item for item in self.list_tags(_force_refresh=force_refresh)}

__all__ = ['TagsMixin']
