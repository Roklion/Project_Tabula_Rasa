from datetime import date
import json

import pytest

from tabula_rasa.storage.google_sheets import StorageConflictError, StorageValidationError
from tests.storage.google_sheets._support import backup_receipt_manifest, rewrite_backup_tables


def _ids(storage):
    return storage.list_accounts()[0]["id"], storage.list_categories(kind="Expense")[0]["id"]


def test_recurring_create_reconcile_is_idempotent(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_expense(
        schedule_id="rent-schedule",
        name="Rent",
        txn_date="2024-01-31",
        recurrence_unit="month",
        recurrence_interval=1,
        amount="10.00",
        account_id=account_id,
        category_id=category_id,
        description="Rent",
    )
    assert result["transaction"]["recurring_schedule_id"] == "rent-schedule"
    assert result["schedule"]["source_kind"] == "transaction"
    assert result["transaction"]["recurring_source_kind"] == "transaction"
    generated = default_storage.reconcile_recurring_schedules(as_of=date(2024, 4, 30))
    assert len(generated["generated"]) == 3
    assert default_storage.reconcile_recurring_schedules(as_of=date(2024, 4, 30))["generated"] == []


def test_recurring_template_rejects_receipts_and_non_expenses(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    with pytest.raises(StorageValidationError, match="Receipts"):
        default_storage.create_recurring_schedule(
            name="Invalid", txn_date="2024-01-01", amount=10,
            account_id=account_id, category_id=category_id,
            receipt_references="[{}]",
        )


def test_recurring_create_resolves_inline_payee_and_tag_values(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_expense(
        schedule_id="inline-refs", name="Inline", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
        new_payee_name="Inline vendor", new_tag_name="Inline tag",
    )
    schedule = result["schedule"]
    assert schedule["payee_id"] == default_storage.list_payees()[0]["id"]
    assert json.loads(schedule["tag_ids"]) == [default_storage.list_tags()[0]["id"]]
    with pytest.raises(StorageValidationError, match="Expense records"):
        default_storage.create_recurring_schedule(
            name="Invalid", txn_date="2024-01-01", amount=10,
            account_id=account_id, category_id=category_id, kind="Income",
        )


def test_recurring_interval_rejects_fractional_values(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    with pytest.raises(StorageValidationError, match="positive integer"):
        default_storage.create_recurring_expense(
            name="Invalid", txn_date="2024-01-01", recurrence_interval=1.5,
            amount=10, account_id=account_id, category_id=category_id,
        )
    default_storage.create_recurring_expense(
        schedule_id="fractional-backup", name="Valid", txn_date="2024-01-01",
        recurrence_interval=1, amount=10, account_id=account_id, category_id=category_id,
    )
    row = default_storage._find_row("RecurringSchedules", "fractional-backup")
    broken = dict(row.values)
    broken["recurrence_interval"] = "1.5"
    default_storage._replace_row("RecurringSchedules", row, broken)
    with pytest.raises(StorageValidationError, match="positive integer"):
        default_storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )


def test_recurring_backup_rejects_missing_interval(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_expense(
        schedule_id="missing-interval", name="Valid", txn_date="2024-01-01",
        recurrence_interval=1, amount=10, account_id=account_id, category_id=category_id,
    )
    row = default_storage._find_row("RecurringSchedules", "missing-interval")
    broken = dict(row.values)
    broken["recurrence_interval"] = ""
    default_storage._replace_row("RecurringSchedules", row, broken)
    with pytest.raises(StorageValidationError, match="positive integer"):
        default_storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )
def test_mixed_use_recurring_occurrence_preserves_source_projection_pair(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_mixed_use_expense(
        schedule_id="vehicle-schedule", name="Vehicle", txn_date="2024-01-31",
        recurrence_unit="month", recurrence_interval=1, total_expense="20.00",
        business_use_percentage="50", account_id=account_id, category_id=category_id,
        allocation_rationale="Business travel",
    )
    assert result["source"]["recurring_schedule_id"] == "vehicle-schedule"
    assert result["schedule"]["source_kind"] == "mixed_use"
    assert result["source"]["recurring_source_kind"] == "mixed_use"
    assert result["transaction"]["recurring_source_kind"] == "mixed_use"
    default_storage.reconcile_recurring_schedules(as_of="2024-02-29")
    sources = default_storage.list_mixed_use_expenses(_force_refresh=True)
    assert len(sources) == 2
    assert len(default_storage.list_transactions(_force_refresh=True)) == 2
    assert all(item.get("recurring_schedule_id") == "vehicle-schedule" for item in sources)
    assert all(item.get("recurring_source_kind") == "mixed_use" for item in sources)


def test_mixed_recurring_create_resolves_inline_payee_and_tag_values(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_mixed_use_expense(
        schedule_id="mixed-inline-refs", name="Inline mixed", txn_date="2024-01-01",
        recurrence_unit="month", total_expense="20.00", business_use_percentage="50",
        account_id=account_id, category_id=category_id, allocation_rationale="Use",
        new_payee_name="Mixed inline vendor", new_tag_name="Mixed inline tag",
    )
    schedule = result["schedule"]
    assert schedule["payee_id"] == default_storage.list_payees()[0]["id"]
    assert json.loads(schedule["tag_ids"]) == [default_storage.list_tags()[0]["id"]]


def test_recurring_source_kind_mismatch_is_rejected(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_mixed_use_expense(
        schedule_id="kind-mismatch", name="Shared", txn_date="2024-01-01",
        recurrence_unit="month", total_expense="20.00", business_use_percentage="50",
        account_id=account_id, category_id=category_id, allocation_rationale="Use",
    )
    row = default_storage._find_row("MixedUseExpenses", result["source"]["id"])
    broken = dict(row.values)
    broken["recurring_source_kind"] = "transaction"
    default_storage._replace_row("MixedUseExpenses", row, broken)
    with pytest.raises(StorageValidationError, match="recurring_source_kind|source kind"):
        default_storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )


def test_mixed_use_recurring_initial_retry_reuses_schedule_and_pair(default_storage, monkeypatch) -> None:
    account_id, category_id = _ids(default_storage)
    payload = dict(
        schedule_id="retry-schedule", name="Vehicle", txn_date="2024-01-31",
        recurrence_unit="month", total_expense="20.00", business_use_percentage="50",
        account_id=account_id, category_id=category_id, allocation_rationale="Business travel",
    )
    first = default_storage.create_recurring_mixed_use_expense(**payload)
    monkeypatch.setattr(
        "tabula_rasa.storage.google_sheets.recurring._utc_now",
        lambda: "2099-01-01T00:00:00+00:00",
    )
    second = default_storage.create_recurring_mixed_use_expense(**payload)
    assert first["source"]["id"] == second["source"]["id"]
    assert len(default_storage.list_recurring_schedules()) == 1
    assert len(default_storage.list_mixed_use_expenses()) == 1


def test_mixed_use_recurring_missing_projection_is_actionable(default_storage, monkeypatch) -> None:
    account_id, category_id = _ids(default_storage)

    def create_source_only(**source):
        return {"id": source["id"]}, {}

    monkeypatch.setattr(default_storage, "create_mixed_use_expense", create_source_only)
    with pytest.raises(StorageConflictError, match="linked projection"):
        default_storage.create_recurring_mixed_use_expense(
            schedule_id="missing-projection", name="Vehicle", txn_date="2024-01-31",
            recurrence_unit="month", total_expense="20.00", business_use_percentage="50",
            account_id=account_id, category_id=category_id, allocation_rationale="Business travel",
        )


def test_mixed_use_source_only_partial_does_not_advance_cutoff(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_mixed_use_expense(
        schedule_id="source-only", name="Vehicle", txn_date="2024-01-01",
        recurrence_unit="month", total_expense="20.00", business_use_percentage="50",
        account_id=account_id, category_id=category_id, allocation_rationale="Business travel",
    )
    projection_row = default_storage._find_row("Transactions", result["transaction"]["id"])
    default_storage._worksheet("Transactions").delete_rows(projection_row.row_number)
    default_storage._invalidate("Transactions")

    outcome = default_storage.reconcile_recurring_schedules(as_of="2024-02-01")

    assert outcome["generated"] == []
    assert outcome["attention"] == {"source-only": "validation"}


def test_recurring_retries_ignore_new_timestamps_but_not_payload_changes(default_storage, monkeypatch) -> None:
    account_id, category_id = _ids(default_storage)
    payload = dict(
        schedule_id="timestamp-retry", name="Rent", txn_date="2024-01-01",
        recurrence_unit="month", recurrence_interval=1, amount=10,
        account_id=account_id, category_id=category_id,
    )
    first = default_storage.create_recurring_expense(**payload)
    monkeypatch.setattr(
        "tabula_rasa.storage.google_sheets.recurring._utc_now",
        lambda: "2099-01-01T00:00:00+00:00",
    )
    second = default_storage.create_recurring_expense(**payload)
    assert second["schedule"]["id"] == first["schedule"]["id"]
    assert second["transaction"]["id"] == first["transaction"]["id"]
    assert len(default_storage.list_recurring_schedules()) == 1
    assert len(default_storage.list_transactions()) == 1


def test_recurring_export_rejects_invalid_occurrence_type(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_expense(
        schedule_id="bad-occurrence", name="Rent", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    row = default_storage._find_row("Transactions", result["transaction"]["id"])
    broken = dict(row.values)
    broken["recurring_occurrence_type"] = "corrupt"
    default_storage._replace_row("Transactions", row, broken)

    with pytest.raises(StorageValidationError, match="occurrence type"):
        default_storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )


def test_recurring_export_rejects_partial_provenance(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_expense(
        schedule_id="partial-provenance", name="Rent", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    row = default_storage._find_row("Transactions", result["transaction"]["id"])
    broken = dict(row.values)
    broken["recurring_schedule_id"] = ""
    default_storage._replace_row("Transactions", row, broken)

    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.export_backup_zip(
            {"schema_version": 1, "business_profile_key": "test", "receipts": []}
        )


def test_current_backup_rejects_partial_provenance(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_expense(
        schedule_id="partial-backup-provenance", name="Rent", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    backup = default_storage.export_backup_zip(backup_receipt_manifest(default_storage))

    def clear_schedule_id(rows: list[list[str]]) -> None:
        schedule_index = rows[0].index("recurring_schedule_id")
        rows[1][schedule_index] = ""

    tampered = rewrite_backup_tables(backup, {"Transactions": clear_schedule_id})
    with pytest.raises(StorageValidationError, match="provided together"):
        default_storage.validate_backup_zip(tampered)


def test_invalid_schedule_status_needs_attention_but_can_be_repaired(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_schedule(
        schedule_id="invalid-status", name="Invalid", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    row = default_storage._find_row("RecurringSchedules", "invalid-status")
    broken = dict(row.values)
    broken["status"] = "corrupt"
    default_storage._replace_row("RecurringSchedules", row, broken)

    outcome = default_storage.reconcile_recurring_schedules(as_of="2024-02-01")
    assert outcome["attention"] == {"invalid-status": "validation"}

    repaired = default_storage.edit_recurring_schedule("invalid-status", status="active")
    assert repaired["status"] == "active"


def test_schedule_pause_resume_and_end_do_not_change_occurrences(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_expense(
        schedule_id="software-schedule", name="Software", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    default_storage.pause_recurring_schedule("software-schedule")
    assert default_storage.reconcile_recurring_schedules(as_of="2024-03-01")["generated"] == []
    default_storage.resume_recurring_schedule("software-schedule")
    assert len(default_storage.reconcile_recurring_schedules(as_of="2024-03-01")["generated"]) == 2
    default_storage.end_recurring_schedule("software-schedule")
    assert default_storage.get_recurring_schedule("software-schedule")["status"] == "ended"


def test_reconcile_cutoff_uses_current_visible_transaction_date(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_expense(
        schedule_id="date-cutoff", name="Charge", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    default_storage.edit_transaction(result["transaction"]["id"], txn_date="2024-03-15")
    generated = default_storage.reconcile_recurring_schedules(as_of="2024-04-30")["generated"]
    assert [item["recurring_scheduled_date"] for item in generated] == ["2024-04-01"]


def test_delete_latest_occurrence_allows_its_scheduled_date_to_regenerate(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_expense(
        schedule_id="delete-latest", name="Charge", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    generated = default_storage.reconcile_recurring_schedules(as_of="2024-03-01")["generated"]
    latest_id = generated[-1]["id"]
    default_storage.delete_transaction(latest_id)
    regenerated = default_storage.reconcile_recurring_schedules(as_of="2024-03-01")["generated"]
    assert [item["recurring_scheduled_date"] for item in regenerated] == ["2024-03-01"]


def test_invalid_stored_schedule_does_not_hide_other_schedules(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_expense(
        schedule_id="valid", name="Valid", txn_date="2024-01-01", amount=10,
        account_id=account_id, category_id=category_id,
    )
    default_storage.create_recurring_expense(
        schedule_id="invalid", name="Invalid", txn_date="2024-01-01", amount=10,
        account_id=account_id, category_id=category_id,
    )
    row = default_storage._find_row("RecurringSchedules", "invalid")
    broken = dict(row.values)
    broken["recurrence_unit"] = "not-a-unit"
    default_storage._replace_row("RecurringSchedules", row, broken)
    schedules = default_storage.list_recurring_schedules(_force_refresh=True)
    assert {item["id"] for item in schedules} == {"valid", "invalid"}


def test_next_due_exposes_future_start_and_current_schedule_dates(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_schedule(
        schedule_id="future", name="Future", txn_date="2099-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    assert default_storage.get_recurring_schedule("future")["next_due_date"] == "2099-01-01"


def test_recurring_provenance_is_immutable_and_generic_create_is_rejected(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    result = default_storage.create_recurring_expense(
        schedule_id="immutable", name="Immutable", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    with pytest.raises(StorageValidationError, match="created only"):
        default_storage.create_transaction(
            txn_date="2024-02-01", kind="Expense", amount=10,
            account_id=account_id, category_id=category_id,
            recurring_schedule_id="immutable", recurring_scheduled_date="2024-02-01",
            recurring_occurrence_type="generated",
        )
    with pytest.raises(StorageValidationError, match="created only"):
        default_storage.create_transaction(
            txn_date="2024-02-02", kind="Expense", amount=10,
            account_id=account_id, category_id=category_id,
            recurring_schedule_id="",
        )
    with pytest.raises(StorageValidationError, match="cannot be changed"):
        default_storage.edit_transaction(result["transaction"]["id"], recurring_scheduled_date="2024-02-02")


def test_schedule_status_transitions_require_current_state_and_baseline(default_storage) -> None:
    account_id, category_id = _ids(default_storage)
    default_storage.create_recurring_schedule(
        schedule_id="states", name="States", txn_date="2024-01-01",
        recurrence_unit="month", amount=10, account_id=account_id, category_id=category_id,
    )
    active = default_storage.get_recurring_schedule("states")
    default_storage.pause_recurring_schedule("states", expected_schedule=active)
    with pytest.raises(StorageConflictError, match="active"):
        default_storage.pause_recurring_schedule("states")
    paused = default_storage.get_recurring_schedule("states")
    default_storage.resume_recurring_schedule("states", expected_schedule=paused)
    ended = default_storage.end_recurring_schedule("states", expected_schedule=default_storage.get_recurring_schedule("states"))
    assert ended["status"] == "ended"
    with pytest.raises(StorageConflictError, match="already ended"):
        default_storage.end_recurring_schedule("states")
