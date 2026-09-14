"""Profile-scoped pending state for retry-safe recurring saves."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from uuid import uuid4


def _profile_key_segment(profile_key: str) -> str:
    """Encode the selected profile so delimiter-containing keys stay distinct."""
    return f"profile_{len(profile_key)}_{profile_key}"


@dataclass(frozen=True)
class PendingRecurrenceState:
    """Own the stable identities and original payload for one recurrence."""

    schedule_id_key: str
    payload_key: str
    identity_keys: tuple[tuple[str, str], ...] = ()
    configuration_revision_key: str | None = None
    configuration_guards_identity_keys: bool = True

    def has_schedule(self, state: Mapping[str, object]) -> bool:
        return bool(state.get(self.schedule_id_key))

    def has_pending(self, state: Mapping[str, object]) -> bool:
        return self.has_schedule(state) or any(
            state.get(key) for _field, key in self.identity_keys
        )

    def discard_if_configuration_changed(
        self,
        state: MutableMapping[str, object],
        configuration_revision: str,
    ) -> bool:
        """Clear recurring retry state that belongs to another workbook."""
        if not self.configuration_revision_key:
            return False
        has_recurring_state = (
            self.has_schedule(state)
            or self.payload_key in state
            or (
                self.configuration_guards_identity_keys
                and any(key in state for _field, key in self.identity_keys)
            )
        )
        if not has_recurring_state:
            return False
        if state.get(self.configuration_revision_key) == configuration_revision:
            return False
        self.clear(state)
        return True

    def payload(
        self, state: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        payload = state.get(self.payload_key)
        return payload if isinstance(payload, Mapping) else None

    def ensure_ids(
        self,
        state: MutableMapping[str, object],
        *,
        configuration_revision: str | None = None,
    ) -> dict[str, str]:
        if configuration_revision is not None:
            self.discard_if_configuration_changed(
                state,
                configuration_revision,
            )
        ids = {
            "schedule_id": str(state.get(self.schedule_id_key) or uuid4())
        }
        state[self.schedule_id_key] = ids["schedule_id"]
        for field, key in self.identity_keys:
            ids[field] = str(state.get(key) or uuid4())
            state[key] = ids[field]
        if self.configuration_revision_key and configuration_revision is not None:
            state[self.configuration_revision_key] = configuration_revision
        return ids

    def remember_payload(
        self,
        state: MutableMapping[str, object],
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        """Keep the original submission while enforcing its stable identities."""
        existing = self.payload(state)
        remembered = dict(payload)
        if existing is not None:
            remembered.update(existing)
        remembered["schedule_id"] = str(state[self.schedule_id_key])
        for field, key in self.identity_keys:
            remembered[field] = str(state[key])
        state[self.payload_key] = dict(remembered)
        return remembered

    def clear(self, state: MutableMapping[str, object]) -> None:
        state.pop(self.schedule_id_key, None)
        state.pop(self.payload_key, None)
        for _field, key in self.identity_keys:
            state.pop(key, None)
        if self.configuration_revision_key:
            state.pop(self.configuration_revision_key, None)


def transaction_create_pending_state(profile_key: str) -> PendingRecurrenceState:
    return PendingRecurrenceState(
        schedule_id_key=f"recurring_pending_schedule_id_{profile_key}",
        payload_key=f"recurring_pending_payload_{profile_key}",
        identity_keys=((
            "transaction_id",
            f"recurring_pending_transaction_id_{profile_key}",
        ),),
        configuration_revision_key=(
            f"recurring_pending_configuration_revision_{profile_key}"
        ),
    )


def mixed_use_create_pending_state(profile_key: str) -> PendingRecurrenceState:
    return PendingRecurrenceState(
        schedule_id_key=f"mixed_use_pending_schedule_id_{profile_key}",
        payload_key=f"mixed_use_pending_payload_{profile_key}",
        identity_keys=(
            ("source_id", f"mixed_use_pending_source_id_{profile_key}"),
            (
                "linked_transaction_id",
                f"mixed_use_pending_transaction_id_{profile_key}",
            ),
        ),
        configuration_revision_key=(
            f"mixed_use_pending_configuration_revision_{profile_key}"
        ),
        configuration_guards_identity_keys=False,
    )


def transaction_edit_pending_state(
    profile_key: str, record_id: str
) -> PendingRecurrenceState:
    profile_segment = _profile_key_segment(profile_key)
    return PendingRecurrenceState(
        schedule_id_key=(
            f"recurring_edit_pending_schedule_id_{record_id}_{profile_segment}"
        ),
        payload_key=(
            f"recurring_edit_pending_payload_{record_id}_{profile_segment}"
        ),
        configuration_revision_key=(
            "recurring_edit_pending_configuration_revision_"
            f"{record_id}_{profile_segment}"
        ),
    )


def mixed_use_edit_pending_state(
    profile_key: str, source_id: str
) -> PendingRecurrenceState:
    profile_segment = _profile_key_segment(profile_key)
    return PendingRecurrenceState(
        schedule_id_key=(
            f"mixed_use_edit_pending_schedule_id_{source_id}_{profile_segment}"
        ),
        payload_key=(
            f"mixed_use_edit_pending_payload_{source_id}_{profile_segment}"
        ),
        configuration_revision_key=(
            "mixed_use_edit_pending_configuration_revision_"
            f"{source_id}_{profile_segment}"
        ),
    )


def clear_edit_pending_state_for_schedule(
    state: MutableMapping[str, object],
    *,
    profile_key: str,
    schedule_id: str,
) -> None:
    """Clear exact-record edit retries for a schedule that was ended."""
    retry_prefixes = (
        (
            "recurring_edit_pending_schedule_id_",
            transaction_edit_pending_state,
            False,
        ),
        (
            "recurring_edit_pending_payload_",
            transaction_edit_pending_state,
            True,
        ),
        (
            "mixed_use_edit_pending_schedule_id_",
            mixed_use_edit_pending_state,
            False,
        ),
        (
            "mixed_use_edit_pending_payload_",
            mixed_use_edit_pending_state,
            True,
        ),
    )
    for prefix, pending_state, payload_key in retry_prefixes:
        profile_suffix = f"_profile_{len(profile_key)}_{profile_key}"
        for key in list(state):
            if not key.startswith(prefix):
                continue
            if not key.endswith(profile_suffix):
                continue
            record_id = key[len(prefix) : -len(profile_suffix)]
            if not record_id:
                continue
            value = state.get(key)
            pending = pending_state(profile_key, record_id)
            if (
                payload_key
                and pending.schedule_id_key in state
                and str(state.get(pending.schedule_id_key) or "")
                != schedule_id
            ):
                continue
            linked_schedule_id = (
                str(value.get("schedule_id") or "")
                if payload_key and isinstance(value, Mapping)
                else str(value or "")
            )
            if linked_schedule_id != schedule_id:
                continue
            pending.clear(state)


__all__ = [
    "PendingRecurrenceState",
    "clear_edit_pending_state_for_schedule",
    "mixed_use_create_pending_state",
    "mixed_use_edit_pending_state",
    "transaction_create_pending_state",
    "transaction_edit_pending_state",
]
