from tabula_rasa.recurrence_state import (
    clear_edit_pending_state_for_schedule,
    mixed_use_create_pending_state,
    mixed_use_edit_pending_state,
    transaction_create_pending_state,
    transaction_edit_pending_state,
)


def test_create_retry_ids_are_stable_and_profile_scoped() -> None:
    state: dict[str, object] = {}
    north = transaction_create_pending_state("north")

    first = north.ensure_ids(state, configuration_revision="revision")
    second = north.ensure_ids(state)

    assert first == second
    assert state["recurring_pending_configuration_revision_north"] == "revision"
    assert first != transaction_create_pending_state("south").ensure_ids(state)


def test_mixed_use_retry_preserves_original_payload_and_all_ids() -> None:
    state: dict[str, object] = {}
    pending = mixed_use_create_pending_state("north")
    ids = pending.ensure_ids(state, configuration_revision="revision")

    first = pending.remember_payload(
        state,
        {"allocation_rationale": "Saved rationale"},
    )
    retry = pending.remember_payload(
        state,
        {"allocation_rationale": "Changed rationale"},
    )

    assert first == retry
    assert retry["allocation_rationale"] == "Saved rationale"
    assert retry["schedule_id"] == ids["schedule_id"]
    assert retry["source_id"] == ids["source_id"]
    assert retry["linked_transaction_id"] == ids["linked_transaction_id"]


def test_workbook_change_clears_only_the_affected_pending_state() -> None:
    state: dict[str, object] = {}
    north = transaction_create_pending_state("north")
    south = transaction_create_pending_state("south")
    north.ensure_ids(state, configuration_revision="old-workbook")
    south_ids = south.ensure_ids(
        state,
        configuration_revision="south-workbook",
    )
    north.remember_payload(state, {"description": "North"})
    south.remember_payload(state, {"description": "South"})

    assert north.discard_if_configuration_changed(state, "new-workbook")
    assert not south.discard_if_configuration_changed(state, "south-workbook")
    assert not north.has_pending(state)
    assert south.has_pending(state)
    assert south.payload(state) == {"description": "South", **south_ids}


def test_configuration_guard_preserves_nonrecurring_mixed_use_create_ids() -> None:
    state = {
        "recurring_pending_transaction_id_north": "ordinary-initial",
        "mixed_use_pending_source_id_north": "mixed-source",
        "mixed_use_pending_transaction_id_north": "mixed-projection",
    }

    transaction_create_pending_state("north").discard_if_configuration_changed(
        state,
        "new-workbook",
    )
    mixed_use_create_pending_state("north").discard_if_configuration_changed(
        state,
        "new-workbook",
    )

    assert "recurring_pending_transaction_id_north" not in state
    assert state["mixed_use_pending_source_id_north"] == "mixed-source"
    assert state["mixed_use_pending_transaction_id_north"] == "mixed-projection"


def test_edit_retry_state_uses_exact_record_and_profile_keys() -> None:
    ordinary = transaction_edit_pending_state("shop", "expense")
    mixed = mixed_use_edit_pending_state("north_shop", "source_profile_shop")

    assert ordinary.schedule_id_key == (
        "recurring_edit_pending_schedule_id_expense_profile_4_shop"
    )
    assert mixed.payload_key == (
        "mixed_use_edit_pending_payload_source_profile_shop_profile_10_north_shop"
    )

    state: dict[str, object] = {}
    ordinary.ensure_ids(state, configuration_revision="old-sheet")
    ordinary.remember_payload(state, {"description": "Pending edit"})
    assert ordinary.discard_if_configuration_changed(state, "new-sheet")
    assert not ordinary.has_pending(state)


def test_schedule_cleanup_uses_the_terminal_profile_segment() -> None:
    state: dict[str, object] = {}
    pending = mixed_use_edit_pending_state(
        "north_profile_shop",
        "source",
    )
    pending.ensure_ids(state, configuration_revision="sheet")
    pending.remember_payload(state, {"description": "Pending edit"})

    other = mixed_use_edit_pending_state("shop", "source_profile_north")
    other.ensure_ids(state, configuration_revision="sheet")
    state[other.schedule_id_key] = state[pending.schedule_id_key]

    clear_edit_pending_state_for_schedule(
        state,
        profile_key="north_profile_shop",
        schedule_id=str(state[pending.schedule_id_key]),
    )

    assert not pending.has_pending(state)
    assert pending.configuration_revision_key not in state
    assert other.has_pending(state)
